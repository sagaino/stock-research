"""EOD Broker data ingestion from Stockbit Exodus REST API."""

from __future__ import annotations

import argparse
import datetime
import sys
import time
from typing import Any

import httpx

from .config import load_environment
from .postgres import connect_database, initialize_schema

EXODUS_BASE = "https://exodus.stockbit.com"
REQUEST_DELAY_SECONDS = 0.5  # Rate limiting antar request
REQUEST_TIMEOUT_SECONDS = 15.0
MAX_RETRIES = 2


def load_exodus_token(env_file=".env") -> str:
    """Load EXODUS_TOKEN dari .env file.
    
    Token ini adalah Bearer token dari session Stockbit yang aktif.
    Bisa didapat dari browser DevTools → Network → Header Authorization
    pada request ke exodus.stockbit.com.
    """
    values = load_environment(env_file)
    token = values.get("EXODUS_TOKEN", "").strip()
    if not token:
        raise ValueError(
            "EXODUS_TOKEN belum diisi di .env. "
            "Ambil dari browser DevTools → Network → exodus.stockbit.com → "
            "Header 'Authorization: Bearer <token>'."
        )
    return token


def _exodus_client(token: str) -> httpx.Client:
    """Create configured httpx client dengan auth header."""
    return httpx.Client(
        base_url=EXODUS_BASE,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Origin": "https://stockbit.com",
            "Referer": "https://stockbit.com/",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
        },
        timeout=REQUEST_TIMEOUT_SECONDS,
        follow_redirects=False,
    )


def fetch_top_brokers(
    client: httpx.Client,
    date: datetime.date,
) -> list[dict[str, Any]]:
    """Fetch top broker ranking untuk satu tanggal.
    
    API: GET /order-trade/broker/top
    Params:
        sort=TB_SORT_BY_TOTAL_VALUE
        order=ORDER_BY_DESC
        from={date}
        to={date}
        market_type=MARKET_TYPE_REGULER
    
    Returns: broker rows sorted locally by ``total_value`` descending.  The
    endpoint may ignore its sort/limit parameters.
    Raises: httpx.HTTPStatusError pada 4xx/5xx
    """
    resp = client.get(
        "/order-trade/broker/top",
        params={
            "sort": "TB_SORT_BY_TOTAL_VALUE",
            "order": "ORDER_BY_DESC",
            "from": date.isoformat(),
            "to": date.isoformat(),
            "market_type": "MARKET_TYPE_REGULER",
        },
    )
    resp.raise_for_status()
    data = resp.json()
    envelope = data.get("data") or {}
    date_meta = envelope.get("date") if isinstance(envelope.get("date"), dict) else {}
    reported_from = envelope.get("from") or date_meta.get("from")
    reported_to = envelope.get("to") or date_meta.get("to")
    if reported_from and str(reported_from)[:10] != date.isoformat():
        raise ValueError("Top broker API returned a different start date")
    if reported_to and str(reported_to)[:10] != date.isoformat():
        raise ValueError("Top broker API returned a different end date")
    brokers = envelope.get("list") or []
    return sorted(
        brokers,
        key=lambda broker: _safe_numeric(broker.get("total_value")) or 0.0,
        reverse=True,
    )


def fetch_broker_activity(
    client: httpx.Client,
    broker_code: str,
    period: str = "RT_PERIOD_LAST_1_DAY",
    transaction_type: str = "TRANSACTION_TYPE_NET",
    limit: int = 50,
    *,
    target_date: datetime.date | None = None,
) -> list[dict[str, Any]]:
    """Fetch aktivitas satu broker (daftar saham yang ditransaksikan).
    
    API: GET /order-trade/broker/activity
    
    ``target_date`` uses the API's explicit ``from``/``to`` window.  The
    endpoint does not provide a reliable historical date when only the
    relative ``period`` preset is sent, so callers must pass the target date
    for an EOD audit.

    Returns: normalized list from ``brokers_buy``/``brokers_sell``.  Each row
    carries an internal ``_side`` marker because both API lists use positive
    values.
    """
    all_items = []
    page = 1
    while True:
        params = {
            "broker_code": broker_code,
            "limit": limit,
            "page": page,
            "transaction_type": transaction_type,
            "market_board": "MARKET_TYPE_REGULER",
            "investor_type": "INVESTOR_TYPE_ALL",
        }
        if target_date is None:
            params["period"] = period
        else:
            params["from"] = target_date.isoformat()
            params["to"] = target_date.isoformat()

        resp = client.get(
            "/order-trade/broker/activity",
            params=params,
        )
        resp.raise_for_status()
        data = resp.json()
        envelope = data.get("data") or {}

        # Refuse to persist a response that advertises a different window.
        # Older API responses omit these fields, in which case the explicit
        # from/to request remains the only available date contract.
        if target_date is not None:
            reported_from = envelope.get("from")
            reported_to = envelope.get("to")
            if reported_from and str(reported_from)[:10] != target_date.isoformat():
                raise ValueError("Broker activity API returned a different start date")
            if reported_to and str(reported_to)[:10] != target_date.isoformat():
                raise ValueError("Broker activity API returned a different end date")
        
        transaction_data = envelope.get("broker_activity_transaction") or {}
        buyers = transaction_data.get("brokers_buy") or []
        sellers = transaction_data.get("brokers_sell") or []

        # The API reports ``value`` and ``lot`` as positive numbers on both
        # sides. Keep the container side attached so storage can derive a
        # signed net value instead of treating every seller as a buyer.
        items = [dict(item, _side="buy") for item in buyers]
        items.extend(dict(item, _side="sell") for item in sellers)
        if not items:
            break
        all_items.extend(items)
        page += 1
        time.sleep(REQUEST_DELAY_SECONDS)
    return all_items


def store_top_brokers(conn, date: datetime.date, brokers: list[dict]) -> int:
    """Replace the daily top-broker snapshot and return its row count."""
    if not brokers:
        return 0
    rows = [
        (
            date,
            b["code"],
            b.get("name"),
            _safe_numeric(b.get("total_value")),
            _safe_numeric(b.get("net_value")),
            _safe_numeric(b.get("buy_value")),
            _safe_numeric(b.get("sell_value")),
            _safe_numeric(b.get("total_volume")),
            int(b["total_frequency"]) if b.get("total_frequency") else None,
            b.get("group"),
        )
        for b in brokers
        if b.get("code")
    ]
    if not rows:
        raise ValueError("Top broker response contains no broker code")
    with conn.transaction():
        conn.execute("DELETE FROM stockbit_ws.broker_top_daily WHERE date = %s", (date,))
        conn.cursor().executemany(
            """INSERT INTO stockbit_ws.broker_top_daily
                (date, broker_code, broker_name, total_value, net_value,
                 buy_value, sell_value, total_volume, total_frequency, broker_group)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (date, broker_code) DO UPDATE SET
                broker_name = EXCLUDED.broker_name,
                total_value = EXCLUDED.total_value,
                net_value = EXCLUDED.net_value,
                buy_value = EXCLUDED.buy_value,
                sell_value = EXCLUDED.sell_value,
                total_volume = EXCLUDED.total_volume,
                total_frequency = EXCLUDED.total_frequency,
                broker_group = EXCLUDED.broker_group,
                fetched_at = now()
            """,
            rows,
        )
    return len(rows)


def store_broker_activity(
    conn,
    date: datetime.date,
    broker_code: str,
    activities: list[dict],
) -> int:
    """Replace one broker/date activity snapshot.
    
    Parsing response structure:
    Setiap item di activities memiliki:
      - stock_code: "DSSA"
      - ``value``, ``lot``, ``avg_price`` on the API's buy/sell lists
      - ``net_val`` / ``buy_val`` / ``sell_val`` for already-normalized data

    Exodus encodes sell ``value``/``lot`` as negative numbers.  Database
    ``buy_*``/``sell_*`` columns store positive magnitudes; ``net_value`` is
    derived as buy minus sell.
    
    Returns: jumlah row yang diproses.
    """
    aggregated = {}
    for a in activities:
        symbol = a.get("stock_code") or a.get("symbol")
        if not symbol:
            continue

        def number(*keys):
            for key in keys:
                if key in a:
                    value = _safe_numeric(a.get(key))
                    if value is not None:
                        return value
            return None

        side = str(a.get("_side") or a.get("type") or "").lower()
        raw_value = number("value")
        net_val = number("net_value", "net_val")
        buy_val = number("buy_value", "buy_val")
        sell_val = number("sell_value", "sell_val")
        if buy_val is not None:
            buy_val = abs(buy_val)
        if sell_val is not None:
            sell_val = abs(sell_val)
        if raw_value is not None and not (buy_val is not None or sell_val is not None):
            magnitude = abs(raw_value)
            if "sell" in side:
                sell_val, net_val = magnitude, -magnitude
            elif "buy" in side:
                buy_val, net_val = magnitude, magnitude
            else:
                net_val = raw_value
        if net_val is None and (buy_val is not None or sell_val is not None):
            net_val = (buy_val or 0) - (sell_val or 0)
        if buy_val is None:
            buy_val = net_val if net_val is not None and net_val > 0 else 0
        if sell_val is None:
            sell_val = abs(net_val) if net_val is not None and net_val < 0 else 0

        lot = number("lot", "net_lot")
        buy_lot = number("buy_lot")
        sell_lot = number("sell_lot")
        if buy_lot is not None:
            buy_lot = abs(buy_lot)
        if sell_lot is not None:
            sell_lot = abs(sell_lot)
        if buy_lot is None and "buy" in side:
            buy_lot = abs(lot or 0)
        if sell_lot is None and "sell" in side:
            sell_lot = abs(lot or 0)
        if buy_lot is None and net_val is not None and net_val > 0:
            buy_lot = abs(lot or 0)
        if sell_lot is None and net_val is not None and net_val < 0:
            sell_lot = abs(lot or 0)
        avg_price = number("avg_price", "buy_avg_price", "buy_avg")
        sell_avg_price = number("sell_avg_price", "sell_avg")

        item = aggregated.setdefault(symbol.upper(), {
            "net_val": 0.0, "buy_val": 0.0, "sell_val": 0.0,
            "buy_lot": 0.0, "sell_lot": 0.0,
            "buy_avg_weight": 0.0, "buy_avg_value": 0.0,
            "sell_avg_weight": 0.0, "sell_avg_value": 0.0,
        })
        item["net_val"] += net_val or 0
        item["buy_val"] += buy_val or 0
        item["sell_val"] += sell_val or 0
        item["buy_lot"] += buy_lot or 0
        item["sell_lot"] += sell_lot or 0
        if avg_price is not None and buy_val:
            weight = buy_lot or buy_val
            item["buy_avg_weight"] += weight
            item["buy_avg_value"] += avg_price * weight
        if sell_avg_price is None and "sell" in side:
            sell_avg_price = avg_price
        if sell_avg_price is not None and sell_val:
            weight = sell_lot or sell_val
            item["sell_avg_weight"] += weight
            item["sell_avg_value"] += sell_avg_price * weight

    rows = []
    for symbol, item in aggregated.items():
        buy_val = item["buy_val"]
        sell_val = item["sell_val"]
        buy_lot = item["buy_lot"]
        sell_lot = item["sell_lot"]
        buy_avg = (
            item["buy_avg_value"] / item["buy_avg_weight"]
            if item["buy_avg_weight"] else (buy_val / (buy_lot * 100) if buy_lot else None)
        )
        sell_avg = (
            item["sell_avg_value"] / item["sell_avg_weight"]
            if item["sell_avg_weight"] else (sell_val / (sell_lot * 100) if sell_lot else None)
        )
        net_val = buy_val - sell_val if buy_val or sell_val else item["net_val"]
        rows.append((
            date, broker_code, symbol, net_val, buy_val, sell_val,
            buy_lot, sell_lot, buy_avg, sell_avg, None, None,
        ))
    if activities and not rows:
        raise ValueError("Broker activity response contains no stock symbol")
    with conn.transaction():
        conn.execute(
            "DELETE FROM stockbit_ws.broker_stock_activity WHERE date = %s AND broker_code = %s",
            (date, broker_code),
        )
        if rows:
            conn.cursor().executemany(
                """INSERT INTO stockbit_ws.broker_stock_activity
                (date, broker_code, symbol, net_value, buy_value, sell_value,
                 buy_lot, sell_lot, buy_avg_price, sell_avg_price,
                 buy_lot_pct, sell_lot_pct)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (date, broker_code, symbol) DO UPDATE SET
                net_value = EXCLUDED.net_value,
                buy_value = EXCLUDED.buy_value,
                sell_value = EXCLUDED.sell_value,
                buy_lot = EXCLUDED.buy_lot,
                sell_lot = EXCLUDED.sell_lot,
                buy_avg_price = EXCLUDED.buy_avg_price,
                sell_avg_price = EXCLUDED.sell_avg_price,
                buy_lot_pct = EXCLUDED.buy_lot_pct,
                sell_lot_pct = EXCLUDED.sell_lot_pct,
                fetched_at = now()
            """,
                rows,
            )
    return len(rows)


def _safe_numeric(val) -> float | None:
    """Safely parse numeric string dari API response.
    
    API Exodus mengembalikan angka sebagai string (misal "5903868083778").
    Fungsi ini mengkonversi ke float, return None jika gagal.
    """
    if val is None or val == "":
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def run_ingestion(
    date: datetime.date | None = None,
    top_n_brokers: int = 20,
    env_file: str = ".env",
) -> dict[str, Any]:
    """Main ingestion orchestrator.
    
    Flow:
    1. Load token dari .env
    2. Fetch top brokers untuk tanggal target
    3. Store top brokers ke DB
    4. Untuk top N broker (by total_value), fetch broker activity
    5. Store setiap broker activity ke DB
    6. Return summary statistics
    
    Args:
        date: Tanggal target (default: kemarin sebelum 16:15 WIB, hari ini sesudahnya)
        top_n_brokers: Jumlah top broker yang akan di-drill-down activity-nya
        env_file: Path ke file .env
    
    Returns:
        Dict dengan total brokers fetched, total activities stored, errors
    """
    if date is None:
        date = _resolve_default_date()
    
    token = load_exodus_token(env_file)
    conn = connect_database()
    initialize_schema(conn)
    
    stats = {
        "date": date.isoformat(),
        "brokers_stored": 0,
        "activities_stored": 0,
        "brokers_processed": 0,
        "eod_complete": False,
        "errors": [],
    }
    
    try:
        client = _exodus_client(token)
        
        # Step 1: Fetch & store top brokers
        print(f"📡 Fetching top brokers for {date.isoformat()}...")
        brokers = fetch_top_brokers(client, date)
        if not brokers:
            print(f"⚠️  Tidak ada data top broker untuk {date.isoformat()}")
            return stats
        
        stored = store_top_brokers(conn, date, brokers)
        stats["brokers_stored"] = stored
        print(f"✅ {stored} broker tersimpan ke broker_top_daily")
        
        # Step 2: Drill-down top N brokers → fetch activity per saham
        top_codes = [b["code"] for b in brokers[:top_n_brokers] if b.get("code")]
        # A refresh is incomplete until every requested broker snapshot succeeds.
        conn.execute("DELETE FROM stockbit_ws.broker_eod_ingestion WHERE date = %s", (date,))
        
        for i, code in enumerate(top_codes, 1):
            time.sleep(REQUEST_DELAY_SECONDS)
            try:
                print(f"📡 [{i}/{len(top_codes)}] Fetching activity broker {code}...")
                activities = fetch_broker_activity(client, code, target_date=date)
                count = store_broker_activity(conn, date, code, activities)
                stats["activities_stored"] += count
                stats["brokers_processed"] += 1
                print(f"   → {count} saham tersimpan")
            except (httpx.HTTPStatusError, httpx.RequestError) as e:
                error_msg = f"Broker {code}: {type(e).__name__}"
                stats["errors"].append(error_msg)
                print(f"   ⚠️  {error_msg}")
                continue

        if len(top_codes) == top_n_brokers and not stats["errors"] and stats["brokers_processed"] == len(top_codes):
            with conn.transaction():
                conn.execute(
                    """DELETE FROM stockbit_ws.broker_stock_activity
                       WHERE date = %s AND broker_code <> ALL(%s::text[])""",
                    (date, top_codes),
                )
                conn.execute(
                    """INSERT INTO stockbit_ws.broker_eod_ingestion
                   (date, top_n, brokers_requested, brokers_processed, activities_stored)
                   VALUES (%s, %s, %s, %s, %s)
                   ON CONFLICT (date) DO UPDATE SET
                     top_n = EXCLUDED.top_n,
                     brokers_requested = EXCLUDED.brokers_requested,
                     brokers_processed = EXCLUDED.brokers_processed,
                     activities_stored = EXCLUDED.activities_stored,
                     completed_at = now()""",
                    (date, top_n_brokers, len(top_codes), stats["brokers_processed"], stats["activities_stored"]),
                )
            stats["eod_complete"] = True
            print(f"✅ EOD {date.isoformat()} ditandai lengkap ({len(top_codes)} broker).")
        
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 401:
            print("❌ Token expired atau tidak valid. Update EXODUS_TOKEN di .env")
        raise
    finally:
        conn.close()
    
    return stats


def _resolve_default_date() -> datetime.date:
    """Determine default target date berdasarkan waktu WIB saat ini.
    
    - Sebelum 16:15 WIB → kemarin (data hari ini belum final)
    - Setelah 16:15 WIB → hari ini
    - Weekend → Jumat terakhir
    """
    wib = datetime.timezone(datetime.timedelta(hours=7))
    now = datetime.datetime.now(wib)
    
    if now.hour < 16 or (now.hour == 16 and now.minute < 15):
        target = now.date() - datetime.timedelta(days=1)
    else:
        target = now.date()
    
    # Skip weekend
    while target.weekday() >= 5:  # 5=Saturday, 6=Sunday
        target -= datetime.timedelta(days=1)
    
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Stockbit Exodus Broker Data Ingestion"
    )
    parser.add_argument(
        "--date", type=str, default=None,
        help="Tanggal target YYYY-MM-DD (default: auto-resolve hari trading terakhir)"
    )
    parser.add_argument(
        "--top-n", type=int, default=20,
        help="Jumlah top broker yang di-drill-down activity-nya (default: 20)"
    )
    parser.add_argument(
        "--env-file", default=".env",
        help="File .env untuk EXODUS_TOKEN (default: .env)"
    )
    args = parser.parse_args(argv)
    
    target_date = None
    if args.date:
        try:
            target_date = datetime.date.fromisoformat(args.date)
        except ValueError:
            print(f"❌ Format tanggal tidak valid: '{args.date}'. Gunakan YYYY-MM-DD.")
            return 1
    
    try:
        stats = run_ingestion(
            date=target_date,
            top_n_brokers=args.top_n,
            env_file=args.env_file,
        )
    except Exception as e:
        print(f"❌ Ingestion gagal: {e}")
        return 1
    
    print(f"\\n📊 Ringkasan Ingestion {stats['date']}:")
    print(f"   Broker top: {stats['brokers_stored']}")
    print(f"   Broker di-drill-down: {stats['brokers_processed']}")
    print(f"   Total aktivitas saham: {stats['activities_stored']}")
    if stats["errors"]:
        print(f"   ⚠️  Error: {len(stats['errors'])} broker gagal diambil")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
