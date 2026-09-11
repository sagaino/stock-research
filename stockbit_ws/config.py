"""Read captured frames without exposing their authentication contents."""

import base64
import binascii
from collections.abc import Mapping
import os
from pathlib import Path
import re

from dotenv import dotenv_values

FRAME_NAMES = tuple(f"STOCKBIT_FRAME_{number}" for number in (1, 2, 3))
MAX_FRAME_BYTES = 10 * 1024 * 1024
_BASE64 = re.compile(r"[A-Za-z0-9+/]+={0,2}\Z")


class ConfigurationError(ValueError):
    """A safe, deliberately value-free configuration error."""


def load_environment(env_file=".env", environment: Mapping | None = None):
    # Do not expand ${...}: replay exactly what the user captured.
    path = Path(env_file)
    try:
        values = dotenv_values(path, interpolate=False, encoding="utf-8") if path.is_file() else {}
    except (OSError, UnicodeError):
        raise ConfigurationError("File konfigurasi tidak dapat dibaca.") from None
    values.update(os.environ if environment is None else environment)
    return values


def decode_captured_frame(name, value):
    # Names are allowlisted; neither user-provided names nor values enter errors.
    label = name if name in FRAME_NAMES else "Captured frame"
    if not isinstance(value, str) or not value.strip():
        raise ConfigurationError(f"{label} belum diisi")
    compact = value.strip()
    if len(compact) > (MAX_FRAME_BYTES + 2) // 3 * 4:
        raise ConfigurationError(f"{label} terlalu besar")
    if not _BASE64.fullmatch(compact) or len(compact) % 4 == 1:
        raise ConfigurationError(f"{label} bukan Base64 yang valid")
    try:
        decoded = base64.b64decode(compact + "=" * (-len(compact) % 4), validate=True)
    except (ValueError, binascii.Error):
        raise ConfigurationError(f"{label} bukan Base64 yang valid") from None
    canonical = base64.b64encode(decoded).decode("ascii").rstrip("=")
    if len(decoded) > MAX_FRAME_BYTES:
        raise ConfigurationError(f"{label} terlalu besar")
    if not decoded or canonical != compact.rstrip("="):
        raise ConfigurationError(f"{label} bukan Base64 yang valid")
    return decoded


def load_captured_frames(environment):
    return [decode_captured_frame(name, environment.get(name)) for name in FRAME_NAMES]


def debug_enabled(value):
    return isinstance(value, str) and value.strip().lower() in {"true", "1", "yes", "on"}
