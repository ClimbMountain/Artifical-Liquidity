#!/usr/bin/env python3
import os
import subprocess
import requests
import time
import concurrent.futures

CHEAP_MARKETS_FILE = "cheap_markets.txt"
WALLETS_CSV = "wallets.csv"
DB_PATH = "polyfarm.db"
MAX_RETRIES = 1      # max attempts to regenerate cheap_markets.txt
SLEEP_BETWEEN = 3    # (unused now, but you can still throttle if needed)

def is_market_active(condition_id):
    """Check if a Polymarket market is active and accepting orders."""
    try:
        url = f"https://clob.polymarket.com/markets/{condition_id}"
        resp = requests.get(url, timeout=5)
        resp.raise_for_status()
        data = resp.json()
        return (
            data.get("active", False)
            and not data.get("closed", True)
            and data.get("accepting_orders", False)
        )
    except Exception as e:
        print(f"[WARN] Could not verify market {condition_id}: {e}")
        return False

def get_active_markets_from_file(filepath):
    active = []
    if not os.path.exists(filepath):
        return active
    with open(filepath) as f:
        for line in f:
            cid = line.strip().split()[0]
            if cid and is_market_active(cid):
                active.append(cid)
    return active

def regenerate_cheap_markets():
    print("[INFO] Regenerating cheap_markets.txt …")
    try:
        subprocess.run(["python3", "market_scan.py"], check=True)
        return True
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] market_scan.py failed: {e}")
        return False

def cross_fill_for(condition_id):
    """Worker function: runs the cross_fill.py script for one market."""
    subprocess.run([
        "python3", "cross_fill.py",
        "--wallets", WALLETS_CSV,
        "--condition", condition_id,
        "--volume", "5",
        "--iterations", "2",
        "--db-path", DB_PATH
    ], check=True)
    return condition_id

def main():
    retries = 0
    active_markets = []

    while retries <= MAX_RETRIES:
        active_markets = get_active_markets_from_file(CHEAP_MARKETS_FILE)
        if len(active_markets) < 20:
            print(f"[INFO] Only {len(active_markets)} active markets — regenerating.")
            if not regenerate_cheap_markets():
                return
            retries += 1
        else:
            break

    if not active_markets:
        print("[EXIT] No active markets found after regeneration.")
        return

    print(f"[INFO] Launching cross-fills for {len(active_markets)} markets in parallel…")
    max_workers = min(10, len(active_markets))  # adjust as needed

    with concurrent.futures.ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(cross_fill_for, cid): cid for cid in active_markets}
        for fut in concurrent.futures.as_completed(futures):
            cid = futures[fut]
            try:
                result = fut.result()  # will raise if the subprocess failed
                print(f"[DONE] cross_fill on {result}")
            except Exception as e:
                print(f"[ERROR] cross_fill failed for {cid}: {e}")

if __name__ == "__main__":
    main()
