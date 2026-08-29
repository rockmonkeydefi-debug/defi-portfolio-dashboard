"""MaxFi LP position tracking schema — Phase C.

New tables only; no existing table is touched. `id` (AUTOINCREMENT) is the
identity for a MaxFi position row, not token_id: token_id changes on every
rebalance (Phase A/A.1 finding) so it can never be a stable key.
"""

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
    "ambiguity_auto_split",  # Phase D.3.2b (future) - auto-split on a resolved 2-vs-2 ambiguity
}


def ensure_maxfi_tables(db_connection):
    """CREATE TABLE IF NOT EXISTS for all three MaxFi tables. Idempotent —
    safe to call on every app startup or before every scan."""
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

    db_connection.commit()
