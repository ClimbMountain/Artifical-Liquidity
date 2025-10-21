#!/usr/bin/env python3

import argparse
import csv
import logging
import random
import time
from datetime import datetime
from decimal import Decimal, ROUND_DOWN
from typing import Dict, List, Optional, Tuple

import requests
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs, OrderType

from database_manager import DatabaseManager
from logging_config import configure_logging
from settings import load_settings

def record_sequence(db_manager: DatabaseManager, session_uuid: str, iteration_number: int, group: List[Dict],
                    mark_initial: bool = False, mark_final: bool = False) -> None:
    """Persist one row per wallet in the chain into `chain_sequences`."""
    for order, wallet in enumerate(group):
        db_manager.add_chain_step(
            session_uuid=session_uuid,
            iteration_number=iteration_number,
            sequence_order=order,
            wallet_id=wallet['db_id'],
            is_initial_buy=(mark_initial and order == 0),
            is_final_sell=(mark_final and order == len(group) - 1),
        )

def quantize_decimal(val: float, digits: int = 5) -> Decimal:
    return Decimal(str(val)).quantize(Decimal(f'1e-{digits}'), rounding=ROUND_DOWN)

def get_prices_and_tokens(condition_id: str, side: str, db_manager: Optional[DatabaseManager] = None) -> str:
    """Fetch token_id for given condition/outcome side ("yes" or "no")."""
    url = f"https://clob.polymarket.com/rewards/markets/{condition_id}"
    resp = requests.get(url)
    resp.raise_for_status()
    market_data = resp.json()['data'][0]

    # Store market condition and tokens in DB
    if db_manager:
        try:
            with db_manager.get_connection() as conn:
                conn.execute(
                    """INSERT OR REPLACE INTO market_conditions (condition_id, title, description, category, status)
                       VALUES (?, ?, ?, ?, ?)""",
                    (condition_id,
                     market_data.get('question', 'Unknown Market'),
                     market_data.get('description', ''),
                     market_data.get('category', ''),
                     'active')
                )
                for token in market_data['tokens']:
                    conn.execute(
                        """INSERT OR REPLACE INTO tokens (token_id, condition_id, outcome_side, outcome_label)
                           VALUES (?, ?, ?, ?, ?)""",
                        (token['token_id'], condition_id, token['outcome'].lower(), token.get('outcome', ''))
                    )
                conn.commit()
            db_manager.log_message(f"Market condition {condition_id} stored in database", "INFO")
        except Exception as exc:
            db_manager.log_message(f"Failed to store market condition: {str(exc)}", "WARNING")

    for token in market_data['tokens']:
        if token['outcome'].lower() == side.lower():
            return token['token_id']
    raise ValueError(f"Token for side '{side}' not found in market {condition_id}")


def fetch_nbbo(token_id: str) -> Tuple[Optional[float], Optional[float]]:
    """Return (best_bid, best_ask) for the given token_id."""
    url = f"https://clob.polymarket.com/book?token_id={token_id}"
    resp = requests.get(url)
    resp.raise_for_status()
    data = resp.json()
    bids = [float(b['price']) for b in data.get('bids', [])]
    asks = [float(a['price']) for a in data.get('asks', [])]
    return (max(bids) if bids else None, min(asks) if asks else None)


def get_yes_position_volume(proxy_wallet: str, condition_id: str) -> float:
    """
    Returns the number of 'Yes' shares owned for a given market (condition_id),
    using a Polymarket proxy wallet address.
    """
    url = "https://data-api.polymarket.com/positions"
    params = {"user": proxy_wallet, "market": condition_id, "limit": 100}
    resp = requests.get(url, params=params)
    resp.raise_for_status()
    positions = resp.json()
    return sum(pos.get("size", 0) for pos in positions if pos.get("outcome", "").lower() == "yes")


def init_client(private_key: str, funder: str, host: str, chain_id: int, signature_type: int) -> ClobClient:
    """Initialize and return a configured ClobClient."""
    client = ClobClient(
        host=host,
        chain_id=chain_id,
        key=private_key,
        signature_type=signature_type,
        funder=funder,
    )
    creds = client.create_or_derive_api_creds()
    client.set_api_creds(creds)
    return client


def load_wallets(csv_path: str, db_manager: DatabaseManager) -> List[Dict]:
    """Load (private_key, funder) pairs and store wallets in DB."""
    wallets: List[Dict] = []
    with open(csv_path, newline='') as f:
        reader = csv.DictReader(f)
        for idx, row in enumerate(reader):
            private_key = row['private_key']
            funder = row['funder']
            try:
                wallet_id = db_manager.add_wallet(
                    wallet_index=idx,
                    private_key=private_key,
                    funder_address=funder,
                    nickname=f"Wallet_{idx}"
                )
                db_manager.log_message(f"Added wallet {idx} to database", "INFO")
            except Exception:
                existing = db_manager.get_wallets(active_only=False)
                wallet_id = next((w['id'] for w in existing if w['wallet_index'] == idx), None)
                if not wallet_id:
                    raise
                db_manager.log_message(f"Using existing wallet {idx}", "INFO")
            wallets.append({
                'private_key': private_key,
                'wallet_address': funder,
                'db_id': wallet_id
            })
    return wallets

def chain_trade(group: List[Dict], condition_id: str, token_id: str, initial_size: float,
                buy_price: float, mid_price: float, *, skip_initial_buy: bool = False,
                db_manager: Optional[DatabaseManager] = None, session_uuid: Optional[str] = None) -> None:
    """Execute a buy-then-sell chain across wallets, verifying on-chain positions."""
    size = initial_size

    # 1) Initial buy if needed
    if not skip_initial_buy:
        buyer0 = group[0]
        start_vol0 = get_yes_position_volume(buyer0['wallet_address'], condition_id)
        acquired = 0.0

        if start_vol0 >= size:
            logging.getLogger(__name__).info("Skip initial buy: wallet %s already has %.4f ≥ %.4f",
                                             buyer0['db_id'], start_vol0, size)
            acquired = size
        else:
            # keep buying until we have the desired size on-chain
            while acquired < size:
                remaining = size - acquired
                logging.getLogger(__name__).info(
                    "Initial buy wallet %s: start %.4f → buying remaining %.4f @ %.4f",
                    buyer0['db_id'], start_vol0 + acquired, remaining, buy_price,
                )
                resp = buyer0['client'].post_order(
                    buyer0['client'].create_order(
                        OrderArgs(price=buy_price, size=remaining, side="BUY", token_id=token_id)
                    ),
                    orderType=OrderType.GTC
                )
                order_id = resp.get('orderID') if isinstance(resp, dict) else resp
                logging.getLogger(__name__).debug("Buy order response: %s", resp)

                time.sleep(random.uniform(10, 13))

                post_vol0 = get_yes_position_volume(buyer0['wallet_address'], condition_id)
                acquired = post_vol0 - start_vol0
                logging.getLogger(__name__).info("On-chain post-buy: %.4f (+%.4f)", post_vol0, acquired)

                if acquired < size:
                    try:
                        cancel_resp = buyer0['client'].cancel(order_id)
                        logging.getLogger(__name__).warning("Canceled partial buy order %s: %s", order_id, cancel_resp)
                    except Exception as exc:
                        logging.getLogger(__name__).error("Could not cancel order %s: %s", order_id, exc)

            # now we’ve done at least one order, so `order_id` is set
            if db_manager and session_uuid:
                db_manager.log_trade(
                    session_uuid,
                    buyer0['db_id'],
                    token_id,
                    "BUY",
                    buy_price,
                    size,
                    "initial_buy",
                    str(order_id)
                )

    # 2) Chain matches
    for i in range(1, len(group)):
        seller = group[i-1]
        buyer = group[i]
        remaining = size
        attempt = 1
        # record starting balances for delta
        start_seller = get_yes_position_volume(seller['wallet_address'], condition_id)
        start_buyer = get_yes_position_volume(buyer['wallet_address'], condition_id)
        logging.getLogger(__name__).info(
            "Match %s→%s: seller start %.4f, buyer start %.4f, size %.4f @ %.4f",
            seller['db_id'], buyer['db_id'], start_seller, start_buyer, remaining, mid_price,
        )

        while remaining > 0:
            logging.getLogger(__name__).debug("Attempt #%d for %.4f shares", attempt, remaining)
            sell_args = OrderArgs(price=mid_price, size=remaining, side="SELL", token_id=token_id)
            buy_args = OrderArgs(price=mid_price, size=remaining, side="BUY", token_id=token_id)
            sell_resp = seller['client'].post_order(
                seller['client'].create_order(sell_args), orderType=OrderType.GTC
            )
            buy_resp = buyer['client'].post_order(
                buyer['client'].create_order(buy_args), orderType=OrderType.GTC
            )
            logging.getLogger(__name__).debug("Sell resp: %s | Buy resp: %s", sell_resp, buy_resp)
            time.sleep(random.uniform(4,8))

            # compute deltas
            post_seller = get_yes_position_volume(seller['wallet_address'], condition_id)
            post_buyer = get_yes_position_volume(buyer['wallet_address'], condition_id)
            sold = start_seller - post_seller
            bought = post_buyer - start_buyer
            logging.getLogger(__name__).info(
                "On-chain: seller %.4f→%.4f sold %.4f; buyer %.4f→%.4f bought %.4f",
                start_seller, post_seller, sold, start_buyer, post_buyer, bought,
            )

            # full match
            if sold >= remaining and bought >= remaining:
                if db_manager and session_uuid:
                    db_manager.log_trade(session_uuid, buyer['db_id'], token_id,
                                         "BUY", mid_price, remaining, "chain_match",
                                         str(buy_resp.get('orderID', buy_resp)))
                    db_manager.log_trade(session_uuid, seller['db_id'], token_id,
                                         "SELL", mid_price, remaining, "chain_match",
                                         str(sell_resp.get('orderID', sell_resp)))
                remaining = 0

            # partial fill
            elif sold > 0 and sold < remaining:
                logging.getLogger(__name__).info("Partial fill: %.4f filled, %.4f remains", sold, remaining - sold)
                oid_buy  = buy_resp.get('orderID')  if isinstance(buy_resp, dict)  else buy_resp
                oid_sell = sell_resp.get('orderID') if isinstance(sell_resp, dict) else sell_resp
                buyer['client'].cancel(oid_buy)
                seller['client'].cancel(oid_sell)
                remaining -= sold
                attempt += 1
                continue

            # fallback misfill/divert with original divert logic
            # fallback misfill/divert with re-check logic
            else:
                logging.getLogger(__name__).warning("Misfill/divert: sold %.4f, bought %.4f", sold, bought)
                # give on-chain a moment and re-check
                time.sleep(2)
                re_seller = get_yes_position_volume(seller['wallet_address'], condition_id)
                re_buyer = get_yes_position_volume(buyer['wallet_address'], condition_id)
                re_sold = start_seller - re_seller
                re_bought = re_buyer - start_buyer
                logging.getLogger(__name__).info(
                    "Recheck: seller %.4f→%.4f sold %.4f; buyer %.4f→%.4f bought %.4f",
                    start_seller, re_seller, re_sold, start_buyer, re_buyer, re_bought,
                )
                # if it actually filled, move on
                if re_sold >= remaining and re_bought >= remaining:
                    logging.getLogger(__name__).info("Recheck indicates full fill; continuing chain")
                    remaining = 0
                    break

                # Divert: buyer acquired elsewhere but seller still holds
                if bought >= remaining and sold < remaining:
                    logging.getLogger(__name__).info("Divert: buyer bought elsewhere, seller still has %.4f", post_seller)
                    best_bid, _ = fetch_nbbo(token_id)
                    if post_seller > 0 and best_bid:
                        div_args = OrderArgs(price=best_bid, size=post_seller, side="SELL", token_id=token_id)
                        div_resp = seller['client'].post_order(
                            seller['client'].create_order(div_args), orderType=OrderType.GTC
                        )
                        logging.getLogger(__name__).info("Divert: market sell of diverted shares @ %.4f: %s", best_bid, div_resp)
                    # continue with remaining chain
                    break

                # Misfill: seller sold but buyer got nothing
                if sold >= remaining and bought == 0:
                    logging.getLogger(__name__).warning("Misfill: seller sold but buyer got none; restarting initial buy")
                    buyer['client'].cancel(buy_resp.get('orderID') if isinstance(buy_resp, dict) else buy_resp)
                    return chain_trade(
                        group, condition_id, token_id, initial_size, buy_price, mid_price,
                        skip_initial_buy=False, db_manager=db_manager, session_uuid=session_uuid
                    )

                # For any other weirdness: cancel and retry match
                oid_buy  = buy_resp.get('orderID')  if isinstance(buy_resp, dict)  else buy_resp
                oid_sell = sell_resp.get('orderID') if isinstance(sell_resp, dict) else sell_resp
                buyer['client'].cancel(oid_buy)
                seller['client'].cancel(oid_sell)
                logging.getLogger(__name__).warning("Unexpected state; retrying remainder %.4f", remaining)
                continue
        # end while
        size = initial_size  # reset for next wallet pair

    # chain complete; return to main for final sell
    return

# --- Main execution ---

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Chain-trade across N wallets from a CSV."
    )
    parser.add_argument(
        "--wallets", required=True,
        help="Path to CSV file of wallets (private_key,funder)"
    )
    parser.add_argument(
        "--condition", required=True,
        help="Polymarket condition_id"
    )
    parser.add_argument(
        "--iterations", type=int, default=1,
        help="Number of 5-wallet chains after the first 6-wallet run"
    )
    parser.add_argument(
        "--volume", type=int, default=5,
        help="Trade size (number of shares/contracts) per order"
    )
    parser.add_argument(
        "--db-path", default=None,
        help="Path to SQLite database file"
    )
    args = parser.parse_args()

    settings = load_settings()
    configure_logging(settings.log_level)

    db_path = args.db_path or settings.db_path
    db_manager = DatabaseManager(db_path)
    db_manager.log_message("Trading session started", "INFO")
        
    try:
        wallet_entries = load_wallets(args.wallets, db_manager)
        clients = []
        for idx, w in enumerate(wallet_entries):
            pk = w['private_key']
            funder = w['wallet_address']
            db_id = w['db_id']

            client = init_client(pk, funder, settings.clob_host, settings.chain_id, settings.clob_signature_type)
            clients.append({
                'id': idx,
                'client': client,
                'db_id': db_id,
                'wallet_address': funder
            })

        if len(clients) < 5:
            raise RuntimeError("Need at least 5 wallets for the first iteration")

        # Fetch token & NBBO
        token_id = get_prices_and_tokens(args.condition, "yes", db_manager)
        best_bid, best_ask = fetch_nbbo(token_id)
        if best_bid is None or best_ask is None:
            raise RuntimeError("Could not fetch NBBO bid/ask")

        # Save market data to database
        db_manager.save_market_data(token_id, best_bid, best_ask)
        db_manager.log_message(f"Market data: bid={best_bid:.4f}, ask={best_ask:.4f}", "INFO")

        # Use CLI volume
        size      = args.volume
        buy_price = best_ask
        mid_price = (best_ask + best_bid) / 2

        # Create trading session in database
        session_uuid = db_manager.create_session(
            condition_id=args.condition,
            token_id=token_id,
            volume=args.volume,
            iterations=args.iterations,
            initial_wallet_count=len(clients)
        )
        db_manager.log_message(f"Created trading session {session_uuid}", "INFO", session_uuid)

        # First iteration: fixed 6 wallets
        initial_group = clients[:5]

        record_sequence(
            db_manager,
            session_uuid,
            iteration_number=0,
            group=initial_group,
            mark_initial=True,
            mark_final=(args.iterations == 0)
        )
        last_group = initial_group
        last_iter_no = 0

        chain_trade(
            initial_group, args.condition, token_id, size,
            buy_price, mid_price,
            skip_initial_buy=False,
            db_manager=db_manager,
            session_uuid=session_uuid
        )
        last_wallet_obj = initial_group[-1]

        # Subsequent chains
        for iter_no in range(1, args.iterations + 1):
            pool       = [c for c in clients if c['id'] != last_wallet_obj['id']]
            next_group = random.sample(pool, k=4)
            group      = [last_wallet_obj] + next_group

            # record this chain
            record_sequence(
                db_manager,
                session_uuid,
                iteration_number=iter_no,
                group=group,
                mark_initial=False,
                mark_final=(iter_no == args.iterations)  # last loop → flag final seller
            )

            chain_trade(
                group, args.condition, token_id, size,
                buy_price, mid_price,
                skip_initial_buy=True,
                db_manager=db_manager,
                session_uuid=session_uuid
            )

            last_wallet_obj = group[-1]

        # Final market-like SELL at best_bid
        final_id = last_wallet_obj['id']
        final_client = last_wallet_obj['client']
        logging.getLogger(__name__).info("Final sell wallet %s @ %.2f", final_id, best_bid)
        sell_args = OrderArgs(
            price=best_bid,
            size=size,
            side="SELL",
            token_id=token_id
        )
        order = final_client.create_order(sell_args)
        response = final_client.post_order(order, orderType=OrderType.GTC)
        logging.getLogger(__name__).debug("Final sell response: %s", response)
        
        # Log final sell to database
        try:
            trade_id = db_manager.log_trade(
                session_uuid=session_uuid,
                wallet_id=last_wallet_obj['db_id'],
                token_id=token_id,
                side="SELL",
                price=best_bid,
                size=size,
                trade_type="final_sell",
                order_id=str(response.get('orderID', '')) if isinstance(response, dict) else str(response)
            )
            db_manager.log_message(f"Final sell logged: Wallet {final_id} @ {best_bid:.2f}", "INFO", session_uuid)
        except Exception as exc:
            db_manager.log_message(f"Failed to log final sell: {str(exc)}", "ERROR", session_uuid)

        # Mark session as completed
        db_manager.update_session_status(session_uuid, "completed", datetime.now())
        db_manager.log_message("Trading session completed successfully", "INFO", session_uuid)

    except Exception as exc:
        db_manager.log_message(f"Trading session failed: {str(exc)}", "ERROR")
        if 'session_uuid' in locals():
            db_manager.update_session_status(session_uuid, "failed", datetime.now())
        raise


if __name__ == "__main__":
    main()
