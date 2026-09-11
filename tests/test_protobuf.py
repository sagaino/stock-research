import base64
import unittest
from unittest.mock import patch

from stockbit_ws.protobuf import (
    MAX_FIELD_NUMBER,
    MAX_UINT64,
    ProtobufDecodeError,
    decode_printable_utf8,
    encode_bytes_field,
    encode_message,
    encode_string_field,
    encode_tag,
    encode_varint,
    find_order_book_payload,
    is_likely_jwt,
    normalize_incoming_buffer,
    parse_protobuf,
    read_varint,
    try_parse_nested_protobuf,
)


class VarintTests(unittest.TestCase):
    def test_known_vectors_and_full_uint64_precision(self):
        for value, wire in (
            (0, b"\x00"),
            (127, b"\x7f"),
            (128, b"\x80\x01"),
            (300, b"\xac\x02"),
            (MAX_UINT64, b"\xff" * 9 + b"\x01"),
        ):
            with self.subTest(value=value):
                self.assertEqual(encode_varint(value), wire)
                self.assertEqual(read_varint(b"!" + wire, 1), {"value": value, "offset": 1 + len(wire)})

    def test_truncation_and_uint64_overflow_are_rejected(self):
        for wire in (b"", b"\x80", b"\xff" * 9 + b"\x02", b"\x80" * 10 + b"\x00"):
            with self.subTest(wire=wire), self.assertRaises(ProtobufDecodeError):
                read_varint(wire)
        for value in (-1, MAX_UINT64 + 1):
            with self.assertRaises(ValueError):
                encode_varint(value)
        for value in (True, 1.5, "3"):
            with self.assertRaises(TypeError):
                encode_varint(value)

    def test_offset_validation_and_noncanonical_valid_encoding(self):
        self.assertEqual(read_varint(b"\x81\x00"), {"value": 1, "offset": 2})
        for offset in (-1, 2, True, 0.5):
            with self.assertRaises(ProtobufDecodeError):
                read_varint(b"\x00", offset)


class WireParserTests(unittest.TestCase):
    def test_supported_types_and_unknown_field_numbers_round_trip(self):
        fields = [
            {"fieldNumber": 1, "wireType": 0, "value": MAX_UINT64},
            {"fieldNumber": 2, "wireType": 2, "value": b"COCO"},
            {"fieldNumber": 30, "wireType": 1, "value": b"12345678"},
            {"fieldNumber": MAX_FIELD_NUMBER, "wireType": 5, "value": b"1234"},
        ]
        self.assertEqual(parse_protobuf(encode_message(fields), strict=True), fields)
        self.assertEqual(encode_string_field(2, "COCO"), b"\x12\x04COCO")

    def test_defensive_mode_keeps_only_complete_prefix_fields(self):
        prefix = encode_string_field(2, "COCO")
        for tail in (b"\x0a\xff", b"\x0a\x03ab", b"\x09xx", b"\x0dxx", b"\x08\x80"):
            with self.subTest(tail=tail):
                self.assertEqual(parse_protobuf(prefix + tail), parse_protobuf(prefix))
                with self.assertRaises(ProtobufDecodeError):
                    parse_protobuf(prefix + tail, strict=True)

    def test_invalid_tags_and_unsupported_group_wire_types(self):
        for tag in (0, 1, 3, 7, 11, 12, (MAX_FIELD_NUMBER + 1) << 3):
            wire = encode_varint(tag)
            with self.subTest(tag=tag):
                self.assertEqual(parse_protobuf(wire), [])
                with self.assertRaises(ProtobufDecodeError):
                    parse_protobuf(wire, strict=True)

    def test_raw_metadata_preserves_noncanonical_wire_representation(self):
        wire = b"\x8a\x00\x83\x00abc\x90\x00\x81\x00"
        fields = parse_protobuf(wire, strict=True, include_raw=True)
        self.assertEqual(b"".join(field["raw"] for field in fields), wire)
        self.assertEqual(fields[0]["rawTag"], b"\x8a\x00")
        self.assertEqual(fields[1]["value"], 1)
        self.assertEqual(set(parse_protobuf(wire)[0]), {"fieldNumber", "wireType", "value"})

    def test_field_and_size_limits(self):
        wire = encode_string_field(1, "abc") * 3
        self.assertEqual(len(parse_protobuf(wire, max_fields=2)), 2)
        with self.assertRaises(ProtobufDecodeError):
            parse_protobuf(wire, strict=True, max_fields=2)
        with patch("stockbit_ws.protobuf.MAX_MESSAGE_BYTES", 4):
            self.assertEqual(parse_protobuf(wire), [])
            with self.assertRaises(ProtobufDecodeError):
                parse_protobuf(wire, strict=True)
            with self.assertRaises(ProtobufDecodeError):
                normalize_incoming_buffer(wire)
            self.assertEqual(encode_bytes_field(1, b"ab"), b"\x0a\x02ab")
            with self.assertRaises(ValueError):
                encode_bytes_field(1, b"abc")

    def test_encoder_rejects_bad_fixed_widths_and_tags(self):
        for wire_type in (1, 5):
            with self.assertRaises(ValueError):
                encode_message([{"fieldNumber": 1, "wireType": wire_type, "value": b"abc"}])
        for number in (0, MAX_FIELD_NUMBER + 1, True):
            with self.assertRaises(ValueError):
                encode_tag(number, 2)
        with self.assertRaises(ValueError):
            encode_tag(1, 3)


class NestedPayloadTests(unittest.TestCase):
    PAYLOAD = "#O|COCO|OFFER|140;1476;58320500|"

    def test_payload_found_under_unknown_wrappers_and_base64(self):
        wire = encode_bytes_field(17, encode_string_field(2, self.PAYLOAD))
        self.assertEqual(find_order_book_payload(wire), self.PAYLOAD)
        self.assertEqual(find_order_book_payload(base64.b64encode(wire)), self.PAYLOAD)
        self.assertEqual(find_order_book_payload(self.PAYLOAD.encode()), self.PAYLOAD)

    def test_depth_and_visited_field_bounds_stop_search(self):
        wire = self.PAYLOAD.encode()
        for _ in range(16):
            wire = encode_bytes_field(17, wire)
        self.assertIsNone(find_order_book_payload(wire))
        self.assertEqual(find_order_book_payload(wire, max_depth=16), self.PAYLOAD)
        wire = encode_string_field(1, "ignored") + encode_string_field(2, self.PAYLOAD)
        self.assertIsNone(find_order_book_payload(wire, max_visited_fields=1))

    def test_malformed_wrapper_is_not_searched_as_a_valid_nested_message(self):
        wire = encode_string_field(2, self.PAYLOAD) + b"\x0a\x80"
        self.assertIsNone(try_parse_nested_protobuf(wire))
        self.assertIsNone(find_order_book_payload(wire))

    def test_base64_requires_canonical_encoding_and_minimum_length(self):
        wire = b"x" * 14
        encoded = base64.b64encode(wire)
        self.assertEqual(normalize_incoming_buffer(b"\n" + encoded + b"\n"), wire)
        # Change unused padding bits; decoders may accept this, our heuristic must not.
        noncanonical = encoded[:-2] + b"h="
        self.assertEqual(base64.b64decode(noncanonical), wire)
        self.assertEqual(normalize_incoming_buffer(noncanonical), noncanonical)
        self.assertEqual(normalize_incoming_buffer(b"YWJj"), b"YWJj")

    def test_utf8_printability_and_token_heuristic(self):
        self.assertEqual(decode_printable_utf8("harga\tnaik\n✓".encode()), "harga\tnaik\n✓")
        self.assertIsNone(decode_printable_utf8(b"\xff"))
        self.assertIsNone(decode_printable_utf8(b"abc\x00"))
        self.assertIsNone(decode_printable_utf8(b"abc\x7f"))
        self.assertTrue(is_likely_jwt(b"eyJtest.payload.signature"))
        self.assertFalse(is_likely_jwt("eyJtest.payload.signature\n"))
        self.assertFalse(is_likely_jwt(None))


if __name__ == "__main__":
    unittest.main()
