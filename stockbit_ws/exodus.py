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
    
    Returns: list of broker dicts dari response["data"]["list"]
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
    return data.get("data", {}).get("list", [])


def fetch_broker_activity(
    client: httpx.Client,
    broker_code: str,
    period: str = "RT_PERIOD_LAST_1_DAY",
    transaction_type: str = "TRANSACTION_TYPE_NET",
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Fetch aktivitas satu broker (daftar saham yang ditransaksikan).
    
    API: GET /order-trade/broker/activity
    
    Returns: list of stock activity dicts dari response["data"]["list"]
    """
    all_items = []
    page = 1
    while True:
        resp = client.get(
            "/order-trade/broker/activity",
            params={
                "broker_code": broker_code,
                "limit": limit,
                "page": page,
                "transaction_type": transaction_type,
                "market_board": "MARKET_TYPE_REGULER",
                "investor_type": "INVESTOR_TYPE_ALL",
                "period": period,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        
        transaction_data = data.get("data", {}).get("broker_activity_transaction", {})
        buyers = transaction_data.get("brokers_buy", [])
        sellers = transaction_data.get("brokers_sell", [])
        
        items = buyers + sellers
        if not items:
            break
        all_items.extend(items)
        # Safety cap: max 10 pages (500 items) per broker per day
        page += 1
        if page > 10:
            break
        time.sleep(REQUEST_DELAY_SECONDS)
    return all_items


def store_top_brokers(conn, date: datetime.date, brokers: list[dict]) -> int:
    """Upsert top broker data ke stockbit_ws.broker_top_daily.
    
    Menggunakan ON CONFLICT DO UPDATE agar re-run aman (idempotent).
    Returns: jumlah row yang diproses.
    """
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
    with conn.transaction():
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
    """Upsert broker stock activity ke stockbit_ws.broker_stock_activity.
    
    Parsing response structure:
    Setiap item di activities memiliki:
      - stock_code: "DSSA"
      - net_val: "-15343500"
      - buy_val / sell_val (mungkin nested atau flat)
      - buy_lot / sell_lot
      - buy_avg / sell_avg (jika tersedia)
    
    Returns: jumlah row yang diproses.
    """
    if not activities:
        return 0
    rows = []
    for a in activities:
        symbol = a.get("stock_code") or a.get("symbol")
        if not symbol:
            continue
        
        net_val = _safe_numeric(a.get("value"))
        lot = _safe_numeric(a.get("lot"))
        avg_price = _safe_numeric(a.get("avg_price"))
        
        is_buy = net_val is not None and net_val > 0
        
        rows.append((
            date,
            broker_code,
            symbol.upper(),
            net_val,
            net_val if is_buy else 0,
            abs(net_val) if not is_buy and net_val is not None else 0,
            lot if is_buy else 0,
            abs(lot) if not is_buy and lot is not None else 0,
            avg_price if is_buy else None,
            avg_price if not is_buy else None,
            None,
            None,
        ))
    if not rows:
        return 0
    with conn.transaction():
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
        date: Tanggal target (default: hari ini jika sebelum 16:15, kemarin jika sudah lewat)
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
        
        for i, code in enumerate(top_codes, 1):
            time.sleep(REQUEST_DELAY_SECONDS)
            try:
                print(f"📡 [{i}/{len(top_codes)}] Fetching activity broker {code}...")
                activities = fetch_broker_activity(client, code)
                count = store_broker_activity(conn, date, code, activities)
                stats["activities_stored"] += count
                stats["brokers_processed"] += 1
                print(f"   → {count} saham tersimpan")
            except (httpx.HTTPStatusError, httpx.RequestError) as e:
                error_msg = f"Broker {code}: {type(e).__name__}"
                stats["errors"].append(error_msg)
                print(f"   ⚠️  {error_msg}")
                continue
        
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
