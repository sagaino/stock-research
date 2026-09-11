"""Inspect capture shapes, showing only explicitly recognized symbol values."""

import argparse

from .config import FRAME_NAMES, ConfigurationError, decode_captured_frame, load_environment
from .protobuf import decode_printable_utf8, parse_protobuf
from .subscription import SYMBOL_PATTERN


def inspect_frame(frame, *, max_depth=6, max_fields=300):
    lines = []
    remaining = max_fields

    def visit(data, path=(), depth=0):
        nonlocal remaining
        if depth > max_depth or remaining <= 0:
            lines.append("  " * depth + "[inspection limit]")
            return
        try:
            fields = parse_protobuf(data, strict=True, max_fields=max_fields)
        except (ValueError, TypeError):
            lines.append("  " * depth + "[opaque/malformed; content hidden]")
            return
        for field in fields:
            if remaining <= 0:
                lines.append("  " * depth + "[inspection limit]")
                break
            remaining -= 1
            number, wire, value = field["fieldNumber"], field["wireType"], field["value"]
            location = path + (number,)
            size = f", {len(value)} B" if isinstance(value, bytes) else ""
            prefix = "  " * depth + f"field {number} (wire {wire}{size})"
            # User/account, JWT, session are always hidden, regardless of wire.
            if not path and number in (1, 3, 5):
                lines.append(prefix + " [redacted]")
                continue
            text = decode_printable_utf8(value) if wire == 2 else None
            if len(location) == 2 and location[0] == 2 and number in (2, 5, 6, 7, 9) and text and SYMBOL_PATTERN.fullmatch(text):
                lines.append(prefix + f" symbol={text}")
            elif wire == 2 and value and text is None:
                lines.append(prefix)
                visit(value, location, depth + 1)
            else:
                lines.append(prefix + " [redacted]")

    visit(frame)
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Inspect struktur capture tanpa menampilkan credential.")
    parser.add_argument("name", choices=FRAME_NAMES, help="Nama variabel, bukan frame Base64 mentah")
    parser.add_argument("--env-file", default=".env")
    args = parser.parse_args(argv)
    try:
        values = load_environment(args.env_file)
        frame = decode_captured_frame(args.name, values.get(args.name))
    except ConfigurationError as error:
        print(f"Error: {error}")
        return 1
    print(inspect_frame(frame))
    return 0
