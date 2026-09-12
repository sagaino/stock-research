"""Small, shared broker-code classification used by the research scanners."""

RETAIL_BROKERS = frozenset({"XL", "YP", "XC", "PD", "NI"})
SMART_MONEY_BROKERS = frozenset({
    "AK", "BK", "ZP", "KZ", "RX", "YU", "IN", "MG", "CP",
    "LG", "KI", "SQ", "AZ", "GR", "EP", "XA", "YB", "OD", "BB",
    "DR", "SS", "FS", "AG",
})


def broker_group(code: str | None) -> str | None:
    """Return ``retail``/``smart`` for known codes, else ``None``."""
    code = (code or "").split()[0].upper()
    if code in RETAIL_BROKERS:
        return "retail"
    if code in SMART_MONEY_BROKERS:
        return "smart"
    return None
