import base64
from pathlib import Path
import unittest
from unittest.mock import patch

from stockbit_ws.config import ConfigurationError, FRAME_NAMES, debug_enabled, decode_captured_frame, load_captured_frames, load_environment


class ConfigurationTests(unittest.TestCase):
    def test_three_frames_decoded_in_order_and_padding_optional(self):
        values = [b"frame-1", b"frame-2", b"frame-3"]
        environment = {name: base64.b64encode(value).decode().rstrip("=") for name, value in zip(FRAME_NAMES, values)}
        self.assertEqual(load_captured_frames(environment), values)
        self.assertEqual(decode_captured_frame(FRAME_NAMES[0], "  QQ==\n"), b"A")

    def test_missing_and_invalid_errors_never_echo_credentials(self):
        for value in (None, "", " ", "secret-token-!", "YR==", "A", "AA\nAA", "data:abc", "eyJfake.jwt.secret"):
            with self.subTest(value=value):
                with self.assertRaises(ConfigurationError) as caught:
                    decode_captured_frame(FRAME_NAMES[0], value)
                self.assertIn(FRAME_NAMES[0], str(caught.exception))
                if value and len(value.strip()) > 1:
                    self.assertNotIn(value, str(caught.exception))
        with self.assertRaises(ConfigurationError) as caught:
            decode_captured_frame("sensitive-variable-name", "!")
        self.assertNotIn("sensitive-variable-name", str(caught.exception))

    def test_frame_size_limit_includes_decoded_bytes(self):
        with patch("stockbit_ws.config.MAX_FRAME_BYTES", 1):
            self.assertEqual(decode_captured_frame(FRAME_NAMES[0], "QQ=="), b"A")
            with self.assertRaises(ConfigurationError):
                decode_captured_frame(FRAME_NAMES[0], "QUI=")
            with self.assertRaises(ConfigurationError):
                decode_captured_frame(FRAME_NAMES[0], "QUJDRA==")

    def test_environment_overrides_file_without_mutating_input_or_interpolation(self):
        supplied = {"DEBUG_WS": "false", "STOCKBIT_FRAME_1": "runtime"}
        with patch.object(Path, "is_file", return_value=True), patch("stockbit_ws.config.dotenv_values", return_value={"STOCKBIT_FRAME_1": "file", "KEEP": "${CAPTURE}"}) as read:
            actual = load_environment("fixture.env", supplied)
        self.assertEqual(actual["STOCKBIT_FRAME_1"], "runtime")
        self.assertEqual(actual["KEEP"], "${CAPTURE}")
        self.assertNotIn("KEEP", supplied)
        read.assert_called_once_with(Path("fixture.env"), interpolate=False, encoding="utf-8")

    def test_missing_file_still_allows_environment_and_read_errors_are_safe(self):
        with patch.object(Path, "is_file", return_value=False):
            self.assertEqual(load_environment("missing", {"a": "b"}), {"a": "b"})
        with patch.object(Path, "is_file", side_effect=OSError("do-not-log-this")):
            with self.assertRaises(ConfigurationError) as caught:
                load_environment("fixture", {})
        self.assertNotIn("do-not-log-this", str(caught.exception))

    def test_debug_is_opt_in(self):
        for value in ("true", "TRUE", "1", " yes ", "on"):
            self.assertTrue(debug_enabled(value))
        for value in (None, "false", "0", "", "anything", False):
            self.assertFalse(debug_enabled(value))
