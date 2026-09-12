import argparse
import datetime
import itertools
from collections import defaultdict
from stockbit_ws.postgres import connect_database

RETAIL_BROKERS = {"YP", "PD", "XC", "NI", "CC", "XL"}
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
    Detect Iceberg buying: high frequency of small lot buys by the same broker at a specific price.
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
    Detect who is absorbing retail panic selling.
    Looks at 'sell' action (HAKI) where seller is retail.
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
        
        if scode in RETAIL_BROKERS:
            vol = t['lot']
            val = vol * 100 * t['price']
            
            total_retail_dump_vol += vol
            total_retail_dump_val += val
            
            absorption_vol[bcode] += vol
            absorption_val[bcode] += val
            
    absorbers = []
    for broker, vol in absorption_vol.items():
        if broker not in RETAIL_BROKERS and vol > 0:
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
    Detect aggressive sweeping: same buyer, sequential rapid buys crossing multiple price levels.
    """
    buy_ticks = [t for t in ticks if t['action'] == 'buy']
    sweeps = []
    
    for i in range(len(buy_ticks)):
        base_t = buy_ticks[i]
        bcode = base_t['buyer_code'].split()[0] if base_t['buyer_code'] else None
        if not bcode: continue
        
        prices_hit = {base_t['price']}
        total_vol = base_t['lot']
        total_val = base_t['lot'] * 100 * base_t['price']
        end_idx = i
        
        for j in range(i + 1, len(buy_ticks)):
            next_t = buy_ticks[j]
            next_bcode = next_t['buyer_code'].split()[0] if next_t['buyer_code'] else None
            
            if next_bcode != bcode:
                break
                
            t1 = datetime.datetime.combine(datetime.date.today(), base_t['time'])
            t2 = datetime.datetime.combine(datetime.date.today(), next_t['time'])
            diff = (t2 - t1).total_seconds()
            
            if diff > 3:
                break
                
            prices_hit.add(next_t['price'])
            total_vol += next_t['lot']
            total_val += next_t['lot'] * 100 * next_t['price']
            end_idx = j
            
        if len(prices_hit) >= 3 and end_idx > i:
            sweeps.append({
                "broker": bcode,
                "time": base_t['time'].strftime("%H:%M:%S"),
                "prices": sorted(list(prices_hit)),
                "total_lot": total_vol,
                "total_value": total_val
            })
            
    dedup = {}
    for s in sweeps:
        key = (s['broker'], s['time'])
        if key not in dedup or dedup[key]['total_value'] < s['total_value']:
            dedup[key] = s
            
    return sorted(list(dedup.values()), key=lambda x: x['time'])

def generate_session_story(ticks):
    """
    Reconstruct the chronological timeline and narrative of each session phase with exact Rupiah values.
    """
    phases = [
        ("08:45:00", "10:00:00", "Sesi 1 Pagi (Morning Wave)"),
        ("10:00:00", "11:30:00", "Sesi 1 Siang (Konsolidasi/Cooling)"),
        ("13:30:00", "15:00:00", "Sesi 2 Awal (Akumulasi/Konsolidasi)"),
        ("15:00:00", "15:35:00", "Sesi 2 Sore (Rampage / Euphoria)"),
        ("15:35:00", "15:50:00", "Sesi 2 Akhir (Distribusi / Panic Dump)"),
        ("15:50:00", "16:15:00", "Closing & Post-Closing (Pencocokan Akhir)")
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
        
        haka_buyers = defaultdict(float)
        haki_sellers = defaultdict(float)
        net_brokers = defaultdict(float)
        
        for t in p_ticks:
            val = t['lot'] * 100 * t['price']
            bcode = t['buyer_code'].split()[0] if t['buyer_code'] else None
            scode = t['seller_code'].split()[0] if t['seller_code'] else None
            
            if t['action'] == 'buy' and bcode:
                haka_buyers[bcode] += val
            elif t['action'] == 'sell' and scode:
                haki_sellers[scode] += val
                
            if bcode: net_brokers[bcode] += val
            if scode: net_brokers[scode] -= val
            
        top_haka = sorted(haka_buyers.items(), key=lambda x: x[1], reverse=True)[:3]
        top_haki = sorted(haki_sellers.items(), key=lambda x: x[1], reverse=True)[:3]
        top_net_buy = sorted([x for x in net_brokers.items() if x[1] > 0], key=lambda x: x[1], reverse=True)[:2]
        top_net_sell = sorted([x for x in net_brokers.items() if x[1] < 0], key=lambda x: x[1])[:2]
        
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
    target_date = args.date or datetime.date.today().isoformat()
    
    conn = connect_database()
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
        narrative.append(f"Terdeteksi broker {top_ice['broker']} melakukan Iceberg Buying ({top_ice['frequency']} kali HAKA) dominan di harga {top_ice['price']} senilai {format_rupiah(top_ice['total_value'])}.")
    
    if absorbers and total_dump_vol > 0:
        top_abs = absorbers[0]
        narrative.append(f"Saat ritel panik HAKI sebesar {format_rupiah(total_dump_val)}, broker {top_abs['broker']} menampung {top_abs['percentage']}% guyuran tersebut senilai {format_rupiah(top_abs['absorbed_value'])} (Avg Harga: {top_abs['avg_price']}).")
        
    if sweeps:
        s = sweeps[-1]
        narrative.append(f"Pada jam {s['time']}, broker {s['broker']} secara buas menyapu HAKA {len(s['prices'])} level harga {s['prices']} sekaligus senilai {format_rupiah(s['total_value'])}!")
        
    if not narrative:
        print("Tidak ada pergerakan Smart Money yang mencolok. Kondisi tape netral/sepi.")
    else:
        for n in narrative:
            print(" ► " + n)
            
    print("\n--------------------------------------------------")
    print("📋 DATA PENDUKUNG (TEKNIS):")
    print("\n[1] ICEBERG DETECTOR (Top 3):")
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
        
    print("\n[3] AGGRESSIVE SWEEPS (Sapu Rata):")
    if sweeps:
        for x in sweeps:
            print(f"    - Jam {x['time']} | {x['broker']} sapu {len(x['prices'])} level {x['prices']} ({format_rupiah(x['total_value'])})")
    else:
        print("    Nihil")
        
    print("\n--------------------------------------------------")
    print("📜 [4] REKONSTRUKSI PERJALANAN HARGA & ALIRAN DANA (INTRADAY STORY):")
    for phase in story_phases:
        chg_sign = '+' if phase['pct_chg'] > 0 else ''
        haka_str = ', '.join([f"{b} ({format_rupiah(v)})" for b, v in phase['top_haka']]) or "Nihil"
        haki_str = ', '.join([f"{s} ({format_rupiah(v)})" for s, v in phase['top_haki']]) or "Nihil"
        net_buy_str = ', '.join([f"{b} (+{format_rupiah(v)})" for b, v in phase['top_net_buy']]) or "Nihil"
        net_sell_str = ', '.join([f"{s} (-{format_rupiah(abs(v))})" for s, v in phase['top_net_sell']]) or "Nihil"
        
        print(f"\n[{phase['window']}] {phase['name']}")
        print(f"  • Rentang Harga  : {phase['open']:.0f} ➔ {phase['close']:.0f} ({chg_sign}{phase['pct_chg']:.1f}%) | High: {phase['high']:.0f}, Low: {phase['low']:.0f}")
        print(f"  • Total Transaksi: {phase['total_lot']:,} lot ({format_rupiah(phase['total_val'])}) | Dominasi: {phase['haka_pct']:.1f}% HAKA vs {100-phase['haka_pct']:.1f}% HAKI")
        print(f"  • Top HAKA (Agresif Buy) : {haka_str}")
        print(f"  • Top HAKI (Agresif Sell): {haki_str}")
        print(f"  • Net Akumulasi : {net_buy_str}")
        print(f"  • Net Distribusi: {net_sell_str}")
    print()

if __name__ == "__main__":
    main()
