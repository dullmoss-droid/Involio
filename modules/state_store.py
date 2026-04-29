import json
import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent.parent / "trading_bot.db"
SCHEMA_PATH = Path(__file__).parent.parent / "database" / "schema.sql"


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, detect_types=sqlite3.PARSE_DECLTYPES)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def initialize_db() -> None:
    schema = SCHEMA_PATH.read_text()
    with get_connection() as conn:
        conn.executescript(schema)
    logger.info("Database initialized at %s", DB_PATH)


@dataclass
class SignalRecord:
    symbol: str
    decision: str
    confidence: float
    reasoning: str
    key_factors: list[str]
    risk_factors: list[str]
    entry_price: float
    suggested_sl_pct: float
    suggested_tp_pct: float
    indicators_15m: dict
    indicators_1h: dict
    indicators_4h: dict


@dataclass
class PaperTradeRecord:
    signal_id: int
    symbol: str
    direction: str
    entry_price: float
    quantity: float
    leverage: int
    sl_price: float
    tp_price: float


def save_signal(record: SignalRecord) -> int:
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO signals (
                symbol, decision, confidence, reasoning,
                key_factors, risk_factors, entry_price,
                suggested_sl_pct, suggested_tp_pct,
                indicators_15m, indicators_1h, indicators_4h
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.symbol,
                record.decision,
                record.confidence,
                record.reasoning,
                json.dumps(record.key_factors),
                json.dumps(record.risk_factors),
                record.entry_price,
                record.suggested_sl_pct,
                record.suggested_tp_pct,
                json.dumps(record.indicators_15m),
                json.dumps(record.indicators_1h),
                json.dumps(record.indicators_4h),
            ),
        )
        signal_id = cursor.lastrowid
    logger.debug("Saved signal id=%d %s %s (%.0f%%)", signal_id, record.symbol, record.decision, record.confidence)
    return signal_id


def mark_signal_acted(signal_id: int) -> None:
    with get_connection() as conn:
        conn.execute("UPDATE signals SET acted_on = 1 WHERE id = ?", (signal_id,))


def open_paper_trade(record: PaperTradeRecord) -> int:
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO paper_trades (
                signal_id, symbol, direction, entry_price,
                quantity, leverage, sl_price, tp_price
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.signal_id,
                record.symbol,
                record.direction,
                record.entry_price,
                record.quantity,
                record.leverage,
                record.sl_price,
                record.tp_price,
            ),
        )
        trade_id = cursor.lastrowid
    logger.info("Opened paper trade id=%d %s %s @ %.4f", trade_id, record.symbol, record.direction, record.entry_price)
    return trade_id


def close_paper_trade(trade_id: int, exit_price: float, status: str, pnl_usdt: float, pnl_pct: float) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE paper_trades
            SET status = ?, exit_price = ?, pnl_usdt = ?, pnl_pct = ?, closed_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (status, exit_price, pnl_usdt, pnl_pct, trade_id),
        )
    logger.info("Closed paper trade id=%d status=%s pnl=%.2f USDT (%.2f%%)", trade_id, status, pnl_usdt, pnl_pct)


def get_open_paper_trades() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM paper_trades WHERE status = 'OPEN' ORDER BY opened_at"
        ).fetchall()
    return [dict(row) for row in rows]


def get_open_paper_trades_for_symbol(symbol: str) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM paper_trades WHERE status = 'OPEN' AND symbol = ?",
            (symbol,),
        ).fetchall()
    return [dict(row) for row in rows]


def get_paper_portfolio_summary() -> dict:
    with get_connection() as conn:
        totals = conn.execute(
            """
            SELECT
                COUNT(*) as total_trades,
                SUM(CASE WHEN status != 'OPEN' THEN 1 ELSE 0 END) as closed_trades,
                SUM(CASE WHEN pnl_usdt > 0 THEN 1 ELSE 0 END) as winning_trades,
                SUM(COALESCE(pnl_usdt, 0)) as total_pnl,
                COUNT(CASE WHEN status = 'OPEN' THEN 1 END) as open_positions
            FROM paper_trades
            """
        ).fetchone()
    result = dict(totals)
    closed = result["closed_trades"] or 0
    wins = result["winning_trades"] or 0
    result["win_rate"] = round(wins / closed * 100, 1) if closed > 0 else 0.0
    return result


def log_event(level: str, module: str, message: str) -> None:
    try:
        with get_connection() as conn:
            conn.execute(
                "INSERT INTO system_logs (level, module, message) VALUES (?, ?, ?)",
                (level, module, message),
            )
    except Exception:
        pass
