"""SQLite storage for portfolio snapshots, market data, and historical tracking."""

import sqlite3
import os
from datetime import datetime
from typing import Optional

DB_PATH = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'portfolio.db')


def get_db_path() -> str:
    """Get the absolute, normalized database file path, creating the data directory if needed.

    On Railway, RAILWAY_VOLUME_MOUNT_PATH points to the persistent volume mount inside the
    container. Use it as the DB directory when set so all tables land on the volume.
    Falls back to data/portfolio.db for local dev.
    """
    volume_mount = os.environ.get('RAILWAY_VOLUME_MOUNT_PATH', '').strip()
    if volume_mount:
        abs_path = os.path.join(volume_mount, 'portfolio.db')
    else:
        abs_path = os.path.abspath(DB_PATH)
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)
    return abs_path


def get_connection() -> sqlite3.Connection:
    """Get a database connection with row factory."""
    conn = sqlite3.connect(get_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _backup_db_if_needed():
    """Copy the DB to a timestamped backup before migrations run.
    Only acts if the source file exists and today's backup doesn't yet."""
    src = get_db_path()
    if not os.path.exists(src):
        return
    stamp = datetime.utcnow().strftime('%Y%m%d')
    dst = os.path.join(os.path.dirname(src), f'portfolio_backup_{stamp}.db')
    if os.path.exists(dst):
        return
    import shutil
    try:
        shutil.copy2(src, dst)
        print(f'[DB] Backup created: {dst}')
    except Exception as e:
        print(f'[DB] Backup failed: {e}')


def init_db():
    """Initialize all database tables and indexes."""
    _backup_db_if_needed()
    conn = get_connection()
    c = conn.cursor()

    # --- Users ---
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # Insert default user if not exists
    c.execute("INSERT OR IGNORE INTO users (id, username) VALUES (1, 'default')")

    # --- Portfolio Snapshots (master record per snapshot run) ---
    c.execute("""
        CREATE TABLE IF NOT EXISTS portfolio_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL DEFAULT 1,
            timestamp TIMESTAMP NOT NULL,
            wallet TEXT NOT NULL,
            total_value_usd REAL DEFAULT 0,
            total_tokens_usd REAL DEFAULT 0,
            total_lp_usd REAL DEFAULT 0,
            total_lending_usd REAL DEFAULT 0,
            total_hedge_collateral_usd REAL DEFAULT 0,
            status TEXT DEFAULT 'pending',
            duration_seconds REAL,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)

    # --- Token Snapshots ---
    c.execute("""
        CREATE TABLE IF NOT EXISTS token_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            snapshot_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL DEFAULT 1,
            timestamp TIMESTAMP NOT NULL,
            wallet TEXT NOT NULL,
            chain TEXT NOT NULL,
            symbol TEXT NOT NULL,
            token_address TEXT,
            balance REAL NOT NULL,
            price_usd REAL NOT NULL,
            value_usd REAL NOT NULL,
            entry_price REAL,
            FOREIGN KEY (snapshot_id) REFERENCES portfolio_snapshots(id),
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)

    # --- LP Snapshots ---
    c.execute("""
        CREATE TABLE IF NOT EXISTS lp_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            snapshot_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL DEFAULT 1,
            timestamp TIMESTAMP NOT NULL,
            wallet TEXT NOT NULL,
            chain TEXT NOT NULL,
            protocol TEXT NOT NULL,
            position_id TEXT NOT NULL,
            token0 TEXT NOT NULL,
            token1 TEXT NOT NULL,
            fee_tier REAL,
            amount0 REAL,
            amount1 REAL,
            price0_usd REAL,
            price1_usd REAL,
            value_usd REAL NOT NULL,
            range_lower REAL,
            range_upper REAL,
            current_price REAL,
            in_range BOOLEAN,
            fees_uncollected_usd REAL DEFAULT 0,
            fees_collected_usd REAL DEFAULT 0,
            total_earned_fees_usd REAL DEFAULT 0,
            daily_apr REAL,
            monthly_apr REAL,
            FOREIGN KEY (snapshot_id) REFERENCES portfolio_snapshots(id),
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)

    # --- Hedge Snapshots (GMX, Hyperliquid, etc.) ---
    c.execute("""
        CREATE TABLE IF NOT EXISTS hedge_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            snapshot_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL DEFAULT 1,
            timestamp TIMESTAMP NOT NULL,
            wallet TEXT NOT NULL,
            exchange TEXT NOT NULL,
            market TEXT NOT NULL,
            direction TEXT NOT NULL,
            size_usd REAL NOT NULL,
            collateral_usd REAL NOT NULL,
            entry_price REAL,
            current_price REAL,
            liquidation_price REAL,
            pnl_usd REAL,
            pnl_pct REAL,
            leverage REAL,
            stop_loss_price REAL,
            take_profit_price REAL,
            FOREIGN KEY (snapshot_id) REFERENCES portfolio_snapshots(id),
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)

    # --- Lending Position Snapshots (per-asset rows) ---
    c.execute("""
        CREATE TABLE IF NOT EXISTS lending_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            snapshot_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL DEFAULT 1,
            timestamp TIMESTAMP NOT NULL,
            wallet TEXT NOT NULL,
            chain TEXT NOT NULL,
            protocol TEXT NOT NULL,
            side TEXT NOT NULL,
            symbol TEXT NOT NULL,
            token_address TEXT,
            balance REAL NOT NULL,
            price_usd REAL,
            value_usd REAL,
            apy REAL,
            collateral_enabled BOOLEAN,
            is_variable BOOLEAN,
            FOREIGN KEY (snapshot_id) REFERENCES portfolio_snapshots(id),
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)

    # --- Lending Account Snapshots (health factor per wallet/chain) ---
    c.execute("""
        CREATE TABLE IF NOT EXISTS lending_account_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            snapshot_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL DEFAULT 1,
            timestamp TIMESTAMP NOT NULL,
            wallet TEXT NOT NULL,
            chain TEXT NOT NULL,
            protocol TEXT NOT NULL,
            total_collateral_usd REAL,
            total_debt_usd REAL,
            health_factor REAL,
            ltv REAL,
            liquidation_threshold REAL,
            FOREIGN KEY (snapshot_id) REFERENCES portfolio_snapshots(id),
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)

    # --- Market Snapshots (3x daily) ---
    c.execute("""
        CREATE TABLE IF NOT EXISTS market_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TIMESTAMP NOT NULL,
            session TEXT NOT NULL,
            btc_price REAL,
            eth_price REAL,
            sol_price REAL,
            tao_price REAL,
            sui_price REAL,
            btc_dominance REAL,
            eth_dominance REAL,
            total_market_cap REAL,
            total_volume_24h REAL,
            stablecoin_supply REAL,
            fear_greed_index INTEGER,
            btc_funding_rate REAL,
            eth_funding_rate REAL,
            sol_funding_rate REAL,
            btc_open_interest REAL,
            eth_open_interest REAL,
            btc_index_price REAL,
            eth_btc_ratio REAL,
            total_defi_tvl REAL,
            eth_gas_price REAL,
            eth_staking_apr REAL,
            aave_usdc_supply_apy REAL,
            aave_usdc_borrow_apy REAL,
            eth_usdc_fee_apr REAL,
            wbtc_usdc_fee_apr REAL,
            lending_rates_json TEXT,
            lp_pools_json TEXT,
            btc_vol_30d REAL,
            eth_vol_30d REAL,
            btc_return_7d REAL,
            btc_return_30d REAL,
            eth_return_7d REAL,
            eth_return_30d REAL,
            btc_range_14d REAL,
            eth_range_14d REAL
        )
    """)

    # --- Token Prices Daily ---
    c.execute("""
        CREATE TABLE IF NOT EXISTS token_prices_daily (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TIMESTAMP NOT NULL,
            symbol TEXT NOT NULL,
            price_usd REAL NOT NULL,
            high_24h REAL,
            low_24h REAL,
            volume_24h REAL,
            UNIQUE(timestamp, symbol)
        )
    """)

    # --- DeFi Rates (lending/LP rates per asset per chain) ---
    c.execute("""
        CREATE TABLE IF NOT EXISTS defi_rates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TIMESTAMP NOT NULL,
            chain TEXT NOT NULL,
            protocol TEXT NOT NULL,
            asset TEXT NOT NULL,
            rate_type TEXT NOT NULL,
            supply_apy REAL,
            borrow_apy REAL,
            fee_apr REAL,
            reward_apr REAL,
            tvl REAL,
            volume_1d REAL
        )
    """)

    # --- LP Positions (current state — both auto-detected and manual) ---
    c.execute("""
        CREATE TABLE IF NOT EXISTS lp_positions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL DEFAULT 1,
            source TEXT NOT NULL DEFAULT 'manual',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            wallet TEXT,
            chain TEXT,
            protocol TEXT,
            position_id TEXT,
            token0 TEXT,
            token1 TEXT,
            fee_tier REAL,
            amount0 REAL,
            amount1 REAL,
            price0_usd REAL,
            price1_usd REAL,
            value_usd REAL,
            entry_value_usd REAL,
            range_lower REAL,
            range_upper REAL,
            current_price REAL,
            in_range BOOLEAN,
            fees_uncollected_usd REAL DEFAULT 0,
            fees_collected_usd REAL DEFAULT 0,
            total_earned_fees_usd REAL DEFAULT 0,
            daily_apr REAL,
            monthly_apr REAL,
            notes TEXT,
            is_active BOOLEAN DEFAULT 1,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)

    # --- Hedge Positions (current state — both auto-detected and manual) ---
    c.execute("""
        CREATE TABLE IF NOT EXISTS hedge_positions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL DEFAULT 1,
            source TEXT NOT NULL DEFAULT 'manual',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            wallet TEXT,
            exchange TEXT,
            market TEXT NOT NULL,
            direction TEXT NOT NULL,
            margin_usd REAL NOT NULL,
            leverage REAL NOT NULL,
            size_usd REAL,
            entry_price REAL,
            current_price REAL,
            liquidation_price REAL,
            pnl_usd REAL DEFAULT 0,
            pnl_pct REAL DEFAULT 0,
            stop_loss_price REAL,
            take_profit_price REAL,
            notes TEXT,
            is_active BOOLEAN DEFAULT 1,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)

    # --- AI Reports ---
    c.execute("""
        CREATE TABLE IF NOT EXISTS ai_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL DEFAULT 1,
            timestamp TIMESTAMP NOT NULL,
            provider TEXT,
            model TEXT,
            market_regime_json TEXT,
            portfolio_alignment TEXT,
            summary TEXT,
            full_report_json TEXT,
            previous_recs_review_json TEXT,
            prompt_tokens INTEGER,
            completion_tokens INTEGER,
            data_freshness_json TEXT,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_ai_reports_ts ON ai_reports(user_id, timestamp)")

    # --- Daily Digest (pure DB-driven, no LLM) ---
    c.execute("""
        CREATE TABLE IF NOT EXISTS daily_digests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL DEFAULT 1,
            timestamp TIMESTAMP NOT NULL,
            total_value_usd REAL,
            value_change_24h_pct REAL,
            value_change_24h_usd REAL,
            positions_opened TEXT,
            positions_closed TEXT,
            positions_out_of_range TEXT,
            hedge_health_json TEXT,
            total_fees_usd REAL,
            average_apr REAL,
            digest_json TEXT,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_daily_digests_ts ON daily_digests(user_id, timestamp)")

    # --- Spot P&L ---
    c.execute("""
        CREATE TABLE IF NOT EXISTS spot_transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trade_date TEXT NOT NULL,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL CHECK(side IN ('buy','sell')),
            units REAL NOT NULL,
            price_usd REAL NOT NULL,
            total_usd REAL NOT NULL,
            platform TEXT DEFAULT '',
            notes TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS spot_token_config (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT UNIQUE NOT NULL,
            cg_id TEXT DEFAULT '',
            contract_address TEXT DEFAULT '',
            chain TEXT DEFAULT '',
            notes TEXT DEFAULT '',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # --- Strategy Documents ---
    c.execute("""
        CREATE TABLE IF NOT EXISTS strategy_documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT NOT NULL,
            category TEXT NOT NULL CHECK(category IN ('bear','bull','stablecoin','cashflow_other')),
            extracted_text TEXT NOT NULL,
            file_size_bytes INTEGER,
            uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            notes TEXT DEFAULT ''
        )
    """)

    # Keep old tables for backward compatibility with imports
    c.execute("""CREATE TABLE IF NOT EXISTS manual_positions (
        id INTEGER PRIMARY KEY, user_id INTEGER DEFAULT 1, created_at TIMESTAMP, updated_at TIMESTAMP,
        chain TEXT, protocol TEXT, position_id TEXT, token0 TEXT, token1 TEXT, fee_tier REAL,
        amount0 REAL, amount1 REAL, price0_usd REAL, price1_usd REAL, value_usd REAL, entry_value_usd REAL,
        range_lower REAL, range_upper REAL, current_price REAL, in_range BOOLEAN,
        fees_uncollected_usd REAL DEFAULT 0, fees_collected_usd REAL DEFAULT 0, notes TEXT, is_active BOOLEAN DEFAULT 1)""")
    c.execute("""CREATE TABLE IF NOT EXISTS manual_hedges (
        id INTEGER PRIMARY KEY, user_id INTEGER DEFAULT 1, created_at TIMESTAMP, updated_at TIMESTAMP,
        exchange TEXT, market TEXT, direction TEXT, margin_usd REAL, leverage REAL, size_usd REAL,
        entry_price REAL, current_price REAL, liquidation_price REAL, pnl_usd REAL DEFAULT 0, pnl_pct REAL DEFAULT 0,
        stop_loss_price REAL, take_profit_price REAL, notes TEXT, is_active BOOLEAN DEFAULT 1)""")

    # --- Indexes ---
    c.execute("CREATE INDEX IF NOT EXISTS idx_portfolio_snapshots_user_ts ON portfolio_snapshots(user_id, timestamp)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_portfolio_snapshots_wallet ON portfolio_snapshots(user_id, wallet, timestamp)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_token_snapshots_snap ON token_snapshots(snapshot_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_token_snapshots_user_ts ON token_snapshots(user_id, timestamp, symbol)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_lp_snapshots_snap ON lp_snapshots(snapshot_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_lp_snapshots_user_ts ON lp_snapshots(user_id, timestamp)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_hedge_snapshots_snap ON hedge_snapshots(snapshot_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_hedge_snapshots_user_ts ON hedge_snapshots(user_id, timestamp)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_lending_snapshots_snap ON lending_snapshots(snapshot_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_lending_snapshots_user_ts ON lending_snapshots(user_id, timestamp)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_lending_account_snap ON lending_account_snapshots(snapshot_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_lp_positions_active ON lp_positions(user_id, is_active)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_hedge_positions_active ON hedge_positions(user_id, is_active)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_market_snapshots_ts ON market_snapshots(timestamp)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_market_snapshots_session ON market_snapshots(session, timestamp)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_token_prices_daily_ts ON token_prices_daily(timestamp, symbol)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_defi_rates_ts ON defi_rates(timestamp, chain, protocol)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_defi_rates_asset ON defi_rates(asset, chain, timestamp)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_manual_positions_user ON manual_positions(user_id, is_active)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_spot_tx_symbol ON spot_transactions(symbol)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_spot_tx_date ON spot_transactions(trade_date)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_spot_token_cfg ON spot_token_config(symbol)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_strategy_docs_category ON strategy_documents(category)")

    # --- Migrations: add columns to existing tables ---
    migrations = [
        ("market_snapshots", "lending_rates_json", "TEXT"),
        ("market_snapshots", "lp_pools_json", "TEXT"),
        ("market_snapshots", "btc_vol_30d", "REAL"),
        ("market_snapshots", "eth_vol_30d", "REAL"),
        ("market_snapshots", "btc_return_7d", "REAL"),
        ("market_snapshots", "btc_return_30d", "REAL"),
        ("market_snapshots", "eth_return_7d", "REAL"),
        ("market_snapshots", "eth_return_30d", "REAL"),
        ("market_snapshots", "btc_range_14d", "REAL"),
        ("market_snapshots", "eth_range_14d", "REAL"),
        ("market_snapshots", "btc_200d_ma", "REAL"),
        ("lp_snapshots", "entry_value_usd", "REAL"),
        # Aerodrome staking rewards (AERO). Pending is the live earned() value;
        # claimed_total is the high-water-mark grown by snapshot delta-detection.
        ("lp_snapshots", "reward_symbol", "TEXT"),
        ("lp_snapshots", "reward_pending", "REAL"),
        ("lp_snapshots", "reward_pending_usd", "REAL"),
        ("lp_snapshots", "reward_claimed_total", "REAL"),
        ("lp_snapshots", "reward_claimed_total_usd", "REAL"),
        ("defi_rates", "volume_1d", "REAL"),
    ]
    for table, col, col_type in migrations:
        try:
            c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}")
        except Exception:
            pass  # Column already exists

    # Drop columns removed from schema (SQLite 3.35+; silently skipped on older versions)
    drop_columns = [
        ("spot_transactions", "is_opening_balance"),
    ]
    for table, col in drop_columns:
        try:
            c.execute(f"ALTER TABLE {table} DROP COLUMN {col}")
        except Exception:
            pass

    conn.commit()
    conn.close()


# --- Insert helpers ---

def create_portfolio_snapshot(wallet: str, user_id: int = 1, timestamp: str = None) -> int:
    """Create a new portfolio snapshot run. Returns snapshot_id."""
    conn = get_connection()
    c = conn.cursor()
    ts = timestamp or datetime.utcnow().isoformat()
    c.execute(
        "INSERT INTO portfolio_snapshots (user_id, timestamp, wallet, status) VALUES (?, ?, ?, 'pending')",
        (user_id, ts, wallet)
    )
    snapshot_id = c.lastrowid
    conn.commit()
    conn.close()
    return snapshot_id


def complete_portfolio_snapshot(snapshot_id: int, totals: dict, duration: float):
    """Mark a snapshot as completed with totals."""
    conn = get_connection()
    conn.execute(
        """UPDATE portfolio_snapshots SET status='completed', duration_seconds=?,
           total_value_usd=?, total_tokens_usd=?, total_lp_usd=?,
           total_lending_usd=?, total_hedge_collateral_usd=?
           WHERE id=?""",
        (duration, totals.get('total_value_usd', 0), totals.get('total_tokens_usd', 0),
         totals.get('total_lp_usd', 0), totals.get('total_lending_usd', 0),
         totals.get('total_hedge_collateral_usd', 0), snapshot_id)
    )
    conn.commit()
    conn.close()


def fail_portfolio_snapshot(snapshot_id: int, duration: float):
    """Mark a snapshot as failed."""
    conn = get_connection()
    conn.execute(
        "UPDATE portfolio_snapshots SET status='failed', duration_seconds=? WHERE id=?",
        (duration, snapshot_id)
    )
    conn.commit()
    conn.close()


def insert_token_snapshot(snapshot_id: int, data: dict, user_id: int = 1):
    """Insert a token snapshot row."""
    conn = get_connection()
    # Check for entry_price: first occurrence of this token for this user
    existing = conn.execute(
        "SELECT entry_price FROM token_snapshots WHERE user_id=? AND symbol=? AND chain=? AND entry_price IS NOT NULL LIMIT 1",
        (user_id, data['symbol'], data['chain'])
    ).fetchone()
    entry_price = existing['entry_price'] if existing else data.get('price_usd')

    conn.execute(
        """INSERT INTO token_snapshots
           (snapshot_id, user_id, timestamp, wallet, chain, symbol, token_address, balance, price_usd, value_usd, entry_price)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (snapshot_id, user_id, data['timestamp'], data['wallet'], data['chain'],
         data['symbol'], data.get('token_address'), data['balance'],
         data['price_usd'], data['value_usd'], entry_price)
    )
    conn.commit()
    conn.close()


def get_lp_fee_high_water_mark(user_id: int, position_id: str) -> float:
    """Get the highest total_earned_fees_usd ever recorded for this LP position.
    Used to prevent fee totals from decreasing after collection (especially on Base)."""
    conn = get_connection()
    row = conn.execute(
        "SELECT MAX(total_earned_fees_usd) as max_fees FROM lp_snapshots WHERE user_id=? AND position_id=?",
        (user_id, position_id)
    ).fetchone()
    conn.close()
    return row['max_fees'] if row and row['max_fees'] else 0.0


def get_lp_aero_claimed(user_id: int, position_id: str) -> float:
    """Get cumulative claimed AERO (token amount, not USD) for an LP position.

    snapshot_service.take_portfolio_snapshot grows this when the live pending
    AERO drops between snapshots (the diff was claimed). Returns 0 for new
    positions.
    """
    conn = get_connection()
    row = conn.execute(
        "SELECT MAX(reward_claimed_total) as claimed FROM lp_snapshots WHERE user_id=? AND position_id=?",
        (user_id, position_id)
    ).fetchone()
    conn.close()
    return row['claimed'] if row and row['claimed'] else 0.0


def insert_lp_snapshot(snapshot_id: int, data: dict, user_id: int = 1):
    """Insert an LP position snapshot row."""
    conn = get_connection()
    conn.execute(
        """INSERT INTO lp_snapshots
           (snapshot_id, user_id, timestamp, wallet, chain, protocol, position_id,
            token0, token1, fee_tier, amount0, amount1, price0_usd, price1_usd, value_usd,
            entry_value_usd,
            range_lower, range_upper, current_price, in_range,
            fees_uncollected_usd, fees_collected_usd, total_earned_fees_usd,
            daily_apr, monthly_apr,
            reward_symbol, reward_pending, reward_pending_usd,
            reward_claimed_total, reward_claimed_total_usd)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                   ?, ?, ?, ?, ?)""",
        (snapshot_id, user_id, data['timestamp'], data['wallet'], data['chain'],
         data['protocol'], data['position_id'],
         data['token0'], data['token1'], data.get('fee_tier'),
         data.get('amount0'), data.get('amount1'),
         data.get('price0_usd'), data.get('price1_usd'), data['value_usd'],
         data.get('entry_value_usd'),
         data.get('range_lower'), data.get('range_upper'),
         data.get('current_price'), data.get('in_range'),
         data.get('fees_uncollected_usd', 0), data.get('fees_collected_usd', 0),
         data.get('total_earned_fees_usd', 0),
         data.get('daily_apr'), data.get('monthly_apr'),
         data.get('reward_symbol'), data.get('reward_pending'),
         data.get('reward_pending_usd'),
         data.get('reward_claimed_total'), data.get('reward_claimed_total_usd'))
    )
    conn.commit()
    conn.close()


def insert_hedge_snapshot(snapshot_id: int, data: dict, user_id: int = 1):
    """Insert a hedge position snapshot row."""
    conn = get_connection()
    conn.execute(
        """INSERT INTO hedge_snapshots
           (snapshot_id, user_id, timestamp, wallet, exchange, market, direction,
            size_usd, collateral_usd, entry_price, current_price, liquidation_price,
            pnl_usd, pnl_pct, leverage, stop_loss_price, take_profit_price)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (snapshot_id, user_id, data['timestamp'], data['wallet'], data['exchange'],
         data['market'], data['direction'], data['size_usd'], data['collateral_usd'],
         data.get('entry_price'), data.get('current_price'), data.get('liquidation_price'),
         data.get('pnl_usd'), data.get('pnl_pct'), data.get('leverage'),
         data.get('stop_loss_price'), data.get('take_profit_price'))
    )
    conn.commit()
    conn.close()


def insert_lending_snapshot(snapshot_id: int, data: dict, user_id: int = 1):
    """Insert a lending position snapshot row (one per supplied/borrowed asset)."""
    conn = get_connection()
    conn.execute(
        """INSERT INTO lending_snapshots
           (snapshot_id, user_id, timestamp, wallet, chain, protocol, side,
            symbol, token_address, balance, price_usd, value_usd, apy,
            collateral_enabled, is_variable)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (snapshot_id, user_id, data['timestamp'], data['wallet'], data['chain'],
         data['protocol'], data['side'], data['symbol'], data.get('token_address'),
         data['balance'], data.get('price_usd'), data.get('value_usd'),
         data.get('apy'), data.get('collateral_enabled'), data.get('is_variable'))
    )
    conn.commit()
    conn.close()


def insert_lending_account_snapshot(snapshot_id: int, data: dict, user_id: int = 1):
    """Insert a lending account summary snapshot."""
    conn = get_connection()
    conn.execute(
        """INSERT INTO lending_account_snapshots
           (snapshot_id, user_id, timestamp, wallet, chain, protocol,
            total_collateral_usd, total_debt_usd, health_factor, ltv, liquidation_threshold)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (snapshot_id, user_id, data['timestamp'], data['wallet'], data['chain'],
         data['protocol'], data.get('total_collateral_usd'), data.get('total_debt_usd'),
         data.get('health_factor'), data.get('ltv'), data.get('liquidation_threshold'))
    )
    conn.commit()
    conn.close()


def insert_market_snapshot(data: dict):
    """Insert a market data snapshot."""
    conn = get_connection()
    conn.execute(
        """INSERT INTO market_snapshots
           (timestamp, session, btc_price, eth_price, sol_price, tao_price, sui_price,
            btc_dominance, eth_dominance, total_market_cap, total_volume_24h,
            stablecoin_supply, fear_greed_index,
            btc_funding_rate, eth_funding_rate, sol_funding_rate,
            btc_open_interest, eth_open_interest, btc_index_price, eth_btc_ratio,
            total_defi_tvl, eth_gas_price, eth_staking_apr,
            aave_usdc_supply_apy, aave_usdc_borrow_apy,
            eth_usdc_fee_apr, wbtc_usdc_fee_apr,
            lending_rates_json, lp_pools_json,
            btc_vol_30d, eth_vol_30d,
            btc_return_7d, btc_return_30d, eth_return_7d, eth_return_30d,
            btc_range_14d, eth_range_14d, btc_200d_ma)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (data['timestamp'], data['session'],
         data.get('btc_price'), data.get('eth_price'), data.get('sol_price'),
         data.get('tao_price'), data.get('sui_price'),
         data.get('btc_dominance'), data.get('eth_dominance'),
         data.get('total_market_cap'), data.get('total_volume_24h'),
         data.get('stablecoin_supply'), data.get('fear_greed_index'),
         data.get('btc_funding_rate'), data.get('eth_funding_rate'), data.get('sol_funding_rate'),
         data.get('btc_open_interest'), data.get('eth_open_interest'),
         data.get('btc_index_price'), data.get('eth_btc_ratio'),
         data.get('total_defi_tvl'), data.get('eth_gas_price'), data.get('eth_staking_apr'),
         data.get('aave_usdc_supply_apy'), data.get('aave_usdc_borrow_apy'),
         data.get('eth_usdc_fee_apr'), data.get('wbtc_usdc_fee_apr'),
         data.get('lending_rates_json'), data.get('lp_pools_json'),
         data.get('btc_vol_30d'), data.get('eth_vol_30d'),
         data.get('btc_return_7d'), data.get('btc_return_30d'),
         data.get('eth_return_7d'), data.get('eth_return_30d'),
         data.get('btc_range_14d'), data.get('eth_range_14d'),
         data.get('btc_200d_ma'))
    )
    conn.commit()
    conn.close()


def insert_defi_rates(timestamp: str, rates: list):
    """Insert DeFi lending/LP rate rows. Each item: {chain, protocol, asset, rate_type, supply_apy, borrow_apy, fee_apr, reward_apr, tvl}."""
    if not rates:
        return
    conn = get_connection()
    for r in rates:
        conn.execute(
            """INSERT INTO defi_rates (timestamp, chain, protocol, asset, rate_type, supply_apy, borrow_apy, fee_apr, reward_apr, tvl, volume_1d)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (timestamp, r.get('chain', ''), r.get('protocol', ''), r.get('asset', ''),
             r.get('rate_type', 'lending'),
             r.get('supply_apy'), r.get('borrow_apy'),
             r.get('fee_apr'), r.get('reward_apr'), r.get('tvl'), r.get('volume_1d'))
        )
    conn.commit()
    conn.close()



def insert_token_price_daily(data: dict):
    """Insert or update a daily token price."""
    conn = get_connection()
    conn.execute(
        """INSERT OR REPLACE INTO token_prices_daily
           (timestamp, symbol, price_usd, high_24h, low_24h, volume_24h)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (data['timestamp'], data['symbol'], data['price_usd'],
         data.get('high_24h'), data.get('low_24h'), data.get('volume_24h'))
    )
    conn.commit()
    conn.close()


# --- Query helpers ---

def get_portfolio_timeseries(user_id: int = 1, days: int = 30, wallet: str = None) -> list:
    """Get portfolio value timeseries."""
    conn = get_connection()
    query = "SELECT * FROM portfolio_snapshots WHERE user_id=? AND status='completed'"
    params = [user_id]
    if wallet:
        query += " AND wallet=?"
        params.append(wallet)
    if days < 9999:
        query += f" AND timestamp >= datetime('now', '-{days} days')"
    query += " ORDER BY timestamp ASC"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_market_timeseries(days: int = 30) -> list:
    """Get market data timeseries."""
    conn = get_connection()
    query = "SELECT * FROM market_snapshots"
    if days < 9999:
        query += f" WHERE timestamp >= datetime('now', '-{days} days')"
    query += " ORDER BY timestamp ASC"
    rows = conn.execute(query).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_token_price_history(symbol: str, days: int = 30) -> list:
    """Get daily price history for a token."""
    conn = get_connection()
    query = "SELECT * FROM token_prices_daily WHERE symbol=?"
    params = [symbol]
    if days < 9999:
        query += f" AND timestamp >= datetime('now', '-{days} days')"
    query += " ORDER BY timestamp ASC"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]
