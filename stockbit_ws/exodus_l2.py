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
    wib = datetime.timezone(datetime.timedelta(hours=7))
    now = datetime.datetime.now(wib)
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
        if trade_number_cursor is not None:
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
                    raise RuntimeError(
                        f"L2 ingestion gagal setelah {MAX_RETRIES} percobaan beruntun (HTTP {status})."
                    ) from e
                print(f"⚠️ Server mendeteksi spam (Error {status}). Istirahat {BACKOFF_SECONDS} detik agar aman...")
                time.sleep(BACKOFF_SECONDS)
                continue
            else:
                raise RuntimeError(f"L2 ingestion dihentikan oleh API (HTTP {status}).") from e
        except httpx.RequestError as e:
            consecutive_errors += 1
            if consecutive_errors > MAX_RETRIES:
                raise RuntimeError(
                    f"L2 ingestion gagal setelah {MAX_RETRIES} kesalahan koneksi."
                ) from e
            print(f"⚠️ Koneksi terputus: {e}. Menunggu 10 detik...")
            time.sleep(10)
            continue
            
        data = resp.json()
        items = data.get("data", {}).get("running_trade", [])
        
        if not items:
            break
            
        yield items
        
        total_fetched += len(items)
        raw_cursor = items[-1].get("trade_number")
        try:
            next_cursor = int(raw_cursor)
        except (TypeError, ValueError):
            next_cursor = None
        if next_cursor is None or (
            trade_number_cursor is not None and next_cursor <= int(trade_number_cursor)
        ):
            raise RuntimeError("L2 API tidak mengembalikan cursor trade_number yang maju")
        trade_number_cursor = next_cursor
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
    try:
        target_date = datetime.date.fromisoformat(target_date).isoformat()
    except ValueError:
        raise ValueError("Format tanggal L2 harus YYYY-MM-DD") from None

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
    start_cursor = row['max'] if row and row['max'] is not None else None
    
    if start_cursor is not None:
        print(f"🔄 Auto-Resume aktif: Melanjutkan dari trade_number terakhir di DB ({start_cursor})")
    
    total_saved = 0
    completed = False
    try:
        for batch in fetch_l2_ticks_forward(client, target_date, symbols, start_cursor):
            saved = store_l2_ticks(conn, batch, target_date)
            total_saved += saved
        completed = True

        # A symbol's presence in broker_l2_ticks is not a completeness proof.
        # Record the terminal empty-page pass so downstream scanners can tell
        # a complete scrape from an interrupted one.
        for symbol in symbols or ["*"]:
            row = conn.execute(
                "SELECT max(trade_number) AS max_trade FROM stockbit_ws.broker_l2_ticks WHERE date = %s AND (%s = '*' OR symbol = %s)",
                (target_date, symbol, symbol),
            ).fetchone()
            conn.execute(
                """INSERT INTO stockbit_ws.broker_l2_ingestion
                   (date, symbol, last_trade_number)
                   VALUES (%s, %s, %s)
                   ON CONFLICT (date, symbol) DO UPDATE SET
                     completed_at = now(), last_trade_number = EXCLUDED.last_trade_number""",
                (target_date, symbol, row["max_trade"] if row else None),
            )

    except KeyboardInterrupt:
        print("\n⚠️ Dihentikan paksa oleh pengguna.")
    finally:
        conn.close()
        client.close()
        
    print(f"\n📊 Ringkasan L2 Tape Ingestion {target_date}:")
    print(f"   Target: {symbols or 'WILDCARD (Seluruh IHSG)'}")
    print(f"   Total Tick L2 Tersimpan Baru: {total_saved}")
    return total_saved if completed else None

def main():
    parser = argparse.ArgumentParser(description="Stockbit Exodus L2 Tick Scraper")
    parser.add_argument("--date", type=str, help="YYYY-MM-DD", default=None)
    parser.add_argument("--symbols", type=str, help="Comma separated symbols (e.g. DSSA,BBCA)", default=None)
    parser.add_argument("--wildcard", action="store_true", help="Scrape all symbols (WARNING: extremely heavy/slow)")
    args = parser.parse_args()

    if args.date:
        try:
            target_date = datetime.date.fromisoformat(args.date).isoformat()
        except ValueError:
            print(f"❌ Format tanggal tidak valid: '{args.date}'. Gunakan YYYY-MM-DD.")
            return 1
    else:
        target_date = _resolve_default_date().isoformat()

    symbols = None
    if args.symbols:
        symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
        if not symbols:
            print("❌ --symbols harus berisi setidaknya satu kode saham")
            return 2
        symbols = list(dict.fromkeys(symbols))
        
    if args.wildcard and args.symbols:
        print("❌ Jangan gabungkan --wildcard dan --symbols")
        return 2
        
    if not args.wildcard and not args.symbols:
        print("❌ Pilih salah satu: mode L2 spesifik (--symbols) atau mode seluruh pasar (--wildcard)")
        return 2
        
    print(f"Mulai menyedot L2 Tape untuk tanggal {target_date}...")
    try:
        run_ingestion(target_date, symbols)
    except Exception as e:
        print(f"❌ Ingestion L2 gagal: {e}")
        return 1
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
