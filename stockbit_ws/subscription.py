"""Validate and selectively rewrite the captured subscription symbol.

Unlike a generic decode/re-encode, this keeps every untouched wire slice exact,
including unknown fields and noncanonical varints in credential fields. Each
nonempty subscription must have all four distinct core fields; a repeated field
or four partial frames cannot masquerade as the validated capture shape.
"""

from __future__ import annotations

import re

from .protobuf import decode_printable_utf8, encode_varint, parse_protobuf


SYMBOL_PATTERN = re.compile(r"\A[A-Z][A-Z0-9._-]{1,19}\Z")
CORE_SYMBOL_FIELDS = frozenset((2, 6, 7, 9))
REPLACEABLE_SYMBOL_FIELDS = CORE_SYMBOL_FIELDS | {5}


def prepare_frames_for_running_trade(frames):
    """Build the reported field-2/field-5 wildcard command; live validation pending.

    Preserve authentication wire slices. Earlier frames become auth-only;
    the final frame requests trades only, never wildcard order books.
    """
    if not isinstance(frames, (list, tuple)) or len(frames) != 3 or not all(isinstance(frame, bytes) for frame in frames):
        raise TypeError("Exactly three captured byte frames are required")
    validated = prepare_frames_for_symbol(frames, detect_captured_symbol(frames))
    rewritten = []
    for index, frame in enumerate(validated["frames"]):
        root, nested, _ = _inspect_frame(frame)
        for number in (1, 3, 5):
            fields = [field for field in root if field["fieldNumber"] == number]
            if len(fields) != 1 or fields[0]["wireType"] != 2 or not fields[0]["value"]:
                raise ValueError("Ambiguous authentication envelope")
        if nested and any(field["fieldNumber"] not in REPLACEABLE_SYMBOL_FIELDS for field in nested):
            raise ValueError("Unknown subscription command in wildcard template")
        if index == 2 and not nested:
            raise ValueError("Final frame must contain a subscription template")
        body = b"\x2a\x01*" if index == 2 else b""
        rewritten.append(b"".join(
            field["rawTag"] + encode_varint(len(body)) + body
            if field["fieldNumber"] == 2 else field["raw"]
            for field in root
        ))
    return {"frames": rewritten, "capturedSymbol": validated["capturedSymbol"],
            "replacementCount": 1, "modifiedFrames": [i + 1 for i in range(3) if rewritten[i] != frames[i]]}


def _inspect_frame(frame: bytes) -> tuple[list[dict], list[dict] | None, str | None]:
    root = parse_protobuf(frame, strict=True, include_raw=True)
    containers = [field for field in root if field["fieldNumber"] == 2]
    if not containers:
        return root, None, None
    if len(containers) != 1 or containers[0]["wireType"] != 2:
        raise ValueError("Ambiguous captured subscription container")
    if not containers[0]["value"]:
        return root, None, None
    nested = parse_protobuf(containers[0]["value"], strict=True, include_raw=True)
    symbol_fields = {}
    for field in nested:
        number = field["fieldNumber"]
        if number not in REPLACEABLE_SYMBOL_FIELDS:
            continue
        if number in symbol_fields or field["wireType"] != 2:
            raise ValueError("Ambiguous captured symbol fields")
        symbol = decode_printable_utf8(field["value"])
        if symbol is None or SYMBOL_PATTERN.fullmatch(symbol) is None:
            raise ValueError("Invalid symbol in captured subscription")
        symbol_fields[number] = symbol
    if not CORE_SYMBOL_FIELDS.issubset(symbol_fields):
        raise ValueError("Captured subscription is missing core symbol fields")
    if len(set(symbol_fields.values())) != 1:
        raise ValueError("Captured subscription contains conflicting symbols")
    return root, nested, symbol_fields[2]


def detect_captured_symbol(frames: list[bytes]) -> str:
    symbols = set()
    for frame in frames:
        _, _, symbol = _inspect_frame(frame)
        if symbol is not None:
            symbols.add(symbol)
    if not symbols:
        raise ValueError("Symbol asal tidak ditemukan pada captured subscription frames")
    if len(symbols) != 1:
        raise ValueError("Captured frames berisi lebih dari satu kandidat symbol")
    return symbols.pop()


def rewrite_frame_symbol(frame: bytes, captured_symbol: str, requested_symbol: str) -> dict:
    if not isinstance(requested_symbol, str) or not SYMBOL_PATTERN.fullmatch(requested_symbol):
        raise ValueError("Symbol tidak valid. Gunakan contoh seperti COCO, BMRI, atau BBRI.")
    root, nested, symbol = _inspect_frame(frame)
    if symbol is None:
        return {"frame": frame, "replacementCount": 0}
    if symbol != captured_symbol:
        raise ValueError("Captured subscription symbol does not match expected symbol")
    if symbol == requested_symbol:
        return {"frame": frame, "replacementCount": 0}
    replacement_count = 0
    new_symbol = requested_symbol.encode("ascii")
    nested_chunks = []
    for field in nested:
        if field["fieldNumber"] in REPLACEABLE_SYMBOL_FIELDS:
            nested_chunks.append(field["rawTag"] + encode_varint(len(new_symbol)) + new_symbol)
            replacement_count += 1
        else:
            nested_chunks.append(field["raw"])
    body = b"".join(nested_chunks)
    rewritten = b"".join(
        field["rawTag"] + encode_varint(len(body)) + body
        if field["fieldNumber"] == 2
        else field["raw"]
        for field in root
    )
    return {"frame": rewritten, "replacementCount": replacement_count}


def prepare_frames_for_symbol(frames: list[bytes], symbol: str) -> dict:
    if not isinstance(frames, (list, tuple)) or len(frames) != 3 or not all(
        isinstance(frame, bytes) for frame in frames
    ):
        raise TypeError("Exactly three captured byte frames are required")
    if not isinstance(symbol, str) or not SYMBOL_PATTERN.fullmatch(symbol):
        raise ValueError("Symbol tidak valid. Gunakan contoh seperti COCO, BMRI, atau BBRI.")
    captured_symbol = detect_captured_symbol(frames)
    if captured_symbol == symbol:
        return {
            "frames": frames,
            "capturedSymbol": captured_symbol,
            "replacementCount": 0,
            "modifiedFrames": [],
        }
    rewritten_frames = []
    replacement_count = 0
    modified_frames = []
    for index, frame in enumerate(frames, start=1):
        result = rewrite_frame_symbol(frame, captured_symbol, symbol)
        rewritten_frames.append(result["frame"])
        replacement_count += result["replacementCount"]
        if result["replacementCount"]:
            modified_frames.append(index)
    if replacement_count < len(CORE_SYMBOL_FIELDS):
        raise ValueError("Tidak cukup field symbol yang berhasil diganti dengan aman")
    if detect_captured_symbol(rewritten_frames) != symbol:
        raise ValueError("Validasi ulang dynamic subscription gagal")
    return {
        "frames": rewritten_frames,
        "capturedSymbol": captured_symbol,
        "replacementCount": replacement_count,
        "modifiedFrames": modified_frames,
    }
