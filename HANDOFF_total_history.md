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

1. Snapshot cadence: the loop sleeps 2 h before its first run and restarts on every deploy (HANDOFF_total_portfolio_value.md backlog 6). Its own follow-up.
2. A one-time Hyperliquid backfill for past runs from Hyperliquid's `portfolio` info request. Chat's Sep 27 probe confirmed it includes spot, with points about every 2.3 h for 7 days, daily for 30 days and weekly all-time. Its own follow-up, soon after this lands.
3. Frontend use (chart series, 24h change) at the dashboard redesign.

## Landings

SHAs added by chat after merge.

- portfolio: portfolio_total_snapshots table (one row per snapshot run: complete total, parts, as-ofs, old snapshot total, definition version, full detail JSON) + insert/read helpers + read-only GET /api/history/portfolio-total (backend only; nothing writes to it yet)
- portfolio: extract /api/portfolio/total input gathering into _portfolio_total_db_inputs() and _hl_accounts_cache_copy() (behavior-identical; route output unchanged) so the snapshot writer can reuse it
- snapshot: every snapshot run also writes one portfolio_total_snapshots row - compose_total's complete total and parts (Hyperliquid refreshed inline when the cache is older than 15 min; MaxFi fees as-is), status mirrored from the run, the old snapshot total beside it; composer failures never touch portfolio_snapshots; HANDOFF_total_history.md (backend only; nothing displayed changes)
