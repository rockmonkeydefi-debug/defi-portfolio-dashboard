"""MaxFi LP position tracking schema — Phase C.

New tables only; no existing table is touched. `id` (AUTOINCREMENT) is the
identity for a MaxFi position row, not token_id: token_id changes on every
rebalance (Phase A/A.1 finding) so it can never be a stable key.
"""

import logging
import sqlite3

logger = logging.getLogger(__name__)

# maxfi_initial_value.source recognised values (Phase D.3.2a). Registration
# only - the column is plain TEXT with no CHECK constraint, and no existing
# call site is changed to reference this constant (web_portfolio.py's
# /initial-value route keeps its own hardcoded 'manual_override' literals).
# This exists so a future write path (D.3.2b) has one place to point at
# rather than inventing another bare string. 'ambiguity_auto_split' is not
# written by any code as of this phase - it is registered ahead of the write
# path that will use it, same pattern as MAXFI_ANCHOR_REGISTRY_DEFAULTS was
# seeded ahead of the anchor-registry UI in Phase D.1.
KNOWN_INITIAL_VALUE_SOURCES = {
    "manual_override",      # existing - a human set this via the /initial-value route
    "ambiguity_auto_split",  # Phase D.3.2b - auto-split on a resolved 2-vs-2 ambiguity
}

# Phase D.3.2b: the exact partial UNIQUE index DDL that
# GET /api/maxfi/index-precheck validated against live data BEFORE this was
# ever executed. Defined once, here, and imported by both the precheck
# endpoint and ensure_maxfi_tables() below so the statement that was
# checked and the statement that actually runs can never drift into two
# separately-typed strings that only happen to match today.
MAXFI_OPEN_IDENTITY_INDEX_SQL = (
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_maxfi_positions_open_identity "
    "ON maxfi_positions(chain, wallet, token_id) WHERE status = 'open'"
)


def ensure_maxfi_tables(db_connection):
    """CREATE TABLE IF NOT EXISTS for all three MaxFi tables, plus (Phase
    D.3.2b) a notes column on maxfi_positions and the open-identity unique
    index the auto-split write path depends on. Idempotent - safe to call
    on every app startup or before every MaxFi route.

    Returns {"unique_index_ready": bool, "notes_column_ready": bool} - both
    True on the clean/idempotent-repeat path. This is additive: every
    existing call site ignores the return value today and keeps working
    unchanged.

    The ALTER TABLE and the CREATE UNIQUE INDEX are each wrapped
    individually rather than left to raise: this function runs at the top
    of EVERY MaxFi route, so an uncaught exception here would be a total
    feature outage across all of MaxFi, not a degraded single feature.
    maxfi_orchestration.resolve_ambiguous_auto_splits refuses to run at all
    when unique_index_ready is not True - see that function's first guard.
    """
    c = db_connection.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS maxfi_positions (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          chain TEXT NOT NULL,
          wallet TEXT NOT NULL,
          token_id TEXT NOT NULL,
          array_index INTEGER NOT NULL,
          pool_address TEXT NOT NULL,
          token0_address TEXT NOT NULL,
          token1_address TEXT NOT NULL,
          fee_tier INTEGER NOT NULL,
          status TEXT NOT NULL DEFAULT 'open',
          first_seen_at TEXT NOT NULL,
          first_seen_at_source TEXT NOT NULL,
          first_seen_block TEXT,
          last_scan_at TEXT NOT NULL,
          closed_at TEXT
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS maxfi_initial_value (
          position_id INTEGER PRIMARY KEY REFERENCES maxfi_positions(id),
          source TEXT NOT NULL,
          initial_value_usd REAL,
          set_at TEXT NOT NULL,
          set_by TEXT NOT NULL
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS maxfi_strategy_labels (
          position_id INTEGER PRIMARY KEY REFERENCES maxfi_positions(id),
          label TEXT NOT NULL,
          set_at TEXT NOT NULL
        )
    """)

    # Phase D.3.2b: notes column - provenance for an auto-split position
    # (e.g. a discarded basis value with nowhere else to be recorded - see
    # maxfi_orchestration.resolve_ambiguous_auto_splits). Deliberately
    # STRICTER than src/storage/portfolio_db.py's init_db() bare
    # `except Exception: pass` idiom: that pattern would silently swallow
    # a typo'd column type forever. Here, only the expected "column
    # already exists" repeat case is treated as success; anything else is
    # logged and reported via the return value.
    notes_column_ready = True
    try:
        c.execute("ALTER TABLE maxfi_positions ADD COLUMN notes TEXT")
    except sqlite3.OperationalError as e:
        if "duplicate column" in str(e).lower():
            pass  # expected repeat case - column already exists
        else:
            logger.warning(f"[maxfi schema] notes column migration failed: {e}")
            notes_column_ready = False

    # Phase D.3.2b: the open-identity uniqueness guarantee the auto-split
    # write path depends on to make a double-open structurally impossible
    # rather than merely unlikely. A failure here (e.g. live data actually
    # violates it, despite the precheck) means that guarantee does not
    # exist - logged as an ERROR, not a warning, since a caller depends on
    # this to decide whether it's safe to auto-resolve anything at all.
    unique_index_ready = True
    try:
        c.execute(MAXFI_OPEN_IDENTITY_INDEX_SQL)
    except Exception as e:
        logger.error(f"[maxfi schema] unique index creation failed: {e}")
        unique_index_ready = False

    db_connection.commit()

    return {"unique_index_ready": unique_index_ready, "notes_column_ready": notes_column_ready}
