"""SQLite helpers for the local DeFi tracker."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any


DB_PATH = Path(__file__).resolve().parent / "data" / "portfolio.db"


SCHEMA = """
CREATE TABLE IF NOT EXISTS daily_snapshots (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp       TEXT NOT NULL,
    eth_price       REAL,
    btc_price       REAL,
    eth_main        REAL,
    eth_lp          REAL,
    aave_collateral REAL,
    aave_debt       REAL,
    aave_equity     REAL,
    health_factor   REAL,
    ltv_pct         REAL,
    aweth_balance   REAL,
    vdusdt_balance  REAL,
    uni_positions   INTEGER,
    total_equity    REAL,
    notes           TEXT
);
"""


COLUMNS = (
    "timestamp",
    "eth_price",
    "btc_price",
    "eth_main",
    "eth_lp",
    "aave_collateral",
    "aave_debt",
    "aave_equity",
    "health_factor",
    "ltv_pct",
    "aweth_balance",
    "vdusdt_balance",
    "uni_positions",
    "total_equity",
    "notes",
)


def init_db(db_path: Path = DB_PATH) -> None:
    """Create the data directory and schema if needed."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute(SCHEMA)
        conn.commit()


def insert_snapshot(snapshot: dict[str, Any], db_path: Path = DB_PATH) -> None:
    """Insert one daily snapshot row."""
    placeholders = ", ".join("?" for _ in COLUMNS)
    columns = ", ".join(COLUMNS)
    values = [snapshot.get(column) for column in COLUMNS]

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            f"INSERT INTO daily_snapshots ({columns}) VALUES ({placeholders})",
            values,
        )
        conn.commit()


def get_history(limit: int = 30, db_path: Path = DB_PATH) -> list[dict[str, Any]]:
    """Return the latest rows in chronological order."""
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT *
            FROM daily_snapshots
            ORDER BY timestamp DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    return [dict(row) for row in reversed(rows)]
