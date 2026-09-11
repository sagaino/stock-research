import base64
from contextlib import redirect_stdout
from io import StringIO
import unittest
from unittest.mock import patch

from stockbit_ws import inspection
from stockbit_ws.protobuf import encode_bytes_field, encode_message, encode_string_field


class InspectionTests(unittest.TestCase):
    def test_auth_roots_are_redacted_including_numeric_and_nested_values(self):
        frame = encode_message([
            {"fieldNumber": 1, "wireType": 0, "value": 998877665544},
            {"fieldNumber": 3, "wireType": 2, "value": b"private-session-SECRET"},
            {"fieldNumber": 5, "wireType": 2, "value": encode_string_field(2, "NESTED-AUTH-SECRET")},
        ])
        result = inspection.inspect_frame(frame)
        self.assertEqual(result.count("[redacted]"), 3)
        for secret in ("998877665544", "private-session-SECRET", "NESTED-AUTH-SECRET"):
            self.assertNotIn(secret, result)
        self.assertEqual(len(result.splitlines()), 3)

    def test_only_allowlisted_subscription_symbol_paths_are_visible(self):
        body = b"".join(encode_string_field(number, "COCO") for number in (2, 5, 6, 7, 9))
        body += encode_string_field(11, "SECRETUNKNOWN")
        body += encode_string_field(12, "eyJ.secret.jwt")
        frame = encode_bytes_field(2, body) + encode_string_field(30, "ROOTSECRET")
        frame += encode_bytes_field(20, encode_string_field(2, "FAKESYMBOL"))
        result = inspection.inspect_frame(frame)
        self.assertEqual(result.count("symbol=COCO"), 5)
        for secret in ("SECRETUNKNOWN", "eyJ.secret.jwt", "ROOTSECRET", "FAKESYMBOL"):
            self.assertNotIn(secret, result)
        self.assertIn("field 11", result)
        self.assertIn("[redacted]", result)

    def test_depth_and_global_field_limits_stop_recursive_inspection(self):
        nested = encode_string_field(30, "DEEPESTSECRET")
        for _ in range(12):
            nested = encode_bytes_field(20, nested)
        result = inspection.inspect_frame(nested, max_depth=2)
        self.assertIn("[inspection limit]", result)
        self.assertLessEqual(len(result.splitlines()), 4)
        self.assertNotIn("DEEPESTSECRET", result)
        frame = encode_bytes_field(20, encode_string_field(21, "ONE") + encode_string_field(22, "TWO"))
        frame += encode_string_field(30, "THREE")
        result = inspection.inspect_frame(frame, max_fields=3)
        self.assertIn("[inspection limit]", result)
        self.assertNotIn("THREE", result)

    def test_malformed_content_remains_hidden(self):
        for value in (None, b"\xff", b"\x0a\x80"):
            result = inspection.inspect_frame(value)
            self.assertIn("[opaque/malformed; content hidden]", result)
        result = inspection.inspect_frame(encode_bytes_field(30, b"\xffsecret\x1b[2J"))
        self.assertNotIn("secret", result)
        self.assertNotIn("\x1b", result)

    def test_cli_loads_named_synthetic_frame_without_revealing_values(self):
        secret = b"unprintable-credential"
        frame = encode_bytes_field(3, secret)
        output = StringIO()
        with (
            patch.object(inspection, "load_environment", return_value={"STOCKBIT_FRAME_1": base64.b64encode(frame).decode("ascii")}) as load,
            redirect_stdout(output),
        ):
            result = inspection.main(["STOCKBIT_FRAME_1", "--env-file", "synthetic-only.env"])
        self.assertEqual(result, 0)
        load.assert_called_once_with("synthetic-only.env")
        self.assertIn("[redacted]", output.getvalue())
        self.assertNotIn(secret.decode(), output.getvalue())


if __name__ == "__main__":
    unittest.main()
