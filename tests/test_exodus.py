"""Unit tests for exodus broker ingestion module.

Run: uv run python -m unittest tests/test_exodus.py -v
Integration tests with real DB:
    STOCKBIT_TEST_POSTGRES=1 uv run python -m unittest tests/test_exodus.py -v
"""

import datetime
import os
import unittest
from unittest.mock import MagicMock, patch

import httpx

from stockbit_ws.exodus import (
    _safe_numeric,
    _resolve_default_date,
    fetch_top_brokers,
    store_top_brokers,
    store_broker_activity,
    load_exodus_token
)
from stockbit_ws.postgres import connect_database, initialize_schema


class TestExodusUnit(unittest.TestCase):
    def test_safe_numeric_parses_string_integers(self):
        self.assertEqual(_safe_numeric("5903868083778"), 5903868083778.0)
        self.assertEqual(_safe_numeric("0"), 0.0)

    def test_safe_numeric_parses_negative_strings(self):
        self.assertEqual(_safe_numeric("-261003011300"), -261003011300.0)

    def test_safe_numeric_returns_none_on_invalid(self):
        self.assertIsNone(_safe_numeric(""))
        self.assertIsNone(_safe_numeric(None))
        self.assertIsNone(_safe_numeric("abc"))

    @patch("stockbit_ws.exodus.datetime")
    def test_resolve_default_date_weekday_after_market(self, mock_datetime):
        wib = datetime.timezone(datetime.timedelta(hours=7))
        # Thursday 17:00 WIB
        mock_datetime.datetime.now.return_value = datetime.datetime(2026, 9, 10, 17, 0, tzinfo=wib)
        mock_datetime.timedelta = datetime.timedelta
        mock_datetime.timezone = datetime.timezone
        self.assertEqual(_resolve_default_date(), datetime.date(2026, 9, 10))

    @patch("stockbit_ws.exodus.datetime")
    def test_resolve_default_date_weekday_before_market(self, mock_datetime):
        wib = datetime.timezone(datetime.timedelta(hours=7))
        # Thursday 10:00 WIB
        mock_datetime.datetime.now.return_value = datetime.datetime(2026, 9, 10, 10, 0, tzinfo=wib)
        mock_datetime.timedelta = datetime.timedelta
        mock_datetime.timezone = datetime.timezone
        self.assertEqual(_resolve_default_date(), datetime.date(2026, 9, 9))

    @patch("stockbit_ws.exodus.datetime")
    def test_resolve_default_date_saturday(self, mock_datetime):
        wib = datetime.timezone(datetime.timedelta(hours=7))
        # Saturday 10:00 WIB
        mock_datetime.datetime.now.return_value = datetime.datetime(2026, 9, 12, 10, 0, tzinfo=wib)
        mock_datetime.timedelta = datetime.timedelta
        mock_datetime.timezone = datetime.timezone
        # Should drop back to Friday
        self.assertEqual(_resolve_default_date(), datetime.date(2026, 9, 11))

    @patch("stockbit_ws.exodus.datetime")
    def test_resolve_default_date_monday_morning(self, mock_datetime):
        wib = datetime.timezone(datetime.timedelta(hours=7))
        # Monday 09:00 WIB
        mock_datetime.datetime.now.return_value = datetime.datetime(2026, 9, 14, 9, 0, tzinfo=wib)
        mock_datetime.timedelta = datetime.timedelta
        mock_datetime.timezone = datetime.timezone
        # Before market close on Monday -> drops to Sunday -> drops to Friday
        self.assertEqual(_resolve_default_date(), datetime.date(2026, 9, 11))

    def test_fetch_top_brokers_parses_response(self):
        client = MagicMock(spec=httpx.Client)
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": {
                "list": [{"code": "YU", "net_value": "100"}]
            }
        }
        client.get.return_value = mock_response

        res = fetch_top_brokers(client, datetime.date(2026, 9, 10))
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["code"], "YU")
        client.get.assert_called_once()

    def test_fetch_top_brokers_empty_response(self):
        client = MagicMock(spec=httpx.Client)
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": {}}
        client.get.return_value = mock_response

        res = fetch_top_brokers(client, datetime.date(2026, 9, 10))
        self.assertEqual(res, [])

    @patch("stockbit_ws.exodus.load_environment")
    def test_token_not_set_raises_value_error(self, mock_env):
        mock_env.return_value = {}
        with self.assertRaisesRegex(ValueError, "EXODUS_TOKEN belum diisi"):
            load_exodus_token()


@unittest.skipUnless(os.environ.get("STOCKBIT_TEST_POSTGRES") == "1", "Set STOCKBIT_TEST_POSTGRES=1")
class TestExodusIntegration(unittest.TestCase):
    def setUp(self):
        self.conn = connect_database()
        initialize_schema(self.conn)
        self.test_date = datetime.date(1999, 1, 1)
        self.addCleanup(self.cleanup)

    def cleanup(self):
        self.conn.execute("DELETE FROM stockbit_ws.broker_stock_activity WHERE date = %s", (self.test_date,))
        self.conn.execute("DELETE FROM stockbit_ws.broker_top_daily WHERE date = %s", (self.test_date,))
        self.conn.close()

    def test_store_and_read_top_brokers(self):
        brokers = [
            {
                "code": "YU",
                "name": "CGS CIMB",
                "total_value": "1000",
                "net_value": "500",
                "buy_value": "750",
                "sell_value": "250",
                "total_volume": "100",
                "total_frequency": "10",
                "group": "BROKER_GROUP_LOCAL"
            }
        ]
        count = store_top_brokers(self.conn, self.test_date, brokers)
        self.assertEqual(count, 1)

        row = self.conn.execute(
            "SELECT * FROM stockbit_ws.broker_top_daily WHERE date = %s AND broker_code = 'YU'",
            (self.test_date,)
        ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["broker_name"], "CGS CIMB")
        self.assertEqual(row["net_value"], 500)
        self.assertEqual(row["total_frequency"], 10)

    def test_store_broker_activity_upsert_idempotent(self):
        activities = [
            {
                "stock_code": "DSSA",
                "net_val": "100",
                "buy_val": "200",
                "sell_val": "100"
            }
        ]
        count1 = store_broker_activity(self.conn, self.test_date, "YU", activities)
        self.assertEqual(count1, 1)

        # Insert exact same data
        count2 = store_broker_activity(self.conn, self.test_date, "YU", activities)
        self.assertEqual(count2, 1)

        rows = self.conn.execute(
            "SELECT count(*) as c FROM stockbit_ws.broker_stock_activity WHERE date = %s",
            (self.test_date,)
        ).fetchone()
        self.assertEqual(rows["c"], 1)

    def test_store_broker_activity_updates_on_conflict(self):
        act1 = [{"stock_code": "DSSA", "net_val": "100", "buy_val": "200", "sell_val": "100"}]
        store_broker_activity(self.conn, self.test_date, "YU", act1)

        # Update with new net value
        act2 = [{"stock_code": "DSSA", "net_val": "300", "buy_val": "400", "sell_val": "100"}]
        store_broker_activity(self.conn, self.test_date, "YU", act2)

        row = self.conn.execute(
            "SELECT net_value FROM stockbit_ws.broker_stock_activity WHERE date = %s AND symbol = 'DSSA'",
            (self.test_date,)
        ).fetchone()
        self.assertEqual(row["net_value"], 300)
