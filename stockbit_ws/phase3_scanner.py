import argparse
import datetime
import itertools
from collections import defaultdict
from stockbit_ws.postgres import connect_database

RETAIL_BROKERS = {"YP", "PD", "XC", "NI", "CC"}
ICEBERG_MIN_FREQ = 20  # Minimum ticks to be considered an iceberg
ICEBERG_MAX_AVG_LOT = 50 # Small lots

def scan_iceberg(ticks):
    """
    Detect Iceberg buying: high frequency of small lot buys by the same broker at a specific price.
    Returns list of dicts.
    """
    # Group by (buyer, price)
    buy_ticks = [t for t in ticks if t['action'] == 'buy']
    grouped = defaultdict(list)
    for t in buy_ticks:
        if t['buyer_code']:
            # Strip "[D]" if present
            bcode = t['buyer_code'].split()[0]
            grouped[(bcode, t['price'])].append(t['lot'])
            
    icebergs = []
    for (broker, price), lots in grouped.items():
        freq = len(lots)
        total_vol = sum(lots)
        if freq == 0: continue
        avg_lot = total_vol / freq
        
        if freq >= ICEBERG_MIN_FREQ and avg_lot <= ICEBERG_MAX_AVG_LOT:
            icebergs.append({
                "broker": broker,
                "price": price,
                "frequency": freq,
                "total_lot": total_vol,
                "avg_lot": round(avg_lot, 1)
            })
            
    return sorted(icebergs, key=lambda x: x['total_lot'], reverse=True)

def scan_absorption(ticks):
    """
    Detect who is absorbing retail panic selling.
    Looks at 'sell' action (HAKI) where seller is retail.
    """
    sell_ticks = [t for t in ticks if t['action'] == 'sell']
    retail_dump = defaultdict(int)
    absorption = defaultdict(int)
    
    total_retail_dump = 0
    
    for t in sell_ticks:
        if not t['seller_code'] or not t['buyer_code']:
            continue
        scode = t['seller_code'].split()[0]
        bcode = t['buyer_code'].split()[0]
        
        if scode in RETAIL_BROKERS:
            vol = t['lot']
            retail_dump[scode] += vol
            total_retail_dump += vol
            # Track who is the buyer of this dumped lot
            absorption[bcode] += vol
            
    absorbers = []
    for broker, vol in absorption.items():
        if broker not in RETAIL_BROKERS and vol > 0:
            pct = (vol / total_retail_dump) * 100 if total_retail_dump > 0 else 0
            if pct >= 5.0:  # Minimum 5% absorption
                absorbers.append({
                    "broker": broker,
                    "absorbed_lot": vol,
                    "percentage": round(pct, 1)
                })
                
    return sorted(absorbers, key=lambda x: x['absorbed_lot'], reverse=True), total_retail_dump

def scan_sweeping(ticks):
    """
    Detect aggressive sweeping: same buyer, sequential rapid buys crossing multiple price levels.
    """
    buy_ticks = [t for t in ticks if t['action'] == 'buy']
    sweeps = []
    
    # We will look for sequences of buys by the same broker within a 3-second window
    # spanning at least 3 different prices.
    
    for i in range(len(buy_ticks)):
        base_t = buy_ticks[i]
        bcode = base_t['buyer_code'].split()[0] if base_t['buyer_code'] else None
        if not bcode: continue
        
        prices_hit = {base_t['price']}
        total_vol = base_t['lot']
        end_idx = i
        
        # Look ahead
        for j in range(i + 1, len(buy_ticks)):
            next_t = buy_ticks[j]
            next_bcode = next_t['buyer_code'].split()[0] if next_t['buyer_code'] else None
            
            if next_bcode != bcode:
                # Stop if interrupted by another buyer? 
                # Or just ignore and check time? Let's strictly require sequence.
                # Actually, in a busy tape, others might interleave. Let's just check time difference.
                break
                
            # Time difference check
            # time is datetime.time
            t1 = datetime.datetime.combine(datetime.date.today(), base_t['time'])
            t2 = datetime.datetime.combine(datetime.date.today(), next_t['time'])
            diff = (t2 - t1).total_seconds()
            
            if diff > 3:
                break
                
            prices_hit.add(next_t['price'])
            total_vol += next_t['lot']
            end_idx = j
            
        if len(prices_hit) >= 3 and end_idx > i:
            # Found a sweep
            sweeps.append({
                "broker": bcode,
                "time": base_t['time'].strftime("%H:%M:%S"),
                "prices": sorted(list(prices_hit)),
                "total_lot": total_vol
            })
            
    # Deduplicate sweeps (since i loop will find overlapping sequences)
    dedup = {}
    for s in sweeps:
        key = (s['broker'], s['time'])
        if key not in dedup or dedup[key]['total_lot'] < s['total_lot']:
            dedup[key] = s
            
    return sorted(list(dedup.values()), key=lambda x: x['time'])

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
        print(f"Pastikan Anda sudah menyedot datanya menggunakan: uv run stockbit-l2 --symbols {symbol} --date {target_date}")
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
    absorbers, total_dump = scan_absorption(ticks)
    sweeps = scan_sweeping(ticks)
    
    print("🎯 KESIMPULAN NARRATIVE:")
    narrative = []
    
    # 1. Iceberg Narrative
    if icebergs:
        top_ice = icebergs[0]
        narrative.append(f"Terdeteksi broker {top_ice['broker']} melakukan Iceberg Buying ({top_ice['frequency']} kali HAKA kecil-kecil) dominan di harga {top_ice['price']}.")
    
    # 2. Absorption Narrative
    if absorbers and total_dump > 0:
        top_abs = absorbers[0]
        narrative.append(f"Saat ritel panik HAKI, broker {top_abs['broker']} bertindak sebagai pahlawan menampung {top_abs['percentage']}% ({top_abs['absorbed_lot']} lot) dari total guyuran ritel.")
        
    # 3. Sweep Narrative
    if sweeps:
        s = sweeps[-1] # Most recent
        narrative.append(f"Pada jam {s['time']}, broker {s['broker']} secara buas menyapu HAKA {len(s['prices'])} level harga sekaligus sebanyak {s['total_lot']} lot!")
        
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
            print(f"    {i+1}. {x['broker']} di harga {x['price']} | Frekuensi: {x['frequency']}x | Total: {x['total_lot']} lot | Rata-rata lot: {x['avg_lot']}")
    else:
        print("    Nihil")
        
    print(f"\n[2] ABSORPTION DETECTOR (Total Guyuran Ritel: {total_dump} lot):")
    if absorbers:
        for i, x in enumerate(absorbers[:3]):
            print(f"    {i+1}. {x['broker']} menampung {x['absorbed_lot']} lot ({x['percentage']}%)")
    else:
        print("    Nihil")
        
    print("\n[3] AGGRESSIVE SWEEPS (Sapu Rata):")
    if sweeps:
        for x in sweeps:
            print(f"    - Jam {x['time']} | {x['broker']} menyapu {len(x['prices'])} level harga ({x['prices']}) total {x['total_lot']} lot")
    else:
        print("    Nihil")
    print()

if __name__ == "__main__":
    main()
