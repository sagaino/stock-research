"""Compatibility entry point: uv run python index.py BMRI."""

if __name__ == "__main__":
    try:
        from stockbit_ws.cli import main
    except ModuleNotFoundError as error:
        if error.name not in {"dotenv", "websockets", "certifi"}:
            raise
        print("Dependency Python belum terpasang. Jalankan: uv sync")
        raise SystemExit(1) from None
    raise SystemExit(main())
