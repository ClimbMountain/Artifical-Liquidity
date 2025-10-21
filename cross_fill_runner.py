#!/usr/bin/env python3
import argparse
import concurrent.futures
import logging
import os
import subprocess
from typing import List

import requests

from logging_config import configure_logging
from settings import load_settings


def is_market_active(condition_id: str, timeout: float) -> bool:
    """Return True if a market is active and accepting orders."""
    try:
        url = f"https://clob.polymarket.com/markets/{condition_id}"
        resp = requests.get(url, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        return bool(
            data.get("active", False)
            and not data.get("closed", True)
            and data.get("accepting_orders", False)
        )
    except Exception as exc:
        logging.getLogger(__name__).warning("Could not verify market %s: %s", condition_id, exc)
        return False


def get_active_markets_from_file(filepath: str, timeout: float) -> List[str]:
    active: List[str] = []
    if not os.path.exists(filepath):
        return active
    with open(filepath, encoding="utf-8") as f:
        for line in f:
            cid = line.strip().split()[0]
            if cid and is_market_active(cid, timeout):
                active.append(cid)
    return active


def regenerate_cheap_markets() -> bool:
    logging.getLogger(__name__).info("Regenerating cheap_markets.txt")
    try:
        subprocess.run(["python", "market_scan.py"], check=True)
        return True
    except subprocess.CalledProcessError as exc:
        logging.getLogger(__name__).error("market_scan.py failed: %s", exc)
        return False


def cross_fill_for(condition_id: str, wallets_csv: str, db_path: str) -> str:
    """Run cross_fill.py for one market and return the condition_id on success."""
    subprocess.run([
        "python", "cross_fill.py",
        "--wallets", wallets_csv,
        "--condition", condition_id,
        "--volume", "5",
        "--iterations", "2",
        "--db-path", db_path,
    ], check=True)
    return condition_id


def main() -> None:
    parser = argparse.ArgumentParser(description="Run cross fills for active cheap markets")
    parser.add_argument("--max-retries", type=int, default=1, help="File regeneration attempts")
    parser.add_argument("--min-active", type=int, help="Minimum active required before running")
    args = parser.parse_args()

    settings = load_settings()
    configure_logging(settings.log_level)

    max_retries = args.max_retries
    min_active = args.min_active or settings.min_active_markets

    retries = 0
    active_markets: List[str] = []

    while retries <= max_retries:
        active_markets = get_active_markets_from_file(settings.cheap_markets_file, settings.http_timeout_sec)
        if len(active_markets) < min_active:
            logging.getLogger(__name__).info("Only %d active markets — regenerating.", len(active_markets))
            if not regenerate_cheap_markets():
                return
            retries += 1
        else:
            break

    if not active_markets:
        logging.getLogger(__name__).info("No active markets found after regeneration.")
        return

    logging.getLogger(__name__).info("Launching cross-fills for %d markets in parallel", len(active_markets))
    max_workers = min(settings.max_workers, len(active_markets))

    with concurrent.futures.ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(cross_fill_for, cid, settings.wallets_csv, settings.db_path): cid
            for cid in active_markets
        }
        for fut in concurrent.futures.as_completed(futures):
            cid = futures[fut]
            try:
                result = fut.result()
                logging.getLogger(__name__).info("cross_fill completed: %s", result)
            except Exception as exc:
                logging.getLogger(__name__).error("cross_fill failed for %s: %s", cid, exc)


if __name__ == "__main__":
    main()
