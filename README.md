# Artificial-Liquidity

This is an automated system for identifying profitable Polymarket markets, executing chain trades across multiple wallets, and logging activity to a local SQLite database. It supports reward farming, liquidity bootstrapping, and volume simulation across markets with tight spreads.

---

## Project Structure

```text
PolyFarm/
├── market_scan.py          # Scans Polymarket for cheap, active markets
├── cross_fill.py           # Executes chain-trade strategy on a single market
├── cross_fill_runner.py    # Orchestrates multiple cross-fill runs from cheap_markets.txt
├── cheap_markets.txt       # Auto-generated list of tradable condition_ids
├── wallets.csv             # List of private_key,funder wallet pairs
├── polyfarm.db             # SQLite database to log trades and sessions
```

## Setup

You need to fill wallets.csv with your wallets and their associated proxy addresses. You also need to edit config and market_scan with any wallets private key and proxy address.
