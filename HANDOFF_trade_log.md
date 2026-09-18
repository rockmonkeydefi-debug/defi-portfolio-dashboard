# HANDOFF — Spot Trade Log (sizing-gate revival)

Rulings locked 2026-09-18. Baseline at lock: main @ ccfafb7bc49207d866ffe7783f16058305c77ba5, 1106 tests. Parent context: strategy ruling of Sep 13 (spot book alongside the LP book; risk base = crypto capital only; start at 1% risk per trade, graduate to 2% after ~20 logged trades taken per MHC rules show positive realized expectancy; 5% cap on total concurrent open risk; the log captures entry, stop, exit, R-result, followed-vs-deviated). Slotted in the Sep 17 scanner sequence after flip quality (done, ccfafb7) and before RS vs BTC.

## Purpose

Give the Sep 13 sizing gate something to count. No active trade log exists today — the old one is the hidden Trading Tools → Journal (see "Why not revive" below), and every spot trade since Sep 13 has gone unlogged against the 20-trade gate. v1 is the smallest honest log: R computed from prices (never typed), followed-vs-deviated recorded, and the scanner state at entry captured automatically because it cannot be reconstructed later.

## Why not revive the old Journal (ruled — do not reopen)

Step-1 findings on the hidden `tt-journal` (static/journal.js, `trading_journal` table, CRUD at /api/trading/journal): journal-first shape (title/body/mood/market_regime) with trade fields bolted on via an ad-hoc startup ALTER block (web_portfolio.py ~6189, the deprecated migration pattern); `r_multiple` is typed by hand, not computed; no entry/stop/exit prices, no size, no followed-vs-deviated, no scanner stamp; coupled to the retired ICT Validator; zero tests; `HIDDEN_TABS` hides the whole `tt` namespace by prefix, so un-hiding it resurrects seven dead tabs. Glenn confirmed the old Journal holds none-to-a-couple real trade rows on production — nothing worth migrating. Ruling: new purpose-built log; the old Journal stays hidden and untouched; no row migration.

## Deferred / explicitly NOT this workstream

- Risk as % of capital and the 5% concurrent-open-risk cap readout — no spot-capital setting exists (ADVISOR_SETTINGS.total_capital_usd is MaxFi-scoped). v1 shows open risk in USD only; a spot-capital setting + % readouts is a small follow-on.
- USD P/L — that lives in the P/L tab and spot_transactions. This log is about R and discipline, not accounting. No join to spot_transactions in v1 (possible v2).
- Auto-fetched prices (entry/exit/mark) — all prices are entered by hand in v1. No live-price column.
- Any analysis UI over the scanner snapshot (e.g. "win rate when entered inside confluence") — v1 captures and displays the snapshot; querying it is a later workstream once there are enough rows to mean anything.
- Structured deviation reasons — v1 is a yes/no plus a free-text note (ruled).
- Alerts, reminders, stop-hit detection — none.

## Rulings (locked, do not reopen)

1. New table `spot_trade_log` created in `init_db()` (base CREATE TABLE IF NOT EXISTS, same as the `noodle_scan_runs` precedent — a new table, not an ALTER). Columns: id, ticker TEXT NOT NULL (uppercase, the HL perp symbol string so it matches noodle_state.symbol), direction TEXT NOT NULL ('long'|'short'), source TEXT NOT NULL DEFAULT 'MHC' (short tag; the gate counts source='MHC'), venue TEXT (nullable; e.g. 'hyperliquid'|'onchain'|'cex'), entry_price REAL NOT NULL, stop_price REAL NOT NULL, qty REAL NOT NULL (token units), target_price REAL (nullable, planned target), exit_price REAL (nullable — NULL means open), entered_at TEXT NOT NULL (ISO UTC, defaults to now, editable), exited_at TEXT (nullable), followed_rules INTEGER (nullable; 0|1), deviation_note TEXT, notes TEXT, scanner_snapshot_json TEXT (nullable), created_at, updated_at.
2. R is COMPUTED, never stored and never typed. Pure helper (route-side, mirroring `_noodle_dist_to_flip_pct`): risk_per_unit = |entry − stop|; r_result = (exit − entry)/risk_per_unit for long, (entry − exit)/risk_per_unit for short; planned_rr uses target_price the same way; risk_usd = risk_per_unit × qty; notional_usd = entry × qty. entry == stop is rejected at write time (400) — zero-risk trades are not loggable. All derived values are computed in the GET route and emitted alongside the stored row.
3. Status is derived: open iff exit_price IS NULL. Closing a trade (PUT with exit_price) REQUIRES followed_rules to be 0 or 1 in the same request or already set — a closed trade with unknown discipline is not allowed (400). deviation_note is free text, optional either way.
4. Scanner snapshot is captured AUTOMATICALLY at POST (entry) time: all noodle_state rows for the ticker (all five timeframes) — state, alignment fields, flip_ts, dist_to_flip_pct, flip_count_window, last_close, scanned_at — plus captured_at, stored as one JSON blob. If the ticker has no noodle_state rows, store {"captured_at": ..., "reason": "not_in_scanner_universe"} rather than NULL, so absence is distinguishable from a capture bug. The snapshot is never recomputed or updated after entry.
5. Routes under /api/spot/trade-log: GET (list, newest first, each row with the derived fields from ruling 2, plus a `summary` block: open_count, closed_count, mhc_followed_closed_count (source='MHC' AND followed_rules=1 AND closed), gate_target=20, win_count/loss_count over closed rows by sign of r_result, net_r, expectancy_r (mean r_result over closed rows), open_risk_usd (sum of risk_usd over open rows)); POST create; PUT update (including close); DELETE. No pagination in v1.
6. Frontend: new static/tradelog.js screen, tab id 'tradelog', nav entry in the Spot section immediately AFTER Trends; app.js render branch; templates/index.html script tag. Entry form (ticker, direction, source, venue, entry, stop, qty, target, entered_at, notes) + open-trades table + closed-trades table + a gate readout line ("N / 20 MHC rule-followed trades · expectancy X.XR"). Close action = inline form on an open row (exit, exited_at, followed yes/no, deviation note). Snapshot shown as an expandable per-row detail (read-only, raw fields, no analysis). Follows the UI/UX visibility standards (13px body floor, no muted text on dark).
7. Commit plan: Commit 1 backend (table + pure helpers + routes + tests, STOP-gated — report before Commit 2); Commit 2 frontend (4 files: new tradelog.js + nav.js/app.js/index.html wiring; zero backend diff; Babel/NUL gate + full pytest as the no-op gate). Doc close-out append with both SHAs.
8. Tests (Commit 1): R helper — long win, long loss, short win, short loss, planned_rr, entry==stop rejected; snapshot capture with rows present and with none (reason recorded); close requires followed_rules; summary math on a small seeded set; table exists after init_db. Mirror tests/test_noodle_scan_runs.py's shape.

## Next

Implementation runs in a fresh chat pointed at this doc: step-1 read-only confirm pass (init_db table pattern via noodle_scan_runs, route conventions, nav Spot-section ordering, noodle_state column list for the snapshot), then Commit 1 (STOP-gated), then Commit 2, then the close-out append.
