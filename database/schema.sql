-- Señales generadas por la IA para cada análisis de mercado
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    decision TEXT NOT NULL,          -- LONG, SHORT, HOLD
    confidence REAL NOT NULL,
    reasoning TEXT,
    key_factors TEXT,                -- JSON array de strings
    risk_factors TEXT,               -- JSON array de strings
    entry_price REAL,
    suggested_sl_pct REAL,
    suggested_tp_pct REAL,
    indicators_15m TEXT,             -- JSON snapshot completo de indicadores
    indicators_1h TEXT,
    indicators_4h TEXT,
    acted_on INTEGER DEFAULT 0,      -- 1 si se abrió un trade
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Trades simulados en modo paper trading
CREATE TABLE IF NOT EXISTS paper_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_id INTEGER REFERENCES signals(id),
    symbol TEXT NOT NULL,
    direction TEXT NOT NULL,         -- LONG, SHORT
    entry_price REAL NOT NULL,
    quantity REAL NOT NULL,
    leverage INTEGER DEFAULT 1,
    sl_price REAL,
    tp_price REAL,
    status TEXT DEFAULT 'OPEN',      -- OPEN, CLOSED_TP, CLOSED_SL, CLOSED_MANUAL
    exit_price REAL,
    pnl_usdt REAL,
    pnl_pct REAL,
    opened_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    closed_at TIMESTAMP
);

-- Trades reales ejecutados en Binance (modo live)
CREATE TABLE IF NOT EXISTS live_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_id INTEGER REFERENCES signals(id),
    exchange_order_id TEXT,
    symbol TEXT NOT NULL,
    direction TEXT NOT NULL,
    entry_price REAL,
    quantity REAL,
    leverage INTEGER,
    sl_price REAL,
    tp_price REAL,
    status TEXT DEFAULT 'OPEN',      -- OPEN, CLOSED, CANCELLED, ERROR
    exit_price REAL,
    pnl_usdt REAL,
    pnl_pct REAL,
    opened_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    closed_at TIMESTAMP,
    raw_response TEXT                -- JSON de respuesta del exchange
);

-- Log general del sistema
CREATE TABLE IF NOT EXISTS system_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    level TEXT NOT NULL,             -- INFO, WARNING, ERROR, CRITICAL
    module TEXT,
    message TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Índices para consultas frecuentes
CREATE INDEX IF NOT EXISTS idx_signals_symbol ON signals(symbol, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_paper_trades_status ON paper_trades(status, symbol);
CREATE INDEX IF NOT EXISTS idx_live_trades_status ON live_trades(status, symbol);
CREATE INDEX IF NOT EXISTS idx_logs_level ON system_logs(level, created_at DESC);
