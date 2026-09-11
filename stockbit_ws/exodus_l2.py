import os
import time
import random
import argparse
import datetime
import httpx
from typing import List, Optional

from dotenv import load_dotenv
from stockbit_ws.postgres import connect_database, initialize_schema

REQUEST_TIMEOUT_SECONDS = 15.0
MIN_DELAY = 1.0
MAX_DELAY = 1.5
BACKOFF_SECONDS = 60
MAX_RETRIES = 10

def _resolve_default_date() -> datetime.date:
    """Resolve the default date for L2 data extraction."""
    now = datetime.datetime.now()
    if now.weekday() >= 5:  # Saturday or Sunday
        days_to_subtract = now.weekday() - 4
        target = now.date() - datetime.timedelta(days=days_to_subtract)
    else:
        if now.hour < 16 or (now.hour == 16 and now.minute < 15):
            target = now.date() - datetime.timedelta(days=1)
            if target.weekday() >= 5:
                days_to_subtract = target.weekday() - 4
                target = target - datetime.timedelta(days=days_to_subtract)
        else:
            target = now.date()
    return target

def _safe_numeric(val) -> Optional[float]:
    if val is None or val == "":
        return None
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        cleaned = val.replace(",", "").replace("%", "").strip()
        if not cleaned:
            return None
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None

def fetch_l2_ticks_forward(client: httpx.Client, date: str, symbols: List[str] = None, start_cursor: int = None):
    """
    Fetches the running trade / L2 ticks chronologically using sort=ASC.
    Yields batches of items to be inserted.
    """
    params = {
        "date": date,
        "sort": "ASC",
        "limit": 80,
        "order_by": "RUNNING_TRADE_ORDER_BY_TIME"
    }
    
    if symbols:
        params["symbols[]"] = symbols

    trade_number_cursor = start_cursor
    total_fetched = 0
    page = 1
    consecutive_errors = 0
    
    while True:
        if trade_number_cursor:
            params["trade_number"] = trade_number_cursor
            
        print(f"📡 Requesting page {page} for {symbols or 'WILDCARD'} (cursor: {trade_number_cursor or 'START'})...")
        try:
            resp = client.get("/order-trade/running-trade", params=params)
            resp.raise_for_status()
            consecutive_errors = 0  # Reset error count on success
        except httpx.HTTPStatusError as e:
            status = e.response.status_code
            if status in (429, 500, 502, 503, 504):
                consecutive_errors += 1
                if consecutive_errors > MAX_RETRIES:
                    print(f"❌ Gagal setelah {MAX_RETRIES} percobaan beruntun. Menghentikan script.")
                    break
                print(f"⚠️ Server mendeteksi spam (Error {status}). Istirahat {BACKOFF_SECONDS} detik agar aman...")
                time.sleep(BACKOFF_SECONDS)
                continue
            else:
                print(f"❌ API Error Fatal: {e}")
                break
        except httpx.RequestError as e:
            consecutive_errors += 1
            if consecutive_errors > MAX_RETRIES:
                break
            print(f"⚠️ Koneksi terputus: {e}. Menunggu 10 detik...")
            time.sleep(10)
            continue
            
        data = resp.json()
        items = data.get("data", {}).get("running_trade", [])
        
        if not items:
            break
            
        yield items
        
        total_fetched += len(items)
        trade_number_cursor = items[-1].get("trade_number")
        page += 1
        
        # Pacing: Random delay to mimic human behavior
        time.sleep(random.uniform(MIN_DELAY, MAX_DELAY))

def store_l2_ticks(conn, items: list, date_str: str) -> int:
    """Store L2 ticks into Postgres idempotently."""
    rows = []
    for item in items:
        # item id is usually string
        _id = item.get("id")
        _time = item.get("time")
        symbol = item.get("code")
        if not _id or not symbol:
            continue
            
        action = item.get("action")
        price = _safe_numeric(item.get("price"))
        lot = _safe_numeric(item.get("lot"))
        buyer = item.get("buyer")
        seller = item.get("seller")
        buyer_type = item.get("buyer_type")
        seller_type = item.get("seller_type")
        trade_number = _safe_numeric(item.get("trade_number"))
        
        rows.append((
            _id, date_str, _time, symbol, price, lot, action,
            buyer, seller, buyer_type, seller_type, trade_number
        ))
        
    if not rows:
        return 0

    query = """
        INSERT INTO stockbit_ws.broker_l2_ticks (
            id, date, time, symbol, price, lot, action,
            buyer_code, seller_code, buyer_type, seller_type, trade_number
        ) VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
        )
        ON CONFLICT (id) DO NOTHING
    """
    
    cur = conn.cursor()
    cur.executemany(query, rows)
    conn.commit()
    return cur.rowcount

def run_ingestion(target_date: str, symbols: List[str] = None):
    load_dotenv()
    token = os.environ.get("EXODUS_TOKEN")
    if not token:
        raise ValueError("EXODUS_TOKEN tidak ditemukan di .env")

    client = httpx.Client(
        base_url="https://exodus.stockbit.com",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
        },
        timeout=REQUEST_TIMEOUT_SECONDS,
        follow_redirects=False,
    )

    conn = connect_database()
    initialize_schema(conn)
    
    # 1. AUTO-RESUME CHECKPOINT
    cur = conn.cursor()
    if symbols:
        cur.execute("SELECT max(trade_number) FROM stockbit_ws.broker_l2_ticks WHERE date = %s AND symbol = ANY(%s)", (target_date, symbols))
    else:
        cur.execute("SELECT max(trade_number) FROM stockbit_ws.broker_l2_ticks WHERE date = %s", (target_date,))
    
    row = cur.fetchone()
    start_cursor = row['max'] if row and row['max'] else None
    
    if start_cursor:
        print(f"🔄 Auto-Resume aktif: Melanjutkan dari trade_number terakhir di DB ({start_cursor})")
    
    total_saved = 0
    try:
        for batch in fetch_l2_ticks_forward(client, target_date, symbols, start_cursor):
            saved = store_l2_ticks(conn, batch, target_date)
            total_saved += saved
            
    except KeyboardInterrupt:
        print("\n⚠️ Dihentikan paksa oleh pengguna.")
    finally:
        conn.close()
        client.close()
        
    print(f"\n📊 Ringkasan L2 Tape Ingestion {target_date}:")
    print(f"   Target: {symbols or 'WILDCARD (Seluruh IHSG)'}")
    print(f"   Total Tick L2 Tersimpan Baru: {total_saved}")

def main():
    parser = argparse.ArgumentParser(description="Stockbit Exodus L2 Tick Scraper")
    parser.add_argument("--date", type=str, help="YYYY-MM-DD", default=None)
    parser.add_argument("--symbols", type=str, help="Comma separated symbols (e.g. DSSA,BBCA)", default=None)
    parser.add_argument("--wildcard", action="store_true", help="Scrape all symbols (WARNING: extremely heavy/slow)")
    args = parser.parse_args()

    if args.date:
        target_date = args.date
    else:
        target_date = _resolve_default_date().isoformat()

    symbols = None
    if args.symbols:
        symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
        
    if args.wildcard and args.symbols:
        print("❌ Jangan gabungkan --wildcard dan --symbols")
        return
        
    if not args.wildcard and not args.symbols:
        print("❌ Anda harus memilih antara mode L2 spesifik (--symbols) ATAU mode barbar (--wildcard)")
        return
        
    print(f"Mulai menyedot L2 Tape untuk tanggal {target_date}...")
    run_ingestion(target_date, symbols)

if __name__ == "__main__":
    main()
