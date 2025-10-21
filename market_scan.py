from config import PolymarketClient

def main():
    host = "https://clob.polymarket.com/"
    chain_id = 137  # Polygon mainnet

    # class handles private_key & funder internally
    poly_client = PolymarketClient(host, chain_id)

    markets = poly_client.get_top_markets_by_price(top_n=50)
    with open("cheap_markets.txt", "w") as f:
        for m in markets:
            line = (
                f"{m['condition_id']}  |  {m['question']:<70}  "
                f"price={float(m['price']):.4f}  spread={float(m.get('spread', 0)):.4f}"
            )
            print(line)
            f.write(line + "\n")

if name == "main":
    main()
