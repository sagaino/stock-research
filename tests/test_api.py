"""Tests for the Stockbit WebSocket REST API.

Run: STOCKBIT_TEST_POSTGRES=1 uv run python -m unittest tests/test_api.py -v
"""

from __future__ import annotations

import os
import unittest
import warnings

from fastapi.testclient import TestClient

from stockbit_ws.api import app
from test_postgres import PostgresTestMixin
from test_quality import START


class ApiTests(PostgresTestMixin, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Suppress httpx2 deprecation warning from starlette.testclient
        warnings.filterwarnings("ignore", category=DeprecationWarning)
        cls.client = TestClient(app)

    def test_root_endpoint_returns_service_info(self):
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["name"], "Stockbit WebSocket Market Data API")
        self.assertIn("endpoints", data)
        self.assertIn("sessions", data["endpoints"])

    def test_health_check_returns_ok_when_database_is_healthy(self):
        resp = self.client.get("/health")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["database"], "connected")

    def test_list_sessions_returns_paginated_list_and_totals(self):
        # Create a synthetic session with the mixin
        writer = self.writer(symbol="COCO", started_at=START)
        writer.append("connection", {"state": "CONNECTED"}, START, 0.1)
        writer.close(START, 1.0, "COMPLETED")

        resp = self.client.get("/api/sessions?source=SYNTHETIC&limit=10")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertGreaterEqual(data["total"], 1)
        self.assertIsInstance(data["sessions"], list)

        # Verify our synthetic session is in the response
        matching = [s for s in data["sessions"] if s["id"] == writer.session_id]
        self.assertEqual(len(matching), 1)
        session = matching[0]
        self.assertEqual(session["symbol"], "COCO")
        self.assertEqual(session["status"], "COMPLETED")
        self.assertEqual(session["source"], "SYNTHETIC")
        self.assertEqual(session["total_events"], 1)

    def test_list_sessions_filters_by_symbol_and_status(self):
        writer_bbri = self.writer(symbol="BBRI", started_at=START)
        writer_bbri.close(START, 0.5, "COMPLETED")

        # Filter by symbol
        resp = self.client.get("/api/sessions?symbol=BBRI")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(all(s["symbol"] == "BBRI" for s in data["sessions"]))
        self.assertTrue(any(s["id"] == writer_bbri.session_id for s in data["sessions"]))

        # Filter by status
        resp = self.client.get("/api/sessions?symbol=BBRI&status=OPEN")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertFalse(any(s["id"] == writer_bbri.session_id for s in data["sessions"]))

    def test_get_session_detail_returns_event_summary(self):
        writer = self.writer(symbol="BMRI", started_at=START)
        writer.append("connection", {"state": "CONNECTING"}, START, 0.0)
        writer.append("connection", {"state": "CONNECTED"}, START, 0.2)
        writer.close(START, 2.0, "COMPLETED")

        resp = self.client.get(f"/api/sessions/{writer.session_id}")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["id"], writer.session_id)
        self.assertEqual(data["symbol"], "BMRI")
        self.assertEqual(data["status"], "COMPLETED")
        self.assertEqual(data["events_summary"]["total_events"], 2)
        self.assertEqual(data["events_summary"]["by_kind"]["connection"], 2)

    def test_get_session_detail_returns_404_for_unknown_id(self):
        unknown_id = "00000000000000000000000000000000"
        resp = self.client.get(f"/api/sessions/{unknown_id}")
        self.assertEqual(resp.status_code, 404)
        self.assertIn("detail", resp.json())

    def test_get_session_events_supports_pagination_and_kind_filtering(self):
        writer = self.writer(symbol="TLKM", started_at=START)
        writer.append("connection", {"state": "CONNECTING"}, START, 0.0)
        writer.append("message", {"format": "binary", "size": 100}, START, 0.1)
        writer.append("connection", {"state": "CONNECTED"}, START, 0.2)
        writer.close(START, 1.0, "COMPLETED")

        # Read all events
        resp = self.client.get(f"/api/sessions/{writer.session_id}/events")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["count"], 3)
        self.assertEqual(data["next_seq"], 3)

        # Pagination using seq_gt
        resp = self.client.get(f"/api/sessions/{writer.session_id}/events?seq_gt=1&limit=2")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["count"], 2)
        self.assertEqual(data["events"][0]["seq"], 2)
        self.assertEqual(data["events"][1]["seq"], 3)

        # Filter by kind
        resp = self.client.get(f"/api/sessions/{writer.session_id}/events?kind=message")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["events"][0]["kind"], "message")
        self.assertEqual(data["events"][0]["payload"]["format"], "binary")

    def test_get_session_events_returns_404_for_unknown_id(self):
        unknown_id = "00000000000000000000000000000000"
        resp = self.client.get(f"/api/sessions/{unknown_id}/events")
        self.assertEqual(resp.status_code, 404)


if __name__ == "__main__":
    unittest.main()
