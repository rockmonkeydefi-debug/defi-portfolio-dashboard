"""SQLite storage for portfolio snapshots and historical tracking."""

import sqlite3
import os
from datetime import datetime
from typing import Optional


DB_PATH = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'portfolio.db')


def get_db_path() -> str:
    """Get the database file path, creating the data directory if needed."""
    db_dir = os.path.dirname(DB_PATH)
    os.makedirs(db_dir, exist_ok=True)
    return DB_PATH


def get_connection() -> sqlite3.Connection:
    """Get a database connection with row factory."""
    conn = sqlite3.connect(get_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """Create all tables if they don't exist."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.executescript("""
        CREATE TABLE IF NOT EXISTS snapshot_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME NOT NULL,
            wallet_address TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'running',
            duration_seconds REAL
        );

        CREATE TABLE IF NOT EXISTS token_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL,
            wallet_address TEXT NOT NULL,
            chain TEXT NOT NULL,
            token_symbol TEXT NOT NULL,
            token_address TEXT,
            balance REAL NOT NULL,
            price_usd REAL NOT NULL,
            value_usd REAL NOT NULL,
            FOREIGN KEY (run_id) REFERENCES snapshot_runs(id)
        );

        CREATE TABLE IF NOT EXISTS lp_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL,
            wallet_address TEXT NOT NULL,
            chain TEXT NOT NULL,
            protocol TEXT NOT NULL,
            position_id TEXT NOT NULL,
            pool_pair TEXT NOT NULL,
            token0_symbol TEXT NOT NULL,
            token1_symbol TEXT NOT NULL,
            token0_amount REAL NOT NULL DEFAULT 0,
            token1_amount REAL NOT NULL DEFAULT 0,
            token0_fees_uncollected REAL NOT NULL DEFAULT 0,
            token1_fees_uncollected REAL NOT NULL DEFAULT 0,
            token0_fees_collected REAL NOT NULL DEFAULT 0,
            token1_fees_collected REAL NOT NULL DEFAULT 0,
            token0_price_usd REAL NOT NULL DEFAULT 0,
            token1_price_usd REAL NOT NULL DEFAULT 0,
            liquidity_value_usd REAL NOT NULL DEFAULT 0,
            fees_uncollected_usd REAL NOT NULL DEFAULT 0,
            fees_collected_usd REAL NOT NULL DEFAULT 0,
            total_value_usd REAL NOT NULL DEFAULT 0,
            in_range INTEGER NOT NULL DEFAULT 1,
            is_open INTEGER NOT NULL DEFAULT 1,
            FOREIGN KEY (run_id) REFERENCES snapshot_runs(id)
        );

        CREATE TABLE IF NOT EXISTS fee_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            wallet_address TEXT NOT NULL,
            chain TEXT NOT NULL,
            protocol TEXT NOT NULL,
            position_id TEXT NOT NULL,
            pool_pair TEXT NOT NULL,
            event_type TEXT NOT NULL,
            token0_symbol TEXT NOT NULL,
            token1_symbol TEXT NOT NULL,
            token0_amount REAL NOT NULL DEFAULT 0,
            token1_amount REAL NOT NULL DEFAULT 0,
            value_usd REAL NOT NULL DEFAULT 0,
            timestamp DATETIME NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_token_snap_run ON token_snapshots(run_id);
        CREATE INDEX IF NOT EXISTS idx_token_snap_wallet ON token_snapshots(wallet_address, chain, token_symbol);
        CREATE INDEX IF NOT EXISTS idx_lp_snap_run ON lp_snapshots(run_id);
        CREATE INDEX IF NOT EXISTS idx_lp_snap_position ON lp_snapshots(position_id);
        CREATE INDEX IF NOT EXISTS idx_fee_events_position ON fee_events(position_id);
        CREATE INDEX IF NOT EXISTS idx_snapshot_runs_ts ON snapshot_runs(timestamp);
    """)

    conn.commit()
    conn.close()


# --- Snapshot Run CRUD ---

def create_snapshot_run(wallet_address: str) -> int:
    """Create a new snapshot run and return its ID."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO snapshot_runs (timestamp, wallet_address, status) VALUES (?, ?, ?)",
        (datetime.utcnow().isoformat(), wallet_address, 'running')
    )
    run_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return run_id


def complete_snapshot_run(run_id: int, duration: float):
    """Mark a snapshot run as completed."""
    conn = get_connection()
    conn.execute(
        "UPDATE snapshot_runs SET status = 'completed', duration_seconds = ? WHERE id = ?",
        (duration, run_id)
    )
    conn.commit()
    conn.close()


def fail_snapshot_run(run_id: int, duration: float):
    """Mark a snapshot run as failed."""
    conn = get_connection()
    conn.execute(
        "UPDATE snapshot_runs SET status = 'failed', duration_seconds = ? WHERE id = ?",
        (duration, run_id)
    )
    conn.commit()
    conn.close()


# --- Token Snapshot CRUD ---

def insert_token_snapshot(run_id: int, wallet: str, chain: str, symbol: str,
                          address: Optional[str], balance: float,
                          price_usd: float, value_usd: float):
    """Insert a token balance snapshot."""
    conn = get_connection()
    conn.execute(
        """INSERT INTO token_snapshots 
           (run_id, wallet_address, chain, token_symbol, token_address, balance, price_usd, value_usd)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (run_id, wallet, chain, symbol, address, balance, price_usd, value_usd)
    )
    conn.commit()
    conn.close()


# --- LP Snapshot CRUD ---

def insert_lp_snapshot(run_id: int, wallet: str, chain: str, protocol: str,
                       position_id: str, pool_pair: str,
                       token0_symbol: str, token1_symbol: str,
                       token0_amount: float, token1_amount: float,
                       token0_fees_uncollected: float, token1_fees_uncollected: float,
                       token0_fees_collected: float, token1_fees_collected: float,
                       token0_price_usd: float, token1_price_usd: float,
                       liquidity_value_usd: float, fees_uncollected_usd: float,
                       fees_collected_usd: float, total_value_usd: float,
                       in_range: bool, is_open: bool):
    """Insert an LP position snapshot."""
    conn = get_connection()
    conn.execute(
        """INSERT INTO lp_snapshots 
           (run_id, wallet_address, chain, protocol, position_id, pool_pair,
            token0_symbol, token1_symbol, token0_amount, token1_amount,
            token0_fees_uncollected, token1_fees_uncollected,
            token0_fees_collected, token1_fees_collected,
            token0_price_usd, token1_price_usd,
            liquidity_value_usd, fees_uncollected_usd, fees_collected_usd,
            total_value_usd, in_range, is_open)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (run_id, wallet, chain, protocol, position_id, pool_pair,
         token0_symbol, token1_symbol, token0_amount, token1_amount,
         token0_fees_uncollected, token1_fees_uncollected,
         token0_fees_collected, token1_fees_collected,
         token0_price_usd, token1_price_usd,
         liquidity_value_usd, fees_uncollected_usd, fees_collected_usd,
         total_value_usd, int(in_range), int(is_open))
    )
    conn.commit()
    conn.close()


# --- Fee Event CRUD ---

def insert_fee_event(wallet: str, chain: str, protocol: str, position_id: str,
                     pool_pair: str, event_type: str,
                     token0_symbol: str, token1_symbol: str,
                     token0_amount: float, token1_amount: float, value_usd: float):
    """Insert a fee collection/accrual event."""
    conn = get_connection()
    conn.execute(
        """INSERT INTO fee_events 
           (wallet_address, chain, protocol, position_id, pool_pair, event_type,
            token0_symbol, token1_symbol, token0_amount, token1_amount, value_usd, timestamp)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (wallet, chain, protocol, position_id, pool_pair, event_type,
         token0_symbol, token1_symbol, token0_amount, token1_amount, value_usd,
         datetime.utcnow().isoformat())
    )
    conn.commit()
    conn.close()


# --- Query Functions for Charts ---

def get_portfolio_timeseries(wallet: Optional[str] = None, days: int = 90) -> list[dict]:
    """Get total portfolio value over time, grouped by snapshot run."""
    conn = get_connection()
    
    query = """
        SELECT 
            sr.timestamp,
            sr.wallet_address,
            COALESCE(t.token_value, 0) as token_value,
            COALESCE(l.lp_value, 0) as lp_value,
            COALESCE(l.fees_value, 0) as fees_value,
            COALESCE(t.token_value, 0) + COALESCE(l.lp_value, 0) + COALESCE(l.fees_value, 0) as total_value
        FROM snapshot_runs sr
        LEFT JOIN (
            SELECT run_id, SUM(value_usd) as token_value
            FROM token_snapshots GROUP BY run_id
        ) t ON t.run_id = sr.id
        LEFT JOIN (
            SELECT run_id, 
                   SUM(liquidity_value_usd) as lp_value,
                   SUM(fees_uncollected_usd) as fees_value
            FROM lp_snapshots GROUP BY run_id
        ) l ON l.run_id = sr.id
        WHERE sr.status = 'completed'
          AND sr.timestamp >= datetime('now', ?)
    """
    params = [f'-{days} days']
    
    if wallet:
        query += " AND sr.wallet_address = ?"
        params.append(wallet)
    
    query += " ORDER BY sr.timestamp ASC"
    
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_token_timeseries(token_symbol: str, wallet: Optional[str] = None,
                         days: int = 90) -> list[dict]:
    """Get a specific token's balance and value over time."""
    conn = get_connection()
    
    query = """
        SELECT sr.timestamp, ts.chain, ts.balance, ts.price_usd, ts.value_usd
        FROM token_snapshots ts
        JOIN snapshot_runs sr ON sr.id = ts.run_id
        WHERE ts.token_symbol = ?
          AND sr.status = 'completed'
          AND sr.timestamp >= datetime('now', ?)
    """
    params = [token_symbol, f'-{days} days']
    
    if wallet:
        query += " AND ts.wallet_address = ?"
        params.append(wallet)
    
    query += " ORDER BY sr.timestamp ASC"
    
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_lp_position_timeseries(position_id: str, days: int = 90) -> list[dict]:
    """Get an LP position's data over time."""
    conn = get_connection()
    
    rows = conn.execute("""
        SELECT sr.timestamp, ls.token0_amount, ls.token1_amount,
               ls.token0_fees_uncollected, ls.token1_fees_uncollected,
               ls.token0_fees_collected, ls.token1_fees_collected,
               ls.liquidity_value_usd, ls.fees_uncollected_usd,
               ls.fees_collected_usd, ls.total_value_usd, ls.in_range
        FROM lp_snapshots ls
        JOIN snapshot_runs sr ON sr.id = ls.run_id
        WHERE ls.position_id = ?
          AND sr.status = 'completed'
          AND sr.timestamp >= datetime('now', ?)
        ORDER BY sr.timestamp ASC
    """, (position_id, f'-{days} days')).fetchall()
    
    conn.close()
    return [dict(r) for r in rows]


def get_fees_timeseries(wallet: Optional[str] = None, days: int = 90) -> list[dict]:
    """Get cumulative fees over time across all positions."""
    conn = get_connection()
    
    query = """
        SELECT sr.timestamp,
               SUM(ls.fees_uncollected_usd + ls.fees_collected_usd) as total_fees_usd,
               SUM(ls.fees_uncollected_usd) as uncollected_usd,
               SUM(ls.fees_collected_usd) as collected_usd
        FROM lp_snapshots ls
        JOIN snapshot_runs sr ON sr.id = ls.run_id
        WHERE sr.status = 'completed'
          AND sr.timestamp >= datetime('now', ?)
    """
    params = [f'-{days} days']
    
    if wallet:
        query += " AND ls.wallet_address = ?"
        params.append(wallet)
    
    query += " GROUP BY sr.id ORDER BY sr.timestamp ASC"
    
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_latest_snapshot_time() -> Optional[str]:
    """Get the timestamp of the most recent completed snapshot."""
    conn = get_connection()
    row = conn.execute(
        "SELECT timestamp FROM snapshot_runs WHERE status='completed' ORDER BY timestamp DESC LIMIT 1"
    ).fetchone()
    conn.close()
    return row['timestamp'] if row else None


def get_snapshot_runs(limit: int = 20) -> list[dict]:
    """Get recent snapshot runs."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM snapshot_runs ORDER BY timestamp DESC LIMIT ?",
        (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_all_tracked_positions() -> list[dict]:
    """Get all unique LP positions ever tracked (including closed ones)."""
    conn = get_connection()
    rows = conn.execute("""
        SELECT DISTINCT position_id, chain, protocol, pool_pair,
               token0_symbol, token1_symbol, 
               MAX(is_open) as is_open
        FROM lp_snapshots
        GROUP BY position_id
        ORDER BY is_open DESC, pool_pair ASC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]
