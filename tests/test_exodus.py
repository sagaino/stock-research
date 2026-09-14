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
    fetch_broker_activity,
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

    def test_fetch_top_brokers_sorts_by_total_value_locally(self):
        client = MagicMock(spec=httpx.Client)
        response = MagicMock()
        response.json.return_value = {
            "data": {
                "list": [
                    {"code": "SMALL", "total_value": "10"},
                    {"code": "BIG", "total_value": "100"},
                ]
            }
        }
        client.get.return_value = response

        rows = fetch_top_brokers(client, datetime.date(2026, 9, 10))
        self.assertEqual([row["code"] for row in rows], ["BIG", "SMALL"])

    def test_fetch_top_brokers_rejects_mismatched_response_window(self):
        client = MagicMock(spec=httpx.Client)
        response = MagicMock()
        response.json.return_value = {
            "data": {"from": "2026-09-11", "to": "2026-09-11", "list": []}
        }
        client.get.return_value = response

        with self.assertRaises(ValueError):
            fetch_top_brokers(client, datetime.date(2026, 9, 10))

    def test_historical_activity_uses_explicit_date_window(self):
        client = MagicMock(spec=httpx.Client)
        response = MagicMock()
        response.json.return_value = {"data": {"from": "2026-09-10", "to": "2026-09-10"}}
        client.get.return_value = response

        self.assertEqual(
            fetch_broker_activity(client, "YU", target_date=datetime.date(2026, 9, 10)),
            [],
        )
        params = client.get.call_args.kwargs["params"]
        self.assertEqual(params["from"], "2026-09-10")
        self.assertEqual(params["to"], "2026-09-10")
        self.assertNotIn("period", params)

    def test_historical_activity_rejects_mismatched_response_window(self):
        client = MagicMock(spec=httpx.Client)
        response = MagicMock()
        response.json.return_value = {"data": {"from": "2026-09-11", "to": "2026-09-11"}}
        client.get.return_value = response

        with self.assertRaises(ValueError):
            fetch_broker_activity(client, "YU", target_date=datetime.date(2026, 9, 10))

    @patch("stockbit_ws.exodus.time.sleep")
    def test_activity_retries_read_timeout_without_changing_page(self, _sleep):
        client = MagicMock(spec=httpx.Client)
        response = MagicMock()
        response.json.return_value = {
            "data": {
                "broker_activity_transaction": {
                    "brokers_buy": [{"stock_code": "ANTM", "value": 100}],
                    "brokers_sell": [],
                }
            }
        }
        empty = MagicMock()
        empty.json.return_value = {"data": {}}
        client.get.side_effect = [
            httpx.ReadTimeout(
                "timed out",
                request=httpx.Request("GET", "https://exodus.stockbit.com/order-trade/broker/activity"),
            ),
            response,
            empty,
        ]

        rows = fetch_broker_activity(client, "CC", target_date=datetime.date(2026, 9, 10))

        self.assertEqual([row["stock_code"] for row in rows], ["ANTM"])
        self.assertEqual(client.get.call_count, 3)
        self.assertEqual(
            client.get.call_args_list[0].kwargs["params"],
            client.get.call_args_list[1].kwargs["params"],
        )

    @patch("stockbit_ws.exodus.time.sleep")
    def test_relative_activity_keeps_period_compatibility(self, _sleep):
        client = MagicMock(spec=httpx.Client)
        response = MagicMock()
        response.json.return_value = {
            "data": {
                "broker_activity_transaction": {
                    "brokers_buy": [{"stock_code": "ANTM", "value": 100}],
                    "brokers_sell": [],
                }
            }
        }
        empty = MagicMock()
        empty.json.return_value = {"data": {}}
        client.get.side_effect = [response, empty]

        rows = fetch_broker_activity(client, "YU")
        self.assertEqual(rows[0]["_side"], "buy")
        params = client.get.call_args_list[0].kwargs["params"]
        self.assertEqual(params["period"], "RT_PERIOD_LAST_1_DAY")
        self.assertNotIn("from", params)

    def test_activity_lists_keep_buy_sell_side(self):
        client = MagicMock(spec=httpx.Client)
        response = MagicMock()
        response.json.return_value = {
            "data": {
                "broker_activity_transaction": {
                    "brokers_buy": [{"stock_code": "DSSA", "value": 200}],
                    "brokers_sell": [{"stock_code": "DSSA", "value": 50}],
                }
            }
        }
        client.get.side_effect = [response, MagicMock(json=lambda: {"data": {}})]

        rows = fetch_broker_activity(client, "YU", target_date=datetime.date(2026, 9, 10))
        self.assertEqual([row["_side"] for row in rows], ["buy", "sell"])

    @patch("stockbit_ws.exodus.time.sleep")
    def test_activity_pagination_is_not_truncated_at_ten_pages(self, _sleep):
        client = MagicMock(spec=httpx.Client)
        pages = []
        for page in range(11):
            response = MagicMock()
            response.json.return_value = {
                "data": {
                    "broker_activity_transaction": {
                        "brokers_buy": [{"stock_code": f"S{page}", "value": 1}],
                        "brokers_sell": [],
                    }
                }
            }
            pages.append(response)
        empty = MagicMock()
        empty.json.return_value = {"data": {}}
        pages.append(empty)
        client.get.side_effect = pages

        rows = fetch_broker_activity(client, "YU", target_date=datetime.date(2026, 9, 10))
        self.assertEqual(len(rows), 11)
        self.assertEqual(client.get.call_count, 12)

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

        store_top_brokers(self.conn, self.test_date, [dict(brokers[0], code="KZ")])
        rows = self.conn.execute(
            "SELECT broker_code FROM stockbit_ws.broker_top_daily WHERE date = %s",
            (self.test_date,),
        ).fetchall()
        self.assertEqual([item["broker_code"] for item in rows], ["KZ"])

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

    def test_store_broker_activity_replaces_stale_symbols(self):
        store_broker_activity(self.conn, self.test_date, "YU", [
            {"stock_code": "DSSA", "net_val": "100"},
            {"stock_code": "BBCA", "net_val": "200"},
        ])

        store_broker_activity(self.conn, self.test_date, "YU", [
            {"stock_code": "DSSA", "net_val": "300"},
        ])

        rows = self.conn.execute(
            """SELECT symbol, net_value
               FROM stockbit_ws.broker_stock_activity
               WHERE date = %s AND broker_code = 'YU'""",
            (self.test_date,),
        ).fetchall()
        self.assertEqual([(row["symbol"], float(row["net_value"])) for row in rows], [("DSSA", 300.0)])

        self.assertEqual(store_broker_activity(self.conn, self.test_date, "YU", []), 0)
        remaining = self.conn.execute(
            "SELECT count(*) AS count FROM stockbit_ws.broker_stock_activity WHERE date = %s",
            (self.test_date,),
        ).fetchone()
        self.assertEqual(remaining["count"], 0)

    def test_store_broker_activity_aggregates_buy_and_sell_rows(self):
        activities = [
            {"stock_code": "DSSA", "value": "200", "lot": "2", "avg_price": "100", "_side": "buy"},
            {"stock_code": "DSSA", "value": "-50", "lot": "-1", "avg_price": "50", "_side": "sell"},
        ]
        self.assertEqual(store_broker_activity(self.conn, self.test_date, "YU", activities), 1)
        row = self.conn.execute(
            "SELECT net_value, buy_value, sell_value, buy_lot, sell_lot FROM stockbit_ws.broker_stock_activity WHERE date = %s AND symbol = 'DSSA'",
            (self.test_date,)
        ).fetchone()
        self.assertEqual(float(row["net_value"]), 150)
        self.assertEqual(float(row["buy_value"]), 200)
        self.assertEqual(float(row["sell_value"]), 50)
        self.assertEqual(float(row["buy_lot"]), 2)
        self.assertEqual(float(row["sell_lot"]), 1)
