from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pandas as pd


DEFAULT_DB_PATH = Path("data") / "app.db"


class SQLiteStore:
    """轻量 SQLite 存储层，用于和 CSV 双写。"""

    def __init__(self, db_path: Path = DEFAULT_DB_PATH) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        return connection

    def _init_schema(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS accounts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    as_of_date TEXT,
                    virtual_cash REAL,
                    equity REAL,
                    daily_start_equity REAL,
                    peak_equity REAL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS account_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    time TEXT,
                    market_date TEXT,
                    virtual_cash REAL,
                    equity REAL,
                    daily_start_equity REAL,
                    peak_equity REAL
                );

                CREATE TABLE IF NOT EXISTS positions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    snapshot_time TEXT DEFAULT CURRENT_TIMESTAMP,
                    symbol TEXT,
                    quantity INTEGER,
                    avg_cost REAL,
                    entry_date TEXT,
                    strategy_name TEXT,
                    signal_score REAL,
                    last_price REAL,
                    market_value REAL,
                    unrealized_return_pct REAL
                );

                CREATE TABLE IF NOT EXISTS orders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    time TEXT,
                    order_id INTEGER,
                    symbol TEXT,
                    action TEXT,
                    quantity INTEGER,
                    signal_price REAL,
                    estimated_amount REAL,
                    status TEXT,
                    strategy_name TEXT,
                    signal_score REAL,
                    reason TEXT
                );

                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    time TEXT,
                    trade_id INTEGER,
                    symbol TEXT,
                    action TEXT,
                    quantity INTEGER,
                    signal_price REAL,
                    fill_price REAL,
                    gross_amount REAL,
                    commission REAL,
                    net_cash_change REAL,
                    virtual_cash REAL,
                    strategy_name TEXT,
                    signal_score REAL,
                    reason TEXT
                );

                CREATE TABLE IF NOT EXISTS decisions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    time TEXT,
                    symbol TEXT,
                    signal_type TEXT,
                    strategy_name TEXT,
                    signal_score REAL,
                    buy_condition_met INTEGER,
                    sell_condition_met INTEGER,
                    risk_passed INTEGER,
                    order_submitted INTEGER,
                    reject_reason TEXT
                );

                CREATE TABLE IF NOT EXISTS run_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    time TEXT,
                    event_type TEXT,
                    message TEXT
                );

                CREATE TABLE IF NOT EXISTS agent_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    time TEXT,
                    agent TEXT,
                    status TEXT,
                    message TEXT,
                    elapsed_seconds REAL,
                    details_json TEXT
                );

                CREATE TABLE IF NOT EXISTS backtest_reports (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source TEXT,
                    total_return REAL,
                    annual_return REAL,
                    max_drawdown REAL,
                    sharpe_ratio REAL,
                    win_rate REAL,
                    avg_profit_loss_ratio REAL,
                    trade_count INTEGER,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS portfolio_allocations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    symbol TEXT,
                    raw_weight REAL,
                    target_weight REAL,
                    target_amount REAL,
                    max_position_pct REAL,
                    method TEXT,
                    source TEXT
                );

                CREATE TABLE IF NOT EXISTS generic_frames (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    table_name TEXT,
                    source TEXT,
                    payload_json TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
            self._ensure_column(connection, "portfolio_allocations", "source", "TEXT")
            self._ensure_column(connection, "positions", "strategy_name", "TEXT")
            self._ensure_column(connection, "positions", "signal_score", "REAL")
            self._ensure_column(connection, "orders", "strategy_name", "TEXT")
            self._ensure_column(connection, "orders", "signal_score", "REAL")
            self._ensure_column(connection, "trades", "strategy_name", "TEXT")
            self._ensure_column(connection, "trades", "signal_score", "REAL")
            self._ensure_column(connection, "decisions", "strategy_name", "TEXT")
            self._ensure_column(connection, "decisions", "signal_score", "REAL")

    def replace_positions(self, frame: pd.DataFrame) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM positions")
            self._insert_frame(connection, "positions", frame)

    def replace_portfolio_allocations(self, frame: pd.DataFrame) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM portfolio_allocations")
            self._insert_frame(connection, "portfolio_allocations", frame)

    def append_frame(self, table_name: str, frame: pd.DataFrame) -> None:
        if frame.empty:
            return
        with self._connect() as connection:
            self._insert_frame(connection, table_name, frame)

    def append_report(self, source: str, report: dict[str, object]) -> None:
        row = dict(report)
        row["source"] = source
        self.append_frame("backtest_reports", pd.DataFrame([row]))

    def append_generic_frame(self, table_name: str, source: str, frame: pd.DataFrame) -> None:
        if frame.empty:
            return
        rows = [
            {
                "table_name": table_name,
                "source": source,
                "payload_json": json.dumps(_json_safe(row), ensure_ascii=False),
            }
            for row in frame.to_dict(orient="records")
        ]
        self.append_frame("generic_frames", pd.DataFrame(rows))

    def _insert_frame(self, connection: sqlite3.Connection, table_name: str, frame: pd.DataFrame) -> None:
        if frame.empty:
            return
        clean = frame.copy()
        for column in clean.columns:
            clean[column] = clean[column].map(_sqlite_value)
        clean.to_sql(table_name, connection, if_exists="append", index=False)

    @staticmethod
    def _ensure_column(connection: sqlite3.Connection, table_name: str, column_name: str, column_type: str) -> None:
        columns = {row[1] for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()}
        if column_name not in columns:
            connection.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")


def _sqlite_value(value):
    if pd.isna(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            return value
    return value


def _json_safe(row: dict[str, object]) -> dict[str, object]:
    return {key: _sqlite_value(value) for key, value in row.items()}


def get_store() -> SQLiteStore:
    return SQLiteStore()
