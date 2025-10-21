import argparse
import logging
from pathlib import Path

from config import build_scanner_client
from logging_config import configure_logging
from settings import load_settings


def scan_and_write(filepath: str, top_n: int) -> int:
    """Scan markets and write cheap markets file. Returns count written."""
    client = build_scanner_client()
    if client is None:
        return 0
    markets = client.get_top_markets_by_price(top_n=top_n)
    count = 0
    with open(filepath, "w", encoding="utf-8") as f:
        for m in markets:
            question = m.get("question") or m.get("title") or ""
            line = (
                f"{m['condition_id']}  |  {question:<70}  "
                f"price={float(m['price']):.4f}  spread={float(m.get('spread', 0)):.4f}"
            )
            logging.getLogger(__name__).info(line)
            f.write(line + "\n")
            count += 1
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description="Scan Polymarket markets by price/spread")
    parser.add_argument("--top", type=int, default=50, help="Number of markets to keep")
    parser.add_argument("--out", type=str, help="Output file path (defaults to env setting)")
    args = parser.parse_args()

    settings = load_settings()
    configure_logging(settings.log_level)

    outfile = args.out or settings.cheap_markets_file
    Path(outfile).parent.mkdir(parents=True, exist_ok=True)

    count = scan_and_write(outfile, top_n=args.top)
    logging.getLogger(__name__).info("Wrote %d markets to %s", count, outfile)


if __name__ == "__main__":
    main()
