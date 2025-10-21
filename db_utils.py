import argparse
import json
import logging
from datetime import datetime
from database_manager import DatabaseManager
from logging_config import configure_logging
from settings import load_settings


def list_sessions(db_manager: DatabaseManager, limit: int = 10) -> None:
    sessions = db_manager.get_recent_sessions(limit)
    print(f"\nRecent Trading Sessions (last {limit}):")
    print("-" * 80)
    if not sessions:
        print("No sessions found.")
        return
    for session in sessions:
        print(f"Session: {session['session_uuid'][:8]}...")
        print(f"   Market: {session.get('market_title', 'Unknown')}")
        print(f"   Status: {session['status']}")
        print(f"   Volume: {session['volume']}")
        print(f"   Trades: {session.get('trade_count', 0)}")
        print(f"   Started: {session['start_time']}")
        print()


def session_details(db_manager: DatabaseManager, session_uuid: str) -> None:
    summary = db_manager.get_session_summary(session_uuid)
    
    if not summary:
        print(f"Session {session_uuid} not found.")
        return
    
    print(f"\nSession Details: {session_uuid}")
    print("-" * 60)
    print(f"Condition ID: {summary['condition_id']}")
    print(f"Token ID: {summary['token_id']}")
    print(f"Status: {summary['status']}")
    print(f"Volume: {summary['volume']}")
    print(f"Iterations: {summary['iterations']}")
    print(f"Start Time: {summary['start_time']}")
    if summary.get('end_time'):
        print(f"End Time: {summary['end_time']}")
    print(f"Total Trades: {summary.get('total_trades', 0)}")
    print(f"Filled Volume: {summary.get('filled_volume', 0)}")
    print(f"Total Fees: ${summary.get('total_fees', 0):.4f}")
    print(f"Avg Price: ${summary.get('avg_price', 0):.4f}")
    
    # Get trades for this session
    with db_manager.get_connection() as conn:
        cursor = conn.execute(
            """SELECT t.*, w.nickname, w.wallet_index 
               FROM trades t
               JOIN wallets w ON t.wallet_id = w.id
               JOIN trading_sessions ts ON t.session_id = ts.id
               WHERE ts.session_uuid = ?
               ORDER BY t.timestamp""",
            (session_uuid,)
        )
        trades = [dict(row) for row in cursor.fetchall()]
    
    if trades:
        print(f"\nTrades ({len(trades)}):")
        print("-" * 60)
        for trade in trades:
            print(f"{trade['side']} {trade['size']} @ ${trade['price']:.4f}")
            print(f"   Wallet: {trade['nickname']} (#{trade['wallet_index']})")
            print(f"   Type: {trade['trade_type']}")
            print(f"   Status: {trade['status']}")
            print(f"   Time: {trade['timestamp']}")
            if trade.get('order_id'):
                print(f"   Order ID: {trade['order_id']}")
            print()


def list_wallets(db_manager: DatabaseManager) -> None:
    wallets = db_manager.get_wallets()
    print(f"\nWallets ({len(wallets)}):")
    print("-" * 80)
    
    for wallet in wallets:
        performance = db_manager.get_wallet_performance(wallet['id'])
        active = 'active' if wallet['is_active'] else 'inactive'
        print(f"{wallet['nickname']} (#{wallet['wallet_index']}) [{active}]")
        print(f"   Funder: {wallet['funder_address'][:20]}...")
        print(f"   Total Trades: {performance.get('total_trades', 0)}")
        print(f"   Total Volume: {performance.get('total_volume', 0)}")
        print(f"   Total Fees: ${performance.get('total_fees', 0):.4f}")
        if performance.get('last_trade_time'):
            print(f"   Last Trade: {performance['last_trade_time']}")
        print()


def show_logs(db_manager: DatabaseManager, session_uuid: str = None, limit: int = 50) -> None:
    with db_manager.get_connection() as conn:
        if session_uuid:
            cursor = conn.execute(
                """SELECT al.*, ts.session_uuid 
                   FROM app_logs al
                   LEFT JOIN trading_sessions ts ON al.session_id = ts.id
                   WHERE ts.session_uuid = ?
                   ORDER BY al.timestamp DESC
                   LIMIT ?""",
                (session_uuid, limit)
            )
        else:
            cursor = conn.execute(
                """SELECT al.*, ts.session_uuid 
                   FROM app_logs al
                   LEFT JOIN trading_sessions ts ON al.session_id = ts.id
                   ORDER BY al.timestamp DESC
                   LIMIT ?""",
                (limit,)
            )
        
        logs = [dict(row) for row in cursor.fetchall()]
    
    print(f"\nApplication Logs (last {limit}):")
    print("-" * 80)
    
    for log in logs:
        session_info = f" [{log['session_uuid'][:8]}...]" if log.get('session_uuid') else ""
        print(f"{log['timestamp']}{session_info}")
        print(f"   {log['message']}")
        if log.get('details'):
            print(f"   Details: {log['details']}")
        print()


def backup_database(db_manager: DatabaseManager, backup_path: str = None) -> None:
    if not backup_path:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = f"polyfarm_backup_{timestamp}.db"
    
    try:
        db_manager.backup_database(backup_path)
        print(f"Database backed up to: {backup_path}")
    except Exception as e:
        print(f"Backup failed: {str(e)}")


def vacuum_database(db_manager: DatabaseManager) -> None:
    try:
        db_manager.vacuum_database()
        print("Database optimized successfully.")
    except Exception as e:
        print(f"Vacuum failed: {str(e)}")


def main() -> None:
    parser = argparse.ArgumentParser(description="PolyFarm Database Utilities")
    parser.add_argument("--db-path", default=None, help="Path to database file")
    
    subparsers = parser.add_subparsers(dest='command', help='Available commands')
    
    # List sessions
    sessions_parser = subparsers.add_parser('sessions', help='List trading sessions')
    sessions_parser.add_argument('--limit', type=int, default=10, help='Number of sessions to show')
    
    # Session details
    details_parser = subparsers.add_parser('details', help='Show session details')
    details_parser.add_argument('session_uuid', help='Session UUID')
    
    # List wallets
    subparsers.add_parser('wallets', help='List wallets')
    
    # Show logs
    logs_parser = subparsers.add_parser('logs', help='Show application logs')
    logs_parser.add_argument('--session', help='Filter logs by session UUID')
    logs_parser.add_argument('--limit', type=int, default=50, help='Number of logs to show')
    
    # Backup database
    backup_parser = subparsers.add_parser('backup', help='Backup database')
    backup_parser.add_argument('--path', help='Backup file path')
    
    # Vacuum database
    subparsers.add_parser('vacuum', help='Optimize database')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return
    
    # Initialize settings and logging
    settings = load_settings()
    configure_logging(settings.log_level)
    db_path = args.db_path or settings.db_path
    db_manager = DatabaseManager(db_path)
    
    # Execute command
    if args.command == 'sessions':
        list_sessions(db_manager, args.limit)
    elif args.command == 'details':
        session_details(db_manager, args.session_uuid)
    elif args.command == 'wallets':
        list_wallets(db_manager)
    elif args.command == 'logs':
        show_logs(db_manager, args.session, args.limit)
    elif args.command == 'backup':
        backup_database(db_manager, args.path)
    elif args.command == 'vacuum':
        vacuum_database(db_manager)


if __name__ == "__main__":
    main()
