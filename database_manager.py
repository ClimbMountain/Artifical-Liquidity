import sqlite3
import hashlib
import uuid
import json
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from contextlib import contextmanager


class DatabaseManager:
    
    def __init__(self, db_path: str = "polyfarm.db"):
        self.db_path = db_path
        self.init_database()
    
    def init_database(self):
        """Initialize the database with the schema."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='wallets'"
            )
            if cursor.fetchone():
                conn.execute("PRAGMA foreign_keys = ON")
                return
            
            try:
                with open('database_schema.sql', 'r') as f:
                    schema = f.read()
                    conn.executescript(schema)
            except FileNotFoundError:
                print("Warning: database_schema.sql not found. Creating basic schema.")
                self._create_basic_schema(conn)
    
    def _create_basic_schema(self, conn):
        """Create basic schema if schema file is not found."""
        conn.execute("""
            CREATE TABLE IF NOT EXISTS wallets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                wallet_index INTEGER NOT NULL UNIQUE,
                private_key_hash TEXT NOT NULL,
                funder_address TEXT NOT NULL,
                nickname TEXT,
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        conn.execute("""
            CREATE TABLE IF NOT EXISTS trading_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_uuid TEXT NOT NULL UNIQUE,
                condition_id TEXT NOT NULL,
                volume INTEGER NOT NULL,
                status TEXT DEFAULT 'running',
                start_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                end_time TIMESTAMP
            )
        """)
        
        conn.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                wallet_id INTEGER NOT NULL,
                side TEXT NOT NULL,
                price REAL NOT NULL,
                size REAL NOT NULL,
                trade_type TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
    
    @contextmanager
    def get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
        finally:
            conn.close()
    
    def add_wallet(self, wallet_index: int, private_key: str, funder_address: str, nickname: str = None) -> int:
        private_key_hash = hashlib.sha256(private_key.encode()).hexdigest()
        
        with self.get_connection() as conn:
            cursor = conn.execute(
                """INSERT INTO wallets (wallet_index, private_key_hash, funder_address, nickname)
                   VALUES (?, ?, ?, ?)""",
                (wallet_index, private_key_hash, funder_address, nickname)
            )
            conn.commit()
            return cursor.lastrowid
    
    def get_wallets(self, active_only: bool = True) -> List[Dict]:
        with self.get_connection() as conn:
            query = "SELECT * FROM wallets"
            if active_only:
                query += " WHERE is_active = TRUE"
            query += " ORDER BY wallet_index"
            
            cursor = conn.execute(query)
            return [dict(row) for row in cursor.fetchall()]
    
    def deactivate_wallet(self, wallet_id: int):
        with self.get_connection() as conn:
            conn.execute("UPDATE wallets SET is_active = FALSE WHERE id = ?", (wallet_id,))
            conn.commit()
    
    def create_session(self, condition_id: str, token_id: str, volume: int, iterations: int, 
                      initial_wallet_count: int) -> str:
        session_uuid = str(uuid.uuid4())
        
        with self.get_connection() as conn:
            conn.execute(
                """INSERT INTO trading_sessions 
                   (session_uuid, condition_id, token_id, volume, iterations, initial_wallet_count)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (session_uuid, condition_id, token_id, volume, iterations, initial_wallet_count)
            )
            conn.commit()
        
        return session_uuid
    
    def get_session_by_uuid(self, session_uuid: str) -> Optional[Dict]:
        with self.get_connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM trading_sessions WHERE session_uuid = ?",
                (session_uuid,)
            )
            row = cursor.fetchone()
            return dict(row) if row else None
    
    def update_session_status(self, session_uuid: str, status: str, end_time: datetime = None):
        with self.get_connection() as conn:
            if end_time:
                conn.execute(
                    "UPDATE trading_sessions SET status = ?, end_time = ? WHERE session_uuid = ?",
                    (status, end_time, session_uuid)
                )
            else:
                conn.execute(
                    "UPDATE trading_sessions SET status = ? WHERE session_uuid = ?",
                    (status, session_uuid)
                )
            conn.commit()
    
    def log_trade(self, session_uuid: str, wallet_id: int, token_id: str, side: str, 
                 price: float, size: float, trade_type: str, order_id: str = None) -> int:
        session = self.get_session_by_uuid(session_uuid)
        if not session:
            raise ValueError(f"Session {session_uuid} not found")
        
        with self.get_connection() as conn:
            cursor = conn.execute(
                """INSERT INTO trades 
                   (session_id, wallet_id, token_id, order_id, side, price, size, trade_type)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (session['id'], wallet_id, token_id, order_id, side, price, size, trade_type)
            )
            conn.commit()
            return cursor.lastrowid
    
    def update_trade_status(self, trade_id: int, status: str, fill_price: float = None, 
                           fill_size: float = None, fees: float = None):
        with self.get_connection() as conn:
            if fill_price is not None and fill_size is not None:
                conn.execute(
                    """UPDATE trades 
                       SET status = ?, fill_price = ?, fill_size = ?, fees = ?, filled_at = CURRENT_TIMESTAMP
                       WHERE id = ?""",
                    (status, fill_price, fill_size, fees or 0.0, trade_id)
                )
            else:
                conn.execute(
                    "UPDATE trades SET status = ? WHERE id = ?",
                    (status, trade_id)
                )
            conn.commit()
    
    def save_market_data(self, token_id: str, best_bid: float, best_ask: float, 
                        session_uuid: str = None):
        session_id = None
        if session_uuid:
            session = self.get_session_by_uuid(session_uuid)
            session_id = session['id'] if session else None
        
        spread = best_ask - best_bid if best_bid and best_ask else None
        
        with self.get_connection() as conn:
            conn.execute(
                """INSERT INTO market_data (token_id, session_id, best_bid, best_ask, spread)
                   VALUES (?, ?, ?, ?, ?)""",
                (token_id, session_id, best_bid, best_ask, spread)
            )
            conn.commit()
    
    def log_message(self, message: str, log_level: str = "INFO", session_uuid: str = None, 
                   details: Dict = None):
        session_id = None
        if session_uuid:
            session = self.get_session_by_uuid(session_uuid)
            session_id = session['id'] if session else None
        
        details_json = json.dumps(details) if details else None
        
        with self.get_connection() as conn:
            conn.execute(
                """INSERT INTO app_logs (session_id, log_level, message, details)
                   VALUES (?, ?, ?, ?)""",
                (session_id, log_level, message, details_json)
            )
            conn.commit()
    
    def get_session_summary(self, session_uuid: str) -> Dict:
        with self.get_connection() as conn:
            cursor = conn.execute(
                """SELECT 
                    ts.*,
                    COUNT(t.id) as total_trades,
                    SUM(CASE WHEN t.status = 'filled' THEN t.size ELSE 0 END) as filled_volume,
                    SUM(t.fees) as total_fees,
                    AVG(t.price) as avg_price
                FROM trading_sessions ts
                LEFT JOIN trades t ON ts.id = t.session_id
                WHERE ts.session_uuid = ?
                GROUP BY ts.id""",
                (session_uuid,)
            )
            row = cursor.fetchone()
            return dict(row) if row else {}
    
    def get_wallet_performance(self, wallet_id: int) -> Dict:
        with self.get_connection() as conn:
            cursor = conn.execute(
                """SELECT 
                    w.*,
                    COUNT(t.id) as total_trades,
                    SUM(CASE WHEN t.status = 'filled' THEN t.size ELSE 0 END) as total_volume,
                    SUM(t.fees) as total_fees,
                    AVG(t.price) as avg_price,
                    MAX(t.timestamp) as last_trade_time
                FROM wallets w
                LEFT JOIN trades t ON w.id = t.wallet_id
                WHERE w.id = ?
                GROUP BY w.id""",
                (wallet_id,)
            )
            row = cursor.fetchone()
            return dict(row) if row else {}
    
    def get_recent_sessions(self, limit: int = 10) -> List[Dict]:
        with self.get_connection() as conn:
            cursor = conn.execute(
                """SELECT * FROM v_active_sessions 
                   ORDER BY start_time DESC 
                   LIMIT ?""",
                (limit,)
            )
            return [dict(row) for row in cursor.fetchall()]
    
    def get_setting(self, key: str) -> Optional[str]:
        with self.get_connection() as conn:
            cursor = conn.execute(
                "SELECT setting_value FROM app_settings WHERE setting_key = ?",
                (key,)
            )
            row = cursor.fetchone()
            return row['setting_value'] if row else None
    
    def set_setting(self, key: str, value: str):
        with self.get_connection() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO app_settings (setting_key, setting_value)
                   VALUES (?, ?)""",
                (key, value)
            )
            conn.commit()
    
    def backup_database(self, backup_path: str):
        with sqlite3.connect(self.db_path) as source:
            with sqlite3.connect(backup_path) as backup:
                source.backup(backup)
    
    def vacuum_database(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("VACUUM") 

    def add_chain_step(self,
                    session_uuid: str,
                    iteration_number: int,
                    sequence_order: int,
                    wallet_id: int,
                    is_initial_buy: bool = False,
                    is_final_sell: bool = False):
        """Insert one row into chain_sequences for UI chain display."""
        session = self.get_session_by_uuid(session_uuid)
        if not session:
            raise ValueError(f"Session {session_uuid} not found")

        with self.get_connection() as conn:
            conn.execute(
                """INSERT INTO chain_sequences
                (session_id, iteration_number, sequence_order, wallet_id,
                    is_initial_buy, is_final_sell)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    session["id"],
                    iteration_number,
                    sequence_order,
                    wallet_id,
                    int(is_initial_buy),
                    int(is_final_sell),
                ),
            )
            conn.commit()

    def add_chain_batch(self, session_uuid: str, rows: list[tuple]):
        """
        rows = [(iteration_number, sequence_order, wallet_id, initial_bool, final_bool), ...]
        """
        session = self.get_session_by_uuid(session_uuid)
        if not session:
            raise ValueError(f"Session {session_uuid} not found")

        with self.get_connection() as conn:
            conn.executemany(
                """INSERT INTO chain_sequences
                (session_id, iteration_number, sequence_order, wallet_id,
                    is_initial_buy, is_final_sell)
                VALUES (?, ?, ?, ?, ?, ?)""",
                [
                    (session["id"], it, seq, wid, int(init), int(fin))
                    for it, seq, wid, init, fin in rows
                ],
            )
            conn.commit()
