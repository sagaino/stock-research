"""Scout & Sniper Microstructure Trading Architecture (Max 5 Slots).

Coordinates between high-throughput market radar (The Scout) and tactical
per-symbol microstructure monitoring & trade management (The Sniper).
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
import math
from statistics import median
import subprocess
import sys
from typing import Any, Callable

from .radar import RadarAlert

_WIB = timezone(timedelta(hours=7))
_WATCHLIST_IDLE_SECONDS = 300.0
_WATCHLIST_HAKA_WINDOW_SECONDS = 5.0


class SniperState(str, Enum):
    IDLE = "IDLE"
    OBSERVING = "OBSERVING"
    WATCHING = "WATCHING"
    ENTERED = "ENTERED"
    EXIT_TP = "EXIT_TP"
    EXIT_CL = "EXIT_CL"
    ABORTED = "ABORTED"
    EXIT_TIMEOUT = "EXIT_TIMEOUT"


def get_idx_tick_size(price: float) -> float:
    """Return IDX standard tick size based on official price fraction."""
    if price < 200:
        return 1.0
    elif price < 500:
        return 2.0
    elif price < 2000:
        return 5.0
    elif price < 5000:
        return 10.0
    else:
        return 25.0


def round_to_idx_tick(price: float) -> float:
    """Round price to the nearest valid IDX tick size."""
    tick = get_idx_tick_size(price)
    return round(price / tick) * tick


def _paper_fill(price: float, buy: bool, slippage_ticks: int) -> float:
    tick = get_idx_tick_size(price)
    aligned = math.ceil(price / tick) * tick if buy else math.floor(price / tick) * tick
    return max(tick, aligned + tick * slippage_ticks if buy else aligned - tick * slippage_ticks)


def _signal_price_for_minimum_exit_fill(minimum_fill: float, slippage_ticks: int) -> float:
    signal = math.ceil(minimum_fill / get_idx_tick_size(minimum_fill)) * get_idx_tick_size(minimum_fill)
    while _paper_fill(signal, False, slippage_ticks) < minimum_fill:
        signal += get_idx_tick_size(signal)
    return signal


def _signal_price_for_maximum_exit_fill(maximum_fill: float, slippage_ticks: int) -> float:
    """Return the highest valid sell signal whose adverse fill stays below a cap."""
    tick = get_idx_tick_size(maximum_fill)
    signal = max(tick, math.floor(maximum_fill / tick) * tick)
    while signal > tick and _paper_fill(signal, False, slippage_ticks) > maximum_fill:
        signal -= get_idx_tick_size(signal)
    return round_to_idx_tick(max(tick, signal))


def _paper_break_even_signal(entry_price: float, config: "SniperConfig") -> float:
    entry_tick = get_idx_tick_size(entry_price)
    paper_entry = _paper_fill(entry_price, True, config.paper_slippage_ticks)
    minimum_fill = paper_entry * (1.0 + config.fee_buy_pct / 100.0) / (1.0 - config.fee_sell_pct / 100.0)
    return max(
        round_to_idx_tick(entry_price + config.hybrid_runner_be_buffer_ticks * entry_tick),
        _signal_price_for_minimum_exit_fill(minimum_fill, config.paper_slippage_ticks),
    )


def apply_paper_friction(record: dict[str, Any], config: "SniperConfig") -> dict[str, Any]:
    """Reprice a simulated round trip with adverse IDX-tick slippage and fees."""
    result = dict(record)
    if result.get("paper_fill_model") or result.get("entry_price", 0) <= 0 or result.get("lots", 0) <= 0:
        return result

    ticks = max(0, int(config.paper_slippage_ticks))

    signal_entry = float(result["entry_price"])
    entry = _paper_fill(signal_entry, True, ticks)
    lots = int(result["lots"])
    result["signal_entry_price"] = signal_entry
    result["entry_price"] = entry
    result["paper_slippage_ticks"] = ticks
    result["paper_fill_model"] = "adverse_idx_ticks_plus_fees"

    if result.get("is_hybrid"):
        exits = []
        for prefix in ("tranche1", "tranche2"):
            tranche_lots = int(result.get(f"{prefix}_lots", 0))
            signal_exit = float(result.get(f"{prefix}_exit_price", 0))
            if tranche_lots <= 0 or signal_exit <= 0:
                continue
            exit_price = _paper_fill(signal_exit, False, ticks)
            val_in = tranche_lots * entry * 100
            val_out = tranche_lots * exit_price * 100
            fee = val_in * config.fee_buy_pct / 100 + val_out * config.fee_sell_pct / 100
            result[f"signal_{prefix}_exit_price"] = signal_exit
            result[f"{prefix}_exit_price"] = exit_price
            result[f"{prefix}_gross_idr"] = round(val_out - val_in, 2)
            result[f"{prefix}_fee_idr"] = round(fee, 2)
            result[f"{prefix}_net_idr"] = round(val_out - val_in - fee, 2)
            result[f"{prefix}_pnl_pct"] = round(result[f"{prefix}_net_idr"] / val_in * 100, 2) if val_in else 0.0
            exits.append((tranche_lots, exit_price))
        val_in = lots * entry * 100
        val_out = sum(qty * price * 100 for qty, price in exits)
        fee = sum(result.get(f"{prefix}_fee_idr", 0.0) for prefix in ("tranche1", "tranche2"))
        result["exit_price"] = round(val_out / (lots * 100), 1) if val_out and lots else 0.0
    else:
        signal_exit = float(result.get("exit_price", 0))
        result["signal_exit_price"] = signal_exit
        result["exit_price"] = _paper_fill(signal_exit, False, ticks) if signal_exit > 0 else 0.0
        val_in = lots * entry * 100
        val_out = lots * result["exit_price"] * 100
        fee = val_in * config.fee_buy_pct / 100 + val_out * config.fee_sell_pct / 100

    result["val_in"] = val_in
    result["val_out"] = val_out
    result["fee_total"] = round(fee, 2)
    result["gross_idr"] = round(val_out - val_in, 2)
    result["net_idr"] = round(val_out - val_in - fee, 2)
    result["pnl_pct"] = round(result["net_idr"] / val_in * 100, 2) if val_in else 0.0
    return result


DEFAULT_BIG_CAPS: frozenset[str] = frozenset({
    "BBCA", "BBRI", "BMRI", "BBNI", "ASII", "TLKM", "ICBP", "INDF",
    "UNVR", "AMMN", "BRPT", "TPIA", "PGAS", "AKRA", "ISAT", "ADRO",
    "PTBA", "GOTO", "ANTM", "INCO", "CPIN", "KLBF", "DSSA", "EMAS",
    "TINS", "SINI", "INDY", "MEDC", "ADMR", "BUMI",
    # Heavy / Slow-movers / High-priced stocks unsuited for tactical scalping:
    "ITMG", "UNTR", "TAPG", "AALI", "LSIP", "HRUM", "MBMA", "SMGR",
    "INTP", "GGRM", "HMSP", "MYOR", "ACES", "MAPI",
})


@dataclass
class SniperConfig:
    max_slots: int = 5
    observation_timeout_seconds: float = 10.0
    max_holding_seconds: float = 130.0
    target_tp_pct: float = 3.0
    stop_loss_pct: float = 1.5
    stop_loss_ticks: int = 2
    bid_fortification_min_ratio: float = 1.5
    auto_release_delay_seconds: float = 3.0
    cooldown_seconds: float = 30.0
    cl_cooldown_seconds: float = 1800.0  # 30-minute blacklist after Cut-Loss to prevent revenge trading
    min_haka_streak: int = 2
    min_follow_through_haka_lots: float = 100.0  # Minimal akumulasi lot HAKA di masa observasi 10s
    exclude_big_caps: bool = True
    custom_excluded_symbols: list[str] = field(default_factory=list)
    focus_patterns: list[str] = field(default_factory=lambda: ["BREAKOUT_MOMENTUM"])
    fee_buy_pct: float = 0.15
    fee_sell_pct: float = 0.25
    trade_capital_idr: float = 550_000.0
    min_stock_price: float = 50.0  # Batas minimal harga saham (default 50: izinkan saham mulai Rp 50)
    max_stock_price: float = 0.0  # Batas maksimal harga saham (default 0: tanpa batas atas)
    spawn_terminal: bool = False
    enable_orderbook_tape_reading: bool = True  # Aktifkan Tape Reading Level 2 (Iceberg Refill TP & Bid Absorption CL)
    dynamic_tp_refill_lots: float = 20_000.0  # Ambang batas reload offer di resistance untuk trigger Dynamic TP
    dynamic_cl_absorb_lots: float = 15_000.0  # Ambang batas akumulasi absorpsi bid support untuk menahan posisi
    absorption_hold_extension_seconds: float = 180.0  # Perpanjangan waktu hold jika support sedang aktif di-absorpsi
    enable_hybrid_mode: bool = False  # Mode Hybrid: Partial Scalp TP (Tranche 1) + Trailing Runner (Tranche 2)
    hybrid_scalp_ratio: float = 0.5  # Rasio alokasi lot untuk Tranche 1 Scalp TP (default 0.5 = 50%)
    hybrid_runner_max_hold_seconds: float = 900.0  # Batas maksimal hold untuk Tranche 2 Runner (default 900s = 15 menit)
    hybrid_runner_trailing_ticks: int = 3  # Jarak trailing ticks dari harga puncak untuk Tranche 2 Runner (default 3 tick fraksi IDX)
    hybrid_runner_be_buffer_ticks: int = 1  # Buffer tick di atas entry price (BEP + N tick) untuk menutup fee broker (default 1 tick)
    min_observation_seconds: float = 0.0  # Minimal durasi observasi sebelum entry (default 0.0)
    min_observing_done_trades: int = 1  # Minimal jumlah transaksi done lanjutan saat observasi (default 1)
    max_tape_silence_seconds: float = 0.0  # Batas jeda tanpa trade saat observasi sebelum abort (0.0 = nonaktif)
    min_observing_haka_value_idr: float = 0.0  # Minimal akumulasi nilai HAKA lanjutan (0.0 = nonaktif)
    stagnant_timeout_seconds: float = 0.0  # Batas maksimal menahan posisi mandek di BEP (0.0 = nonaktif; CLI default: 90s)
    enable_l2_pre_entry_guard: bool = False  # Verifikasi buku order L2 sebelum masuk (default False)
    l2_pre_entry_min_bid_ratio: float = 1.2  # Rasio minimal Bid vs Offer L2 sebelum entry
    l2_pre_entry_min_bid_lots: float = 1_500.0  # Minimal lot di 3 bid teratas L2 sebelum entry
    enable_trading_hours_guard: bool = False  # Cut-off order baru di atas jam 15:35 WIB (default False)
    dynamic_tp_min_refill_strikes: int = 2  # Minimal gelombang/siklus pengisian ulang offer sebelum trigger Dynamic TP (default 2 strikes)
    dynamic_tp_strike_min_refill_lots: float = 1_000.0  # Minimal penambahan lot dalam 1 gelombang untuk dihitung 1 strike
    l2_stale_seconds: float = 15.0
    paper_slippage_ticks: int = 0
    # Full mode is the opt-in L2 Watchlist Pullback strategy; legacy remains unchanged.
    orderbook_exit_mode: str = "legacy"  # legacy | full
    orderbook_wall_min_lots: float = 10_000.0
    orderbook_psychological_wall_min_lots: float = 50_000.0
    orderbook_wall_ratio: float = 3.0
    orderbook_depletion_ratio: float = 0.20
    orderbook_refill_min_lots: float = 1_000.0
    orderbook_support_levels: int = 2
    orderbook_psychological_step: float = 10.0
    orderbook_symbol_wall_min_lots: dict[str, float] = field(default_factory=dict)


@dataclass
class SniperSlot:
    slot_id: int
    symbol: str | None = None
    state: SniperState = SniperState.IDLE
    pattern: str = ""
    alert_time: datetime | None = None
    state_changed_time: datetime | None = None
    entry_time: datetime | None = None
    ref_price: float = 0.0
    entry_price: float = 0.0
    current_price: float = 0.0
    peak_price: float = 0.0
    target_price: float = 0.0
    stop_loss_price: float = 0.0
    pnl_pct: float = 0.0
    ttl_seconds: float = 0.0
    reason: str = "Slot Tersedia"
    haka_streak: int = 0
    observing_haka_lots: float = 0.0
    active_offer_refills: dict[float, float] = field(default_factory=dict)
    active_offer_refill_strikes: dict[float, int] = field(default_factory=dict)
    offer_was_consumed: dict[float, bool] = field(default_factory=dict)
    active_bid_refills: dict[float, float] = field(default_factory=dict)
    hold_extended: bool = False
    effective_max_holding_seconds: float = 0.0
    # Hybrid Mode Tracking
    is_hybrid: bool = False
    total_lots: int = 0
    tranche1_lots: int = 0
    tranche1_status: str = "PENDING"  # PENDING | FILLED | STOPPED
    tranche1_exit_price: float = 0.0
    tranche1_exit_time: datetime | None = None
    tranche1_reason: str = ""
    tranche1_pnl_pct: float = 0.0
    tranche1_gross_idr: float = 0.0
    tranche1_fee_idr: float = 0.0
    tranche1_net_idr: float = 0.0

    tranche2_lots: int = 0
    tranche2_status: str = "PENDING"  # PENDING | FILLED | STOPPED
    tranche2_exit_price: float = 0.0
    tranche2_exit_time: datetime | None = None
    tranche2_reason: str = ""
    tranche2_pnl_pct: float = 0.0
    tranche2_gross_idr: float = 0.0
    tranche2_fee_idr: float = 0.0
    tranche2_net_idr: float = 0.0

    runner_trailing_stop_price: float = 0.0
    l2_summary: str = ""
    observing_done_count: int = 0
    observing_haka_value_idr: float = 0.0
    observing_total_value_idr: float = 0.0
    alert_velocity: int = 0
    alert_haka_pct: float = 0.0
    alert_net_flow_idr: float = 0.0
    alert_delta_pct: float = 0.0
    last_trade_time: datetime | None = None
    # Order-book full mode state. Keys are (BID|OFFER, price).
    wall_states: dict[tuple[str, float], dict[str, Any]] = field(default_factory=dict)
    entry_offer_price: float = 0.0
    entry_ready: bool = False
    entry_ready_done_count: int = 0
    active_support_price: float = 0.0
    active_resistance_price: float = 0.0
    watch_started_at: datetime | None = None
    watch_support_ready: bool = False
    watch_haka_time: datetime | None = None
    exit_signal_price: float = 0.0
    exit_fill_price: float = 0.0
    exit_reason_code: str = ""
    process: Any = None

    def reset(self):
        if self.process is not None:
            try:
                self.process.terminate()
            except Exception:
                pass
            self.process = None
        self.symbol = None
        self.state = SniperState.IDLE
        self.pattern = ""
        self.alert_time = None
        self.state_changed_time = None
        self.entry_time = None
        self.ref_price = 0.0
        self.entry_price = 0.0
        self.current_price = 0.0
        self.peak_price = 0.0
        self.target_price = 0.0
        self.stop_loss_price = 0.0
        self.pnl_pct = 0.0
        self.ttl_seconds = 0.0
        self.reason = "Slot Tersedia"
        self.haka_streak = 0
        self.observing_haka_lots = 0.0
        self.observing_done_count = 0
        self.observing_haka_value_idr = 0.0
        self.observing_total_value_idr = 0.0
        self.alert_velocity = 0
        self.alert_haka_pct = 0.0
        self.alert_net_flow_idr = 0.0
        self.alert_delta_pct = 0.0
        self.last_trade_time = None
        self.wall_states.clear()
        self.entry_offer_price = 0.0
        self.entry_ready = False
        self.entry_ready_done_count = 0
        self.active_support_price = 0.0
        self.active_resistance_price = 0.0
        self.watch_started_at = None
        self.watch_support_ready = False
        self.watch_haka_time = None
        self.exit_signal_price = 0.0
        self.exit_fill_price = 0.0
        self.exit_reason_code = ""
        self.active_offer_refills.clear()
        self.active_offer_refill_strikes.clear()
        self.offer_was_consumed.clear()
        self.active_bid_refills.clear()
        self.hold_extended = False
        self.effective_max_holding_seconds = 0.0
        self.is_hybrid = False
        self.total_lots = 0
        self.tranche1_lots = 0
        self.tranche1_status = "PENDING"
        self.tranche1_exit_price = 0.0
        self.tranche1_exit_time = None
        self.tranche1_reason = ""
        self.tranche1_pnl_pct = 0.0
        self.tranche1_gross_idr = 0.0
        self.tranche1_fee_idr = 0.0
        self.tranche1_net_idr = 0.0
        self.tranche2_lots = 0
        self.tranche2_status = "PENDING"
        self.tranche2_exit_price = 0.0
        self.tranche2_exit_time = None
        self.tranche2_reason = ""
        self.tranche2_pnl_pct = 0.0
        self.tranche2_gross_idr = 0.0
        self.tranche2_fee_idr = 0.0
        self.tranche2_net_idr = 0.0
        self.runner_trailing_stop_price = 0.0
        self.l2_summary = ""

    def format_status(self) -> str:
        sym = self.symbol or "----"
        st = self.state.value
        if self.state == SniperState.IDLE:
            return f"[SLOT {self.slot_id}] {sym:<4} | {st:<12} | -                | -                | {self.reason}"
        elif self.state == SniperState.OBSERVING:
            ttl_str = f"TTL: {max(0.0, self.ttl_seconds):.1f}s"
            ref_str = f"Ref: {self.ref_price:.0f}"
            cur_str = f"Cur: {self.current_price:.0f}"
            l2_part = f" | {self.l2_summary}" if self.l2_summary else ""
            return f"[SLOT {self.slot_id}] {sym:<4} | {st:<12} | {ref_str:<10} | {cur_str:<10}{l2_part} | {ttl_str} | {self.reason}"
        elif self.state == SniperState.WATCHING:
            idle_str = f"Idle: {max(0.0, self.ttl_seconds):.0f}s"
            support = f"Sup: {self.active_support_price:.0f}" if self.active_support_price else "Sup: -"
            l2_part = f" | {self.l2_summary}" if self.l2_summary else ""
            return f"[SLOT {self.slot_id}] {sym:<4} | {st:<12} | Cur: {self.current_price:.0f} Peak: {self.peak_price:.0f}{l2_part} | {support} HAKA:{self.haka_streak}/2 | {idle_str} | {self.reason}"
        elif self.state == SniperState.ENTERED:
            pnl_sign = "+" if self.pnl_pct >= 0 else ""
            in_str = f"In: {self.entry_price:.0f}"
            cur_str = f"Cur: {self.current_price:.0f} ({pnl_sign}{self.pnl_pct:.1f}%)"
            l2_part = f" | {self.l2_summary}" if self.l2_summary else ""
            if self.is_hybrid:
                t1_info = f"T1: {self.tranche1_lots}L @ {self.tranche1_exit_price:.0f}" if self.tranche1_status == "FILLED" else f"T1: {self.tranche1_lots}L TP:{self.target_price:.0f}"
                t2_info = f"T2: {self.tranche2_lots}L Trail:{self.runner_trailing_stop_price:.0f}"
                tp_cl = f"{t1_info} | {t2_info}"
            elif self.target_price <= 0 and self.active_support_price > 0:
                tp_cl = f"TP: OB | CL: {self.active_support_price:.0f}"
            else:
                tp_cl = f"TP: {self.target_price:.0f} | CL: {self.stop_loss_price:.0f}"
            return f"[SLOT {self.slot_id}] {sym:<4} | {st:<12} | {in_str:<9} | {cur_str:<17}{l2_part} | {tp_cl} | {self.reason}"
        else:  # EXIT_TP, EXIT_CL, ABORTED, EXIT_TIMEOUT
            pnl_sign = "+" if self.pnl_pct >= 0 else ""
            res = f"({pnl_sign}{self.pnl_pct:.1f}%)" if self.entry_price > 0 else ""
            return f"[SLOT {self.slot_id}] {sym:<4} | {st:<12} | {res:<8} | {self.reason}"


class SniperManager:
    """Manages up to 5 concurrent tactical Sniper slots."""

    def __init__(
        self,
        config: SniperConfig | None = None,
        on_event: Callable[[str, SniperSlot | None], None] | None = None,
        on_slot_assigned: Callable[[str], None] | None = None,
        on_slot_released: Callable[[str], None] | None = None,
    ):
        self.config = config or SniperConfig()
        if (
            self.config.max_slots < 1
            or self.config.l2_stale_seconds <= 0
            or self.config.paper_slippage_ticks < 0
            or self.config.orderbook_exit_mode not in {"legacy", "full"}
            or self.config.orderbook_wall_min_lots <= 0
            or self.config.orderbook_psychological_wall_min_lots <= 0
            or not 0 < self.config.orderbook_depletion_ratio < 1
            or self.config.orderbook_wall_ratio <= 0
            or self.config.orderbook_refill_min_lots <= 0
            or self.config.orderbook_support_levels < 1
            or self.config.orderbook_psychological_step <= 0
        ):
            raise ValueError("Konfigurasi Sniper tidak valid.")
        if self.config.orderbook_exit_mode == "full" and self.config.enable_hybrid_mode:
            raise ValueError("Mode orderbook-full belum mendukung hybrid tranche.")
        self.on_event = on_event
        self.on_slot_assigned = on_slot_assigned
        self.on_slot_released = on_slot_released
        self.slots: list[SniperSlot] = [
            SniperSlot(slot_id=i + 1) for i in range(self.config.max_slots)
        ]
        self.cooldowns: dict[str, datetime] = {}
        self.history: list[dict[str, Any]] = []
        self.books: dict[str, dict[str, Any]] = {}
        self.seen_trades: set[tuple[Any, ...]] = set()
        self.last_batch_trade_time: dict[str, datetime] = {}
        self.duplicates_ignored = 0
        self.late_ignored = 0

    def active_count(self) -> int:
        return sum(1 for s in self.slots if s.state != SniperState.IDLE)

    def find_slot_by_symbol(self, symbol: str) -> SniperSlot | None:
        for slot in self.slots:
            if slot.symbol == symbol and slot.state != SniperState.IDLE:
                return slot
        return None

    def find_free_slot(self) -> SniperSlot | None:
        for slot in self.slots:
            if slot.state == SniperState.IDLE:
                return slot
        return None

    def _least_active_watch_slot(self) -> SniperSlot | None:
        candidates = [slot for slot in self.slots if slot.state == SniperState.WATCHING]
        if not candidates:
            return None
        return min(candidates, key=lambda slot: (slot.last_trade_time or slot.watch_started_at or slot.alert_time, slot.watch_started_at or slot.alert_time))

    def _release_slot_now(self, slot: SniperSlot) -> None:
        symbol = slot.symbol
        slot.reset()
        if symbol and self.on_slot_released:
            self.on_slot_released(symbol)

    def _drop_watch_slot(self, slot: SniperSlot, now: datetime, outcome: str, reason: str) -> None:
        slot.state = SniperState.ABORTED
        slot.state_changed_time = now
        slot.reason = reason
        self._record_history(slot, outcome)
        if self.on_event:
            self.on_event(f"🔌 [WATCHLIST OUT] Slot {slot.slot_id}: {slot.symbol} {reason}", slot)
        self._release_slot_now(slot)

    def _fresh_book(self, symbol: str, now: datetime | None) -> dict[str, Any]:
        data = self.books.get(symbol, {})
        if not data or now is None:
            return {}
        result = dict(data)
        for side in ("bid", "offer"):
            stamp = data.get(f"{side}_updated_at")
            age = (now - stamp).total_seconds() if stamp is not None else None
            if age is None or age < 0 or age > self.config.l2_stale_seconds:
                result[f"{side}s"] = {}
                result[f"{side}_vol"] = 0.0
        return result if result.get("bids") or result.get("offers") else {}

    def handle_radar_alert(self, alert: RadarAlert) -> SniperSlot | None:
        """Called when MarketRadar fires an anomaly alert."""
        sym = alert.symbol
        if not sym or sym == "*":
            return None

        # Check pattern focus (default BREAKOUT_MOMENTUM)
        if self.config.focus_patterns and alert.pattern not in self.config.focus_patterns:
            return None

        # Check trading hours guard (reject alerts after 15:35 WIB or before 09:02 WIB)
        if self.config.enable_trading_hours_guard:
            tz_wib = timezone(timedelta(hours=7))
            ts = alert.timestamp
            t_wib = ts.replace(tzinfo=timezone.utc).astimezone(tz_wib) if ts.tzinfo is None else ts.astimezone(tz_wib)
            minute_of_day = t_wib.hour * 60 + t_wib.minute
            if minute_of_day < (9 * 60 + 2) or minute_of_day >= (15 * 60 + 35):
                return None

        # Check big caps and custom exclusions
        if self.config.exclude_big_caps:
            if sym in DEFAULT_BIG_CAPS or sym in self.config.custom_excluded_symbols:
                return None

        # Check price band (filter penny stocks or expensive stocks)
        if self.config.min_stock_price > 0 and alert.price_close < self.config.min_stock_price:
            return None
        if self.config.max_stock_price > 0 and alert.price_close > self.config.max_stock_price:
            return None

        now = alert.timestamp

        # Check if already tracked
        existing = self.find_slot_by_symbol(sym)
        if existing is not None:
            if existing.state == SniperState.WATCHING:
                existing.ref_price = alert.price_close
                existing.current_price = alert.price_close
                existing.peak_price = max(existing.peak_price, alert.price_close)
                existing.haka_streak = 0
                existing.watch_haka_time = None
                existing.reason = f"Radar reinforcement ({alert.pattern}) | Tetap pantau pullback"
            elif existing.state == SniperState.OBSERVING:
                existing.ttl_seconds = self.config.observation_timeout_seconds
                existing.reason = f"Radar reinforcement ({alert.pattern})! Memantau..."
            return existing

        # Check symbol cooldown
        cooldown_until = self.cooldowns.get(sym)
        if cooldown_until is not None and now < cooldown_until:
            return None

        slot = self.find_free_slot()
        if slot is None and self.config.orderbook_exit_mode == "full":
            slot = self._least_active_watch_slot()
            if slot is not None:
                self._drop_watch_slot(slot, now, "WATCHLIST_REPLACED", f"Diganti Radar baru {sym}")
        if slot is None:
            if self.on_event:
                self.on_event(
                    f"⚠️ [SNIPER BUSY] Semua {self.config.max_slots} slot penuh! Mengabaikan {sym}.",
                    None,
                )
            return None

        watching = self.config.orderbook_exit_mode == "full"
        slot.symbol = sym
        slot.state = SniperState.WATCHING if watching else SniperState.OBSERVING
        slot.pattern = alert.pattern
        slot.alert_time = now
        slot.state_changed_time = now
        slot.ref_price = alert.price_close
        slot.current_price = alert.price_close
        slot.peak_price = alert.price_close
        slot.ttl_seconds = _WATCHLIST_IDLE_SECONDS if watching else self.config.observation_timeout_seconds
        slot.reason = "Watchlist L2: Menunggu bid support absorb + refill" if watching else f"Observasi {self.config.observation_timeout_seconds:.0f}s: Menunggu konfirmasi HAKA..."
        slot.haka_streak = 0
        slot.observing_haka_lots = 0.0
        slot.observing_done_count = 0
        slot.observing_haka_value_idr = 0.0
        slot.observing_total_value_idr = 0.0
        slot.alert_velocity = alert.velocity
        slot.alert_haka_pct = alert.haka_pct
        slot.alert_net_flow_idr = alert.net_flow_idr
        slot.alert_delta_pct = alert.delta_pct
        # The five-minute watchlist TTL is based on DONE activity, not Radar alerts.
        slot.last_trade_time = None if watching else now
        slot.watch_started_at = now if watching else None
        slot.watch_support_ready = False
        slot.watch_haka_time = None

        # Optional terminal spawner
        if self.config.spawn_terminal:
            self._spawn_external_terminal(sym)

        if self.on_event:
            self.on_event(
                f"🔎 [WATCHLIST] Slot {slot.slot_id}: {sym} memantau L2 pullback @ {slot.ref_price:.0f}" if watching else f"🎯 [SNIPER ENGAGED] Slot {slot.slot_id}: {sym} masuk radar {alert.pattern} @ {slot.ref_price:.0f}",
                slot,
            )
        if self.on_slot_assigned:
            self.on_slot_assigned(sym)
        return slot

    def _spawn_external_terminal(self, symbol: str):
        """Spawn an external terminal window (macOS or fallback subprocess)."""
        cmd = f"uv run python index.py {symbol}"
        if sys.platform == "darwin":
            apple_script = f'''
            tell application "Terminal"
                do script "{cmd}"
                activate
            end tell
            '''
            try:
                subprocess.Popen(["osascript", "-e", apple_script])
            except Exception:
                pass
        else:
            try:
                subprocess.Popen([sys.executable, "index.py", symbol])
            except Exception:
                pass

    def _wall_key(self, side: str, price: float) -> tuple[str, float]:
        return side, float(price)

    def _wall_state(self, slot: SniperSlot, side: str, price: float, lot: float = 0.0) -> dict[str, Any]:
        key = self._wall_key(side, price)
        state = slot.wall_states.get(key)
        if state is None:
            state = {
                "initial_lots": max(0.0, float(lot)),
                "current_lots": max(0.0, float(lot)),
                "strong": False,
                "depleted": False,
                "broken": False,
                "converted": False,
                "depletion_count": 0,
                "refill_strikes": 0,
                "consumption_count": 0,
                "attack_count": 0,
                "last_refill_lots": 0.0,
            }
            slot.wall_states[key] = state
        elif state["initial_lots"] <= 0 and lot > 0:
            state["initial_lots"] = float(lot)
        return state

    def _wall_min_lots(self, symbol: str, *, psychological: bool) -> float:
        override = self.config.orderbook_symbol_wall_min_lots.get(symbol.upper())
        floor = float(override) if override is not None else self.config.orderbook_wall_min_lots
        if psychological:
            floor = max(floor, self.config.orderbook_psychological_wall_min_lots)
        return floor

    def _is_psychological_price(self, price: float) -> bool:
        step = self.config.orderbook_psychological_step
        return abs(price / step - round(price / step)) < 1e-6

    def _is_strong_wall(self, symbol: str, price: float, lot: float, levels: dict[float, float]) -> bool:
        if lot <= 0:
            return False
        psychological = self._is_psychological_price(price)
        neighbors = [
            value for other_price, value in sorted(
                (
                    (abs(p - price), value)
                    for p, value in levels.items()
                    if p != price and value > 0 and not self._is_psychological_price(p)
                ),
                key=lambda item: item[0],
            )[:3]
        ]
        baseline = median(neighbors) if neighbors else 0.0
        floor = self._wall_min_lots(symbol, psychological=psychological)
        return lot >= floor and (psychological or baseline <= 0 or lot >= baseline * self.config.orderbook_wall_ratio)

    def _record_wall_snapshot(
        self,
        slot: SniperSlot | None,
        symbol: str,
        side: str,
        previous: dict[float, float],
        current: dict[float, float],
    ) -> None:
        """Track wall depletion/refill transitions from one complete side snapshot."""
        if slot is None:
            return

        all_prices = set(previous) | set(current)
        for price in all_prices:
            old_lot = float(previous.get(price, 0.0))
            new_lot = float(current.get(price, 0.0))
            state = self._wall_state(slot, side, price, old_lot or new_lot)
            levels_for_strength = current or previous
            state["strong"] = self._is_strong_wall(symbol, price, new_lot, levels_for_strength)
            initial = float(state.get("initial_lots", 0.0))

            if new_lot <= 0 < old_lot:
                state["consumption_count"] += 1
                state["depleted"] = True
                state["depletion_count"] += 1
                state["broken"] = True
                state["current_lots"] = 0.0
                if side == "OFFER" and slot.state == SniperState.ENTERED and price >= slot.entry_price and (old_lot > 0 or previous):
                    slot.offer_was_consumed[price] = True
                continue

            if old_lot > 0 and new_lot < old_lot:
                state["consumption_count"] += 1
                if initial > 0 and new_lot <= initial * self.config.orderbook_depletion_ratio:
                    if not state["depleted"]:
                        state["depletion_count"] += 1
                    state["depleted"] = True
                state["current_lots"] = new_lot
                if side == "OFFER" and slot.state == SniperState.ENTERED and price >= slot.entry_price and (old_lot > 0 or previous):
                    slot.offer_was_consumed[price] = True
                continue

            if new_lot > old_lot:
                refill = new_lot - old_lot
                state["current_lots"] = new_lot
                if side == "OFFER" and slot.state == SniperState.ENTERED and price >= slot.entry_price and (old_lot > 0 or previous):
                    slot.active_offer_refills[price] = slot.active_offer_refills.get(price, 0.0) + refill
                    current_strikes = slot.active_offer_refill_strikes.get(price, 0)
                    if slot.offer_was_consumed.get(price, False) and refill >= self.config.dynamic_tp_strike_min_refill_lots:
                        slot.active_offer_refill_strikes[price] = current_strikes + 1
                        slot.offer_was_consumed[price] = False
                    elif current_strikes == 0 and refill >= self.config.dynamic_tp_strike_min_refill_lots:
                        slot.active_offer_refill_strikes[price] = 1
                        slot.offer_was_consumed[price] = False
                elif side == "BID" and slot.state == SniperState.ENTERED and price <= slot.entry_price:
                    slot.active_bid_refills[price] = slot.active_bid_refills.get(price, 0.0) + refill
                if state.get("depleted") and refill >= self.config.orderbook_refill_min_lots:
                    state["refill_strikes"] += 1
                    state["last_refill_lots"] = refill
                    state["depleted"] = bool(initial > 0 and new_lot <= initial * self.config.orderbook_depletion_ratio)
                elif initial <= 0:
                    state["initial_lots"] = new_lot
                elif state.get("refill_strikes", 0) == 0 and not state.get("depleted"):
                    state["initial_lots"] = max(initial, new_lot)
                continue

            if new_lot > 0:
                state["current_lots"] = new_lot
                if initial <= 0:
                    state["initial_lots"] = new_lot

        if side == "OFFER":
            for price, state in slot.wall_states.items():
                if price[0] == "OFFER" and price[1] not in current and price[1] in previous:
                    state["broken"] = True

    def _entry_support(self, slot: SniperSlot, symbol: str, bids: dict[float, float], entry_price: float) -> float:
        candidates = sorted((p for p in bids if p < entry_price), reverse=True)
        for price in candidates[: self.config.orderbook_support_levels]:
            if self._is_strong_wall(symbol, price, bids[price], bids):
                return price
        return 0.0

    def _watch_support(self, symbol: str, bids: dict[float, float], price: float) -> float:
        for level in sorted((p for p in bids if p <= price), reverse=True):
            if self._is_strong_wall(symbol, level, bids[level], bids):
                return level
        return 0.0

    def _refresh_watch_support(self, slot: SniperSlot, symbol: str, b_data: dict[str, Any], stamp: datetime) -> None:
        if slot.state != SniperState.WATCHING:
            return
        bids = b_data.get("bids", {})
        support = slot.active_support_price
        if support > 0 and support not in bids:
            state = slot.wall_states.get(self._wall_key("BID", support), {})
            if state.get("depleted"):
                self._drop_watch_slot(slot, stamp, "WATCHLIST_SUPPORT_BROKEN", f"Bid support {support:.0f} hilang tanpa refill")
            return
        if support <= 0:
            support = self._watch_support(symbol, bids, slot.current_price)
            if support <= 0:
                slot.reason = "Watchlist L2: Menunggu bid support kuat"
                return
            self._set_support(slot, support, bids[support])
            slot.watch_support_ready = False
            slot.haka_streak = 0
            slot.watch_haka_time = None

        state = self._wall_state(slot, "BID", support, bids.get(support, 0.0))
        strong = self._is_strong_wall(symbol, support, bids.get(support, 0.0), bids)
        slot.watch_support_ready = strong and state.get("refill_strikes", 0) >= self.config.dynamic_tp_min_refill_strikes
        if slot.watch_support_ready:
            slot.reason = f"Bid {support:.0f} absorb/refill {state['refill_strikes']}x | Menunggu {self.config.min_haka_streak} HAKA"

    def _enter_watchlist_position(self, slot: SniperSlot, price: float, ts: datetime, bids: dict[float, float]) -> None:
        self._set_support(slot, slot.active_support_price, bids.get(slot.active_support_price, 0.0))
        slot.state = SniperState.ENTERED
        slot.state_changed_time = ts
        slot.entry_time = ts
        slot.entry_price = price
        slot.target_price = 0.0
        slot.pnl_pct = 0.0
        slot.is_hybrid = False
        slot.total_lots = max(1, round(self.config.trade_capital_idr / (price * 100)))
        slot.reason = f"Entry Pullback @ {price:.0f} | Bid support {slot.active_support_price:.0f} absorb/refill"
        if self.on_event:
            self.on_event(
                f"🚀 [WATCHLIST ENTRY] Slot {slot.slot_id}: {slot.symbol} HAKA pullback @ {price:.0f} | Support {slot.active_support_price:.0f} | CL: {slot.stop_loss_price:.0f}",
                slot,
            )

    def _process_watch_trade(self, slot: SniperSlot, symbol: str, price: float, side_code: int, ts: datetime, book_now: datetime) -> None:
        slot.last_trade_time = ts
        support = slot.active_support_price
        if side_code == 2:
            slot.haka_streak = 0
            slot.watch_haka_time = None
            if support > 0 and price < support:
                self._drop_watch_slot(slot, ts, "WATCHLIST_SUPPORT_BROKEN", f"HAKI menembus bid support {support:.0f} @ {price:.0f}")
            return

        if side_code != 1 or not slot.watch_support_ready or support <= 0:
            return
        b_data = self._fresh_book(symbol, book_now)
        bids, offers = b_data.get("bids", {}), b_data.get("offers", {})
        if not bids or not offers or not self._is_strong_wall(symbol, support, bids.get(support, 0.0), bids):
            slot.haka_streak = 0
            slot.watch_haka_time = None
            slot.reason = "Watchlist: L2 stale atau bid support tidak lagi kuat"
            return

        tick = get_idx_tick_size(support)
        if not support <= price <= support + tick:
            slot.haka_streak = 0
            slot.watch_haka_time = None
            slot.reason = f"HAKA @ {price:.0f} terlalu jauh dari support {support:.0f}"
            return
        if slot.watch_haka_time is None or (ts - slot.watch_haka_time).total_seconds() > _WATCHLIST_HAKA_WINDOW_SECONDS:
            slot.haka_streak = 1
        else:
            slot.haka_streak += 1
        slot.watch_haka_time = ts
        if slot.haka_streak >= self.config.min_haka_streak:
            self._enter_watchlist_position(slot, price, ts, bids)
        else:
            slot.reason = f"Bid {support:.0f} siap | HAKA {slot.haka_streak}/{self.config.min_haka_streak}"

    def _next_resistance(self, slot: SniperSlot, symbol: str, offers: dict[float, float], price: float) -> float:
        candidates = sorted(p for p in offers if p >= price)
        for level in candidates:
            state = self._wall_state(slot, "OFFER", level, offers[level])
            if state.get("strong") or self._is_strong_wall(symbol, level, offers[level], offers):
                return level
        return 0.0

    def _set_support(self, slot: SniperSlot, price: float, lots: float = 0.0, *, converted: bool = False) -> None:
        if price <= 0:
            return
        slot.active_support_price = price
        state = self._wall_state(slot, "BID", price, lots)
        if converted:
            state["converted"] = True
        tick = get_idx_tick_size(price)
        slot.stop_loss_price = round_to_idx_tick(max(tick, price - tick))

    def _full_entry_ready(
        self,
        slot: SniperSlot,
        symbol: str,
        price: float,
        book_now: datetime,
        l2_ok: bool,
    ) -> bool:
        if not l2_ok or not slot.entry_ready or slot.observing_done_count <= slot.entry_ready_done_count:
            return False
        b_data = self._fresh_book(symbol, book_now)
        bids = b_data.get("bids", {})
        offers = b_data.get("offers", {})
        if not bids or not offers or slot.entry_offer_price <= 0 or price < slot.entry_offer_price:
            return False
        offer_state = slot.wall_states.get(self._wall_key("OFFER", slot.entry_offer_price), {})
        if offer_state.get("refill_strikes", 0) > 0 or not offer_state.get("converted"):
            return False
        support = self._entry_support(slot, symbol, bids, price)
        if support <= 0:
            slot.reason = f"Entry ditahan: tidak ada bid support kuat dalam {self.config.orderbook_support_levels} papan"
            return False
        self._set_support(slot, support, bids.get(support, 0.0))
        return True

    def _close_full_orderbook(
        self,
        slot: SniperSlot,
        outcome: str,
        ts: datetime,
        signal_price: float,
        reason_code: str,
        reason: str,
    ) -> None:
        signal_price = round_to_idx_tick(max(0.0, signal_price))
        slot.state_changed_time = ts
        slot.exit_signal_price = signal_price
        slot.exit_fill_price = _paper_fill(signal_price, False, self.config.paper_slippage_ticks)
        slot.current_price = signal_price
        slot.pnl_pct = round((signal_price - slot.entry_price) / slot.entry_price * 100.0, 2) if slot.entry_price else 0.0
        slot.exit_reason_code = reason_code
        slot.reason = reason
        slot.state = SniperState.EXIT_TP if outcome == "TAKE_PROFIT" else SniperState.EXIT_CL
        cooldown = self.config.cooldown_seconds if outcome == "TAKE_PROFIT" else self.config.cl_cooldown_seconds
        if slot.symbol:
            self.cooldowns[slot.symbol] = ts + timedelta(seconds=cooldown)
        self._record_history(slot, outcome)
        if self.on_event:
            icon = "💰" if outcome == "TAKE_PROFIT" else "🛑"
            self.on_event(f"{icon} [SNIPER ORDERBOOK] Slot {slot.slot_id}: {slot.symbol} {reason}", slot)

    def _process_full_orderbook_exit(
        self,
        slot: SniperSlot,
        symbol: str,
        price: float,
        side_code: int,
        ts: datetime,
        b_data: dict[str, Any],
    ) -> bool:
        bids = b_data.get("bids", {})
        offers = b_data.get("offers", {})
        if not bids and not offers:
            self._close_full_orderbook(
                slot, "CUT_LOSS", ts, price, "EMERGENCY_L2_STALE",
                f"Emergency L2 stale/disconnect -> exit @ {price:.0f}",
            )
            return True

        support = slot.active_support_price
        if support <= 0:
            support = self._entry_support(slot, symbol, bids, min(price, slot.entry_price)) if bids else 0.0
            if support > 0:
                self._set_support(slot, support, bids.get(support, 0.0))

        resistance = slot.active_resistance_price
        if resistance <= 0 or price > resistance:
            resistance = self._next_resistance(slot, symbol, offers, price)
            if resistance > 0:
                slot.active_resistance_price = resistance

        if support > 0 and side_code == 2 and price <= support + get_idx_tick_size(support):
            state = self._wall_state(slot, "BID", support, bids.get(support, 0.0))
            state["attack_count"] += 1
            if state.get("depleted") and state.get("refill_strikes", 0) >= self.config.dynamic_tp_min_refill_strikes and price <= support:
                signal = support - get_idx_tick_size(support)
                self._close_full_orderbook(
                    slot, "CUT_LOSS", ts, signal, "SUPPORT_BREAK",
                    f"Support bid {support:.0f} jebol setelah {state['refill_strikes']}x refill -> CL @ {signal:.0f}",
                )
                return True

        if resistance > 0 and side_code == 1 and price >= resistance - get_idx_tick_size(resistance):
            state = self._wall_state(slot, "OFFER", resistance, offers.get(resistance, 0.0))
            state["attack_count"] += 1

        if resistance > 0 and side_code == 2 and price < resistance:
            state = self._wall_state(slot, "OFFER", resistance, offers.get(resistance, 0.0))
            if state.get("refill_strikes", 0) >= self.config.dynamic_tp_min_refill_strikes and state.get("attack_count", 0) > 0 and not state.get("converted"):
                signal = resistance - get_idx_tick_size(resistance)
                self._close_full_orderbook(
                    slot, "TAKE_PROFIT", ts, signal, "RESISTANCE_REFILL",
                    f"Resistance offer {resistance:.0f} gagal lanjut setelah {state['refill_strikes']}x refill -> TP @ {signal:.0f}",
                )
                return True
        return False

    def process_trade(self, trade: dict[str, Any], current_time: datetime | None = None):
        """Update active slots with incoming running trade."""
        sym = trade.get("symbol")
        if not sym:
            return

        slot = self.find_slot_by_symbol(sym)
        if slot is None:
            return

        price = float(trade.get("price", 0.0))
        if price <= 0:
            return

        ts = trade.get("exchange_time") or current_time or datetime.now(timezone.utc)
        book_now = current_time or ts
        side_code = trade.get("sideCode", 0)  # 1 = HAKA, 2 = HAKI

        slot.current_price = price
        slot.peak_price = max(slot.peak_price, price)

        if slot.state == SniperState.WATCHING:
            self._process_watch_trade(slot, sym, price, side_code, ts, book_now)
            return

        # 1. State: OBSERVING -> Confirm Entry or track
        if slot.state == SniperState.OBSERVING:
            slot.observing_done_count += 1
            lot = float(trade.get("lot", trade.get("shares", 0.0) / 100.0))
            trade_val = lot * 100.0 * price
            slot.observing_total_value_idr += trade_val

            if side_code == 1:  # HAKA
                slot.haka_streak += 1
                slot.observing_haka_lots += lot
                slot.observing_haka_value_idr += trade_val
            else:
                slot.haka_streak = max(0, slot.haka_streak - 1)

            # Check Tape Silence during observation:
            # If the gap between trades exceeds max_tape_silence_seconds, abort!
            if self.config.max_tape_silence_seconds > 0 and slot.last_trade_time is not None:
                silence = (ts - slot.last_trade_time).total_seconds()
                if silence > self.config.max_tape_silence_seconds:
                    slot.state = SniperState.ABORTED
                    slot.state_changed_time = ts
                    slot.reason = f"Tape hening {silence:.1f}s > {self.config.max_tape_silence_seconds:.1f}s. Abort!"
                    if slot.symbol:
                        self.cooldowns[slot.symbol] = ts + timedelta(seconds=self.config.cooldown_seconds)
                    self._record_history(slot, "ABORTED_TAPE_SILENCE")
                    if self.on_event:
                        self.on_event(
                            f"⚠️ [SNIPER ABORT] Slot {slot.slot_id}: {slot.symbol} dibatalkan karena tape hening ({silence:.1f}s).",
                            slot,
                        )
                    return
            slot.last_trade_time = ts

            # Continuous Done Flow & Confirmation Conditions:
            obs_duration = (ts - slot.alert_time).total_seconds() if slot.alert_time else 0.0
            has_duration = obs_duration >= self.config.min_observation_seconds
            has_trades_count = slot.observing_done_count >= self.config.min_observing_done_trades
            has_haka_val = (
                slot.observing_haka_value_idr >= self.config.min_observing_haka_value_idr
                if self.config.min_observing_haka_value_idr > 0
                else True
            )
            has_volume = (
                slot.observing_haka_lots >= self.config.min_follow_through_haka_lots
                if self.config.min_follow_through_haka_lots > 0
                else True
            )
            # A repeated print at the alert price is not continuation; require a real price advance.
            price_condition = price > slot.ref_price and (slot.haka_streak >= 1 or self.config.orderbook_exit_mode == "full")

            # L2 Order Book Pre-Entry Guard
            l2_ok = True
            if self.config.enable_l2_pre_entry_guard:
                b_data = self._fresh_book(sym, book_now)
                bids = b_data.get("bids", {})
                offers = b_data.get("offers", {})
                b_vol = b_data.get("bid_vol", 0.0)
                o_vol = b_data.get("offer_vol", 0.0)
                if not (bids or offers or b_vol > 0 or o_vol > 0):
                    l2_ok = False
                else:
                    ratio = b_vol / max(1.0, o_vol)
                    top_bids = sorted(bids.keys(), reverse=True)[:3]
                    top_bid_lots = sum(bids[p] for p in top_bids) if top_bids else b_vol
                    if ratio < self.config.l2_pre_entry_min_bid_ratio or top_bid_lots < self.config.l2_pre_entry_min_bid_lots:
                        l2_ok = False

            full_orderbook_entry = True
            if self.config.orderbook_exit_mode == "full":
                full_orderbook_entry = self._full_entry_ready(slot, sym, price, book_now, l2_ok)

            if price_condition and has_volume and has_duration and has_trades_count and has_haka_val and l2_ok and full_orderbook_entry:
                slot.state = SniperState.ENTERED
                slot.state_changed_time = ts
                slot.entry_time = ts
                slot.entry_price = price
                if self.config.orderbook_exit_mode == "full":
                    slot.target_price = 0.0
                    slot.reason = (
                        f"Entry Order Book @ {price:.0f} | Support {slot.active_support_price:.0f} | "
                        f"Offer {slot.entry_offer_price:.0f} -> Bid"
                    )
                else:
                    # Targets use valid IDX ticks and include the configured adverse paper fill.
                    paper_entry = _paper_fill(price, True, self.config.paper_slippage_ticks)
                    target_fill = paper_entry * (1.0 + self.config.target_tp_pct / 100.0)
                    slot.target_price = _signal_price_for_minimum_exit_fill(target_fill, self.config.paper_slippage_ticks)
                    # Trigger whichever risk limit is reached first: percentage or N real IDX ticks below reference.
                    stop_fill = paper_entry * (1.0 - self.config.stop_loss_pct / 100.0)
                    sl_by_pct = (
                        _signal_price_for_maximum_exit_fill(stop_fill, self.config.paper_slippage_ticks)
                        if self.config.paper_slippage_ticks > 0
                        else _signal_price_for_minimum_exit_fill(stop_fill, self.config.paper_slippage_ticks)
                    )
                    ref_tick = get_idx_tick_size(slot.ref_price)
                    sl_by_ref = max(ref_tick, slot.ref_price - self.config.stop_loss_ticks * ref_tick)
                    raw_stop = max(sl_by_pct, sl_by_ref)
                    slot.stop_loss_price = math.ceil(raw_stop / get_idx_tick_size(raw_stop)) * get_idx_tick_size(raw_stop)
                slot.pnl_pct = 0.0

                # Setup Hybrid Mode if enabled
                lot_price = price * 100
                total_lots = max(1, round(self.config.trade_capital_idr / lot_price)) if lot_price > 0 else 1
                if self.config.enable_hybrid_mode and total_lots >= 2:
                    slot.is_hybrid = True
                    slot.total_lots = total_lots
                    slot.tranche1_lots = round(total_lots * self.config.hybrid_scalp_ratio)
                    slot.tranche2_lots = total_lots - slot.tranche1_lots
                    slot.tranche1_status = "PENDING"
                    slot.tranche2_status = "PENDING"
                    slot.runner_trailing_stop_price = slot.stop_loss_price
                    slot.effective_max_holding_seconds = self.config.hybrid_runner_max_hold_seconds
                    slot.reason = (
                        f"Entry Hybrid @ {price:.0f} (T1: {slot.tranche1_lots}L, T2: {slot.tranche2_lots}L) | "
                        f"TP1: {slot.target_price:.0f} | SL: {slot.stop_loss_price:.0f}"
                    )
                    if self.on_event:
                        self.on_event(
                            f"🚀 [HYBRID ENTRY] Slot {slot.slot_id}: {sym} ENTERED @ {price:.0f} "
                            f"(T1 Scalp: {slot.tranche1_lots}L, T2 Runner: {slot.tranche2_lots}L) | "
                            f"TP1: {slot.target_price:.0f} | Trail SL: {slot.stop_loss_price:.0f}",
                            slot,
                        )
                else:
                    slot.is_hybrid = False
                    slot.total_lots = total_lots
                    if self.config.orderbook_exit_mode == "full":
                        slot.reason = (
                            f"Entry Order Book @ {price:.0f} | Support {slot.active_support_price:.0f} "
                            f"(CL {slot.stop_loss_price:.0f}) | Offer {slot.entry_offer_price:.0f} -> Bid"
                        )
                    else:
                        slot.reason = f"Entry terkonfirmasi @ {price:.0f} ({slot.observing_haka_lots:.0f} lot HAKA) | Target: {slot.target_price:.0f}"
                    if self.on_event:
                        entry_details = (
                            f"Support {slot.active_support_price:.0f} | Offer {slot.entry_offer_price:.0f} -> Bid"
                            if self.config.orderbook_exit_mode == "full"
                            else f"TP: {slot.target_price:.0f}"
                        )
                        self.on_event(
                            f"🚀 [SNIPER ENTRY] Slot {slot.slot_id}: {sym} ENTERED @ {price:.0f} ({slot.observing_haka_lots:.0f} lot HAKA) | {entry_details} | CL: {slot.stop_loss_price:.0f}",
                            slot,
                        )
            return

        # 2. State: ENTERED -> Check Take-Profit & Cut-Loss
        if slot.state == SniperState.ENTERED:
            if slot.entry_price > 0:
                slot.pnl_pct = round((price - slot.entry_price) / slot.entry_price * 100.0, 2)

            b_data = self._fresh_book(sym, book_now)
            bids = b_data.get("bids", {})
            offers = b_data.get("offers", {})
            best_bid = max(bids.keys()) if bids else price
            best_offer = min(offers.keys()) if offers else price

            if self.config.orderbook_exit_mode == "full":
                if self._process_full_orderbook_exit(slot, sym, price, side_code, ts, b_data):
                    return
                return

            # Dynamic Trailing Stop for Tranche 2 in Hybrid Mode
            # Operates on every trade tick (works both with L2 depth and in --all wildcard mode)
            if self.config.orderbook_exit_mode != "full" and slot.is_hybrid and slot.tranche1_status == "FILLED":
                # 1. Breakeven + Fee Buffer Floor: Once T1 is secured, runner stop must never fall below entry + buffer ticks
                bep_floor = _paper_break_even_signal(slot.entry_price, self.config)
                target_trail = max(slot.runner_trailing_stop_price, bep_floor)
                reason_source = f"BEP+{self.config.hybrid_runner_be_buffer_ticks}tick"

                # 2. Peak-based trailing using official IDX tick fractions
                tick_size = get_idx_tick_size(slot.peak_price)
                peak_raw = slot.peak_price - (self.config.hybrid_runner_trailing_ticks * tick_size)
                peak_trail = max(bep_floor, round_to_idx_tick(peak_raw))
                if peak_trail > target_trail:
                    target_trail = peak_trail
                    reason_source = f"Peak {slot.peak_price:.0f} - {self.config.hybrid_runner_trailing_ticks} ticks"

                # 3. Order Book Bid Wall trailing (if L2 depth data is available)
                if bids:
                    candidate_supports = [
                        p for p, lot in bids.items()
                        if slot.entry_price <= p < price and lot >= 20_000.0
                    ]
                    if candidate_supports:
                        wall_sup = max(candidate_supports)
                        wall_tick = get_idx_tick_size(wall_sup)
                        wall_trail = wall_sup - wall_tick
                        if wall_trail > target_trail:
                            target_trail = wall_trail
                            reason_source = f"Benteng Bid {wall_sup:.0f} @ {bids[wall_sup]:,.0f} lot"

                # Apply if trailing stop has moved up
                if target_trail > slot.runner_trailing_stop_price:
                    slot.runner_trailing_stop_price = target_trail
                    if slot.tranche1_exit_price:
                        slot.reason = (
                            f"Tranche 1 TP @ {slot.tranche1_exit_price:.0f} (+{slot.tranche1_pnl_pct:.1f}%) | "
                            f"Runner ({slot.tranche2_lots}L) trailing support {slot.runner_trailing_stop_price:.0f}"
                        )
                    if self.on_event:
                        self.on_event(
                            f"🛡️ [RUNNER TRAIL] Slot {slot.slot_id}: {sym} Trailing Stop dinaikkan ke {target_trail:.0f} ({reason_source})",
                            slot,
                        )

            # Dynamic Trailing Stop for Non-Hybrid Mode (100% position)
            # Activates once peak price reaches profit (peak >= entry + 2 ticks or >= 1.0%)
            elif self.config.orderbook_exit_mode != "full" and not slot.is_hybrid and slot.entry_price > 0:
                entry_tick = get_idx_tick_size(slot.entry_price)
                bep_floor = _paper_break_even_signal(slot.entry_price, self.config)

                if slot.peak_price >= round_to_idx_tick(slot.entry_price + (2 * entry_tick)):
                    target_trail = max(slot.stop_loss_price, bep_floor)
                    reason_source = f"BEP+{self.config.hybrid_runner_be_buffer_ticks}tick"

                    # 1. Peak-based trailing using official IDX tick fractions
                    tick_size = get_idx_tick_size(slot.peak_price)
                    peak_raw = slot.peak_price - (self.config.hybrid_runner_trailing_ticks * tick_size)
                    peak_trail = max(bep_floor, round_to_idx_tick(peak_raw))
                    if peak_trail > target_trail:
                        target_trail = peak_trail
                        reason_source = f"Peak {slot.peak_price:.0f} - {self.config.hybrid_runner_trailing_ticks} ticks"

                    # 2. Order Book Bid Wall trailing (if L2 depth data is available)
                    if bids:
                        candidate_supports = [
                            p for p, lot in bids.items()
                            if slot.entry_price <= p < price and lot >= 20_000.0
                        ]
                        if candidate_supports:
                            wall_sup = max(candidate_supports)
                            wall_tick = get_idx_tick_size(wall_sup)
                            wall_trail = wall_sup - wall_tick
                            if wall_trail > target_trail:
                                target_trail = wall_trail
                                reason_source = f"Benteng Bid {wall_sup:.0f} @ {bids[wall_sup]:,.0f} lot"

                    # Apply if stop loss has moved up
                    if target_trail > slot.stop_loss_price and price >= target_trail:
                        slot.stop_loss_price = target_trail
                        slot.reason = f"Trailing Stop dikunci @ {slot.stop_loss_price:.0f} ({reason_source}) | Peak {slot.peak_price:.0f}"
                        if self.on_event:
                            self.on_event(
                                f"🛡️ [SNIPER TRAIL] Slot {slot.slot_id}: {sym} Trailing Stop dinaikkan ke {target_trail:.0f} ({reason_source})",
                                slot,
                            )

            # Dynamic Order Book & Tape Reading logic (if enabled and order book exists)
            if self.config.enable_orderbook_tape_reading and b_data and self.config.orderbook_exit_mode != "full":
                support_p = slot.stop_loss_price if slot.stop_loss_price > 0 else (slot.entry_price - 2.0)
                s_lot = bids.get(support_p, 0.0)
                b_refill = slot.active_bid_refills.get(support_p, 0.0)
                is_absorbed = (s_lot >= 25_000.0 or b_refill >= self.config.dynamic_cl_absorb_lots)

                # Smart Absorption Hold Extension
                holding_sec = (ts - slot.entry_time).total_seconds() if slot.entry_time else 0.0
                effective_max_hold = slot.effective_max_holding_seconds or self.config.max_holding_seconds
                if is_absorbed and not slot.hold_extended and holding_sec >= (effective_max_hold - 30.0):
                    slot.effective_max_holding_seconds = effective_max_hold + self.config.absorption_hold_extension_seconds
                    slot.hold_extended = True
                    slot.reason = f"Absorpsi support {support_p:.0f} aktif (+{b_refill:,.0f} lot)! Hold untuk rebound..."

                # Dynamic Take-Profit on Iceberg Offer Refill (Multi-wave / 2-Strike Confirmation)
                large_offer_refill = any(
                    ref >= self.config.dynamic_tp_refill_lots
                    and slot.active_offer_refill_strikes.get(p, 1 if self.config.dynamic_tp_min_refill_strikes <= 1 else 0) >= self.config.dynamic_tp_min_refill_strikes
                    for p, ref in slot.active_offer_refills.items()
                    if p >= slot.peak_price
                )
                is_retreating = (price < slot.peak_price and side_code == 2)
                in_profit = (best_bid > slot.entry_price)

                if large_offer_refill and is_retreating and in_profit:
                    ref_details = [
                        f"{p:.0f} (+{ref:,.0f}L, {slot.active_offer_refill_strikes.get(p, 1)}x refill)"
                        for p, ref in slot.active_offer_refills.items()
                        if ref >= self.config.dynamic_tp_refill_lots
                        and slot.active_offer_refill_strikes.get(p, 1 if self.config.dynamic_tp_min_refill_strikes <= 1 else 0) >= self.config.dynamic_tp_min_refill_strikes
                        and p >= slot.peak_price
                    ]
                    if slot.is_hybrid and slot.tranche1_status == "PENDING":
                        # Execute Tranche 1 Take-Profit only!
                        slot.tranche1_status = "FILLED"
                        slot.tranche1_exit_price = best_bid
                        slot.tranche1_exit_time = ts
                        slot.tranche1_pnl_pct = round((best_bid - slot.entry_price) / slot.entry_price * 100.0, 2)
                        val_in = slot.tranche1_lots * slot.entry_price * 100
                        val_out = slot.tranche1_lots * best_bid * 100
                        fee_buy = val_in * (self.config.fee_buy_pct / 100.0)
                        fee_sell = val_out * (self.config.fee_sell_pct / 100.0)
                        slot.tranche1_gross_idr = round(val_out - val_in, 2)
                        slot.tranche1_fee_idr = round(fee_buy + fee_sell, 2)
                        slot.tranche1_net_idr = round(slot.tranche1_gross_idr - slot.tranche1_fee_idr, 2)
                        slot.tranche1_reason = f"Dynamic TP: Offer Wall {ref_details} di-refill berulang -> HAKI @ {best_bid:.0f}"
                        # Secure Breakeven + Fee Buffer floor for Tranche 2 immediately!
                        bep_floor = _paper_break_even_signal(slot.entry_price, self.config)
                        slot.runner_trailing_stop_price = max(slot.runner_trailing_stop_price, bep_floor)
                        slot.reason = (
                            f"Tranche 1 TP @ {best_bid:.0f} (+{slot.tranche1_pnl_pct:.1f}%, Net +Rp {slot.tranche1_net_idr:,.0f}) | "
                            f"Runner ({slot.tranche2_lots}L) trailing support {slot.runner_trailing_stop_price:.0f}"
                        )
                        if self.on_event:
                            self.on_event(
                                f"💰 [HYBRID T1 TP] Slot {slot.slot_id}: {sym} Tranche 1 ({slot.tranche1_lots} lot) TP @ {best_bid:.0f} "
                                f"(+{slot.tranche1_pnl_pct:.1f}%) Net +Rp {slot.tranche1_net_idr:,.0f} | Iceberg {ref_details} | Runner ({slot.tranche2_lots} lot) Aktif...",
                                slot,
                            )
                        return
                    elif not slot.is_hybrid:
                        slot.state = SniperState.EXIT_TP
                        slot.state_changed_time = ts
                        slot.current_price = best_bid
                        slot.pnl_pct = round((best_bid - slot.entry_price) / slot.entry_price * 100.0, 2)
                        slot.reason = f"Dynamic TP: Offer Wall {ref_details} di-refill berulang -> HAKI @ {best_bid:.0f} (+{slot.pnl_pct:.1f}%)"
                        self.cooldowns[sym] = ts + timedelta(seconds=self.config.cooldown_seconds)
                        self._record_history(slot, "TAKE_PROFIT")
                        if self.on_event:
                            self.on_event(
                                f"💰 [SNIPER DYNAMIC TP] Slot {slot.slot_id}: {sym} TAKE-PROFIT @ {best_bid:.0f} (+{slot.pnl_pct:.1f}%) | Iceberg {ref_details}",
                                slot,
                            )
                        return

                # 3. Dynamic Cut-Loss with Absorption Defense
                max_bid_support = max((bids.get(p, 0.0) for p in bids if p <= slot.entry_price), default=0.0)
                total_bid_refill = sum(slot.active_bid_refills.values())
                is_absorbed = (max_bid_support >= 25_000.0 or total_bid_refill >= self.config.dynamic_cl_absorb_lots)

                effective_stop_p = slot.runner_trailing_stop_price if (slot.is_hybrid and slot.tranche1_status == "FILLED") else support_p

                if price <= effective_stop_p:
                    if is_absorbed:
                        slot.reason = f"Support diabsorpsi/dipertahankan ({max_bid_support:,.0f} lot, +{total_bid_refill:,.0f} refill) -> Menahan posisi..."
                        return
                    elif s_lot < 5_000.0 and price < effective_stop_p:
                        exit_price = best_bid if best_bid > 0 else (effective_stop_p - 2.0)
                        if slot.is_hybrid and slot.tranche1_status == "FILLED":
                            slot.tranche2_status = "STOPPED"
                            slot.tranche2_exit_price = exit_price
                            slot.tranche2_exit_time = ts
                            slot.tranche2_pnl_pct = round((exit_price - slot.entry_price) / slot.entry_price * 100.0, 2)
                            val_in = slot.tranche2_lots * slot.entry_price * 100
                            val_out = slot.tranche2_lots * exit_price * 100
                            fee_buy = val_in * (self.config.fee_buy_pct / 100.0)
                            fee_sell = val_out * (self.config.fee_sell_pct / 100.0)
                            slot.tranche2_gross_idr = round(val_out - val_in, 2)
                            slot.tranche2_fee_idr = round(fee_buy + fee_sell, 2)
                            slot.tranche2_net_idr = round(slot.tranche2_gross_idr - slot.tranche2_fee_idr, 2)
                            slot.tranche2_reason = f"Support {effective_stop_p:.0f} jebol -> CL Runner @ {exit_price:.0f}"

                            total_net = round(slot.tranche1_net_idr + slot.tranche2_net_idr, 2)
                            slot.state = SniperState.EXIT_TP if total_net > 0 else SniperState.EXIT_CL
                            slot.state_changed_time = ts
                            slot.current_price = exit_price
                            pnl_sign = "+" if total_net >= 0 else ""
                            slot.reason = (
                                f"Hybrid Selesai: T1 TP +Rp {slot.tranche1_net_idr:,.0f} | "
                                f"T2 CL Rp {slot.tranche2_net_idr:,.0f} (Net: {pnl_sign}Rp {total_net:,.0f})"
                            )
                            self.cooldowns[sym] = ts + timedelta(seconds=self.config.cooldown_seconds)
                            self._record_history(slot, "TAKE_PROFIT" if total_net > 0 else "CUT_LOSS")
                            if self.on_event:
                                self.on_event(
                                    f"🏁 [HYBRID COMPLETED] Slot {slot.slot_id}: {sym} Runner stopped @ {exit_price:.0f}. "
                                    f"Total Net: {pnl_sign}Rp {total_net:,.0f}",
                                    slot,
                                )
                            return
                        else:
                            slot.state_changed_time = ts
                            slot.current_price = exit_price
                            slot.pnl_pct = round((exit_price - slot.entry_price) / slot.entry_price * 100.0, 2)
                            pnl_sign = "+" if slot.pnl_pct >= 0 else ""
                            is_profit = slot.pnl_pct > 0
                            slot.state = SniperState.EXIT_TP if is_profit else SniperState.EXIT_CL
                            if is_profit:
                                slot.reason = f"Trailing Stop HIT @ {exit_price:.0f} ({pnl_sign}{slot.pnl_pct:.1f}%)! Mengamankan profit."
                                self.cooldowns[sym] = ts + timedelta(seconds=self.config.cooldown_seconds)
                                self._record_history(slot, "TAKE_PROFIT")
                                if self.on_event:
                                    self.on_event(
                                        f"💰 [SNIPER TRAIL TP] Slot {slot.slot_id}: {sym} TRAILING TP @ {exit_price:.0f} ({pnl_sign}{slot.pnl_pct:.1f}%)",
                                        slot,
                                    )
                            else:
                                slot.reason = f"Dynamic CL: Support benteng {effective_stop_p:.0f} jebol tanpa refill -> CL @ {exit_price:.0f} ({slot.pnl_pct:.1f}%)"
                                self.cooldowns[sym] = ts + timedelta(seconds=self.config.cl_cooldown_seconds)
                                self._record_history(slot, "CUT_LOSS")
                                if self.on_event:
                                    self.on_event(
                                        f"🛑 [SNIPER DYNAMIC CL] Slot {slot.slot_id}: {sym} CUT-LOSS @ {exit_price:.0f} ({slot.pnl_pct:.1f}%)",
                                        slot,
                                    )
                            return

            # Check Take-Profit
            if self.config.orderbook_exit_mode != "full" and slot.target_price > 0 and price >= slot.target_price:
                if slot.is_hybrid and slot.tranche1_status == "PENDING":
                    slot.tranche1_status = "FILLED"
                    slot.tranche1_exit_price = price
                    slot.tranche1_exit_time = ts
                    slot.tranche1_pnl_pct = round((price - slot.entry_price) / slot.entry_price * 100.0, 2)
                    val_in = slot.tranche1_lots * slot.entry_price * 100
                    val_out = slot.tranche1_lots * price * 100
                    fee_buy = val_in * (self.config.fee_buy_pct / 100.0)
                    fee_sell = val_out * (self.config.fee_sell_pct / 100.0)
                    slot.tranche1_gross_idr = round(val_out - val_in, 2)
                    slot.tranche1_fee_idr = round(fee_buy + fee_sell, 2)
                    slot.tranche1_net_idr = round(slot.tranche1_gross_idr - slot.tranche1_fee_idr, 2)
                    slot.tranche1_reason = f"Target TP @ {price:.0f}"
                    # Secure Breakeven + Fee Buffer floor for Tranche 2 immediately!
                    bep_floor = _paper_break_even_signal(slot.entry_price, self.config)
                    slot.runner_trailing_stop_price = max(slot.runner_trailing_stop_price, bep_floor)
                    slot.reason = (
                        f"Tranche 1 TP @ {price:.0f} (+{slot.tranche1_pnl_pct:.1f}%, Net +Rp {slot.tranche1_net_idr:,.0f}) | "
                        f"Runner ({slot.tranche2_lots}L) trailing support {slot.runner_trailing_stop_price:.0f}"
                    )
                    if self.on_event:
                        self.on_event(
                            f"💰 [HYBRID T1 TP] Slot {slot.slot_id}: {sym} Tranche 1 ({slot.tranche1_lots} lot) TP @ {price:.0f} "
                            f"(+{slot.tranche1_pnl_pct:.1f}%) Net +Rp {slot.tranche1_net_idr:,.0f} | Runner ({slot.tranche2_lots} lot) Aktif...",
                            slot,
                        )
                    return
                elif not slot.is_hybrid:
                    slot.state = SniperState.EXIT_TP
                    slot.state_changed_time = ts
                    slot.reason = f"TP HIT @ {price:.0f} (+{slot.pnl_pct:.1f}%)! Mengamankan profit."
                    self.cooldowns[sym] = ts + timedelta(seconds=self.config.cooldown_seconds)
                    self._record_history(slot, "TAKE_PROFIT")
                    if self.on_event:
                        self.on_event(
                            f"💰 [SNIPER TP] Slot {slot.slot_id}: {sym} TAKE-PROFIT @ {price:.0f} (+{slot.pnl_pct:.1f}%)",
                            slot,
                        )
                    return

            # Check Cut-Loss (only if tape reading is NOT enabled or b_data is not available, to prevent panic cut-loss on absorbed supports)
            stop_price = slot.runner_trailing_stop_price if (slot.is_hybrid and slot.tranche1_status == "FILLED") else slot.stop_loss_price
            if self.config.orderbook_exit_mode != "full" and (not self.config.enable_orderbook_tape_reading or not b_data) and price <= stop_price:
                if slot.is_hybrid and slot.tranche1_status == "FILLED":
                    slot.tranche2_status = "STOPPED"
                    slot.tranche2_exit_price = price
                    slot.tranche2_exit_time = ts
                    slot.tranche2_pnl_pct = round((price - slot.entry_price) / slot.entry_price * 100.0, 2)
                    val_in = slot.tranche2_lots * slot.entry_price * 100
                    val_out = slot.tranche2_lots * price * 100
                    fee_buy = val_in * (self.config.fee_buy_pct / 100.0)
                    fee_sell = val_out * (self.config.fee_sell_pct / 100.0)
                    slot.tranche2_gross_idr = round(val_out - val_in, 2)
                    slot.tranche2_fee_idr = round(fee_buy + fee_sell, 2)
                    slot.tranche2_net_idr = round(slot.tranche2_gross_idr - slot.tranche2_fee_idr, 2)
                    slot.tranche2_reason = f"Stop Loss @ {price:.0f}"

                    total_net = round(slot.tranche1_net_idr + slot.tranche2_net_idr, 2)
                    slot.state = SniperState.EXIT_TP if total_net > 0 else SniperState.EXIT_CL
                    slot.state_changed_time = ts
                    slot.current_price = price
                    pnl_sign = "+" if total_net >= 0 else ""
                    slot.reason = (
                        f"Hybrid Selesai: T1 TP +Rp {slot.tranche1_net_idr:,.0f} | "
                        f"T2 CL Rp {slot.tranche2_net_idr:,.0f} (Net: {pnl_sign}Rp {total_net:,.0f})"
                    )
                    self.cooldowns[sym] = ts + timedelta(seconds=self.config.cooldown_seconds)
                    self._record_history(slot, "TAKE_PROFIT" if total_net > 0 else "CUT_LOSS")
                    if self.on_event:
                        self.on_event(
                            f"🏁 [HYBRID COMPLETED] Slot {slot.slot_id}: {sym} Runner stopped @ {price:.0f}. "
                            f"Total Net: {pnl_sign}Rp {total_net:,.0f}",
                            slot,
                        )
                    return
                else:
                    slot.state_changed_time = ts
                    pnl_sign = "+" if slot.pnl_pct >= 0 else ""
                    is_profit = slot.pnl_pct > 0
                    slot.state = SniperState.EXIT_TP if is_profit else SniperState.EXIT_CL
                    if is_profit:
                        slot.reason = f"Trailing Stop HIT @ {price:.0f} ({pnl_sign}{slot.pnl_pct:.1f}%)! Mengamankan profit."
                        self.cooldowns[sym] = ts + timedelta(seconds=self.config.cooldown_seconds)
                        self._record_history(slot, "TAKE_PROFIT")
                        if self.on_event:
                            self.on_event(
                                f"💰 [SNIPER TRAIL TP] Slot {slot.slot_id}: {sym} TRAILING TP @ {price:.0f} ({pnl_sign}{slot.pnl_pct:.1f}%)",
                                slot,
                            )
                    else:
                        slot.reason = f"CL HIT @ {price:.0f} ({slot.pnl_pct:.1f}%)! Batas invalidasi jebol."
                        self.cooldowns[sym] = ts + timedelta(seconds=self.config.cl_cooldown_seconds)
                        self._record_history(slot, "CUT_LOSS")
                        if self.on_event:
                            self.on_event(
                                f"🛑 [SNIPER CL] Slot {slot.slot_id}: {sym} CUT-LOSS @ {price:.0f} ({slot.pnl_pct:.1f}%)",
                                slot,
                            )
                    return

    def process_batch(self, trades: list[dict[str, Any]], current_time: datetime | None = None):
        """Process a batch once, in event-time order, and update time/TTL."""
        def sort_key(trade):
            value = trade.get("exchange_time") or trade.get("timestamp") or current_time
            if isinstance(value, str):
                try:
                    value = datetime.fromisoformat(value)
                except ValueError:
                    value = None
            return (
                value if isinstance(value, datetime) else datetime.min.replace(tzinfo=timezone.utc),
                trade.get("tradeId") if trade.get("tradeId") is not None else -1,
            )

        for trade in sorted(trades, key=sort_key):
            trade_time = trade.get("exchange_time") or current_time
            sym = trade.get("symbol")
            tid = trade.get("tradeId")
            key = (
                (sym, tid) if tid is not None else
                (sym, str(trade_time), trade.get("price"), trade.get("shares"), trade.get("sideCode"))
            )
            if key in self.seen_trades:
                self.duplicates_ignored += 1
                continue
            self.seen_trades.add(key)
            previous = self.last_batch_trade_time.get(sym)
            if previous is not None and trade_time is not None and trade_time < previous:
                self.late_ignored += 1
                continue
            if sym and trade_time is not None:
                self.last_batch_trade_time[sym] = trade_time
            self.process_trade(trade, current_time=current_time or trade_time)
            if trade_time:
                self.tick(trade_time)

    def _refresh_orderbook_roles(self, slot: SniperSlot | None, symbol: str, b_data: dict[str, Any], stamp: datetime) -> None:
        if slot is None or self.config.orderbook_exit_mode != "full":
            return
        bids = b_data.get("bids", {})
        offers = b_data.get("offers", {})

        if slot.state == SniperState.WATCHING:
            self._refresh_watch_support(slot, symbol, b_data, stamp)
            return

        if slot.state == SniperState.OBSERVING:
            candidates = sorted(
                (p for p, lot in offers.items() if p > slot.current_price and self._is_strong_wall(symbol, p, lot, offers)),
            )
            if candidates and slot.entry_offer_price <= 0:
                slot.entry_offer_price = candidates[0]

            for price, lot in bids.items():
                offer_state = slot.wall_states.get(self._wall_key("OFFER", price))
                if not offer_state or not offer_state.get("depleted"):
                    continue
                if offer_state.get("refill_strikes", 0) > 0:
                    continue
                if self._is_strong_wall(symbol, price, lot, bids):
                    offer_state["converted"] = True
                    slot.entry_offer_price = price
                    slot.entry_ready = True
                    slot.entry_ready_done_count = slot.observing_done_count
                    slot.reason = f"Offer {price:.0f} jebol -> Bid kuat {lot:,.0f}L | Menunggu transaksi entry"
                    break

            if slot.entry_offer_price > 0:
                state = slot.wall_states.get(self._wall_key("OFFER", slot.entry_offer_price), {})
                if state.get("refill_strikes", 0) > 0:
                    slot.entry_ready = False
                    slot.entry_offer_price = 0.0

        elif slot.state == SniperState.ENTERED:
            for price, lot in bids.items():
                offer_state = slot.wall_states.get(self._wall_key("OFFER", price))
                if offer_state and offer_state.get("depleted") and not offer_state.get("converted") and self._is_strong_wall(symbol, price, lot, bids):
                    offer_state["converted"] = True
                    self._set_support(slot, price, lot, converted=True)
                    slot.active_resistance_price = 0.0
                    slot.reason = f"Resistance {price:.0f} menjadi bid support {lot:,.0f}L -> Hold"
                    break

    def _store_orderbook_snapshot(
        self,
        slot: SniperSlot | None,
        symbol: str,
        b_data: dict[str, Any],
        side: str,
        levels: dict[float, float],
        stamp: datetime,
    ) -> None:
        previous_key = "prev_bids" if side == "BID" else "prev_offers"
        current_key = "bids" if side == "BID" else "offers"
        previous = dict(b_data.get(current_key, {}))
        self._record_wall_snapshot(slot, symbol, side, previous, levels)
        b_data[previous_key] = previous
        b_data[current_key] = dict(levels)
        b_data[f"{side.lower()}_updated_at"] = stamp

    def process_book(self, book_update: dict[str, Any], current_time: datetime | None = None):
        """Apply a complete L2 side snapshot and update order-book strategy state."""
        sym = book_update.get("symbol")
        if not sym:
            return
        slot = self.find_slot_by_symbol(sym)
        stamp = current_time or datetime.now(timezone.utc)
        if sym not in self.books:
            self.books[sym] = {"bids": {}, "offers": {}, "prev_bids": {}, "prev_offers": {}}
        b_data = self.books[sym]

        def as_levels(raw: Any) -> dict[float, float]:
            if isinstance(raw, dict):
                return {float(price): float(lot) for price, lot in raw.items() if float(price) > 0 and float(lot) >= 0}
            if isinstance(raw, list):
                return {
                    float(item.get("price", 0.0)): float(item.get("lot", 0.0))
                    for item in raw
                    if isinstance(item, dict) and float(item.get("price", 0.0)) > 0 and float(item.get("lot", 0.0)) >= 0
                }
            return {}

        if "bids" in book_update and "offers" in book_update:
            bids = as_levels(book_update.get("bids"))
            offers = as_levels(book_update.get("offers"))
            # OFFER is processed first so a same-message OFFER->BID conversion is visible.
            self._store_orderbook_snapshot(slot, sym, b_data, "OFFER", offers, stamp)
            self._store_orderbook_snapshot(slot, sym, b_data, "BID", bids, stamp)
            top_bids = sorted(bids.values(), reverse=True)[:3]
            top_offers = sorted(offers.values())[:3]
            b_data["bid_vol"] = float(book_update.get("bid_vol", sum(top_bids)))
            b_data["offer_vol"] = float(book_update.get("offer_vol", sum(top_offers)))
        else:
            side = book_update.get("side")
            levels = book_update.get("levels", [])
            if side not in {"BID", "OFFER"} or not isinstance(levels, list):
                return
            self._store_orderbook_snapshot(slot, sym, b_data, side, as_levels(levels), stamp)
            top_bids = sorted(b_data["bids"].values(), reverse=True)[:3]
            top_offers = sorted(b_data["offers"].values())[:3]
            b_data["bid_vol"] = sum(top_bids)
            b_data["offer_vol"] = sum(top_offers)

        self._refresh_orderbook_roles(slot, sym, b_data, stamp)
        if slot is not None and slot.state != SniperState.IDLE:
            bids = b_data.get("bids", {})
            offers = b_data.get("offers", {})
            if bids and offers:
                bb = max(bids.keys())
                bo = min(offers.keys())
                slot.l2_summary = f"L2: B {bb:.0f}({bids[bb]:,.0f}L) / O {bo:.0f}({offers[bo]:,.0f}L)"
            elif bids:
                bb = max(bids.keys())
                slot.l2_summary = f"L2: B {bb:.0f}({bids[bb]:,.0f}L)"
            elif offers:
                bo = min(offers.keys())
                slot.l2_summary = f"L2: O {bo:.0f}({offers[bo]:,.0f}L)"

            if slot.state == SniperState.OBSERVING:
                bid_vol = b_data.get("bid_vol", 0.0)
                offer_vol = b_data.get("offer_vol", 0.0)
                if offer_vol > 0 and bid_vol / offer_vol >= self.config.bid_fortification_min_ratio:
                    slot.reason = f"Bid menebal ({bid_vol / offer_vol:.1f}x) | Menunggu HAKA..."

    def tick(self, current_time: datetime):
        """Advance time, evaluate timeouts, and auto-release inactive slots."""
        release_delay = timedelta(seconds=self.config.auto_release_delay_seconds)

        for slot in self.slots:
            if slot.state == SniperState.IDLE:
                continue

            # 1. Watchlist keeps L2 until DONE is quiet for five minutes.
            if slot.state == SniperState.WATCHING:
                idle_anchor = slot.last_trade_time or slot.watch_started_at or slot.alert_time
                if idle_anchor is not None:
                    elapsed = (current_time - idle_anchor).total_seconds()
                    slot.ttl_seconds = max(0.0, _WATCHLIST_IDLE_SECONDS - elapsed)
                    if elapsed >= _WATCHLIST_IDLE_SECONDS:
                        self._drop_watch_slot(slot, current_time, "WATCHLIST_IDLE", "Sepi 5 menit tanpa DONE")
                book = self.books.get(slot.symbol or "", {})
                stale = [
                    (current_time - book[key]).total_seconds()
                    for key in ("bid_updated_at", "offer_updated_at")
                    if book.get(key) is not None
                ]
                if stale and any(age < 0 or age > self.config.l2_stale_seconds for age in stale):
                    slot.reason = f"Watchlist L2: STALE > {self.config.l2_stale_seconds:.0f}s | Entry ditahan"
                continue

            # 2. Check OBSERVING timeout
            if slot.state == SniperState.OBSERVING:
                if slot.alert_time is not None:
                    elapsed = (current_time - slot.alert_time).total_seconds()
                    slot.ttl_seconds = max(0.0, self.config.observation_timeout_seconds - elapsed)
                    if elapsed >= self.config.observation_timeout_seconds:
                        slot.state = SniperState.ABORTED
                        slot.state_changed_time = current_time
                        slot.reason = "Timeout 10s: Momentum padam. Abort!"
                        if slot.symbol:
                            self.cooldowns[slot.symbol] = current_time + timedelta(
                                seconds=self.config.cooldown_seconds
                            )
                        self._record_history(slot, "ABORTED_TIMEOUT")
                        if self.on_event:
                            self.on_event(
                                f"⚠️ [SNIPER ABORT] Slot {slot.slot_id}: {slot.symbol} dibatalkan (momentum sepi).",
                                slot,
                            )

            # 3. Check ENTERED max holding timeout
            elif slot.state == SniperState.ENTERED:
                if self.config.orderbook_exit_mode == "full" and slot.symbol:
                    if not self._fresh_book(slot.symbol, current_time):
                        self._close_full_orderbook(
                            slot,
                            "CUT_LOSS",
                            current_time,
                            slot.current_price,
                            "EMERGENCY_L2_STALE",
                            f"Emergency L2 stale/disconnect -> exit @ {slot.current_price:.0f}",
                        )
                        continue
                max_hold = slot.effective_max_holding_seconds or self.config.max_holding_seconds
                if slot.entry_time is not None and max_hold > 0:
                    holding_elapsed = (current_time - slot.entry_time).total_seconds()

                    # Stagnant BEP cut: cut early if position is stuck around BEP (pnl <= 0.8%)
                    if (
                        self.config.stagnant_timeout_seconds > 0
                        and not slot.hold_extended
                        and holding_elapsed >= self.config.stagnant_timeout_seconds
                        and slot.pnl_pct <= 0.8
                        and (not slot.is_hybrid or slot.tranche1_status == "PENDING")
                    ):
                        slot.state = SniperState.EXIT_TIMEOUT
                        slot.state_changed_time = current_time
                        pnl_sign = "+" if slot.pnl_pct >= 0 else ""
                        slot.reason = (
                            f"Stagnant Cut {self.config.stagnant_timeout_seconds:.0f}s: "
                            f"Mandek di BEP ({pnl_sign}{slot.pnl_pct:.1f}%). Scratch exit!"
                        )
                        if slot.symbol:
                            self.cooldowns[slot.symbol] = current_time + timedelta(
                                seconds=self.config.cooldown_seconds
                            )
                        self._record_history(slot, "EXIT_TIMEOUT")
                        if self.on_event:
                            self.on_event(
                                f"⏱️ [STAGNANT CUT] Slot {slot.slot_id}: {slot.symbol} cut dini karena mandek {self.config.stagnant_timeout_seconds:.0f}s ({pnl_sign}{slot.pnl_pct:.1f}%).",
                                slot,
                            )
                        continue

                    if holding_elapsed >= max_hold:
                        if slot.is_hybrid and slot.tranche1_status == "FILLED" and slot.tranche2_status == "PENDING":
                            b_data = self._fresh_book(slot.symbol, current_time)
                            bids = b_data.get("bids", {})
                            best_bid = max(bids.keys()) if bids else slot.current_price
                            exit_p = best_bid if best_bid > 0 else slot.current_price
                            slot.tranche2_status = "FILLED"
                            slot.tranche2_exit_price = exit_p
                            slot.tranche2_exit_time = current_time
                            slot.tranche2_pnl_pct = round((exit_p - slot.entry_price) / slot.entry_price * 100.0, 2)
                            val_in = slot.tranche2_lots * slot.entry_price * 100
                            val_out = slot.tranche2_lots * exit_p * 100
                            fee_buy = val_in * (self.config.fee_buy_pct / 100.0)
                            fee_sell = val_out * (self.config.fee_sell_pct / 100.0)
                            slot.tranche2_gross_idr = round(val_out - val_in, 2)
                            slot.tranche2_fee_idr = round(fee_buy + fee_sell, 2)
                            slot.tranche2_net_idr = round(slot.tranche2_gross_idr - slot.tranche2_fee_idr, 2)
                            slot.tranche2_reason = f"Timeout Runner {max_hold:.0f}s @ {exit_p:.0f}"

                            total_net = round(slot.tranche1_net_idr + slot.tranche2_net_idr, 2)
                            slot.state = SniperState.EXIT_TP if total_net > 0 else SniperState.EXIT_TIMEOUT
                            slot.state_changed_time = current_time
                            pnl_sign = "+" if total_net >= 0 else ""
                            slot.reason = (
                                f"Hybrid Selesai: T1 TP +Rp {slot.tranche1_net_idr:,.0f} | "
                                f"T2 Timeout @ {exit_p:.0f} (Net: {pnl_sign}Rp {total_net:,.0f})"
                            )
                            if slot.symbol:
                                self.cooldowns[slot.symbol] = current_time + timedelta(seconds=self.config.cooldown_seconds)
                            self._record_history(slot, "TAKE_PROFIT" if total_net > 0 else "EXIT_TIMEOUT")
                            if self.on_event:
                                self.on_event(
                                    f"⏱️ [HYBRID TIMEOUT] Slot {slot.slot_id}: {slot.symbol} T2 Runner timeout @ {exit_p:.0f} (Net: {pnl_sign}Rp {total_net:,.0f}).",
                                    slot,
                                )
                        else:
                            slot.state = SniperState.EXIT_TIMEOUT
                            slot.state_changed_time = current_time
                            pnl_sign = "+" if slot.pnl_pct >= 0 else ""
                            slot.reason = f"Timeout {max_hold:.0f}s: Stagnan ({pnl_sign}{slot.pnl_pct:.1f}%). Exit!"
                            if slot.symbol:
                                self.cooldowns[slot.symbol] = current_time + timedelta(
                                    seconds=self.config.cooldown_seconds
                                )
                            self._record_history(slot, "EXIT_TIMEOUT")
                            if self.on_event:
                                self.on_event(
                                    f"⏱️ [SNIPER TIMEOUT] Slot {slot.slot_id}: {slot.symbol} dilepas karena stagnan > {max_hold:.0f}s ({pnl_sign}{slot.pnl_pct:.1f}%).",
                                    slot,
                                )

            # 4. Auto-release slots in terminal states after release delay
            elif slot.state in (SniperState.ABORTED, SniperState.EXIT_TP, SniperState.EXIT_CL, SniperState.EXIT_TIMEOUT):
                if slot.state_changed_time is not None:
                    if (current_time - slot.state_changed_time) >= release_delay:
                        freed_sym = slot.symbol
                        slot.reset()
                        if freed_sym and self.on_slot_released:
                            self.on_slot_released(freed_sym)
                        if self.on_event and freed_sym:
                            self.on_event(
                                f"♻️ [SLOT RELEASED] Slot {slot.slot_id} kembali IDLE (sebelumnya: {freed_sym}).",
                                slot,
                            )

    def close_all(self, end_time: datetime):
        """Finalize any remaining active slots at session end."""
        for slot in self.slots:
            if slot.state == SniperState.ENTERED:
                if slot.is_hybrid and slot.tranche1_status == "FILLED" and slot.tranche2_status == "PENDING":
                    b_data = self._fresh_book(slot.symbol, end_time)
                    bids = b_data.get("bids", {})
                    best_bid = max(bids.keys()) if bids else slot.current_price
                    exit_p = best_bid if best_bid > 0 else slot.current_price
                    slot.tranche2_status = "FILLED"
                    slot.tranche2_exit_price = exit_p
                    slot.tranche2_exit_time = end_time
                    slot.tranche2_pnl_pct = round((exit_p - slot.entry_price) / slot.entry_price * 100.0, 2)
                    val_in = slot.tranche2_lots * slot.entry_price * 100
                    val_out = slot.tranche2_lots * exit_p * 100
                    fee_buy = val_in * (self.config.fee_buy_pct / 100.0)
                    fee_sell = val_out * (self.config.fee_sell_pct / 100.0)
                    slot.tranche2_gross_idr = round(val_out - val_in, 2)
                    slot.tranche2_fee_idr = round(fee_buy + fee_sell, 2)
                    slot.tranche2_net_idr = round(slot.tranche2_gross_idr - slot.tranche2_fee_idr, 2)
                    slot.tranche2_reason = f"Sesi Berakhir @ {exit_p:.0f}"

                    total_net = round(slot.tranche1_net_idr + slot.tranche2_net_idr, 2)
                    slot.state = SniperState.EXIT_TP if total_net > 0 else SniperState.EXIT_TIMEOUT
                    slot.state_changed_time = end_time
                    pnl_sign = "+" if total_net >= 0 else ""
                    slot.reason = (
                        f"Hybrid Selesai: T1 TP +Rp {slot.tranche1_net_idr:,.0f} | "
                        f"T2 Selesai Rp {slot.tranche2_net_idr:,.0f} (Net: {pnl_sign}Rp {total_net:,.0f})"
                    )
                    self._record_history(slot, "SESSION_CLOSED_TP" if total_net > 0 else "SESSION_CLOSED_CL")
                else:
                    slot.state = SniperState.EXIT_TIMEOUT
                    slot.state_changed_time = end_time
                    slot.reason = f"Sesi Berakhir: Posisi ditutup @ {slot.current_price:.0f}"
                    self._record_history(slot, "SESSION_CLOSED")
            elif slot.state in (SniperState.OBSERVING, SniperState.WATCHING):
                watching = slot.state == SniperState.WATCHING
                slot.state = SniperState.ABORTED
                slot.state_changed_time = end_time
                slot.reason = "Sesi Berakhir: Watchlist selesai" if watching else "Sesi Berakhir: Observasi selesai"
                self._record_history(slot, "SESSION_WATCHLIST_CLOSED" if watching else "SESSION_ABORTED")

            if slot.symbol and self.on_slot_released:
                self.on_slot_released(slot.symbol)

    def _orderbook_history_fields(self, slot: SniperSlot) -> dict[str, Any]:
        wall_side = "OFFER" if slot.exit_reason_code == "RESISTANCE_REFILL" else "BID"
        wall_price = slot.active_resistance_price if wall_side == "OFFER" else slot.active_support_price
        state = slot.wall_states.get(self._wall_key(wall_side, wall_price), {}) if wall_price > 0 else {}
        return {
            "orderbook_exit_mode": self.config.orderbook_exit_mode,
            "exit_signal_price": slot.exit_signal_price or slot.current_price,
            "exit_fill_price": slot.exit_fill_price or slot.current_price,
            "exit_reason_code": slot.exit_reason_code,
            "entry_offer_price": slot.entry_offer_price,
            "support_price": slot.active_support_price,
            "resistance_price": slot.active_resistance_price,
            "wall_side": wall_side if wall_price > 0 else "",
            "wall_price": wall_price,
            "wall_initial_lots": state.get("initial_lots", 0.0),
            "wall_current_lots": state.get("current_lots", 0.0),
            "wall_depletion_count": state.get("depletion_count", 0),
            "wall_refill_strikes": state.get("refill_strikes", 0),
            "wall_attack_count": state.get("attack_count", 0),
        }

    def _record_history(self, slot: SniperSlot, outcome: str):
        holding_sec = 0.0
        if slot.entry_time and slot.state_changed_time:
            holding_sec = round((slot.state_changed_time - slot.entry_time).total_seconds(), 1)
        elif slot.alert_time and slot.state_changed_time:
            holding_sec = round((slot.state_changed_time - slot.alert_time).total_seconds(), 1)

        if slot.is_hybrid and slot.tranche1_status == "FILLED":
            lots = slot.total_lots or (slot.tranche1_lots + slot.tranche2_lots)
            val_in = lots * slot.entry_price * 100
            val_out = (slot.tranche1_lots * slot.tranche1_exit_price * 100) + (slot.tranche2_lots * slot.tranche2_exit_price * 100)
            gross_idr = round(slot.tranche1_gross_idr + slot.tranche2_gross_idr, 2)
            fee_total = round(slot.tranche1_fee_idr + slot.tranche2_fee_idr, 2)
            net_idr = round(slot.tranche1_net_idr + slot.tranche2_net_idr, 2)
            pnl_pct = round((val_out - val_in) / val_in * 100.0, 2) if val_in > 0 else 0.0
            avg_exit_price = round(val_out / (lots * 100), 1) if lots > 0 else slot.current_price

            self.history.append({
                "slot_id": slot.slot_id,
                "symbol": slot.symbol,
                "pattern": slot.pattern,
                "outcome": outcome,
                "ref_price": slot.ref_price,
                "entry_price": slot.entry_price,
                "exit_price": avg_exit_price,
                "peak_price": slot.peak_price,
                "target_price": slot.target_price,
                "stop_loss_price": slot.stop_loss_price,
                "pnl_pct": pnl_pct,
                "holding_seconds": holding_sec,
                "lots": lots,
                "val_in": val_in,
                "val_out": val_out,
                "fee_total": fee_total,
                "gross_idr": gross_idr,
                "net_idr": net_idr,
                "reason": slot.reason,
                **self._orderbook_history_fields(slot),
                "alert_time": slot.alert_time,
                "entry_time": slot.entry_time,
                "exit_time": slot.state_changed_time,
                "is_hybrid": True,
                "alert_velocity": slot.alert_velocity,
                "alert_haka_pct": slot.alert_haka_pct,
                "alert_net_flow_idr": slot.alert_net_flow_idr,
                "alert_delta_pct": slot.alert_delta_pct,
                "observing_done_count": slot.observing_done_count,
                "observing_haka_pct": round(slot.observing_haka_value_idr / slot.observing_total_value_idr * 100, 2) if slot.observing_total_value_idr else 0.0,
                "observing_haka_value_idr": slot.observing_haka_value_idr,
                "observing_total_value_idr": slot.observing_total_value_idr,
                "entry_vs_ref_pct": round((slot.entry_price / slot.ref_price - 1) * 100, 2) if slot.ref_price else 0.0,
                "tranche1_lots": slot.tranche1_lots,
                "tranche1_exit_price": slot.tranche1_exit_price,
                "tranche1_pnl_pct": slot.tranche1_pnl_pct,
                "tranche1_net_idr": slot.tranche1_net_idr,
                "tranche1_reason": slot.tranche1_reason,
                "tranche2_lots": slot.tranche2_lots,
                "tranche2_exit_price": slot.tranche2_exit_price,
                "tranche2_pnl_pct": slot.tranche2_pnl_pct,
                "tranche2_net_idr": slot.tranche2_net_idr,
                "tranche2_reason": slot.tranche2_reason,
            })
            return

        lot_price = slot.entry_price * 100
        lots = slot.total_lots or (max(1, round(self.config.trade_capital_idr / lot_price)) if lot_price > 0 else 0)
        val_in = lots * lot_price
        val_out = lots * slot.current_price * 100
        fee_buy = val_in * (self.config.fee_buy_pct / 100.0)
        fee_sell = val_out * (self.config.fee_sell_pct / 100.0)
        fee_total = round(fee_buy + fee_sell, 2)
        gross_idr = round(val_out - val_in, 2)
        net_idr = round((val_out - fee_sell) - (val_in + fee_buy), 2)

        self.history.append({
            "slot_id": slot.slot_id,
            "symbol": slot.symbol,
            "pattern": slot.pattern,
            "outcome": outcome,
            "ref_price": slot.ref_price,
            "entry_price": slot.entry_price,
            "exit_price": slot.current_price,
            "peak_price": slot.peak_price,
            "target_price": slot.target_price,
            "stop_loss_price": slot.stop_loss_price,
            "pnl_pct": slot.pnl_pct,
            "holding_seconds": holding_sec,
            "lots": lots,
            "val_in": val_in,
            "val_out": val_out,
            "fee_total": fee_total,
            "gross_idr": gross_idr,
            "net_idr": net_idr,
            "reason": slot.reason,
            **self._orderbook_history_fields(slot),
            "alert_time": slot.alert_time,
            "entry_time": slot.entry_time,
            "exit_time": slot.state_changed_time,
            "is_hybrid": False,
            "alert_velocity": slot.alert_velocity,
            "alert_haka_pct": slot.alert_haka_pct,
            "alert_net_flow_idr": slot.alert_net_flow_idr,
            "alert_delta_pct": slot.alert_delta_pct,
            "observing_done_count": slot.observing_done_count,
            "observing_haka_pct": round(slot.observing_haka_value_idr / slot.observing_total_value_idr * 100, 2) if slot.observing_total_value_idr else 0.0,
            "observing_haka_value_idr": slot.observing_haka_value_idr,
            "observing_total_value_idr": slot.observing_total_value_idr,
            "entry_vs_ref_pct": round((slot.entry_price / slot.ref_price - 1) * 100, 2) if slot.ref_price else 0.0,
        })

    def format_table(self) -> list[str]:
        """Render ASCII lines for the 5-slot sniper panel."""
        active = self.active_count()
        lines = [f"========== SNIPER ACTIVE SLOTS ({active}/{self.config.max_slots} AKTIF) =========="]
        for slot in self.slots:
            lines.append(slot.format_status())
        return lines


def scan_session_sniper(
    session_id: str,
    sniper_config: SniperConfig | None = None,
    radar_config: Any = None,
    conn: Any = None,
    on_event: Callable[[str, SniperSlot | None], None] | None = None,
) -> dict[str, Any]:
    """Replay a session from PostgreSQL through MarketRadar + SniperManager."""
    from .postgres import connect_database
    from .radar import MarketRadar, RadarConfig

    should_close = False
    if conn is None:
        conn = connect_database(readonly=True)
        should_close = True

    try:
        session = conn.execute(
            "SELECT id, symbol, started_at, ended_at FROM stockbit_ws.sessions WHERE id = %s",
            (session_id,),
        ).fetchone()
        if not session:
            raise ValueError(f"Sesi tidak ditemukan: {session_id}")

        r_cfg = radar_config or RadarConfig(enable_breakout=True, enable_squeeze=False, enable_absorption=False)
        s_cfg = sniper_config or SniperConfig(max_slots=5)

        sniper = SniperManager(config=s_cfg, on_event=on_event)

        def _on_radar_alert(alert: RadarAlert):
            sniper.handle_radar_alert(alert)

        radar = MarketRadar(
            config=r_cfg, on_alert=_on_radar_alert,
            start_time=session["started_at"], end_time=session["ended_at"],
        )

        cur = conn.cursor()
        kinds = (
            ("book", "done")
            if (s_cfg.enable_orderbook_tape_reading or s_cfg.enable_hybrid_mode or s_cfg.orderbook_exit_mode == "full")
            else ("done",)
        )
        query = (
            "SELECT kind, payload, received_at FROM stockbit_ws.events "
            "WHERE session_id = %s AND kind = ANY(%s) "
            "ORDER BY seq ASC"
        )
        cur.execute(query, (session_id, list(kinds)))

        last_time = session["started_at"]
        for row in cur:
            k = row["kind"]
            payload = row["payload"]
            rcv_time = row["received_at"]

            if k == "book":
                sniper.process_book(payload, current_time=rcv_time)
                continue

            trades = payload.get("trades", []) if isinstance(payload, dict) else []
            batch = []
            for t in trades:
                ts_str = t.get("timestamp")
                code = t.get("symbol")
                tid = t.get("tradeId")
                if not code or not ts_str:
                    continue

                ex_time = datetime.fromisoformat(ts_str) if isinstance(ts_str, str) else ts_str
                batch.append({
                    "symbol": code,
                    "tradeId": tid,
                    "price": float(t.get("price", 0.0)),
                    "shares": float(t.get("shares", 0.0)),
                    "lot": float(t.get("lot", t.get("shares", 0.0) / 100)),
                    "sideCode": int(t.get("sideCode", 0)),
                    "value": float(t.get("transactionValue", t.get("price", 0.0) * t.get("shares", 0.0))),
                    "timestamp": ts_str,
                    "exchange_time": ex_time,
                })
            for trade_obj in radar.ordered_trades(batch):
                ex_time = trade_obj["exchange_time"]
                last_time = max(last_time, ex_time)
                radar.process_trade(trade_obj)
                sniper.process_batch([trade_obj], current_time=rcv_time)
                sniper.tick(ex_time)

        end_time = session["ended_at"] or last_time
        sniper.close_all(end_time)

        return {
            "session_id": session_id,
            "session_symbol": session["symbol"],
            "started_at": session["started_at"],
            "ended_at": end_time,
            "total_radar_alerts": len(radar.alerts),
            "history": [apply_paper_friction(item, s_cfg) for item in sniper.history],
            "sniper_config": s_cfg,
            "quality": {
                "radar_duplicates_ignored": radar.duplicates_ignored,
                "radar_historical_ignored": radar.historical_ignored,
                "radar_late_ignored": radar.late_ignored,
                "sniper_duplicates_ignored": sniper.duplicates_ignored,
                "sniper_late_ignored": sniper.late_ignored,
            },
        }
    finally:
        if should_close and conn is not None and not conn.closed:
            conn.close()


def format_sniper_report(scan_res: dict[str, Any]) -> str:
    """Format sniper backtest results into a comprehensive Markdown document."""
    from .report import timestamp_text

    sid = scan_res["session_id"]
    sym = scan_res["session_symbol"]
    start_str = timestamp_text(scan_res["started_at"])
    end_str = timestamp_text(scan_res["ended_at"])
    cfg: SniperConfig = scan_res["sniper_config"]
    history = [apply_paper_friction(item, cfg) for item in scan_res["history"]]

    # Filter into categories
    entered = [h for h in history if h.get("entry_price", 0) > 0 and h.get("lots", 0) > 0]
    tp_list = [h for h in entered if h.get("net_idr", 0.0) > 0]
    cl_list = [h for h in entered if h.get("net_idr", 0.0) < 0]
    stale_list = [h for h in entered if h["outcome"] in ("EXIT_TIMEOUT", "SESSION_CLOSED")]
    watchlist_outcomes = {"WATCHLIST_IDLE", "WATCHLIST_REPLACED", "WATCHLIST_SUPPORT_BROKEN", "SESSION_WATCHLIST_CLOSED"}
    aborted_list = [
        h for h in history
        if h["outcome"].startswith("ABORTED") or h["outcome"] == "SESSION_ABORTED" or h["outcome"] in watchlist_outcomes
    ]

    total_ops = len(history)
    total_entered = len(entered)
    total_tp = len(tp_list)
    total_cl = len(cl_list)
    total_stale = len(stale_list)
    total_aborted = len(aborted_list)

    win_rate = (total_tp / (total_tp + total_cl) * 100.0) if (total_tp + total_cl) > 0 else 0.0
    tp_pct_entered = (total_tp / total_entered * 100.0) if total_entered > 0 else 0.0
    cl_pct_entered = (total_cl / total_entered * 100.0) if total_entered > 0 else 0.0
    stale_pct_entered = (total_stale / total_entered * 100.0) if total_entered > 0 else 0.0

    avg_win = (sum(h["pnl_pct"] for h in tp_list) / total_tp) if total_tp > 0 else 0.0
    avg_loss = (sum(h["pnl_pct"] for h in cl_list) / total_cl) if total_cl > 0 else 0.0
    net_pnl_pct = sum(h["pnl_pct"] for h in entered)

    total_gross_idr = sum(h.get("gross_idr", 0.0) for h in entered)
    total_fees_idr = sum(h.get("fee_total", 0.0) for h in entered)
    total_net_idr = sum(h.get("net_idr", 0.0) for h in entered)
    total_capital_deployed = sum(h.get("val_in", 0.0) for h in entered)

    net_status_tag = "PAPER PROFIT 🟢" if total_net_idr > 0 else ("PAPER LOSS 🔴" if total_net_idr < 0 else "PAPER FLAT ⚪")

    hybrid_status = f" | Mode Hybrid `T1 {cfg.hybrid_scalp_ratio*100:.0f}% Scalp / T2 {100-cfg.hybrid_scalp_ratio*100:.0f}% Runner` (Max Hold {cfg.hybrid_runner_max_hold_seconds:.0f}s)" if cfg.enable_hybrid_mode else ""
    strategy_line = (
        "**Order Book Strategy**: mode `full` — Watchlist Pullback: bid absorb/refill 2x + "
        "2 HAKA dekat support; TP/CL memakai wall."
        if cfg.orderbook_exit_mode == "full"
        else "**Order Book Strategy**: mode `legacy` — target persentase + tape-reading dinamis."
    )
    target_text = "Order Book" if cfg.orderbook_exit_mode == "full" else f"+{cfg.target_tp_pct:.1f}%"
    stop_text = "Support wall" if cfg.orderbook_exit_mode == "full" else f"-{cfg.stop_loss_pct:.1f}%"
    pre_entry_label = "Dilepas dari Watchlist Pra-Entry" if cfg.orderbook_exit_mode == "full" else "Dibatalkan Pra-Entry (ABORTED)"
    pre_entry_note = "Idle, support jebol, atau diganti Radar baru (nol risiko modal)" if cfg.orderbook_exit_mode == "full" else "Momentum padam dalam 10s (nol risiko modal)"
    observation_text = "Watchlist idle 300s" if cfg.orderbook_exit_mode == "full" else f"Observasi `{cfg.observation_timeout_seconds:.0f}s`"
    lines = [
        f"# Laporan Paper Backtest Scout & Sniper (Trade Log, TP & CL)",
        f"**Session ID**: `{sid}` | **Symbol**: `{sym}` | **Rentang Sesi**: {start_str} s.d. {end_str}",
        f"**Konfigurasi Sniper**: Kapasitas `{cfg.max_slots} Slot` | Target TP `{target_text}` | Stop Loss `{stop_text}` | Max Hold `{cfg.max_holding_seconds:.0f}s` | {observation_text}{hybrid_status}",
        strategy_line,
        f"**Paper Frictions**: Modal per posisi `Rp {cfg.trade_capital_idr:,.0f}` | Fee Beli `{cfg.fee_buy_pct:.2f}%` | Fee Jual `{cfg.fee_sell_pct:.2f}%` | Slippage adverse `{cfg.paper_slippage_ticks} tick/sisi`",
        "**Peringatan**: ini simulasi sinyal, bukan order broker. Antrean, partial fill, market impact, reject, dan latency belum dimodelkan.",
        "",
        "---",
        "",
        "## 1. Papan Skor Kinerja & Return Finansial (Financial Scoreboard)",
        "",
        f"| Metrik Evaluasi Finansial | Nilai Kinerja | Keterangan |",
        f"|---|:---:|---|",
        f"| **Status Paper Backtest** | **{net_status_tag}** | Sesudah fee dan asumsi slippage; belum membuktikan fill nyata |",
        f"| **Estimasi Net Paper Return** | **{'+' if total_net_idr >= 0 else ''}Rp {total_net_idr:,.0f}** | Estimasi simulasi, bukan saldo akun trading |",
        f"| **Laba Kotor (Gross Profit/Loss)**| {'+' if total_gross_idr >= 0 else ''}Rp {total_gross_idr:,.0f} | Akumulasi selisih harga jual dikurangi harga beli |",
        f"| **Total Biaya Broker (Fees Paid)**| Rp {total_fees_idr:,.0f} | Beban komisi transaksi beli & jual |",
        f"| **Total Modal Ditransaksikan**    | Rp {total_capital_deployed:,.0f} | Akumulasi perputaran modal dari {total_entered} kali transaksi |",
        f"| **Win Rate Paper (sesudah biaya)**| **{win_rate:.1f}%** | Posisi net positif dibanding posisi net negatif |",
        f"| **Posisi Net Positif**            | **{total_tp}** ({tp_pct_entered:.1f}%) | Setelah fee dan slippage asumsi |",
        f"| **Posisi Net Negatif**            | **{total_cl}** ({cl_pct_entered:.1f}%) | Setelah fee dan slippage asumsi |",
        f"| **Stagnant Exit (Timeout)**       | **{total_stale}** ({stale_pct_entered:.1f}%) | Posisi mandek dilepas pada {cfg.max_holding_seconds:.0f}s |",
        f"| **{pre_entry_label}**| **{total_aborted}** | {pre_entry_note} |",
        f"| **Rata-rata Net Return Positif**  | **+{avg_win:.2f}%** | Sudah memperhitungkan fee dan slippage asumsi |",
        f"| **Rata-rata Net Return Negatif**  | **{avg_loss:.2f}%** | Sudah memperhitungkan fee dan slippage asumsi |",
        f"| **Akumulasi Net Paper Return (%)**| **{net_pnl_pct:+.2f}%** | Penjumlahan return tiap posisi, bukan return portofolio majemuk |",
        "",
        "---",
        "",
        "## 2. Rangkuman Hasil per Kode Saham (P&L dan Biaya Broker)",
        "",
        "| Saham | Masuk | TP | CL | Timeout | Gross PnL (Rp) | Fee Broker (Rp) | Net Return (Rp) | Akumulasi PnL (%) | Status / Perilaku |",
        "|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|---|",
    ]

    by_sym: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for h in entered:
        by_sym[h["symbol"]].append(h)

    for s, trades in sorted(by_sym.items(), key=lambda x: sum(t.get("net_idr", 0.0) for t in x[1]), reverse=True):
        tps = sum(1 for t in trades if t.get("net_idr", 0.0) > 0)
        cls = sum(1 for t in trades if t.get("net_idr", 0.0) < 0)
        stales = sum(1 for t in trades if t["outcome"] in ("EXIT_TIMEOUT", "SESSION_CLOSED"))
        pnl = sum(t["pnl_pct"] for t in trades)
        s_gross = sum(t.get("gross_idr", 0.0) for t in trades)
        s_fees = sum(t.get("fee_total", 0.0) for t in trades)
        s_net = sum(t.get("net_idr", 0.0) for t in trades)
        pnl_sign = "+" if pnl >= 0 else ""
        net_sign = "+" if s_net >= 0 else ""
        gross_sign = "+" if s_gross >= 0 else ""
        behavior = "Juara Momentum 🚀" if tps > 0 and cls == 0 else ("Aman / Konsisten 👍" if s_net >= 0 else "High Volatility / Choppy ⚠️")
        lines.append(
            f"| **{s}** | {len(trades)} | {tps} | {cls} | {stales} | "
            f"{gross_sign}Rp {s_gross:,.0f} | Rp {s_fees:,.0f} | **{net_sign}Rp {s_net:,.0f}** | "
            f"**{pnl_sign}{pnl:.2f}%** | {behavior} |"
        )

    lines.extend([
        "",
        "---",
        "",
        "## 3. Log Rinci Seluruh Posisi Yang Masuk (Trade Log)",
        "",
        "| Waktu (WIB) | Saham | Pola Radar | Lot | Modal Beli | Beli | Jual | TP | CL | Fee (Rp) | Net Return (Rp) | PnL (%) | Durasi | Hasil | Catatan Alasan |",
        "|---|:---:|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|---|",
    ])

    for h in entered:
        entry_wib = h["entry_time"].astimezone(_WIB).strftime("%H:%M:%S") if h["entry_time"] else "-"
        pnl_sign = "+" if h["pnl_pct"] >= 0 else ""
        net_sign = "+" if h.get("net_idr", 0) >= 0 else ""
        dur_str = f"{h['holding_seconds']:.0f}s"
        lots_str = f"{h.get('lots', 0):,}"
        val_in_str = f"Rp {h.get('val_in', 0):,.0f}"
        fee_str = f"Rp {h.get('fee_total', 0):,.0f}"
        net_str = f"{net_sign}Rp {h.get('net_idr', 0):,.0f}"

        if h.get("is_hybrid"):
            t1_sign = "+" if h.get("tranche1_pnl_pct", 0) >= 0 else ""
            t2_sign = "+" if h.get("tranche2_pnl_pct", 0) >= 0 else ""
            t1_part = f"T1({h.get('tranche1_lots',0)}L): TP@{h.get('tranche1_exit_price',0):.0f} ({t1_sign}{h.get('tranche1_pnl_pct',0):.1f}%, Net:+Rp {h.get('tranche1_net_idr',0):,.0f})"
            t2_part = f"T2({h.get('tranche2_lots',0)}L): Out@{h.get('tranche2_exit_price',0):.0f} ({t2_sign}{h.get('tranche2_pnl_pct',0):.1f}%, Net:+Rp {h.get('tranche2_net_idr',0):,.0f})"
            reason_text = f"⚡ Hybrid: {t1_part} | {t2_part}"
        else:
            reason_text = h['reason']

        lines.append(
            f"| {entry_wib} | **{h['symbol']}** | `{h['pattern']}` | {lots_str} | {val_in_str} | {h['entry_price']:.0f} | {h['exit_price']:.0f} | "
            f"{h['target_price']:.0f} | {h['stop_loss_price']:.0f} | {fee_str} | **{net_str}** | **{pnl_sign}{h['pnl_pct']:.1f}%** | {dur_str} | "
            f"`{h['outcome']}` | {reason_text} |"
        )

    lines.extend([
        "",
        "---",
        "",
        "## 4. Log Kandidat Pra-Entry yang Dilepas",
        "*Daftar kandidat tanpa posisi terbuka; tidak ada risiko modal:*" if cfg.orderbook_exit_mode == "full" else "*Daftar sinyal radar yang tidak memenuhi konfirmasi follow-through HAKA sehingga otomatis dibatalkan dalam 10 detik tanpa risiko modal:*",
        "",
        "| Waktu Radar (WIB) | Saham | Pola Radar | Harga Ref | Durasi Watchlist | Alasan Pelepasan |" if cfg.orderbook_exit_mode == "full" else "| Waktu Radar (WIB) | Saham | Pola Radar | Harga Ref | Durasi Observasi | Alasan Pembatalan |",
        "|---|:---:|---|:---:|:---:|---|",
    ])

    for h in aborted_list:
        alert_wib = h["alert_time"].astimezone(_WIB).strftime("%H:%M:%S") if h["alert_time"] else "-"
        lines.append(f"| {alert_wib} | **{h['symbol']}** | `{h['pattern']}` | {h['ref_price']:.0f} | {h['holding_seconds']:.0f}s | {h['reason']} |")

    lines.extend([
        "",
        "---",
        "",
        "## 5. Batasan dan Hipotesis Riset Berikutnya",
        "",
        "- Hasil hanya berlaku pada sesi dan konfigurasi di atas; uji pada hari lain tanpa mengubah parameter sebelum menyimpulkan ada edge.",
        "- Slippage adverse dan fee sudah dihitung, tetapi antrean, partial fill, market impact, reject, serta latency belum dimodelkan.",
        "- Filter harga, velocity, follow-through HAKA, holding time, dan pengecualian big-cap masih merupakan hipotesis yang perlu diuji out-of-sample.",
        "- Gunakan sesi wildcard untuk screening; konfirmasi mikrostruktur dan kelengkapan transaksi sebaiknya memakai feed dedicated per saham.",
    ])

    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Stockbit Scout & Sniper Backtester & Report Generator")
    parser.add_argument("session_id", nargs="?", help="ID sesi rekaman wildcard yang ingin di-backtest (default: sesi terakhir)")
    parser.add_argument("--slots", type=int, default=5, help="Jumlah slot maksimal sniper (default 5)")
    parser.add_argument("--max-hold", type=float, default=130.0, help="Batas maksimal menahan posisi stagnan dalam detik (default 130)")
    parser.add_argument("--tp", type=float, default=3.0, help="Target persentase Take Profit (default 3.0)")
    parser.add_argument("--cl", type=float, default=1.5, help="Batas persentase Cut Loss (default 1.5)")
    parser.add_argument("--min-velocity", type=int, default=50, help="Ambang batas minimal transaksi per 5 detik untuk Breakout (default 50)")
    parser.add_argument("--min-delta-pct", type=float, default=0.75, help="Minimal kenaikan harga dalam window radar (default 0.75%%)")
    parser.add_argument("--min-haka-lots", type=float, default=100.0, help="Minimal akumulasi lot HAKA saat observasi 10s sebelum entry (default 100)")
    parser.add_argument("--min-price", type=float, default=50.0, help="Minimal harga saham untuk masuk radar sniper (default 50)")
    parser.add_argument("--max-price", type=float, default=0.0, help="Maksimal harga saham untuk masuk radar sniper (default 0 / tanpa batas)")
    parser.add_argument("--capital", type=float, default=550000.0, help="Modal trading per posisi dalam Rupiah (default Rp 550.000)")
    parser.add_argument("--fee-buy", type=float, default=0.15, help="Persentase biaya beli broker (default 0.15%%)")
    parser.add_argument("--fee-sell", type=float, default=0.25, help="Persentase biaya jual broker (default 0.25%%)")
    parser.add_argument("--include-big-caps", action="store_true", help="Sertakan saham big-caps (default: dikecualikan)")
    parser.add_argument("--all-patterns", action="store_true", help="Sertakan seluruh pola radar termasuk Squeeze & Absorption (default: Breakout saja)")
    parser.add_argument("--output", "-o", help="Path file output untuk menyimpan laporan Markdown")
    parser.add_argument("--json", action="store_true", help="Cetak output dalam format JSON")
    parser.add_argument("--orderbook", action="store_true", help="Aktifkan Tape Reading L2 (Iceberg Refill TP, Support Absorption CL, Smart Extension)")
    parser.add_argument("--hybrid", action="store_true", help="Aktifkan Mode Hybrid (Partial Scalp TP + Trailing Runner)")
    parser.add_argument("--hybrid-scalp-ratio", type=float, default=0.5, help="Rasio alokasi lot untuk Tranche 1 Scalp TP (default 0.5 = 50%%)")
    parser.add_argument("--hybrid-runner-max-hold", type=float, default=900.0, help="Batas maksimal hold untuk Tranche 2 Runner dalam detik (default 900)")
    parser.add_argument("--min-obs-seconds", type=float, default=4.0, help="Minimum durasi observasi kontinu sebelum entry (default 4 detik)")
    parser.add_argument("--min-obs-trades", type=int, default=15, help="Minimum transaksi DONE saat observasi (default 15)")
    parser.add_argument("--max-tape-silence", type=float, default=2.5, help="Maksimum jeda tape sebelum observasi batal (default 2.5 detik)")
    parser.add_argument("--min-obs-val", type=float, default=25_000_000.0, help="Minimum nilai HAKA saat observasi (default Rp 25 juta)")
    parser.add_argument("--stagnant-hold", type=float, default=90.0, help="Batas posisi mandek sebelum scratch exit (default 90 detik)")
    parser.add_argument("--l2-pre-entry", action=argparse.BooleanOptionalAction, default=False, help="Wajibkan order book L2 segar sebelum entry (default false untuk rekaman lama)")
    parser.add_argument("--orderbook-exit-mode", choices=("legacy", "full"), default="legacy", help="Mode order book: legacy atau full Watchlist Pullback")
    parser.add_argument("--orderbook-wall-min-lots", type=float, default=10_000.0, help="Minimum lot wall biasa")
    parser.add_argument("--orderbook-psych-wall-min-lots", type=float, default=50_000.0, help="Minimum lot wall psikologis")
    parser.add_argument("--orderbook-wall-ratio", type=float, default=3.0, help="Rasio wall terhadap median depth sekitar")
    parser.add_argument("--orderbook-depletion-ratio", type=float, default=0.20, help="Sisa lot maksimal untuk depleted")
    parser.add_argument("--orderbook-refill-min-lots", type=float, default=1_000.0, help="Minimum lot refill per siklus")
    parser.add_argument("--orderbook-support-levels", type=int, default=2, help="Jumlah papan support yang dicari")
    parser.add_argument("--trading-hours-guard", action=argparse.BooleanOptionalAction, default=True, help="Blokir entry di luar jam strategi (default true)")
    parser.add_argument("--paper-slippage-ticks", type=int, default=1, help="Slippage adverse per sisi dalam tick IDX (default 1)")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.slots < 1 or args.paper_slippage_ticks < 0 or args.min_delta_pct < 0:
        parser.error("slots minimal 1; slippage dan minimum delta persen tidak boleh negatif")

    from .postgres import connect_database, verify_schema
    from .radar import RadarConfig
    from pathlib import Path

    conn = None
    try:
        conn = connect_database(readonly=True)
        verify_schema(conn)

        target_session = args.session_id
        if not target_session:
            row = conn.execute(
                "SELECT id, symbol FROM stockbit_ws.sessions WHERE symbol = '*' ORDER BY run_no DESC LIMIT 1"
            ).fetchone()
            if not row:
                print("Tidak ada sesi wildcard yang ditemukan.")
                return 1
            target_session = row["id"]

        print(f"Menjalankan Backtest Scout & Sniper untuk sesi: {target_session}...")
        
        focus_patterns = [] if args.all_patterns else ["BREAKOUT_MOMENTUM"]
        radar_cfg = RadarConfig(
            enable_breakout=True,
            enable_squeeze=args.all_patterns,
            enable_absorption=False,
            breakout_min_trades=args.min_velocity,
            breakout_min_delta_pct=args.min_delta_pct,
        )

        cfg = SniperConfig(
            max_slots=args.slots,
            max_holding_seconds=args.max_hold,
            target_tp_pct=args.tp,
            stop_loss_pct=args.cl,
            trade_capital_idr=args.capital,
            fee_buy_pct=args.fee_buy,
            fee_sell_pct=args.fee_sell,
            exclude_big_caps=not args.include_big_caps,
            focus_patterns=focus_patterns,
            min_follow_through_haka_lots=args.min_haka_lots,
            min_stock_price=args.min_price,
            max_stock_price=args.max_price,
            enable_orderbook_tape_reading=args.orderbook or args.orderbook_exit_mode == "full",
            orderbook_exit_mode=args.orderbook_exit_mode,
            orderbook_wall_min_lots=args.orderbook_wall_min_lots,
            orderbook_psychological_wall_min_lots=args.orderbook_psych_wall_min_lots,
            orderbook_wall_ratio=args.orderbook_wall_ratio,
            orderbook_depletion_ratio=args.orderbook_depletion_ratio,
            orderbook_refill_min_lots=args.orderbook_refill_min_lots,
            orderbook_support_levels=args.orderbook_support_levels,
            enable_hybrid_mode=args.hybrid,
            hybrid_scalp_ratio=args.hybrid_scalp_ratio,
            hybrid_runner_max_hold_seconds=args.hybrid_runner_max_hold,
            min_observation_seconds=args.min_obs_seconds,
            min_observing_done_trades=args.min_obs_trades,
            max_tape_silence_seconds=args.max_tape_silence,
            min_observing_haka_value_idr=args.min_obs_val,
            stagnant_timeout_seconds=args.stagnant_hold,
            enable_l2_pre_entry_guard=args.l2_pre_entry,
            enable_trading_hours_guard=args.trading_hours_guard,
            paper_slippage_ticks=args.paper_slippage_ticks,
        )

        scan_res = scan_session_sniper(
            target_session,
            sniper_config=cfg,
            radar_config=radar_cfg,
            conn=conn,
        )

        if args.json:
            import json
            # Convert datetime objects to string for json serialization
            clean_hist = []
            for h in scan_res["history"]:
                c = dict(h)
                for k in ("alert_time", "entry_time", "exit_time"):
                    if c.get(k):
                        c[k] = c[k].isoformat()
                clean_hist.append(c)
            print(json.dumps(clean_hist, indent=2))
        else:
            report_text = format_sniper_report(scan_res)
            print("\n" + report_text + "\n")

            out_path = Path(args.output) if args.output else Path("reports") / f"sniper_{target_session[:8]}.md"
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(report_text, encoding="utf-8")
            print(f"Laporan hasil Sniper disimpan ke: {out_path.resolve()}")

        return 0
    finally:
        if conn is not None and not conn.closed:
            conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
