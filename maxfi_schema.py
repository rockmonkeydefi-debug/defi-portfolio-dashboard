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

# maxfi_positions.open_token_price_source recognised values (Token Δ column,
# commit 1 of 3; extended by the GeckoTerminal backfill workstream, commit 1
# of 3). Registration only - the column is plain TEXT with no CHECK
# constraint, and no call site is changed by this commit (the write path is
# a future commit, at the end of the valuation route). 'recorded' means the
# price was captured within an hour of first_seen_at; 'seeded' means it was
# back-filled from the first observation after this feature shipped;
# 'backfilled' means the open price was replaced with the GeckoTerminal
# historical candle at the row's first_seen_at - the backfill write path
# (a later commit) may overwrite 'seeded' rows ONLY; 'recorded' rows are
# never overwritten by anything. Same pattern/rationale as
# KNOWN_INITIAL_VALUE_SOURCES above - one place to point at rather than
# inventing bare strings at the write site.
KNOWN_OPEN_TOKEN_PRICE_SOURCES = {"recorded", "seeded", "backfilled"}

# maxfi_token_price_stats.ath_source recognised values (GeckoTerminal
# backfill workstream, commit 1 of 3). Registration only, same pattern as
# KNOWN_OPEN_TOKEN_PRICE_SOURCES above - no CHECK constraint, no call site
# changed by this commit. 'observed' means the ATH's coverage window is
# whatever this app has itself tracked since the row was first written;
# 'backfilled' means GeckoTerminal's own pool-history candles have been
# incorporated, extending that coverage further into the past. The backfill
# route (a later commit) is the only writer of 'backfilled'.
KNOWN_ATH_SOURCES = {"observed", "backfilled"}

# maxfi_position_user_data.closing_value_source recognised values (MaxFi
# closing-value capture, commit 1 of 4). Registration only, same pattern as
# KNOWN_ATH_SOURCES above - no CHECK constraint, no call site changed by
# this commit. 'auto_last_observed' means closing_value_usd was seeded at
# close time from maxfi_positions.last_value_usd (the rolling
# last-observed valuation); 'manual' means a human entered it via the
# /user-data route. NULL means the row predates provenance tracking -
# readers treat NULL as manual-equivalent (no badge), never as a third
# distinct state. The close paths and the /user-data route (later
# commits) are the only writers.
KNOWN_CLOSING_VALUE_SOURCES = {"auto_last_observed", "manual"}

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

# LP Advisor Phase A2: 35 daily closes covers the 30d trend window plus
# slack. Referenced here (not just in the write path) so the schema's
# comment and the Phase B writer's pruning logic can never drift onto two
# separately-typed numbers.
MAXFI_TOKEN_DAILY_MAX_ROWS = 35


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

    # Token Δ column (commit 1 of 3: schema only). One compact row per
    # (chain, token address) for the volatile side of a MaxFi pool. `address`
    # is ALWAYS stored lowercased, matching the maxfi_token_symbols
    # convention above - maxfi_positions.token0_address/token1_address are
    # NOT normalized on write, so a raw-cased key here would silently miss.
    # ath_price_usd is "since tracking began" (first observation forward at
    # writer time), never a true lifetime ATH - that would require a future
    # historical-backfill upgrade this commit does not attempt. No unbounded
    # price history is kept anywhere; this table is the entire record -
    # except for maxfi_token_daily below (LP Advisor Phase A2), the single
    # sanctioned exception: a bounded rolling window of
    # MAXFI_TOKEN_DAILY_MAX_ROWS daily closes per token, pruned on every
    # write, still never unbounded.
    c.execute("""
        CREATE TABLE IF NOT EXISTS maxfi_token_price_stats (
          chain             TEXT NOT NULL,
          address           TEXT NOT NULL,
          symbol            TEXT,
          last_price_usd    REAL NOT NULL,
          last_price_at     TEXT NOT NULL,
          ath_price_usd     REAL NOT NULL,
          ath_at            TEXT NOT NULL,
          first_recorded_at TEXT NOT NULL,
          PRIMARY KEY (chain, address)
        )
    """)

    # LP Advisor Phase A2 - the live MaxFi pool catalogue, enumerated
    # on-chain from NPM position NFTs custodied by the vault (see
    # maxfi_client.enumerate_owner_token_ids / decode_positions_and_pools);
    # refreshed by a budgeted resumable route (Phase B). first_seen_at is
    # INSERT-only per the house invariant - zero UPDATE sites, matching
    # maxfi_positions.first_seen_at. All address columns stored lowercased
    # by the write route.
    c.execute("""
        CREATE TABLE IF NOT EXISTS maxfi_catalogue_pools (
          chain               TEXT NOT NULL,
          pool_address        TEXT NOT NULL,
          token0_address      TEXT NOT NULL,
          token1_address      TEXT NOT NULL,
          token0_symbol       TEXT,
          token1_symbol       TEXT,
          fee_tier            INTEGER NOT NULL,
          position_count      INTEGER NOT NULL,
          first_seen_at       TEXT NOT NULL,
          last_seen_at        TEXT NOT NULL,
          last_enumerated_at  TEXT NOT NULL,
          PRIMARY KEY (chain, pool_address)
        )
    """)

    # LP Advisor Phase A2 - DexScreener market snapshot per catalogue pool.
    # OVERWRITE-ALWAYS by design (deliberate contrast to write-once open
    # prices - same rationale as _maxfi_persist_last_values in
    # web_portfolio.py: a snapshot's only value is being current). Metric
    # columns are nullable because DexScreener omits fields on thin pairs.
    # fetched_at is the staleness gate every consumer must surface.
    c.execute("""
        CREATE TABLE IF NOT EXISTS maxfi_pool_metrics (
          chain             TEXT NOT NULL,
          pool_address      TEXT NOT NULL,
          price_usd         REAL,
          liquidity_usd     REAL,
          volume_h24        REAL,
          volume_h6         REAL,
          volume_h1         REAL,
          price_change_h24  REAL,
          fetched_at        TEXT NOT NULL,
          PRIMARY KEY (chain, pool_address)
        )
    """)

    # LP Advisor Phase A2 - one close price per token per UTC day, sourced
    # from GeckoTerminal daily candles via the token's deepest catalogue
    # pool, feeding 7d/30d trend + downtrend-gate math. BOUNDED BY CONTRACT
    # to MAXFI_TOKEN_DAILY_MAX_ROWS rows per (chain, address) - the Phase B
    # write path prunes oldest-beyond-bound in the same transaction as every
    # insert, keeping this table a rolling window, never an archive.
    c.execute("""
        CREATE TABLE IF NOT EXISTS maxfi_token_daily (
          chain                TEXT NOT NULL,
          address              TEXT NOT NULL,
          date                 TEXT NOT NULL,
          close_usd            REAL NOT NULL,
          source_pool_address  TEXT,
          fetched_at           TEXT NOT NULL,
          PRIMARY KEY (chain, address, date)
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

    # Token Δ column (commit 1 of 3: schema only). Per-row USD price of the
    # pool's volatile token at position open. WRITE-ONCE, same spirit as
    # first_seen_at: populated exactly one time - source 'recorded' when
    # captured within an hour of first_seen_at, 'seeded' when back-filled
    # from the first observation after this feature shipped - then never
    # overwritten. A future historical-backfill upgrade may, by explicit
    # design decision at that time, be permitted to overwrite 'seeded'
    # values only. Not included in the returned status dict, same reasoning
    # as closed_by above. The write path (valuation route, a later commit)
    # enforces write-once in SQL via WHERE open_token_price_usd IS NULL.
    try:
        c.execute("ALTER TABLE maxfi_positions ADD COLUMN open_token_price_usd REAL")
    except sqlite3.OperationalError as e:
        if "duplicate column" in str(e).lower():
            pass  # expected repeat case - column already exists
        else:
            logger.warning(f"[maxfi schema] open_token_price_usd column migration failed: {e}")

    try:
        c.execute("ALTER TABLE maxfi_positions ADD COLUMN open_token_price_source TEXT")
    except sqlite3.OperationalError as e:
        if "duplicate column" in str(e).lower():
            pass  # expected repeat case - column already exists
        else:
            logger.warning(f"[maxfi schema] open_token_price_source column migration failed: {e}")

    # GeckoTerminal backfill workstream (commit 1 of 3): ath_source
    # provenance on maxfi_token_price_stats. DEFAULT 'observed' does double
    # duty - SQLite reports the default for rows that predate this column
    # (a row written before this migration ran), and the live valuation
    # upsert (which deliberately never names this column, so its
    # ON CONFLICT update can never clobber provenance) gets 'observed'
    # stamped on every fresh INSERT for free. The backfill route (a later
    # commit) is the only writer of 'backfilled'. Not included in the
    # returned status dict, same reasoning as closed_by above.
    try:
        c.execute("ALTER TABLE maxfi_token_price_stats ADD COLUMN ath_source TEXT DEFAULT 'observed'")
    except sqlite3.OperationalError as e:
        if "duplicate column" in str(e).lower():
            pass  # expected repeat case - column already exists
        else:
            logger.warning(f"[maxfi schema] ath_source column migration failed: {e}")

    # MaxFi closing-value capture (commit 1 of 4): last_value_usd is a
    # rolling last-observed USD value for an OPEN position, written by the
    # valuation route on every cycle (a later commit). Deliberately
    # OVERWRITE-ALWAYS, NOT write-once like open_token_price_usd above - it
    # is a snapshot of "what was this worth last time we priced it," so
    # each new valuation cycle is expected to replace the prior figure
    # rather than protect it. Not included in the returned status dict,
    # same reasoning as closed_by above.
    try:
        c.execute("ALTER TABLE maxfi_positions ADD COLUMN last_value_usd REAL")
    except sqlite3.OperationalError as e:
        if "duplicate column" in str(e).lower():
            pass  # expected repeat case - column already exists
        else:
            logger.warning(f"[maxfi schema] last_value_usd column migration failed: {e}")

    # MaxFi closing-value capture (commit 1 of 4): ISO-8601 UTC timestamp of
    # the last_value_usd snapshot above - same overwrite-always contract,
    # same writer (the valuation route, a later commit).
    try:
        c.execute("ALTER TABLE maxfi_positions ADD COLUMN last_value_at TEXT")
    except sqlite3.OperationalError as e:
        if "duplicate column" in str(e).lower():
            pass  # expected repeat case - column already exists
        else:
            logger.warning(f"[maxfi schema] last_value_at column migration failed: {e}")

    # C1.1: uncollected fees persisted at valuation time (commit 1 of 2:
    # schema only) — written by _maxfi_persist_last_values in commit 2
    try:
        c.execute("ALTER TABLE maxfi_positions ADD COLUMN last_uncollected_usd REAL")
    except sqlite3.OperationalError as e:
        if "duplicate column" in str(e).lower():
            pass  # expected repeat case - column already exists
        else:
            logger.warning(f"[maxfi schema] last_uncollected_usd column migration failed: {e}")

    # C1.2 (commit 1 of 2: schema only): last_rebalanced_at is the UTC
    # timestamp of the most recent in-place rebalance (the REBALANCED
    # branch's re-mint, run_scan_and_persist in maxfi_orchestration.py) -
    # NULL means never rebalanced since this column landed. Written by the
    # scan path only, in commit 2 of 2 - nothing writes it yet.
    try:
        c.execute("ALTER TABLE maxfi_positions ADD COLUMN last_rebalanced_at TEXT")
    except sqlite3.OperationalError as e:
        if "duplicate column" in str(e).lower():
            pass  # expected repeat case - column already exists
        else:
            logger.warning(f"[maxfi schema] last_rebalanced_at column migration failed: {e}")

    # MaxFi closing-value capture (commit 1 of 4): provenance for
    # maxfi_position_user_data.closing_value_usd - see
    # KNOWN_CLOSING_VALUE_SOURCES above for the two known values and the
    # NULL-means-pre-provenance rule. The close paths and the /user-data
    # route (later commits) are the only writers. Not included in the
    # returned status dict, same reasoning as closed_by above.
    try:
        c.execute("ALTER TABLE maxfi_position_user_data ADD COLUMN closing_value_source TEXT")
    except sqlite3.OperationalError as e:
        if "duplicate column" in str(e).lower():
            pass  # expected repeat case - column already exists
        else:
            logger.warning(f"[maxfi schema] closing_value_source column migration failed: {e}")

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
