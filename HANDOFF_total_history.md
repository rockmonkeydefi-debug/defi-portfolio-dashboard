# HANDOFF — Snapshot history for the complete total

Workstream opened Sep 27, 2026. Backend only. Implements backlog item 1 of HANDOFF_total_portfolio_value.md.

## Goal

GET /api/portfolio/total (portfolio_total.compose_total) was live-only: portfolio_snapshots.total_value_usd excludes Hyperliquid and MaxFi uncollected fees, so no history of the complete total existed. Every snapshot run now also stores compose_total's result in a new table, one row per run. No displayed number changes.

## Rulings (Glenn, Sep 27)

1. New table portfolio_total_snapshots, one row per snapshot run: the total and each part as columns, per-part as-of, the run's old snapshot total beside it, a definition version, and the full compose_total output as JSON.
2. The row is composed inside take_portfolio_snapshot through an optional injected composer. The route and the snapshot share one extracted input helper.
3. Hyperliquid at snapshot time: use the cache if it is under 15 min old; otherwise refresh inline (or wait up to 60 s for a refresh already in flight); if there is still no data, write the row with hl_counted = 0.
4. MaxFi uncollected fees: as they are (headline parity); the oldest as-of is recorded.
5. Every snapshot run that is not skipped writes a row; its status mirrors the run (completed / partial); readers filter. usable = status 'completed' AND hl_counted = 1.
6. Landing-day step: the old snapshot total and a definition_version go on every row. No backfill in this work (a Hyperliquid-history backfill is a separate follow-up).
7. New read-only GET /api/history/portfolio-total. /api/history/portfolio-chart and every other existing reader stay untouched.

## The table: portfolio_total_snapshots

Created by init_db (CREATE TABLE IF NOT EXISTS; index idx_portfolio_total_snapshots_user_ts on (user_id, timestamp)). Columns:

- id, user_id
- timestamp — the run's ts string verbatim; equals that run's portfolio_snapshots.timestamp.
- status — 'completed' | 'partial' (mirrors the run) | 'failed' (the composer raised or did not answer status 'ok').
- definition_version — PORTFOLIO_TOTAL_DEFINITION_VERSION (src/engines/snapshot_service.py).
- total_usd — compose_total total_usd; NULL when failed.
- snapshot_total_usd — the sum of this run's completed portfolio_snapshots.total_value_usd (the old headline definition).
- wallets_total, wallets_completed
- hl_counted — 1 when the Hyperliquid part was counted.
- wallet_tokens_usd, stablecoins_usd, maxfi_lp_usd, other_lp_usd, lp_uncollected_usd, maxfi_uncollected_usd, hyperliquid_usd, lending_net_usd, gmx_usd, zerion_staking_usd — each compose_total component's value_usd (NULL when failed or missing). zerion_staking is reported, never counted.
- portfolio_as_of, hyperliquid_as_of, maxfi_values_oldest — compose_total's as_of.
- warning_count
- detail_json — the full compose_total output.
- error, duration_seconds

Usable rule: status = 'completed' AND hl_counted = 1. The read route returns every row with a "usable" flag; readers filter.

Definition version 1 = the definition on main at bfb9b7a (PR #170: perp counted only for standard-mode Hyperliquid accounts; unified / portfolio-margin accounts count spot only).

## Where the row is written

take_portfolio_snapshot(get_portfolio_data_fn, wallets, user_id=1, compose_total_fn=None), after the wallet loop, through _write_portfolio_total_snapshot. All three callers pass compose_total_fn=web_portfolio._compose_total_for_snapshot:

- the 2-hour scheduler (start_snapshot_scheduler -> start_scheduler -> portfolio_loop);
- /api/portfolio?refresh=true (its background auto-snapshot thread);
- POST /api/snapshot.

A skipped run (3 or more token/zerion failures) writes nothing. The composer runs after every portfolio_snapshots row is final, and any failure of it becomes a 'failed' row; it can never change or fail a portfolio_snapshots row. With compose_total_fn=None, take_portfolio_snapshot behaves exactly as before.

_compose_total_for_snapshot(portfolio) uses the run's own portfolio dict plus the same inputs as the route: _portfolio_total_db_inputs() (MaxFi rows, latest scans, ledger withdrawn heads) and the Hyperliquid cache.

## Hyperliquid freshness and budget

_hl_accounts_state_for_snapshot(now_utc):

- cache under 15 min old -> used as is;
- stale or empty, nothing in flight -> _hl_accounts_refresh_worker runs inline for the visible EVM wallets (sets the in-flight flag and the last-kick time; the worker clears the flag);
- a refresh already in flight -> polls every 2 s for up to 60 s, then uses whatever the cache holds;
- the last-kick cooldown is not applied (snapshot runs are infrequent);
- any failure is logged ("[hl-accounts] snapshot freshen failed") and the current cache is used. With no data, the row has hl_counted = 0.

Budget: when the cache is stale, a refresh costs 1 + 2N calls (N = visible EVM wallets) plus one userAbstraction call per wallet that holds Hyperliquid balances, through _hl_post's shared 55/min budget. The inline refresh also warms the Dashboard headline's cache.

## What did not change

- portfolio_snapshots: same rows, values and statuses.
- Every existing reader: /api/history/portfolio-chart, /api/history/portfolio, /api/history/runs, /api/spot/stablecoins, the spot price diagnostic route, ai_advisor, telegram_service.
- The Dashboard and Performance pages (nothing reads the new table yet).
- GET /api/portfolio/total: output identical; its input gathering was extracted into _portfolio_total_db_inputs() and _hl_accounts_cache_copy(); the request path still makes no network call and no DB write.
- portfolio_total.py and _hl_fetch_accounts.

## How to check it

- GET /api/history/portfolio-total?days=2 — rows, oldest first, with "usable".
- GET /api/history/portfolio-total?days=2&detail=1 — adds "detail", the parsed compose_total output.
- A row appears after each snapshot run (Refresh on the Dashboard, POST /api/snapshot, or the 2-hour loop).

## Rule

Bump PORTFOLIO_TOTAL_DEFINITION_VERSION (src/engines/snapshot_service.py) whenever what compose_total counts changes, so readers can tell definitions apart.

## Backlog

1. Snapshot cadence: deploys restart the loop, giving occasional gaps of up to ~14 h (production May 25 - Sep 27: 1,290 runs, median gap 2.01 h, max 14.1 h). See HANDOFF_total_portfolio_value.md backlog 6. Its own follow-up.
2. Done: the Hyperliquid backfill for past runs (see "Hyperliquid backfill (definition_version 0)" below).
3. Frontend use (chart series, 24h change) at the dashboard redesign.

## Hyperliquid backfill (definition_version 0)

Added Sep 27, 2026 (backlog 2). One portfolio_total_snapshots row for every chart-visible snapshot run before the first measured row, so the complete-total history reaches back to May 25.

Rulings (Glenn, Sep 27):
- One PR. Raw Hyperliquid responses are captured, and the rows are derived from that capture.
- definition_version 0 = old snapshot total + Hyperliquid; no MaxFi fees; old GMX and lending rules.
- Filled: total_usd, snapshot_total_usd, hyperliquid_usd, hl_counted = 1, wallets_total / wallets_completed, detail_json provenance; status 'completed'. Every other part column stays NULL.
- Runs: every chart-visible run (at least one completed portfolio_snapshots row) before the first row with definition_version >= 1.
- Hyperliquid is read for every visible EVM wallet. Per run, only wallets with a portfolio_snapshots row in that run count.
- Between Hyperliquid's points: the last point, plus ledger transfers since it at their true time, plus a straight-line share of the remaining change (trading P/L) to the next point.
- Raw Hyperliquid responses live only in the Railway DB. Never commit them to the repo.

Method (hl_history_backfill.py):
- Sources: `portfolio` (account value history; windows day, week, month, allTime; perp windows ignored) and `userNonFundingLedgerUpdates` (paged).
- Window: the finest window with a point at or before the run.
- Leading $0 points are dropped. Hyperliquid's history starts with a $0 point even when the account already holds money (seen on both funded accounts). Before a wallet's first remaining point, its value is its cumulative ledger transfers.
- Ledger types valued: deposit (+usdc), withdraw (-usdc), send and spotTransfer (+/- usdcValue by direction; a send to yourself counts 0), accountClassTransfer (0). Any other type, or a transfer with no USD value, blocks the real run only when a run's value depends on it (the dry run lists it). A negative wallet value also blocks it.

Raw capture: table hl_history_captures (capture_id, captured_at, wallet, request_type, request_json, response_json). A real run writes the capture and all rows in one transaction and replaces only definition_version 0 rows. Live rows are never touched.

How to run:
- POST /api/history/portfolio-total/backfill-hyperliquid?dry_run=true - fetch and derive, write nothing. Returns the checks, the funded wallets, the seam against the first measured row, and every run's values.
- POST /api/history/portfolio-total/backfill-hyperliquid - fetch, capture, write.
- Add capture_id=<id> (with or without dry_run) to re-derive from a stored capture without calling Hyperliquid.
- 409 when a backfill is running or no measured row exists; 404 for an unknown capture_id; 422 when checks block a real run; 502 when Hyperliquid fails. Nothing is written in any of these cases.

Readers: definition_version 0 rows read usable: true. A reader charting the complete total must tell v0 from v1: v0 lacks MaxFi fees and the other v1 parts, so a small step at the seam is expected. detail_json on v0 rows holds the backfill provenance, not compose_total output.

Production ground truth (Sep 27, before the backfill):
- Both Hyperliquid wallets were in every snapshot run from when their accounts were funded, so the per-run rule drops nothing. Only two of the 15 visible EVM wallets have ever held Hyperliquid value.
- Hyperliquid RM was funded on May 30. Hyperliquid's history for it starts on Jun 3 at $0, then shows exactly the funded amount an hour later.
- Rabby's only jump between points since May 25 matches a transfer on Jun 10. Neither account has a transfer after Jun 13.
- Resolution: points about every 2.3 h for the last 7 days, about 22 h for 30 days, then weekly (Rabby) or about 49 h (Hyperliquid RM).

## Landings

SHAs added by chat after merge.

- portfolio: portfolio_total_snapshots table (one row per snapshot run: complete total, parts, as-ofs, old snapshot total, definition version, full detail JSON) + insert/read helpers + read-only GET /api/history/portfolio-total (backend only; nothing writes to it yet)
- portfolio: extract /api/portfolio/total input gathering into _portfolio_total_db_inputs() and _hl_accounts_cache_copy() (behavior-identical; route output unchanged) so the snapshot writer can reuse it
- snapshot: every snapshot run also writes one portfolio_total_snapshots row - compose_total's complete total and parts (Hyperliquid refreshed inline when the cache is older than 15 min; MaxFi fees as-is), status mirrored from the run, the old snapshot total beside it; composer failures never touch portfolio_snapshots; HANDOFF_total_history.md (backend only; nothing displayed changes)
- storage: hl_history_captures table (raw Hyperliquid responses for the history backfill, Railway DB only) + single-transaction backfill writer (captures + replace definition_version 0 rows) + readers (backend only; nothing writes to it yet)
- history: Hyperliquid backfill for past snapshot runs (definition_version 0) - POST /api/history/portfolio-total/backfill-hyperliquid; pure module hl_history_backfill.py (backend only; nothing displayed changes)
- docs: HANDOFF_total_history.md Hyperliquid backfill section and backlog 1-2; HANDOFF_total_portfolio_value.md backlog 6 corrected
