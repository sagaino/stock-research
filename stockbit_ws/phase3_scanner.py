import argparse
import datetime
from collections import defaultdict, deque
from stockbit_ws.postgres import connect_database, initialize_schema
from stockbit_ws.broker_groups import broker_group
ICEBERG_MIN_FREQ = 20  # Minimum ticks to be considered an iceberg
ICEBERG_MAX_AVG_LOT = 50 # Small lots

def format_rupiah(value):
    if value >= 1_000_000_000:
        return f"Rp {value/1_000_000_000:.1f} Miliar"
    elif value >= 1_000_000:
        return f"Rp {value/1_000_000:.1f} Juta"
    else:
        return f"Rp {value:,.0f}"

def scan_iceberg(ticks):
    """
    Heuristic: repeated small-lot buys by the same broker at a specific price.
    Returns list of dicts.
    """
    buy_ticks = [t for t in ticks if t['action'] == 'buy']
    grouped = defaultdict(lambda: {'lots': [], 'value': 0.0})
    for t in buy_ticks:
        if t['buyer_code']:
            bcode = t['buyer_code'].split()[0]
            grouped[(bcode, t['price'])]['lots'].append(t['lot'])
            grouped[(bcode, t['price'])]['value'] += t['lot'] * 100 * t['price']
            
    icebergs = []
    for (broker, price), data in grouped.items():
        lots = data['lots']
        freq = len(lots)
        total_vol = sum(lots)
        total_val = data['value']
        
        if freq == 0: continue
        avg_lot = total_vol / freq
        
        if freq >= ICEBERG_MIN_FREQ and avg_lot <= ICEBERG_MAX_AVG_LOT:
            icebergs.append({
                "broker": broker,
                "price": price,
                "frequency": freq,
                "total_lot": total_vol,
                "total_value": total_val,
                "avg_lot": round(avg_lot, 1)
            })
            
    return sorted(icebergs, key=lambda x: x['total_value'], reverse=True)

def scan_absorption(ticks):
    """
    Heuristic for a non-retail broker repeatedly taking prints from a
    configured retail-code cohort.
    """
    sell_ticks = [t for t in ticks if t['action'] == 'sell']
    absorption_vol = defaultdict(int)
    absorption_val = defaultdict(float)
    
    total_retail_dump_vol = 0
    total_retail_dump_val = 0.0
    
    for t in sell_ticks:
        if not t['seller_code'] or not t['buyer_code']:
            continue
        scode = t['seller_code'].split()[0]
        bcode = t['buyer_code'].split()[0]
        
        if broker_group(scode) == "retail":
            vol = t['lot']
            val = vol * 100 * t['price']
            
            total_retail_dump_vol += vol
            total_retail_dump_val += val
            
            absorption_vol[bcode] += vol
            absorption_val[bcode] += val
            
    absorbers = []
    for broker, vol in absorption_vol.items():
        if broker_group(broker) == "smart" and vol > 0:
            val = absorption_val[broker]
            pct_vol = (vol / total_retail_dump_vol) * 100 if total_retail_dump_vol > 0 else 0
            if pct_vol >= 5.0:
                absorbers.append({
                    "broker": broker,
                    "absorbed_lot": vol,
                    "absorbed_value": val,
                    "avg_price": round((val / vol) / 100, 1) if vol > 0 else 0,
                    "percentage": round(pct_vol, 1)
                })
                
    return sorted(absorbers, key=lambda x: x['absorbed_value'], reverse=True), total_retail_dump_vol, total_retail_dump_val

def scan_sweeping(ticks):
    """
    Detect rapid same-broker buy prints across multiple prices.  This is a
    trade-print heuristic; the feed does not contain the offer queue itself.
    """
    buy_ticks = [t for t in ticks if t['action'] == 'buy']
    windows = defaultdict(deque)
    sweeps = {}

    def seconds(value):
        return value.hour * 3600 + value.minute * 60 + value.second

    for tick in buy_ticks:
        bcode = tick['buyer_code'].split()[0] if tick['buyer_code'] else None
        if not bcode:
            continue
        window = windows[bcode]
        tick_seconds = seconds(tick['time'])
        while window and tick_seconds - seconds(window[0]['time']) > 3:
            window.popleft()
        window.append(tick)
        prices_hit = {item['price'] for item in window}
        if len(prices_hit) < 3:
            continue
        base_t = window[0]
        total_lot = sum(item['lot'] for item in window)
        total_value = sum(item['lot'] * 100 * item['price'] for item in window)
        time_label = base_t['time'].strftime("%H:%M:%S")
        key = (bcode, time_label)
        candidate = {
            "broker": bcode,
            "time": time_label,
            "prices": sorted(prices_hit),
            "total_lot": total_lot,
            "total_value": total_value,
        }
        if key not in sweeps or sweeps[key]["total_value"] < total_value:
            sweeps[key] = candidate

    return sorted(sweeps.values(), key=lambda x: x['time'])

def generate_session_story(ticks):
    """
    Reconstruct the chronological timeline and narrative of each session phase with exact Rupiah values.
    """
    phases = [
        ("09:00:00", "10:00:00", "Pagi Awal"),
        ("10:00:00", "12:00:00", "Pagi Lanjutan"),
        ("13:30:00", "15:00:00", "Siang Awal"),
        ("15:00:00", "15:35:00", "Sore Awal"),
        ("15:35:00", "15:50:00", "Sore Akhir"),
        ("15:50:00", "16:15:00", "Penutupan")
    ]
    
    results = []
    
    for t_start, t_end, name in phases:
        p_ticks = [
            t for t in ticks 
            if str(t['time']) >= t_start and str(t['time']) < t_end
        ]
        if not p_ticks:
            continue
            
        p_open = p_ticks[0]['price']
        p_close = p_ticks[-1]['price']
        p_high = max(t['price'] for t in p_ticks)
        p_low = min(t['price'] for t in p_ticks)
        pct_chg = ((p_close - p_open) / p_open * 100) if p_open else 0.0
        
        total_lot = sum(t['lot'] for t in p_ticks)
        total_val = sum(t['lot'] * 100 * t['price'] for t in p_ticks)
        
        haka_val = sum(t['lot'] * 100 * t['price'] for t in p_ticks if t['action'] == 'buy')
        haka_pct = (haka_val / total_val * 100) if total_val else 50.0
        
        haka_buyers = defaultdict(lambda: {'lot': 0, 'val': 0.0, 'prices': []})
        haki_sellers = defaultdict(lambda: {'lot': 0, 'val': 0.0, 'prices': []})
        net_brokers = defaultdict(lambda: {'buy_lot': 0, 'buy_val': 0.0, 'sell_lot': 0, 'sell_val': 0.0})
        
        for t in p_ticks:
            val = t['lot'] * 100 * t['price']
            bcode = t['buyer_code'].split()[0] if t['buyer_code'] else None
            scode = t['seller_code'].split()[0] if t['seller_code'] else None
            
            if t['action'] == 'buy' and bcode:
                haka_buyers[bcode]['lot'] += t['lot']
                haka_buyers[bcode]['val'] += val
                haka_buyers[bcode]['prices'].append(t['price'])
            elif t['action'] == 'sell' and scode:
                haki_sellers[scode]['lot'] += t['lot']
                haki_sellers[scode]['val'] += val
                haki_sellers[scode]['prices'].append(t['price'])
                
            if bcode:
                net_brokers[bcode]['buy_lot'] += t['lot']
                net_brokers[bcode]['buy_val'] += val
            if scode:
                net_brokers[scode]['sell_lot'] += t['lot']
                net_brokers[scode]['sell_val'] += val
            
        top_haka = sorted(haka_buyers.items(), key=lambda x: x[1]['val'], reverse=True)[:3]
        top_haki = sorted(haki_sellers.items(), key=lambda x: x[1]['val'], reverse=True)[:3]
        
        net_summary = []
        for b, d in net_brokers.items():
            net_val = d['buy_val'] - d['sell_val']
            net_lot = d['buy_lot'] - d['sell_lot']
            net_summary.append((b, net_val, net_lot))

        top_net_buy = sorted([x for x in net_summary if x[1] > 0 and x[2] > 0], key=lambda x: x[1], reverse=True)[:2]
        top_net_sell = sorted([x for x in net_summary if x[1] < 0 and x[2] < 0], key=lambda x: x[1])[:2]
        
        results.append({
            "window": f"{t_start[:5]} - {t_end[:5]}",
            "name": name,
            "open": p_open, "close": p_close, "high": p_high, "low": p_low,
            "pct_chg": pct_chg,
            "total_lot": total_lot,
            "total_val": total_val,
            "haka_pct": haka_pct,
            "top_haka": top_haka,
            "top_haki": top_haki,
            "top_net_buy": top_net_buy,
            "top_net_sell": top_net_sell
        })
        
    return results

def main():
    parser = argparse.ArgumentParser(description="Smart Money Confluence Scanner (Phase 3)")
    parser.add_argument("--symbol", type=str, required=True, help="Stock symbol (e.g. DSSA)")
    parser.add_argument("--date", type=str, help="YYYY-MM-DD", default=None)
    args = parser.parse_args()
    
    symbol = args.symbol.upper()
    if args.date:
        try:
            target_date = datetime.date.fromisoformat(args.date).isoformat()
        except ValueError:
            parser.error("--date harus berformat YYYY-MM-DD")
    else:
        target_date = datetime.date.today().isoformat()
    
    conn = connect_database()
    initialize_schema(conn)
    complete = conn.execute(
        "SELECT 1 FROM stockbit_ws.broker_l2_ingestion WHERE date = %s AND (symbol = '*' OR symbol = %s) LIMIT 1",
        (target_date, symbol),
    ).fetchone()
    if not complete:
        print(f"❌ L2 {symbol} pada {target_date} belum ditandai lengkap.")
        conn.close()
        return
    cur = conn.cursor()
    
    query = """
        SELECT time, price, lot, action, buyer_code, seller_code 
        FROM stockbit_ws.broker_l2_ticks
        WHERE symbol = %s AND date = %s
        ORDER BY time ASC, trade_number ASC
    """
    cur.execute(query, (symbol, target_date))
    rows = cur.fetchall()
    conn.close()
    
    if not rows:
        print(f"❌ Tidak ada data L2 Ticks untuk {symbol} pada {target_date}.")
        return
        
    ticks = []
    for r in rows:
        ticks.append({
            'time': r['time'],
            'price': float(r['price']) if r['price'] else 0,
            'lot': int(r['lot']) if r['lot'] else 0,
            'action': r['action'],
            'buyer_code': r['buyer_code'],
            'seller_code': r['seller_code']
        })
        
    print(f"\n🔬 [SMART MONEY SCANNER] Membedah {len(ticks)} ticks untuk {symbol} ({target_date})\n")
    
    icebergs = scan_iceberg(ticks)
    absorbers, total_dump_vol, total_dump_val = scan_absorption(ticks)
    sweeps = scan_sweeping(ticks)
    story_phases = generate_session_story(ticks)
    
    print("🎯 KESIMPULAN NARRATIVE:")
    narrative = []
    
    if icebergs:
        top_ice = icebergs[0]
        narrative.append(f"Heuristik pola buy kecil berulang: broker {top_ice['broker']} ({top_ice['frequency']} kali HAKA) dominan di harga {top_ice['price']} senilai {format_rupiah(top_ice['total_value'])}.")
    
    if absorbers and total_dump_vol > 0:
        top_abs = absorbers[0]
        narrative.append(f"Dalam penjualan kode ritel sebesar {format_rupiah(total_dump_val)}, broker {top_abs['broker']} mengambil {top_abs['percentage']}% print tersebut senilai {format_rupiah(top_abs['absorbed_value'])} (Avg Harga: {top_abs['avg_price']}).")
        
    if sweeps:
        s = sweeps[-1]
        narrative.append(f"Pada jam {s['time']}, broker {s['broker']} mencetak buy pada {len(s['prices'])} level harga {s['prices']} dalam jendela cepat senilai {format_rupiah(s['total_value'])}.")
        
    if not narrative:
        print("Tidak ada pola trade-print yang mencolok. Kondisi tape netral/sepi.")
    else:
        for n in narrative:
            print(" ► " + n)
            
    print("\n--------------------------------------------------")
    print("📋 DATA PENDUKUNG (TEKNIS):")
    print("\n[1] REPEATED SMALL-BUY HEURISTIC (Top 3):")
    if icebergs:
        for i, x in enumerate(icebergs[:3]):
            print(f"    {i+1}. {x['broker']} di harga {x['price']} | {x['frequency']}x | {x['total_lot']} lot ({format_rupiah(x['total_value'])})")
    else:
        print("    Nihil")
        
    print(f"\n[2] ABSORPTION DETECTOR (Total Guyuran Ritel: {total_dump_vol} lot / {format_rupiah(total_dump_val)}):")
    if absorbers:
        for i, x in enumerate(absorbers[:3]):
            print(f"    {i+1}. {x['broker']} menampung {x['absorbed_lot']} lot ({format_rupiah(x['absorbed_value'])}) di Avg Harga {x['avg_price']} - {x['percentage']}%")
    else:
        print("    Nihil")
        
    print("\n[3] RAPID MULTI-PRICE BUY HEURISTIC:")
    if sweeps:
        for x in sweeps:
            print(f"    - Jam {x['time']} | {x['broker']} sapu {len(x['prices'])} level {x['prices']} | {x['total_lot']:,} lot ({format_rupiah(x['total_value'])})")
    else:
        print("    Nihil")
        
    print("\n--------------------------------------------------")
    print("📜 [4] REKONSTRUKSI PERJALANAN HARGA & ALIRAN DANA (INTRADAY STORY):")
    for phase in story_phases:
        chg_sign = '+' if phase['pct_chg'] > 0 else ''
        
        # Format HAKA details
        haka_items = []
        for b, d in phase['top_haka']:
            avg_p = d['val'] / (d['lot'] * 100) if d['lot'] else 0
            min_p, max_p = min(d['prices']), max(d['prices'])
            haka_items.append(f"{b} ({d['lot']:,} lot | {format_rupiah(d['val'])} | Avg: {avg_p:.1f} [{min_p:.0f}-{max_p:.0f}])")
        haka_str = '\n      ► ' + '\n      ► '.join(haka_items) if haka_items else "Nihil"

        # Format HAKI details
        haki_items = []
        for s, d in phase['top_haki']:
            avg_p = d['val'] / (d['lot'] * 100) if d['lot'] else 0
            min_p, max_p = min(d['prices']), max(d['prices'])
            haki_items.append(f"{s} ({d['lot']:,} lot | {format_rupiah(d['val'])} | Avg: {avg_p:.1f} [{min_p:.0f}-{max_p:.0f}])")
        haki_str = '\n      ► ' + '\n      ► '.join(haki_items) if haki_items else "Nihil"

        # Format Net Buy details
        net_buy_items = []
        for b, n_val, n_lot in phase['top_net_buy']:
            avg_p = n_val / (n_lot * 100) if n_lot else 0
            net_buy_items.append(f"{b} (+{n_lot:,} lot | +{format_rupiah(n_val)} | Avg: {avg_p:.1f})")
        net_buy_str = ', '.join(net_buy_items) if net_buy_items else "Nihil"

        # Format Net Sell details
        net_sell_items = []
        for s, n_val, n_lot in phase['top_net_sell']:
            avg_p = abs(n_val) / (abs(n_lot) * 100) if n_lot else 0
            net_sell_items.append(f"{s} (-{abs(n_lot):,} lot | -{format_rupiah(abs(n_val))} | Avg: {avg_p:.1f})")
        net_sell_str = ', '.join(net_sell_items) if net_sell_items else "Nihil"
        
        print(f"\n[{phase['window']}] {phase['name']}")
        print(f"  • Rentang Harga  : {phase['open']:.0f} ➔ {phase['close']:.0f} ({chg_sign}{phase['pct_chg']:.1f}%) | High: {phase['high']:.0f}, Low: {phase['low']:.0f}")
        print(f"  • Total Turnover : {phase['total_lot']:,} lot ({format_rupiah(phase['total_val'])}) | Dominasi: {phase['haka_pct']:.1f}% HAKA vs {100-phase['haka_pct']:.1f}% HAKI")
        print(f"  • Top HAKA (Agresif Buy) :{haka_str}")
        print(f"  • Top HAKI (Agresif Sell):{haki_str}")
        print(f"  • Net Akumulasi : {net_buy_str}")
        print(f"  • Net Distribusi: {net_sell_str}")
    print()

    # SECTION 5: derived full-day broker summary from captured prints
    eod_brokers = defaultdict(lambda: {'b_lot': 0.0, 'b_val': 0.0, 's_lot': 0.0, 's_val': 0.0})
    for t in ticks:
        price = t['price']
        lot = t['lot']
        val = lot * 100 * price
        bcode = t['buyer_code'].split()[0] if t['buyer_code'] else None
        scode = t['seller_code'].split()[0] if t['seller_code'] else None
        
        if bcode:
            eod_brokers[bcode]['b_lot'] += lot
            eod_brokers[bcode]['b_val'] += val
        if scode:
            eod_brokers[scode]['s_lot'] += lot
            eod_brokers[scode]['s_val'] += val
            
    net_buyers_eod = []
    net_sellers_eod = []
    
    for b, d in eod_brokers.items():
        net_val = d['b_val'] - d['s_val']
        net_lot = d['b_lot'] - d['s_lot']
        
        b_avg = (d['b_val'] / (d['b_lot'] * 100)) if d['b_lot'] else 0
        s_avg = (d['s_val'] / (d['s_lot'] * 100)) if d['s_lot'] else 0
        
        if net_val > 0 and net_lot > 0:
            net_buyers_eod.append({
                'broker': b, 'val': net_val, 'lot': net_lot, 'avg': b_avg
            })
        elif net_val < 0 and net_lot < 0:
            net_sellers_eod.append({
                'broker': b, 'val': abs(net_val), 'lot': abs(net_lot), 'avg': s_avg
            })
            
    net_buyers_eod.sort(key=lambda x: x['val'], reverse=True)
    net_sellers_eod.sort(key=lambda x: x['val'], reverse=True)
    
    def fmt_short(v):
        if v >= 1e9: return f"{v/1e9:.1f}B"
        if v >= 1e6: return f"{v/1e6:.1f}M"
        if v >= 1e3: return f"{v/1e3:.1f}K"
        return f"{v:,.0f}"

    def fmt_lot_short(l):
        if l >= 1e6: return f"{l/1e6:.1f}M"
        if l >= 1e3: return f"{l/1e3:.0f}K"
        return f"{l:,.0f}"

    print("--------------------------------------------------")
    print("🏆 [5] RINGKASAN BROKER 1 HARI (DITURUNKAN DARI L2):")
    print(f"{'BY':<4} {'B.val':<8} {'B.lot':<8} {'B.avg':<6} | {'SL':<4} {'S.val':<8} {'S.lot':<8} {'S.avg':<6}")
    print("-" * 55)
    
    max_len = max(len(net_buyers_eod), len(net_sellers_eod))
    for i in range(min(10, max_len)):
        b = net_buyers_eod[i] if i < len(net_buyers_eod) else None
        s = net_sellers_eod[i] if i < len(net_sellers_eod) else None
        
        b_str = f"{b['broker']:<4} {fmt_short(b['val']):<8} {fmt_lot_short(b['lot']):<8} {b['avg']:<6.0f}" if b else " " * 28
        s_str = f"{s['broker']:<4} {fmt_short(s['val']):<8} {fmt_lot_short(s['lot']):<8} {s['avg']:<6.0f}" if s else ""
        print(f"{b_str} | {s_str}")
    print()

if __name__ == "__main__":
    main()
