"""Bounded, schema-free protobuf wire helpers.

The parser deliberately leaves length-delimited values as bytes. No protobuf
schema or credential interpretation is needed to inspect received market data.
"""

from __future__ import annotations

import base64
import binascii
import re
from collections.abc import Mapping


MAX_MESSAGE_BYTES = 16 * 1024 * 1024
MAX_FIELD_NUMBER = (1 << 29) - 1
MAX_UINT64 = (1 << 64) - 1
_BASE64_PATTERN = re.compile(r"[A-Za-z0-9+/]+={0,2}")
_JWT_PATTERN = re.compile(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+")


class ProtobufDecodeError(ValueError):
    """A malformed message or a configured parsing bound was encountered."""


def _as_bytes(value: bytes | bytearray | memoryview) -> bytes:
    if isinstance(value, bytes):
        return value
    if isinstance(value, (bytearray, memoryview)):
        return bytes(value)
    raise TypeError("Protobuf input must be bytes, bytearray, or memoryview")


def _is_integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def read_varint(buffer: bytes, offset: int = 0) -> dict:
    """Read an unsigned 64-bit varint without rounding large integers."""
    buffer = _as_bytes(buffer)
    if not _is_integer(offset) or offset < 0 or offset > len(buffer):
        raise ProtobufDecodeError("Invalid varint offset")
    value = 0
    for byte_index in range(10):
        if offset >= len(buffer):
            raise ProtobufDecodeError("Truncated varint")
        byte = buffer[offset]
        offset += 1
        if byte_index == 9 and byte > 1:
            raise ProtobufDecodeError("Varint exceeds 64 bits")
        value |= (byte & 0x7F) << (byte_index * 7)
        if byte & 0x80 == 0:
            return {"value": value, "offset": offset}
    raise ProtobufDecodeError("Varint exceeds 10 bytes")


def encode_varint(value: int) -> bytes:
    if not _is_integer(value):
        raise TypeError("Varint value must be an integer")
    if not 0 <= value <= MAX_UINT64:
        raise ValueError("Varint value must fit in an unsigned 64-bit integer")
    result = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        result.append(byte | (0x80 if value else 0))
        if not value:
            return bytes(result)


def encode_tag(field_number: int, wire_type: int) -> bytes:
    if not _is_integer(field_number) or not 1 <= field_number <= MAX_FIELD_NUMBER:
        raise ValueError("Invalid protobuf field number")
    if not _is_integer(wire_type) or wire_type not in (0, 1, 2, 5):
        raise ValueError("Unsupported protobuf wire type")
    return encode_varint((field_number << 3) | wire_type)


def encode_bytes_field(field_number: int, value: bytes) -> bytes:
    value = _as_bytes(value)
    prefix = encode_tag(field_number, 2) + encode_varint(len(value))
    if len(prefix) + len(value) > MAX_MESSAGE_BYTES:
        raise ValueError("Protobuf message size limit exceeded")
    return prefix + value


def encode_string_field(field_number: int, value: str) -> bytes:
    if not isinstance(value, str):
        raise TypeError("String field value must be a string")
    return encode_bytes_field(field_number, value.encode("utf-8"))


def encode_message(fields: list[dict]) -> bytes:
    """Encode supported field types; raw parser metadata is intentionally ignored."""
    if not isinstance(fields, (list, tuple)):
        raise TypeError("Protobuf message fields must be a list or tuple")
    chunks = []
    total = 0
    for field in fields:
        if not isinstance(field, Mapping):
            raise TypeError("Invalid protobuf field")
        number, wire_type = field.get("fieldNumber"), field.get("wireType")
        tag = encode_tag(number, wire_type)
        if wire_type == 0:
            chunk = tag + encode_varint(field["value"])
        else:
            value = _as_bytes(field["value"])
            if wire_type == 1 and len(value) != 8:
                raise ValueError("Wire type 1 field must contain exactly 8 bytes")
            if wire_type == 5 and len(value) != 4:
                raise ValueError("Wire type 5 field must contain exactly 4 bytes")
            chunk = tag + (encode_varint(len(value)) if wire_type == 2 else b"") + value
        total += len(chunk)
        if total > MAX_MESSAGE_BYTES:
            raise ValueError("Protobuf message size limit exceeded")
        chunks.append(chunk)
    return b"".join(chunks)


def parse_protobuf(
    buffer: bytes,
    strict: bool = False,
    max_fields: int = 10_000,
    *,
    include_raw: bool = False,
) -> list[dict]:
    """Parse wire fields, returning complete prefix fields for malformed tails.

    Strict mode raises instead of returning a prefix. With ``include_raw``, each
    field includes its exact ``raw`` encoding and ``rawTag`` bytes, permitting
    unknown fields to survive selective edits even with noncanonical varints.
    """
    buffer = _as_bytes(buffer)
    if not _is_integer(max_fields) or max_fields < 0:
        raise ValueError("max_fields must be a nonnegative integer")
    fields = []
    offset = 0
    try:
        if len(buffer) > MAX_MESSAGE_BYTES:
            raise ProtobufDecodeError("Protobuf message size limit exceeded")
        while offset < len(buffer):
            if len(fields) >= max_fields:
                raise ProtobufDecodeError("Protobuf field limit exceeded")
            start = offset
            tag_result = read_varint(buffer, offset)
            offset = tag_end = tag_result["offset"]
            number, wire_type = tag_result["value"] >> 3, tag_result["value"] & 7
            if not 1 <= number <= MAX_FIELD_NUMBER:
                raise ProtobufDecodeError("Invalid protobuf field number")
            if wire_type == 0:
                result = read_varint(buffer, offset)
                value, offset = result["value"], result["offset"]
            elif wire_type in (1, 2, 5):
                if wire_type == 2:
                    result = read_varint(buffer, offset)
                    length, offset = result["value"], result["offset"]
                else:
                    length = 8 if wire_type == 1 else 4
                if length > len(buffer) - offset:
                    raise ProtobufDecodeError("Truncated protobuf field")
                value = buffer[offset : offset + length]
                offset += length
            else:
                raise ProtobufDecodeError("Unsupported protobuf wire type")
            field = {"fieldNumber": number, "wireType": wire_type, "value": value}
            if include_raw:
                field.update(raw=buffer[start:offset], rawTag=buffer[start:tag_end])
            fields.append(field)
    except ProtobufDecodeError:
        if strict:
            raise
    return fields


def decode_printable_utf8(buffer: bytes) -> str | None:
    buffer = _as_bytes(buffer)
    try:
        text = buffer.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        return None
    for character in text:
        codepoint = ord(character)
        if codepoint in (9, 10, 13):
            continue
        if codepoint < 32 or codepoint == 127:
            return None
    return text


def normalize_incoming_buffer(data: bytes) -> bytes:
    """Accept binary messages or canonical base64 transported as text bytes."""
    buffer = _as_bytes(data)
    if len(buffer) > MAX_MESSAGE_BYTES:
        raise ProtobufDecodeError("Protobuf message size limit exceeded")
    text = decode_printable_utf8(buffer)
    text = text.strip() if text is not None else None
    if not text or len(text) < 20 or len(text) % 4 or not _BASE64_PATTERN.fullmatch(text):
        return buffer
    try:
        decoded = base64.b64decode(text, validate=True)
    except (ValueError, binascii.Error):
        return buffer
    if decoded and text.rstrip("=") == base64.b64encode(decoded).decode("ascii").rstrip("="):
        return decoded
    return buffer


def try_parse_nested_protobuf(buffer: bytes) -> list[dict] | None:
    buffer = _as_bytes(buffer)
    if not buffer:
        return None
    try:
        return parse_protobuf(buffer, strict=True) or None
    except ProtobufDecodeError:
        return None


def find_order_book_payload(
    buffer: bytes, max_depth: int = 12, max_visited_fields: int = 25_000
) -> str | None:
    """Find a #O| string under unknown wrapper fields with bounded recursion."""
    if not _is_integer(max_depth) or not 0 <= max_depth <= 64:
        raise ValueError("max_depth must be an integer between 0 and 64")
    if not _is_integer(max_visited_fields) or max_visited_fields < 0:
        raise ValueError("max_visited_fields must be a nonnegative integer")
    root = normalize_incoming_buffer(buffer)
    visited_fields = 0

    def visit(message: bytes, depth: int) -> str | None:
        nonlocal visited_fields
        if depth > max_depth or visited_fields >= max_visited_fields:
            return None
        text = decode_printable_utf8(message)
        if text is not None and text.startswith("#O|"):
            return text
        fields = try_parse_nested_protobuf(message)
        if fields is None:
            return None
        for field in fields:
            visited_fields += 1
            if visited_fields > max_visited_fields:
                return None
            if field["wireType"] != 2:
                continue
            text = decode_printable_utf8(field["value"])
            if text is not None and text.startswith("#O|"):
                return text
            nested = visit(field["value"], depth + 1)
            if nested is not None:
                return nested
        return None

    return visit(root, 0)


def is_likely_jwt(value: object) -> bool:
    if isinstance(value, (bytes, bytearray, memoryview)):
        text = decode_printable_utf8(value)
    else:
        text = str(value or "")
    return bool(text and _JWT_PATTERN.fullmatch(text))
