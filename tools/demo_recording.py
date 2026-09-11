"""Create explicitly SYNTHETIC market events without Stockbit credentials or networking."""

import argparse
from datetime import datetime, timedelta, timezone

from stockbit_ws.recording import RecordingError
from stockbit_ws.postgres import PostgresRecorder


def create_demo():
    start = datetime(2026, 9, 4, 2, tzinfo=timezone.utc)
    writer = PostgresRecorder("COCO", start, source="SYNTHETIC")

    def emit(seconds, kind, payload):
        writer.append(kind, payload, start + timedelta(seconds=seconds), seconds)

    def book(side, price, shares):
        return {"symbol": "COCO", "side": side, "levels": [{"price": price, "shares": shares, "frequency": 3}]}

    def trade(identifier, seconds, side=1):
        return {"symbol": "COCO", "timestamp": start + timedelta(seconds=seconds), "price": 136,
                "shares": 10000, "sideCode": side, "tradeId": identifier,
                "changePoints": 6, "changePercent": 4.62, "transactionValue": 1360000}

    try:
        emit(0, "connection", {"state": "CONNECTING"})
        emit(0.2, "connection", {"state": "CONNECTED"})
        emit(1, "book", book("BID", 135, 12000))
        emit(1, "book", book("OFFER", 136, 22000))
        emit(1, "done", {"trades": [trade(100, 0)]})
        emit(3, "done", {"trades": [trade(100, 0), trade(101, 2)]})
        emit(4, "book", book("BID", 135, 15000))
        # A heartbeat-like message after silence does not refresh market data.
        emit(22, "message", {"format": "binary", "size": 29})
        emit(25, "connection", {"state": "DISCONNECTED"})
        writer.close(start + timedelta(seconds=25), 25)
    except Exception:
        writer.close(start + timedelta(seconds=25), 25, "ERROR")
        raise
    return writer.session_id


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Buat rekaman SYNTHETIC untuk mencoba replay offline.")
    parser.add_argument("--output", choices=["postgres"], default="postgres", help="Rekam demo ke PostgreSQL")
    args = parser.parse_args()
    try:
        session_id = create_demo()
        print(f"Demo SYNTHETIC tersimpan. Session: {session_id}")
        print("Jalankan replay dengan: uv run python index.py --replay")
    except RecordingError as error:
        print(f"Error: {error}")
        raise SystemExit(1) from None
