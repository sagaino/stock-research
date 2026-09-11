import unittest

from stockbit_ws.protobuf import encode_bytes_field, encode_message, encode_string_field, parse_protobuf
from stockbit_ws.subscription import detect_captured_symbol, prepare_frames_for_symbol


def core_fields(symbol="COCO"):
    return [{"fieldNumber": number, "wireType": 2, "value": symbol.encode()} for number in (2, 6, 7, 9)]


def make_root(fields=None):
    wire = encode_string_field(1, "account")
    if fields is not None:
        wire += encode_bytes_field(2, encode_message(fields))
    return wire + encode_string_field(3, "session-key") + encode_string_field(5, "jwt-value")


def make_frames():
    return [
        make_root(),
        make_root(core_fields()),
        make_root(core_fields() + [{"fieldNumber": 5, "wireType": 2, "value": b"COCO"}]),
    ]


def field_at(wire, number):
    return next(field for field in parse_protobuf(wire, strict=True, include_raw=True) if field["fieldNumber"] == number)


class SubscriptionTests(unittest.TestCase):
    def test_dynamic_symbol_rewrites_nine_fields_in_two_frames(self):
        frames = make_frames()
        result = prepare_frames_for_symbol(frames, "BMRI")
        self.assertEqual(result["capturedSymbol"], "COCO")
        self.assertEqual(result["replacementCount"], 9)
        self.assertEqual(result["modifiedFrames"], [2, 3])
        self.assertEqual(detect_captured_symbol(result["frames"]), "BMRI")
        self.assertEqual(result["frames"][0], frames[0])
        for index in (1, 2):
            for number in (1, 3, 5):
                self.assertEqual(field_at(result["frames"][index], number)["raw"], field_at(frames[index], number)["raw"])

    def test_same_symbol_reuses_original_capture_exactly(self):
        frames = make_frames()
        result = prepare_frames_for_symbol(frames, "COCO")
        self.assertIs(result["frames"], frames)
        self.assertEqual(result["replacementCount"], 0)
        self.assertEqual(result["modifiedFrames"], [])

    def test_empty_init_subscription_is_accepted(self):
        frames = [make_root(), make_root([]), make_root(core_fields())]
        result = prepare_frames_for_symbol(frames, "BBRI")
        self.assertEqual(result["replacementCount"], 4)
        self.assertEqual(result["modifiedFrames"], [3])
        self.assertEqual(result["frames"][1], frames[1])

    def test_length_changes_recalculate_outer_varints_across_boundary(self):
        fields = core_fields() + [{"fieldNumber": 11, "wireType": 2, "value": b"x" * 90}]
        original = [make_root(), make_root([]), make_root(fields)]
        old_body = field_at(original[2], 2)["value"]
        self.assertLess(len(old_body), 128)
        grown = prepare_frames_for_symbol(original, "A" * 20)
        grown_body = field_at(grown["frames"][2], 2)["value"]
        self.assertGreaterEqual(len(grown_body), 128)
        self.assertEqual(detect_captured_symbol(grown["frames"]), "A" * 20)
        shrunk = prepare_frames_for_symbol(grown["frames"], "AB")
        self.assertLess(len(field_at(shrunk["frames"][2], 2)["value"]), 128)
        self.assertEqual(detect_captured_symbol(shrunk["frames"]), "AB")

    def test_unknown_and_auth_bytes_survive_noncanonical_wire_encodings(self):
        # Noncanonical tag/length/value encodings are valid wire data. A complete
        # decode/re-encode would normalize them and fail this preservation test.
        auth = b"\x8a\x00\x87\x00account"
        unknown_root = b"\x98\x01\x81\x00"
        unknown_nested = b"\xda\x00\x84\x00COCO" + b"\x60\x81\x00"
        body = encode_message(core_fields()) + unknown_nested
        root = auth + b"\x92\x00" + bytes([len(body)]) + body + unknown_root
        frames = [make_root(), make_root([]), root]
        result = prepare_frames_for_symbol(frames, "BBCA")
        rewritten = result["frames"][2]
        self.assertTrue(rewritten.startswith(auth + b"\x92\x00"))
        self.assertTrue(rewritten.endswith(unknown_root))
        new_body = field_at(rewritten, 2)["value"]
        self.assertTrue(new_body.endswith(unknown_nested))
        self.assertEqual(result["replacementCount"], 4)
        self.assertEqual(detect_captured_symbol(result["frames"]), "BBCA")

    def test_missing_distinct_core_fields_cannot_pass_as_four_occurrences(self):
        repeated = [{"fieldNumber": 2, "wireType": 2, "value": b"COCO"}] * 4
        partial = core_fields()[:-1]
        for fields in (repeated, partial):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                prepare_frames_for_symbol([make_root(), make_root(core_fields()), make_root(fields)], "BMRI")

    def test_mixed_capture_symbols_or_optional_done_symbol_are_rejected(self):
        mismatch_done = core_fields() + [{"fieldNumber": 5, "wireType": 2, "value": b"BBRI"}]
        for fields in (core_fields("BBRI"), mismatch_done):
            frames = [make_root(), make_root(core_fields()), make_root(fields)]
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                prepare_frames_for_symbol(frames, "COCO")

    def test_malformed_nested_and_root_frames_fail_closed_even_for_same_symbol(self):
        for frame in (
            make_root(core_fields()) + b"\x0a\x80",
            make_root() + encode_bytes_field(2, b"\x0a\x80"),
            make_root(core_fields()) + encode_bytes_field(2, b""),
            make_root() + encode_message([{"fieldNumber": 2, "wireType": 0, "value": 3}]),
        ):
            for symbol in ("COCO", "BMRI"):
                with self.subTest(frame=frame, symbol=symbol), self.assertRaises(ValueError):
                    prepare_frames_for_symbol([make_root(), make_root(core_fields()), frame], symbol)

    def test_wrong_wire_type_or_duplicate_optional_symbol_is_rejected(self):
        bad_core = core_fields()
        bad_core[0] = {"fieldNumber": 2, "wireType": 0, "value": 3}
        done = {"fieldNumber": 5, "wireType": 2, "value": b"COCO"}
        for fields in (bad_core, core_fields() + [done, done]):
            with self.assertRaises(ValueError):
                prepare_frames_for_symbol([make_root(), make_root([]), make_root(fields)], "BMRI")

    def test_invalid_symbols_and_frame_counts_are_rejected(self):
        for symbol in ("", "A", "bmri", "BMRI\n", "A" * 21, "*", 123):
            with self.subTest(symbol=symbol), self.assertRaises(ValueError):
                prepare_frames_for_symbol(make_frames(), symbol)
        for frames in ([], make_frames()[:2], make_frames() + [make_root()], [b"", b"", "text"]):
            with self.assertRaises(TypeError):
                prepare_frames_for_symbol(frames, "BMRI")
        with self.assertRaises(ValueError):
            prepare_frames_for_symbol([make_root()] * 3, "BMRI")


if __name__ == "__main__":
    unittest.main()
