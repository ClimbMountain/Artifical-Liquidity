PRAGMA foreign_keys = ON;

CREATE TABLE wallets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    wallet_index INTEGER NOT NULL UNIQUE,
    private_key_hash TEXT NOT NULL,
    funder_address TEXT NOT NULL,
    nickname TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE market_conditions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    condition_id TEXT NOT NULL UNIQUE,
    title TEXT,
    description TEXT,
    category TEXT,
    end_date TIMESTAMP,
    status TEXT DEFAULT 'active',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE tokens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    token_id TEXT NOT NULL UNIQUE,
    condition_id TEXT NOT NULL,
    outcome_side TEXT NOT NULL,
    outcome_label TEXT,
    FOREIGN KEY (condition_id) REFERENCES market_conditions(condition_id) ON DELETE CASCADE
);

CREATE TABLE trading_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_uuid TEXT NOT NULL UNIQUE,
    condition_id TEXT NOT NULL,
    token_id TEXT NOT NULL,
    volume INTEGER NOT NULL,
    iterations INTEGER NOT NULL,
    initial_wallet_count INTEGER NOT NULL,
    status TEXT DEFAULT 'running',
    start_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    end_time TIMESTAMP,
    total_trades INTEGER DEFAULT 0,
    total_volume REAL DEFAULT 0.0,
    profit_loss REAL DEFAULT 0.0,
    notes TEXT,
    FOREIGN KEY (condition_id) REFERENCES market_conditions(condition_id),
    FOREIGN KEY (token_id) REFERENCES tokens(token_id)
);

CREATE TABLE market_data (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    token_id TEXT NOT NULL,
    session_id INTEGER,
    best_bid REAL,
    best_ask REAL,
    spread REAL,
    bid_volume REAL,
    ask_volume REAL,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (token_id) REFERENCES tokens(token_id),
    FOREIGN KEY (session_id) REFERENCES trading_sessions(id) ON DELETE CASCADE
);

CREATE TABLE trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    wallet_id INTEGER NOT NULL,
    token_id TEXT NOT NULL,
    order_id TEXT, 
    side TEXT NOT NULL,
    price REAL NOT NULL,
    size REAL NOT NULL,
    order_type TEXT DEFAULT 'GTC',
    status TEXT DEFAULT 'pending',
    trade_type TEXT NOT NULL,
    counterpart_wallet_id INTEGER,
    fill_price REAL,
    fill_size REAL,
    fees REAL DEFAULT 0.0,
    gas_cost REAL DEFAULT 0.0,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    filled_at TIMESTAMP,
    error_message TEXT,
    FOREIGN KEY (session_id) REFERENCES trading_sessions(id) ON DELETE CASCADE,
    FOREIGN KEY (wallet_id) REFERENCES wallets(id),
    FOREIGN KEY (token_id) REFERENCES tokens(token_id),
    FOREIGN KEY (counterpart_wallet_id) REFERENCES wallets(id)
);

CREATE TABLE chain_sequences (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    iteration_number INTEGER NOT NULL,
    sequence_order INTEGER NOT NULL,
    wallet_id INTEGER NOT NULL,
    is_initial_buy BOOLEAN DEFAULT FALSE,
    is_final_sell BOOLEAN DEFAULT FALSE,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES trading_sessions(id) ON DELETE CASCADE,
    FOREIGN KEY (wallet_id) REFERENCES wallets(id)
);

CREATE TABLE app_settings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    setting_key TEXT NOT NULL UNIQUE,
    setting_value TEXT NOT NULL,
    description TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE app_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER,
    log_level TEXT NOT NULL,
    message TEXT NOT NULL,
    details TEXT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES trading_sessions(id) ON DELETE CASCADE
);

CREATE TABLE wallet_performance (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    wallet_id INTEGER NOT NULL,
    session_id INTEGER NOT NULL,
    total_trades INTEGER DEFAULT 0,
    total_volume REAL DEFAULT 0.0,
    total_fees REAL DEFAULT 0.0,
    total_gas_cost REAL DEFAULT 0.0,
    profit_loss REAL DEFAULT 0.0,
    success_rate REAL DEFAULT 0.0,
    last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (wallet_id) REFERENCES wallets(id),
    FOREIGN KEY (session_id) REFERENCES trading_sessions(id) ON DELETE CASCADE
);

CREATE INDEX idx_trades_session_id ON trades(session_id);
CREATE INDEX idx_trades_wallet_id ON trades(wallet_id);
CREATE INDEX idx_trades_timestamp ON trades(timestamp);
CREATE INDEX idx_trades_status ON trades(status);
CREATE INDEX idx_market_data_token_id ON market_data(token_id);
CREATE INDEX idx_market_data_timestamp ON market_data(timestamp);
CREATE INDEX idx_chain_sequences_session_id ON chain_sequences(session_id);
CREATE INDEX idx_app_logs_session_id ON app_logs(session_id);
CREATE INDEX idx_app_logs_timestamp ON app_logs(timestamp);
CREATE INDEX idx_wallet_performance_wallet_id ON wallet_performance(wallet_id);

CREATE TRIGGER update_wallets_timestamp 
    AFTER UPDATE ON wallets
    FOR EACH ROW
    BEGIN
        UPDATE wallets SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
    END;

CREATE TRIGGER update_market_conditions_timestamp 
    AFTER UPDATE ON market_conditions
    FOR EACH ROW
    BEGIN
        UPDATE market_conditions SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
    END;

CREATE TRIGGER update_app_settings_timestamp 
    AFTER UPDATE ON app_settings
    FOR EACH ROW
    BEGIN
        UPDATE app_settings SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
    END;

INSERT INTO app_settings (setting_key, setting_value, description) VALUES
    ('proxy_enabled', 'true', 'Enable proxy for API requests'),
    ('default_volume', '5', 'Default trade volume'),
    ('default_iterations', '1', 'Default number of iterations'),
    ('min_wallets_required', '6', 'Minimum wallets required for trading'),
    ('trade_delay_min', '4', 'Minimum delay between trades in seconds'),
    ('trade_delay_max', '8', 'Maximum delay between trades in seconds'),
    ('auto_backup_enabled', 'true', 'Enable automatic database backups'),
    ('log_level', 'INFO', 'Application logging level');

CREATE VIEW v_active_sessions AS
SELECT 
    ts.*,
    mc.title as market_title,
    mc.description as market_description,
    COUNT(t.id) as trade_count,
    SUM(CASE WHEN t.status = 'filled' THEN t.size ELSE 0 END) as filled_volume
FROM trading_sessions ts
LEFT JOIN market_conditions mc ON ts.condition_id = mc.condition_id
LEFT JOIN trades t ON ts.id = t.session_id
WHERE ts.status IN ('running', 'completed')
GROUP BY ts.id;

CREATE VIEW v_wallet_summary AS
SELECT 
    w.*,
    COUNT(t.id) as total_trades,
    SUM(CASE WHEN t.status = 'filled' THEN t.size ELSE 0 END) as total_volume,
    SUM(t.fees) as total_fees,
    MAX(t.timestamp) as last_trade_time
FROM wallets w
LEFT JOIN trades t ON w.id = t.wallet_id
WHERE w.is_active = TRUE
GROUP BY w.id;

CREATE VIEW v_market_summary AS
SELECT 
    mc.*,
    COUNT(DISTINCT ts.id) as session_count,
    COUNT(t.id) as total_trades,
    SUM(CASE WHEN t.status = 'filled' THEN t.size ELSE 0 END) as total_volume,
    MAX(ts.start_time) as last_session_time
FROM market_conditions mc
LEFT JOIN trading_sessions ts ON mc.condition_id = ts.condition_id
LEFT JOIN trades t ON ts.id = t.session_id
GROUP BY mc.id;

-- Wallet x Market filled position (YES/NO collapsed per token)
CREATE VIEW IF NOT EXISTS v_wallet_market_pos AS
SELECT  w.id            AS wallet_id,
        w.nickname,
        tok.condition_id,
        mc.title,
        t.token_id,
        tok.outcome_side,
        SUM(CASE WHEN t.status='filled' THEN t.size ELSE 0 END)         AS filled_size,
        SUM(CASE WHEN t.status='filled' THEN t.fill_price*t.size ELSE 0 END) /
        NULLIF(SUM(CASE WHEN t.status='filled' THEN t.size ELSE 0 END),0) AS avg_fill_price
FROM trades t
JOIN wallets w         ON w.id = t.wallet_id
JOIN tokens tok        ON tok.token_id = t.token_id
JOIN market_conditions mc ON mc.condition_id = tok.condition_id
GROUP BY w.id, tok.token_id;

-- Sequencing per session for quick display
CREATE VIEW IF NOT EXISTS v_chain_sequence AS
SELECT  cs.session_id,
        ts.session_uuid,
        cs.iteration_number,
        cs.sequence_order,
        w.nickname,
        cs.is_initial_buy,
        cs.is_final_sell,
        cs.timestamp
FROM chain_sequences cs
JOIN trading_sessions ts ON ts.id = cs.session_id
JOIN wallets w           ON w.id = cs.wallet_id
ORDER BY cs.session_id, cs.iteration_number, cs.sequence_order;
