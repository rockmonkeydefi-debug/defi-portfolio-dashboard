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

    # Phase D.4 (Block B): durable cache for api_maxfi_token_census's
    # decimals()/symbol() results — that endpoint's own _maxfi_token_metadata_cache
    # is a plain in-process dict, wiped on every worker restart/deploy, so a
    # resolved symbol had to be re-fetched from chain after every deploy.
    # `address` is ALWAYS stored lowercased (positions.token0_address/
    # token1_address are NOT normalized on write — see maxfi_matching.py's
    # comparison-time .lower() calls — so a cache keyed on raw casing would
    # silently miss and re-fetch forever). Row semantics:
    #   row absent                     - never attempted
    #   row present, symbol NOT NULL   - resolved, never re-fetch
    #   row present, symbol IS NULL    - attempted and failed, eligible for retry
    # decimals is stored alongside because the census already fetches it in
    # the same Multicall3 batch as symbol - storing it costs nothing and saves
    # a round trip if a later feature needs it. Nothing in this phase reads it.
    c.execute("""
        CREATE TABLE IF NOT EXISTS maxfi_token_symbols (
          chain TEXT NOT NULL,
          address TEXT NOT NULL,
          symbol TEXT,
          decimals INTEGER,
          last_attempt_at TEXT NOT NULL,
          PRIMARY KEY (chain, address)
        )
    """)

    # User-entered closing value and free-text notes for a position. Both
    # payload columns are nullable so either may exist alone (a note with no
    # closing value yet, or vice versa). Deliberately separate from
    # maxfi_positions.notes, which is owned whole by the auto-split writer
    # (a single JSON blob written once at INSERT time, never patched) - this
    # table is the human-editable counterpart, not a second writer for that
    # column.
    c.execute("""
        CREATE TABLE IF NOT EXISTS maxfi_position_user_data (
          position_id INTEGER PRIMARY KEY REFERENCES maxfi_positions(id),
          closing_value_usd REAL,
          user_note TEXT,
          set_at TEXT NOT NULL,
          set_by TEXT NOT NULL
        )
    """)

    # Asset class is a property of the POOL, not of any one position - the
    # same pool is re-entered repeatedly (a fresh position each time), so
    # this is keyed on (chain, pool_address) rather than position_id.
    # pool_address is stored already-lowercased by the future write route;
    # readers apply LOWER() on the maxfi_positions side only, matching the
    # maxfi_token_symbols convention.
    c.execute("""
        CREATE TABLE IF NOT EXISTS maxfi_pool_meta (
          chain TEXT NOT NULL,
          pool_address TEXT NOT NULL,
          asset_class TEXT NOT NULL CHECK (asset_class IN ('crypto', 'stock')),
          set_at TEXT NOT NULL,
          set_by TEXT NOT NULL,
          PRIMARY KEY (chain, pool_address)
        )
    """)

    # One row per fee claim lot - fees swept from an LP position to the
    # wallet, then sold. position_id references maxfi_positions.id but
    # declares no FK/REFERENCES clause here - unlike maxfi_initial_value,
    # maxfi_strategy_labels and maxfi_position_user_data, which DO declare
    # an inline `REFERENCES maxfi_positions(id)` on their position_id column.
    # This table and maxfi_position_lineage below stay on the plain-column
    # side of that existing split deliberately: referential integrity for
    # both is by discipline, not enforcement.
    #
    # claimed_at is the date fee tokens were swept to the wallet. sold_at and
    # proceeds_usd are the later disposal and are NULL until the sale is
    # recorded, so a swept-but-unsold claim is representable. token0/token1
    # symbol and amount are captured at claim time even though nothing
    # displays them yet, because they cannot be reconstructed later.
    #
    # There is deliberately NO unique constraint: two identical claims on one
    # position on one day are legitimate and must both survive. Identity is
    # the AUTOINCREMENT id and nothing else.
    #
    # proceeds_usd will accept 0 and reject negative at the route layer when
    # that route exists, matching maxfi_position_user_data.closing_value_usd's
    # rule - NOT maxfi_initial_value's <= 0 rule. Do not harmonize them.
    c.execute("""
        CREATE TABLE IF NOT EXISTS maxfi_claims (
          id             INTEGER PRIMARY KEY AUTOINCREMENT,
          position_id    INTEGER NOT NULL,
          claimed_at     TEXT NOT NULL,
          token0_symbol  TEXT,
          token0_amount  REAL,
          token1_symbol  TEXT,
          token1_amount  REAL,
          sold_at        TEXT,
          proceeds_usd   REAL,
          note           TEXT,
          set_at         TEXT NOT NULL,
          set_by         TEXT NOT NULL
        )
    """)

    # An auto-split closes two departing rows and opens two arriving rows for
    # the same economic positions. The departing row's primary key is
    # retained NOWHERE today, so this table is the only record of the
    # succession.
    #
    # decide_ambiguity_resolution deliberately makes NO claim about which
    # departing row became which arriving row - see
    # maxfi_math.split_basis_proportional's own docstring. So a lineage row
    # records that a departing row was succeeded by
    # an arriving row within one split group; it does NOT assert a 1:1
    # pairing. split_group_id groups the rows written by one auto-split
    # resolution.
    #
    # arriving_current_value_usd stores each arriving row's current value AS
    # OBSERVED AT THE SPLIT. It exists so a later read can call
    # maxfi_math.split_basis_proportional(total, [v0, v1]) with these values -
    # the same cents-exact function basis already uses. A pre-computed ratio
    # or frozen amount is deliberately NOT stored: claims will be entered
    # retroactively against rows that were already split, and a frozen figure
    # cannot see a claim that did not exist yet.
    #
    # No FK, no unique constraint, no index - same reasons as maxfi_claims.
    c.execute("""
        CREATE TABLE IF NOT EXISTS maxfi_position_lineage (
          id                         INTEGER PRIMARY KEY AUTOINCREMENT,
          departing_position_id      INTEGER NOT NULL,
          arriving_position_id       INTEGER NOT NULL,
          split_group_id             TEXT NOT NULL,
          arriving_current_value_usd REAL NOT NULL,
          created_at                 TEXT NOT NULL
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

    # Block C1: closed_by column - provenance for a closed row. NULL means
    # closed by a scan (run_scan_and_persist / resolve_ambiguous_auto_splits,
    # neither of which is changed by this phase - they keep writing NULL) or
    # still open; 'manual_ui' means closed via the manual close route. Not
    # included in the returned status dict - deliberately, since that dict is
    # read by resolve_ambiguous_auto_splits's money-path guard and widening it
    # is not worth the risk for a column nothing there depends on.
    try:
        c.execute("ALTER TABLE maxfi_positions ADD COLUMN closed_by TEXT")
    except sqlite3.OperationalError as e:
        if "duplicate column" in str(e).lower():
            pass  # expected repeat case - column already exists
        else:
            logger.warning(f"[maxfi schema] closed_by column migration failed: {e}")

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
