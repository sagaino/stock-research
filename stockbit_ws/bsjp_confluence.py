"""
Stockbit BPJU Confluence Engine.
Fuses Market Microstructure, L2 Tick Flow, and Exodus Broker Footprints
to generate heuristic BPJU (Beli Pagi Jual Untung) candidates for tomorrow.
"""

from __future__ import annotations

import argparse
import datetime
from collections import defaultdict
from pathlib import Path
from typing import Any

from stockbit_ws.postgres import connect_database, initialize_schema
from stockbit_ws.broker_groups import broker_group
from stockbit_ws.sniper import round_to_idx_tick

def format_rupiah(val: float) -> str:
    if abs(val) >= 1_000_000_000:
        return f"Rp {val/1_000_000_000:.2f}B"
    if abs(val) >= 1_000_000:
        return f"Rp {val/1_000_000:.1f}M"
    return f"Rp {val:,.0f}"

def format_lot(val: float) -> str:
    if abs(val) >= 1_000_000:
        return f"{val/1_000_000:.2f}M"
    if abs(val) >= 1_000:
        return f"{val/1_000:.1f}K"
    return f"{val:,.0f}"

def run_bsjp_confluence(
    target_date: str,
    min_turnover_idr: float = 5_000_000_000,
    min_trades: int = 1_000,
    max_premium_pct: float = 4.0,
    trust_existing_l2: bool = False,
) -> list[dict[str, Any]]:
    """Scan broker_l2_ticks for classified broker flow and closing momentum."""
    try:
        target_date = datetime.date.fromisoformat(target_date).isoformat()
    except ValueError:
        raise ValueError("Format tanggal harus YYYY-MM-DD") from None
    conn = connect_database()
    initialize_schema(conn)
    complete = conn.execute(
        "SELECT 1 FROM stockbit_ws.broker_l2_ingestion WHERE date = %s AND symbol = '*'",
        (target_date,),
    ).fetchone()
    if not complete and not trust_existing_l2:
        conn.close()
        return []
    if trust_existing_l2 and not complete:
        existing = conn.execute(
            "SELECT 1 FROM stockbit_ws.broker_l2_ticks WHERE date = %s LIMIT 1",
            (target_date,),
        ).fetchone()
        if not existing:
            conn.close()
            return []
    cur = conn.cursor()

    # 1. Fetch liquid candidates closing green near High of Day
    query_symbols = """
        SELECT 
            symbol,
            count(*) as trades,
            sum(lot) as total_lot,
            sum(lot * price * 100) as total_val,
            (array_agg(price ORDER BY time ASC, trade_number ASC))[1] as open_p,
            (array_agg(price ORDER BY time DESC, trade_number DESC))[1] as close_p,
            max(price) as high_p,
            min(price) as low_p,
            sum(case when time >= '15:00:00' then lot * price * 100 else 0 end) as val_15,
            sum(case when time >= '15:00:00' and action = 'buy' then lot * price * 100 else 0 end) as haka_15,
            sum(case when time >= '15:00:00' and action = 'sell' then lot * price * 100 else 0 end) as haki_15
        FROM stockbit_ws.broker_l2_ticks
        WHERE date = %s
        GROUP BY symbol
        HAVING sum(lot * price * 100) >= %s
           AND count(*) >= %s
    """
    cur.execute(query_symbols, (target_date, min_turnover_idr, min_trades))
    symbols_meta = cur.fetchall()

    if not symbols_meta:
        conn.close()
        return []

    confluence_picks = []

    for s in symbols_meta:
        sym = s["symbol"]
        open_p = float(s["open_p"])
        close_p = float(s["close_p"])
        high_p = float(s["high_p"])
        low_p = float(s["low_p"])
        total_val = float(s["total_val"])
        total_lot = float(s["total_lot"])
        val_15 = float(s["val_15"] or 0)
        haka_15 = float(s["haka_15"] or 0)
        haki_15 = float(s["haki_15"] or 0)

        # Basic Technical Filters
        if close_p <= open_p:
            continue  # Must be a green candle
        
        hod_pct = (close_p / high_p * 100.0) if high_p else 0
        if hod_pct < 95.0:
            continue  # Must close near HOD (minimum 95% of HOD)

        # Afternoon momentum: must have active turnover in power-hour (15:00+)
        if val_15 < 100_000_000:
            continue
        haka_15_pct = (haka_15 / val_15 * 100.0) if val_15 else 50.0

        # Fetch ticks for full day broker dissection
        cur.execute("""
            SELECT buyer_code, seller_code, price, lot, action, time
            FROM stockbit_ws.broker_l2_ticks
            WHERE symbol = %s AND date = %s
        """, (sym, target_date))
        ticks = cur.fetchall()

        brokers = defaultdict(lambda: {"b_val": 0.0, "s_val": 0.0, "b_lot": 0.0, "s_lot": 0.0})
        retail_net_val = 0.0
        smart_net_val = 0.0

        # Also track 15:00+ late session broker moves
        late_brokers = defaultdict(lambda: {"b_val": 0.0, "s_val": 0.0})

        for t in ticks:
            p = float(t["price"])
            l = float(t["lot"])
            v = l * 100 * p
            b = t["buyer_code"].split()[0] if t["buyer_code"] else None
            sc = t["seller_code"].split()[0] if t["seller_code"] else None
            t_time = str(t["time"])

            if b:
                brokers[b]["b_val"] += v
                brokers[b]["b_lot"] += l
                if t_time >= "15:00:00":
                    late_brokers[b]["b_val"] += v
            if sc:
                brokers[sc]["s_val"] += v
                brokers[sc]["s_lot"] += l
                if t_time >= "15:00:00":
                    late_brokers[sc]["s_val"] += v

        # Calculate Net
        net_list = []
        for bcode, d in brokers.items():
            n_val = d["b_val"] - d["s_val"]
            n_lot = d["b_lot"] - d["s_lot"]
            b_avg = (d["b_val"] / (d["b_lot"] * 100)) if d["b_lot"] else 0
            s_avg = (d["s_val"] / (d["s_lot"] * 100)) if d["s_lot"] else 0
            
            group = broker_group(bcode)
            if group == "retail":
                retail_net_val += n_val
            elif group == "smart":
                smart_net_val += n_val

            net_list.append({
                "broker": bcode,
                "net_val": n_val,
                "net_lot": n_lot,
                "buy_avg": b_avg,
                "sell_avg": s_avg,
                "gross_buy_val": d["b_val"],
                "gross_sell_val": d["s_val"],
            })

        net_list.sort(key=lambda x: x["net_val"], reverse=True)
        top_buyers = [
            x for x in net_list
            if x["net_val"] > 0 and broker_group(x["broker"]) == "smart"
        ]
        top_sellers = [x for x in net_list if x["net_val"] < 0]
        top_sellers.sort(key=lambda x: x["net_val"])  # Most negative first

        if not top_buyers:
            continue

        primary_buyer = top_buyers[0]

        # FILTER 2: Retail Must Be Net Sellers (Smart Money is taking their shares)
        if retail_net_val >= 0:
            continue

        # FILTER 3: Top Buyer's gross average cost vs close price.
        top_b_avg = primary_buyer["buy_avg"]
        premium_pct = ((close_p - top_b_avg) / top_b_avg * 100.0) if top_b_avg else 0.0
        if premium_pct > max_premium_pct:
            continue  # Already extended above the broker average.

        # Late session check: did smart money dump at the close?
        late_top_buyer_net = late_brokers[primary_buyer["broker"]]["b_val"] - late_brokers[primary_buyer["broker"]]["s_val"]

        # CONFLUENCE SCORING ALGORITHM (0 - 100)
        score = 60.0  # Base pass score

        # 1. Retail Dumping Strength (+15 max)
        retail_dump_ratio = abs(retail_net_val) / total_val if total_val else 0
        if retail_dump_ratio >= 0.15:
            score += 15.0
        elif retail_dump_ratio >= 0.08:
            score += 10.0
        else:
            score += 5.0

        # 2. Cost Basis Cushion (+15 max)
        # The closer the close price is to the broker average, the higher the score.
        if -1.0 <= premium_pct <= 1.5:
            score += 15.0
        elif 1.5 < premium_pct <= 3.5:
            score += 10.0
        elif 3.5 < premium_pct <= max_premium_pct:
            score += 5.0

        # 3. Close to HOD strength (+10 max)
        if hod_pct >= 99.0:
            score += 10.0
        elif hod_pct >= 97.0:
            score += 7.0
        else:
            score += 4.0

        # 4. Late Session / Power Hour Flow (+10 max)
        if late_top_buyer_net > 0 and haka_15_pct >= 55.0:
            score += 10.0
        elif late_top_buyer_net >= 0:
            score += 5.0

        # Grade Assignment
        score = min(100.0, score)
        if score >= 90.0:
            grade = "A+ (STRONG CONFLUENCE)"
        elif score >= 80.0:
            grade = "A (STRONG HEURISTIC)"
        else:
            grade = "B+ (SOLID SPECULATIVE)"

        # Trading Plan formulation
        entry_low = round_to_idx_tick(close_p)
        entry_high = round_to_idx_tick(close_p * 1.015)  # up to +1.5% at open
        tp1 = round_to_idx_tick(close_p * 1.025)        # +2.5% morning scalp
        tp2 = round_to_idx_tick(close_p * 1.050)        # +5.0% runner
        sl = round_to_idx_tick(min(open_p, top_b_avg * 0.98))  # Below open or -2% of broker average.
        risk = entry_low - sl
        rr_ratio = (tp1 - entry_low) / risk if risk > 0 else 0.0

        gain_pct = ((close_p - open_p) / open_p * 100.0) if open_p else 0.0

        confluence_picks.append({
            "symbol": sym,
            "close": close_p,
            "open": open_p,
            "high": high_p,
            "low": low_p,
            "gain_pct": gain_pct,
            "hod_pct": hod_pct,
            "total_val": total_val,
            "total_lot": total_lot,
            "score": score,
            "grade": grade,
            "primary_buyer": primary_buyer["broker"],
            "primary_buyer_val": primary_buyer["net_val"],
            "primary_buyer_lot": primary_buyer["net_lot"],
            "primary_buyer_avg": top_b_avg,
            "premium_pct": premium_pct,
            "smart_net": smart_net_val,
            "retail_net": retail_net_val,
            "top_buyers_summary": [f"{x['broker']} (+{format_rupiah(x['net_val'])})" for x in top_buyers[:3]],
            "top_sellers_summary": [f"{x['broker']} ({format_rupiah(x['net_val'])})" for x in top_sellers[:3]],
            "plan": {
                "entry": f"{int(entry_low)} - {int(entry_high)}",
                "tp1": f"{int(tp1)} (+2.5%)",
                "tp2": f"{int(tp2)} (+5.0%)",
                "sl": f"{int(sl)} ({round((sl - close_p)/close_p*100, 1)}%)",
                "rr_ratio": f"1 : {rr_ratio:.1f}"
            }
        })

    conn.close()
    confluence_picks.sort(key=lambda x: (x["score"], x["smart_net"]), reverse=True)
    return confluence_picks


def generate_report(picks: list[dict[str, Any]], target_date: str) -> str:
    """Generate a Markdown report of BPJU heuristic candidates."""
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    md = []
    md.append(f"# 🚀 LAPORAN KANDIDAT BPJU CONFLUENCE")
    md.append(f"**Tanggal Analisis:** `{target_date}` | **Waktu Rilis:** `{now_str}`")
    md.append(f"**Engine:** `Stockbit Exodus L2 Microstructure & Smart Money Confluence`\n")
    
    md.append("---")
    md.append("### 🎯 Executive Summary (Filosofi Sinyal):")
    md.append("Kandidat BPJU ini dihasilkan melalui **5 Pilar Confluence** (heuristik, bukan probabilitas teruji):")
    md.append("1. **Broker Terklasifikasi**: Pembeli utama harus ada dalam daftar broker smart-money terkonfigurasi.")
    md.append("2. **Penjualan Kode Ritel**: Kode ritel terkonfigurasi tercatat melakukan **Net Sell**.")
    md.append("3. **Closing Urgency**: Harga ditutup kuat di atas 95% s/d 100% High of Day.")
    md.append("4. **Cost Basis Heuristic**: Harga closing belum lari jauh dari rata-rata pembelian broker tersebut (Margin < +4%).")
    md.append("5. **Likuiditas Minimum**: Turnover tercatat minimal Rp 5 Miliar.\n")

    if not picks:
        md.append("⚠️ **Tidak ada saham yang memenuhi seluruh 5 Pilar Confluence ketat untuk tanggal ini.**")
        md.append("*(Disiplin trading: Lebih baik tidak trading daripada masuk ke jebakan ritel/fake markup).*")
        return "\n".join(md)

    md.append(f"## 🏆 TOP {min(5, len(picks))} REKOMENDASI UTAMA UNTUK BESOK PAGI\n")

    for i, p in enumerate(picks[:5], 1):
        md.append(f"### {i}. {p['symbol']} — {p['grade']} (Skor: {p['score']:.0f}/100)")
        md.append(f"- **Harga Closing:** `Rp {int(p['close']):,}` (`+{p['gain_pct']:.1f}%`) | **HOD Strength:** `{p['hod_pct']:.1f}%`")
        md.append(f"- **Total Turnover:** `{format_rupiah(p['total_val'])}` ({format_lot(p['total_lot'])} lot)")
        md.append(f"- **Broker Smart-Money Utama (terklasifikasi):** **`{p['primary_buyer']}`** Net Buy `{format_rupiah(p['primary_buyer_val'])}` @ Avg `Rp {p['primary_buyer_avg']:.1f}`")
        md.append(f"- **Margin terhadap Rata-rata Broker:** `{p['premium_pct']:+.1f}%` *(indikator jarak harga, bukan bukti posisi terbuka)*")
        md.append(f"- **Aliran Dana Terklasifikasi:** Smart **`+{format_rupiah(p['smart_net'])}`** ➔ Kode Ritel **`{format_rupiah(p['retail_net'])}`**")
        md.append(f"- **Top 3 Pembeli:** {', '.join(p['top_buyers_summary'])}")
        md.append(f"- **Top 3 Penjual:** {', '.join(p['top_sellers_summary'])}")
        md.append(f"\n📋 **Rencana Trading Eksekusi Besok Pagi:**")
        md.append(f"| Area Masuk (Beli Pagi) | Target Profit 1 (Scalp) | Target Profit 2 (Runner) | Cut Loss (SL) | Risk/Reward |")
        md.append(f"| :---: | :---: | :---: | :---: | :---: |")
        md.append(f"| `Rp {p['plan']['entry']}` | `Rp {p['plan']['tp1']}` | `Rp {p['plan']['tp2']}` | `Rp {p['plan']['sl']}` | `{p['plan']['rr_ratio']}` |")
        md.append("\n" + "-" * 50 + "\n")

    md.append("## 📊 TABEL RADAR SELURUH KANDIDAT LOLOS SCREENING CONFLUENCE\n")
    md.append("| No | Saham | Close | Chg (%) | HOD (%) | Top Buyer | Net Val | Avg Broker | Margin | Smart Net | Ritel Net | Skor |")
    md.append("|:--:|:-----:|:-----:|:-------:|:-------:|:---------:|:-------:|:------------:|:------:|:----------:|:---------:|:----:|")
    
    for i, p in enumerate(picks, 1):
        md.append(f"| {i} | **{p['symbol']}** | {int(p['close']):,} | +{p['gain_pct']:.1f}% | {p['hod_pct']:.1f}% | {p['primary_buyer']} | {format_rupiah(p['primary_buyer_val'])} | {p['primary_buyer_avg']:.0f} | {p['premium_pct']:+.1f}% | +{format_rupiah(p['smart_net'])} | {format_rupiah(p['retail_net'])} | **{p['score']:.0f}** |")

    md.append("\n\n---\n*Peringatan Risiko: Kandidat ini bersifat heuristik dan menggunakan data yang tersedia saja. Verifikasi likuiditas, fraksi harga, dan risiko sebelum mengambil keputusan.*")
    return "\n".join(md)


def main():
    parser = argparse.ArgumentParser(description="Stockbit BPJU Confluence Candidate Scanner")
    parser.add_argument("--date", type=str, help="YYYY-MM-DD", default=None)
    parser.add_argument("--min-val", type=float, default=5_000_000_000, help="Minimum turnover IDR (default: 5B)")
    parser.add_argument("--max-prem", type=float, default=4.0, help="Maximum premium above broker average (default: 4%%)")
    parser.add_argument(
        "--trust-existing-l2", action="store_true",
        help="Gunakan tick L2 lama pada tanggal target meski belum punya marker kelengkapan",
    )
    args = parser.parse_args()

    conn = connect_database()
    if args.date:
        try:
            target_date = datetime.date.fromisoformat(args.date).isoformat()
        except ValueError:
            parser.error("--date harus berformat YYYY-MM-DD")
    else:
        # Default to latest date in broker_l2_ticks
        row = conn.execute("SELECT max(date) as d FROM stockbit_ws.broker_l2_ticks").fetchone()
        if not row or not row.get("d"):
            print("❌ Tidak ada data L2 Ticks di database.")
            conn.close()
            return
        target_date = row["d"].isoformat()
    conn.close()

    print(f"🔍 Menjalankan BPJU Confluence Scanner untuk tanggal {target_date}...")
    print(f"   Filter: Min Turnover {format_rupiah(args.min_val)} | Max Premium {args.max_prem}%")

    if args.trust_existing_l2:
        print("⚠️ Menggunakan L2 lama tanpa marker kelengkapan sesuai pilihan pengguna.")
    picks = run_bsjp_confluence(
        target_date,
        min_turnover_idr=args.min_val,
        max_premium_pct=args.max_prem,
        trust_existing_l2=args.trust_existing_l2,
    )

    report_md = generate_report(picks, target_date)

    # Save report
    out_dir = Path("reports")
    out_dir.mkdir(exist_ok=True)
    out_file = out_dir / f"bsjp_confluence_{target_date.replace('-', '')}.md"
    out_file.write_text(report_md, encoding="utf-8")

    print(f"\n✅ Ditemukan {len(picks)} saham lolos screening Confluence!")
    print(f"📄 Laporan lengkap tersimpan di: {out_file}")
    print("\n" + "=" * 60)
    
    # Print Top 5 to terminal
    for i, p in enumerate(picks[:5], 1):
        print(f"{i}. [{p['grade']}] {p['symbol']} (Close: {int(p['close']):,} | Skor: {p['score']:.0f}/100)")
        print(f"   Top Buyer: {p['primary_buyer']} Net +{format_rupiah(p['primary_buyer_val'])} @ Avg {p['primary_buyer_avg']:.0f} (Margin: {p['premium_pct']:+.1f}%)")
        print(f"   Aliran terklasifikasi: Smart Net +{format_rupiah(p['smart_net'])} vs Ritel Net {format_rupiah(p['retail_net'])}")
        print(f"   Plan: Beli {p['plan']['entry']} | TP1: {p['plan']['tp1']} | TP2: {p['plan']['tp2']} | SL: {p['plan']['sl']}")
        print("-" * 60)

if __name__ == "__main__":
    main()
