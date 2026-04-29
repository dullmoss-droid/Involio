import sqlite3
import json
from datetime import datetime
from pathlib import Path

DB_PATH = Path("involio.db")


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    with get_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS copied_trades (
                trade_id        TEXT PRIMARY KEY,
                trader_id       TEXT NOT NULL,
                asset           TEXT,
                direction       TEXT,
                parsed_fields   TEXT,
                action_taken    TEXT,
                result          TEXT,
                errors          TEXT,
                detected_at     TEXT NOT NULL,
                executed_at     TEXT,
                closed_at       TEXT,
                status          TEXT DEFAULT 'open'
            );

            CREATE TABLE IF NOT EXISTS system_events (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type  TEXT NOT NULL,
                detail      TEXT,
                created_at  TEXT NOT NULL
            );
        """)


def is_trade_copied(trade_id: str) -> bool:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT 1 FROM copied_trades WHERE trade_id = ?", (trade_id,)
        ).fetchone()
        return row is not None


def save_copied_trade(
    trade_id: str,
    trader_id: str,
    parsed_fields: dict,
    action_taken: str,
    result: str,
    errors: str = "",
) -> None:
    now = datetime.utcnow().isoformat()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO copied_trades
                (trade_id, trader_id, asset, direction, parsed_fields,
                 action_taken, result, errors, detected_at, executed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                trade_id,
                trader_id,
                parsed_fields.get("asset"),
                parsed_fields.get("direction"),
                json.dumps(parsed_fields),
                action_taken,
                result,
                errors,
                now,
                now,
            ),
        )


def mark_trade_closed(trade_id: str) -> None:
    now = datetime.utcnow().isoformat()
    with get_connection() as conn:
        conn.execute(
            "UPDATE copied_trades SET status = 'closed', closed_at = ? WHERE trade_id = ?",
            (now, trade_id),
        )


def get_open_trades() -> list[sqlite3.Row]:
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM copied_trades WHERE status = 'open'"
        ).fetchall()


def log_event(event_type: str, detail: str = "") -> None:
    now = datetime.utcnow().isoformat()
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO system_events (event_type, detail, created_at) VALUES (?, ?, ?)",
            (event_type, detail, now),
        )
