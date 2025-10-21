import csv
from pathlib import Path
from py_clob_client.client import ClobClient
from typing import Dict, List

# ---- grab first key/funder from wallets.csv ----
def _first_wallet(csv_name: str = "wallets.csv"):
    path = Path(__file__).with_name(csv_name)
    with path.open(newline="") as f:
        row = next(csv.DictReader(f))  # first row only
    return row["private_key"].strip(), row["funder"].strip()

_PRIVATE_KEY, _FUNDER = _first_wallet()
# ------------------------------------------------

class PolymarketClient:
    def __init__(self, host: str, chain_id: int):
        self.client = ClobClient(
            host=host,
            chain_id=chain_id,
            key=_PRIVATE_KEY,
            signature_type=1,
            funder=_FUNDER,
        )

    def get_top_markets_by_price(self, top_n: int = 50) -> List[Dict]:
        allowed_spreads = {0.002, 0.003, 0.004}
        candidates: List[Dict] = []

        for market in self.get_all_markets():
            try:
                ob = self.get_orderbook(market["condition_id"])
            except Exception:
                continue

            spreads: List[float] = []
            asks: List[float] = []
            for outcome in ("Yes", "No"):
                side = ob.get(outcome, {})
                bids = side.get("bids", [])
                ask_list = side.get("asks", [])
                if not bids or not ask_list:
                    break

                best_bid = max(b["price"] for b in bids)
                best_ask = min(a["price"] for a in ask_list)

                spreads.append(best_ask - best_bid)
                asks.append(best_ask)
            else:
                spread = max(spreads)
                if any(abs(spread - s) < 1e-9 for s in allowed_spreads):
                    market["spread"] = spread
                    market["price"] = min(asks)
                    candidates.append(market)

        candidates.sort(key=lambda m: m["price"])
        return candidates[:top_n]

    def get_all_markets(self) -> List[Dict]:
        open_markets: List[Dict] = []
        next_cursor = ""

        while next_cursor != "LTE=":
            response = self.client.get_markets(next_cursor=next_cursor)
            markets_data = response.get("data", [])

            for market in markets_data:
                if not market.get("closed") and market.get("active"):
                    open_markets.append(market)

            next_cursor = response.get("next_cursor", "LTE=")

        return open_markets

    def get_orderbook(self, condition_id: str) -> Dict[str, Dict[str, List[Dict[str, float]]]]:
        market = self.get_market_details(condition_id)
        if not market:
            raise ValueError(f"Market with condition_id '{condition_id}' not found.")

        orderbook_data: Dict[str, Dict[str, List[Dict[str, float]]]] = {}
        for token in market.get("tokens", []):
            token_id = token.get("token_id")
            outcome = token.get("outcome")
            orderbook = self.client.get_order_book(token_id)

        orderbook_data[outcome] = {
                "bids": [{"price": float(b.price), "size": float(b.size)} for b in orderbook.bids],
                "asks": [{"price": float(a.price), "size": float(a.size)} for a in orderbook.asks],
            }

        return orderbook_data

    def get_market_details(self, condition_id: str) -> Dict:
        try:
            return self.client.get_market(condition_id)
        except Exception as e:
            print(f"Error fetching market: {e}")
            return None
