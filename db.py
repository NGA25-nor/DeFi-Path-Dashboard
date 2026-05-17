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
    awbtc_balance   REAL,
    vdusdt_balance  REAL,
    vdusdc_balance  REAL,
    uni_positions   INTEGER,
    uni_position_ids TEXT,
    uni_position_value REAL,
    uni_fees_unclaimed REAL,
    uni_weth_fees REAL,
    uni_usdt_fees REAL,
    uni_weth_amount REAL,
    uni_usdt_amount REAL,
    uni_in_range INTEGER,
    uni_tick_lower INTEGER,
    uni_tick_upper INTEGER,
    uni_current_tick INTEGER,
    liq_price_eth   REAL,
    liq_price_btc   REAL,
    correlated_liq_drop_pct  REAL,
    correlated_liq_price_eth REAL,
    correlated_liq_price_btc REAL,
    eth_supply_apy      REAL,
    usdt_borrow_apy     REAL,
    usdc_borrow_apy     REAL,
    aave_daily_carry    REAL,
    uni_daily_fee_yield REAL,
    gas_eth             REAL,
    gas_usd             REAL,
    gas_drag_pct        REAL,
    total_daily_yield   REAL,
    cumulative_realized_fees_usd REAL,
    cumulative_realized_fees_eth REAL,
    cumulative_realized_fees_usdt REAL,
    cumulative_total_farm_output_usd REAL,
    total_equity    REAL,
    notes           TEXT
);
"""


MIGRATIONS = (
    ("btc_price", "REAL"),
    ("awbtc_balance", "REAL"),
    ("vdusdc_balance", "REAL"),
    ("liq_price_eth", "REAL"),
    ("liq_price_btc", "REAL"),
    ("correlated_liq_drop_pct", "REAL"),
    ("correlated_liq_price_eth", "REAL"),
    ("correlated_liq_price_btc", "REAL"),
    ("uni_position_ids", "TEXT"),
    ("uni_position_value", "REAL"),
    ("uni_fees_unclaimed", "REAL"),
    ("uni_weth_fees", "REAL"),
    ("uni_usdt_fees", "REAL"),
    ("uni_weth_amount", "REAL"),
    ("uni_usdt_amount", "REAL"),
    ("uni_in_range", "INTEGER"),
    ("uni_tick_lower", "INTEGER"),
    ("uni_tick_upper", "INTEGER"),
    ("uni_current_tick", "INTEGER"),
    ("eth_supply_apy", "REAL"),
    ("usdt_borrow_apy", "REAL"),
    ("usdc_borrow_apy", "REAL"),
    ("aave_daily_carry", "REAL"),
    ("uni_daily_fee_yield", "REAL"),
    ("gas_eth", "REAL"),
    ("gas_usd", "REAL"),
    ("gas_drag_pct", "REAL"),
    ("total_daily_yield", "REAL"),
    ("cumulative_realized_fees_usd", "REAL"),
    ("cumulative_realized_fees_eth", "REAL"),
    ("cumulative_realized_fees_usdt", "REAL"),
    ("cumulative_total_farm_output_usd", "REAL"),
)


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
    "awbtc_balance",
    "vdusdt_balance",
    "vdusdc_balance",
    "uni_positions",
    "uni_position_ids",
    "uni_position_value",
    "uni_fees_unclaimed",
    "uni_weth_fees",
    "uni_usdt_fees",
    "uni_weth_amount",
    "uni_usdt_amount",
    "uni_in_range",
    "uni_tick_lower",
    "uni_tick_upper",
    "uni_current_tick",
    "liq_price_eth",
    "liq_price_btc",
    "correlated_liq_drop_pct",
    "correlated_liq_price_eth",
    "correlated_liq_price_btc",
    "eth_supply_apy",
    "usdt_borrow_apy",
    "usdc_borrow_apy",
    "aave_daily_carry",
    "uni_daily_fee_yield",
    "gas_eth",
    "gas_usd",
    "gas_drag_pct",
    "total_daily_yield",
    "cumulative_realized_fees_usd",
    "cumulative_realized_fees_eth",
    "cumulative_realized_fees_usdt",
    "cumulative_total_farm_output_usd",
    "total_equity",
    "notes",
)


def init_db(db_path: Path = DB_PATH) -> None:
    """Create the data directory and schema if needed."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute(SCHEMA)
        existing_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(daily_snapshots)")
        }
        for column, column_type in MIGRATIONS:
            if column not in existing_columns:
                conn.execute(f"ALTER TABLE daily_snapshots ADD COLUMN {column} {column_type}")
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
