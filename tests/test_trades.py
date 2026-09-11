from datetime import datetime, timezone
import math
import struct
import unittest

from stockbit_ws.trades import build_recent_trade_rows, create_recent_trade_state, find_done_trade_batch, parse_done_trade_record, parse_timestamp, update_recent_trades


# Build wire fixtures independently of the application encoder.
def varint(value):
    result = bytearray()
    while value >= 128:
        result.append((value & 127) | 128)
        value >>= 7
    result.append(value)
    return bytes(result)


def vint_field(number, value):
    return varint(number << 3) + varint(value)


def bytes_field(number, value):
    return varint((number << 3) | 2) + varint(len(value)) + value


def double_field(number, value):
    return varint((number << 3) | 1) + struct.pack("<d", value)


def timestamp(seconds=1788496179, nanos=925131564):
    return vint_field(1, seconds) + vint_field(2, nanos)


def record(*, seconds=1788496179, nanos=925131564, price=136, shares=50000, side=1, trade_id=1204718, symbol=b"COCO", value=True):
    change = double_field(1, 6) + double_field(2, 4.615384615)
    result = (
        bytes_field(1, timestamp(seconds, nanos))
        + bytes_field(2, symbol)
        + double_field(3, price)
        + double_field(4, shares)
        + vint_field(5, side)
        + bytes_field(7, timestamp(seconds, max(0, nanos - 1000000)))
        + bytes_field(8, change)
        + (vint_field(9, trade_id) if trade_id is not None else b"")
        + vint_field(10, 1)
    )
    return result + (double_field(11, price * shares) if value else b"")


def batch(records):
    return bytes_field(8, b"".join(bytes_field(1, value) for value in records))


class TradesTests(unittest.TestCase):
    def test_decodes_observed_shape_and_millisecond_timestamp(self):
        trades = find_done_trade_batch(batch([record()]))
        self.assertEqual(len(trades), 1)
        trade = trades[0]
        self.assertEqual({key: trade[key] for key in ("symbol", "price", "shares", "lot", "sideCode", "side", "aggressor", "tradeId", "flag", "transactionValue")}, {
            "symbol": "COCO", "price": 136, "shares": 50000, "lot": 500,
            "sideCode": 1, "side": "BUY", "aggressor": "HAKA", "tradeId": 1204718,
            "flag": 1, "transactionValue": 6800000,
        })
        self.assertEqual(trade["timestamp"], datetime(2026, 9, 4, 4, 29, 39, 925000, tzinfo=timezone.utc))
        self.assertEqual(trade["secondaryTimestamp"].microsecond, 924000)
        self.assertEqual(trade["changePoints"], 6)
        self.assertAlmostEqual(trade["changePercent"], 4.615384615)

    def test_unknown_or_malformed_records_are_ignored(self):
        for value in (None, b"", b"\xff", b"\x00", record(side=3), record(price=0), record(shares=-1), record(price=math.inf), record(shares=math.nan), record(symbol=b"bad\x1b[2J"), record(nanos=1000000000)):
            with self.subTest(length=len(value) if value is not None else None):
                self.assertIsNone(parse_done_trade_record(value))
        for value in (None, b"\xff", bytes_field(10, b"unrelated"), bytes_field(8, b"\xff")):
            self.assertIsNone(find_done_trade_batch(value))
        self.assertEqual(len(find_done_trade_batch(batch([b"\xff", record()]))), 1)

    def test_timestamp_bounds_missing_seconds_and_no_nanos(self):
        self.assertIsNone(parse_timestamp(vint_field(2, 100)))
        self.assertIsNone(parse_timestamp(timestamp(nanos=1000000000)))
        self.assertIsNone(parse_timestamp(timestamp(seconds=(1 << 64) - 1)))
        self.assertEqual(parse_timestamp(vint_field(1, 0)), datetime(1970, 1, 1, tzinfo=timezone.utc))

    def test_absent_value_falls_back_and_invalid_change_remains_optional(self):
        trade = parse_done_trade_record(record(value=False))
        self.assertEqual(trade["transactionValue"], 6800000)
        minimum = bytes_field(1, timestamp()) + bytes_field(2, b"BMRI") + double_field(3, 5000) + double_field(4, 100) + vint_field(5, 2) + bytes_field(8, b"\xff")
        trade = parse_done_trade_record(minimum)
        self.assertIsNone(trade["changePoints"])
        self.assertIsNone(trade["secondaryTimestamp"])
        self.assertIsNone(trade["tradeId"])
        self.assertEqual(trade["transactionValue"], 500000)

    def test_collects_multiple_outer_batches_in_order(self):
        trades = find_done_trade_batch(batch([record(trade_id=1)]) + batch([record(trade_id=2)]))
        self.assertEqual([trade["tradeId"] for trade in trades], [1, 2])

    def test_dedup_retention_and_exact_large_id_ordering(self):
        state = create_recent_trade_state()
        records = [record(trade_id=(1 << 53) + index) for index in range(110)]
        trades = find_done_trade_batch(batch(records))
        update_recent_trades(state, trades)
        update_recent_trades(state, trades)
        self.assertEqual(len(state["trades"]), 100)
        self.assertEqual(len(state["seenKeys"]), 100)
        self.assertEqual(state["trades"][0]["tradeId"], (1 << 53) + 109)
        self.assertEqual(state["trades"][-1]["tradeId"], (1 << 53) + 10)
        update_recent_trades(state, [None, {}, trades[-1]])
        self.assertEqual(len(state["trades"]), 100)
        update_recent_trades(state, [], max_trades=0)
        self.assertEqual(state, {"trades": [], "seenKeys": set()})

    def test_newest_time_takes_priority_and_missing_id_has_fallback_key(self):
        state = create_recent_trade_state()
        trades = find_done_trade_batch(batch([record(trade_id=100), record(trade_id=None, nanos=926131564)]))
        update_recent_trades(state, trades + trades)
        self.assertEqual(len(state["trades"]), 2)
        self.assertIsNone(state["trades"][0]["tradeId"])

    def test_formats_wib_side_rupiah_and_precision(self):
        trade = parse_done_trade_record(record(side=2, shares=11500, trade_id=99))
        self.assertEqual(build_recent_trade_rows([trade]), [{
            "Time": "11:29:39.925", "Price": 136, "Lot": "115", "Side": "HAKI/SELL",
            "Change": "+6 (+4.62%)", "Value": "Rp1.564.000", "Trade ID": "99",
        }])
        self.assertEqual(len(build_recent_trade_rows([trade] * 40)), 20)
        self.assertEqual(build_recent_trade_rows(None), [])
        trade.update(changePoints=-0.0, changePercent=-0.0)
        self.assertEqual(build_recent_trade_rows([trade])[0]["Change"], "0 (0.00%)")


if __name__ == "__main__":
    unittest.main()
