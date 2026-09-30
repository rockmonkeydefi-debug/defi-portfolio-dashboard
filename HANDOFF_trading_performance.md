# HANDOFF — Trading performance (spot vs perps) and an automatic Trade Log

Rulings locked 2026-09-30. Baseline at lock: main @ 91a8333, 1989 tests.

## Purpose

Glenn's focus moved to spot and perps trading on Sep 30. MaxFi positions stay as they are and all MaxFi work is on the back burner. Three problems drive this workstream:

1. Long-term/earned holdings (ESHARE, FOX) and bot capital sit in the same spot book as trades and distort trading P/L.
2. No per-trade perp P/L exists anywhere.
3. The Trade Log (HANDOFF_trade_log.md) went unused: one trade since Sep 18. Every trade had to be typed twice, the ticker list covered only scanner symbols, the notes box was too small, and nothing reminded Glenn it existed.

This workstream tags non-trading holdings, derives trades automatically from spot_transactions and Hyperliquid fills, and rebuilds the Trade Log so Glenn adds only what can't be derived: the stop, followed/deviated, and notes.

## Glenn's rulings of Sep 30

- Tag long-term/earned holdings so trading views and P/L exclude them or show them separately.
- Trade Log entries are created automatically from spot buys and perp fills (tagged holdings excluded). Glenn adds only the stop, followed/deviated, and notes.
- Spot and perp performance are reported separately.
- After the pre-flight: nothing is built around any one idea source (MHC or any other). Trade origin goes in the free-text notes.
- All pre-flight recommendations accepted, as adjusted by the line above.

## Not this workstream

- MaxFi work (back burner), the Bittensor backlog, /api/spot/change-24h fixes (the route stays untouched), the DexScreener retry.
- Per-transaction tagging with a FIFO split by book (documented upgrade path, ruling 1).
- Importing Hyperliquid spot fills into spot_transactions (backlog, ruling 5).
- TXflow automatic import (no public API, ruling 12).
- Telegram reminders (backlog, ruling 14).
- The spot-capital setting, % risk readouts and the 5% concurrent-risk cap (still deferred from HANDOFF_trade_log.md).
- A true 30-day realized P/L on the Dashboard Spot P&L card (debt, below).

## Ground truth (verified on 91a8333)

- spot_transactions.price_usd holds the TOTAL transaction amount including fees, not a per-unit price; total_usd duplicates it. FIFO derives per-unit cost as price_usd / units, and any new code reads it the same way. Not renamed.
- trade_date is a date only (M/D/YYYY, with legacy formats parsed by _parse_trade_date). Spot trades therefore have day precision; same-day order is by row id, which is FIFO's own order.
- _calculate_spot_fifo keys positions by (chain, contract_address), falling back to the uppercased symbol. It keeps realized P/L per position only; no per-sale or per-trade P/L exists.
- spot_position_notes is keyed on (chain, contract_address) and rejects symbol-only positions (for example CEX lots). The tag table must key on the stringified position_key instead.
- The Dashboard spot cards (Spot P&L, 24h movers, Top holdings) are computed in the browser from /api/spot/pnl, /api/spot/history and /api/spot/change-24h. Top holdings and 24h movers read /api/spot/pnl rows. No test pins those route rows exactly.
- Trade Log (spot_trade_log): the gate count is closed + source 'MHC' + followed_rules 1, but expectancy_r averages R over ALL closed trades and nothing checks that it is positive. The nav label and page title already read "Trade Log". The POST route defaults source to 'MHC'.
- Hyperliquid: every call goes through _hl_post (55/min, process-wide). _hl_fetch_accounts downloads clearinghouseState for each visible EVM wallet every 15 minutes but keeps only accountValue and the position count, discarding per-position entryPx, unrealizedPnl and cumFunding. hl_history_captures and the userNonFundingLedgerUpdates paging loop (startTime = last time seen, dedup, stop on no new rows or a short page) are the precedent for raw capture and paging.
- A 2-hour portfolio snapshot loop exists (snapshot_service.start_scheduler, PORTFOLIO_INTERVAL 7200). _get_portfolio_data_for_snapshot already freshens Taostats inline (_tao_state_for_snapshot), and the Hyperliquid accounts cache freshens in the compose-total path. That is the hook pattern for a fills sync.
- Hyperliquid info API (docs): userFillsByTime returns at most 2,000 fills per call, and only the 10,000 most recent fills are ever available, so raw fills must be stored locally. Fill fields: coin, px, sz, side, time, startPosition, dir, closedPnl, fee, feeToken, builderFee, oid, tid, hash, crossed. Perp dir values: Open/Close Long/Short, "Long > Short", "Short > Long", Liquidation. Spot fills say Buy/Sell and use "@N" coin names. HIP-3 coins carry a dex prefix ("xyz:TSLA"). userFunding pages by startTime (time-range responses cap at 500 items). frontendOpenOrders carries isTrigger, triggerPx, reduceOnly and isPositionTpsl (optional dex parameter). historicalOrders returns at most 2,000 recent orders.
- TXflow: its own Layer 1 with a fully on-chain order book (perps including stock perps, plus spot). Login is by EVM wallet or email. Funding settles every 1, 4 or 8 hours depending on the contract. The Platform API page reads "Coming Soon"; there is no documented way to pull fills.

## Open before Commit 3 (from the Sep 30 data ask)

- Which Hyperliquid wallet labels Glenn trades perps from, and any Hyperliquid sub-account (sub-accounts have their own address, outside the Playbook wallet list).
- Sanitized real samples of userFillsByTime, userFunding, frontendOpenOrders and historicalOrders, to confirm: whether closedPnl excludes fees; the funding sign; whether HIP-3 fills appear in userFillsByTime; whether the original stop price survives in historicalOrders after a stop is moved (this decides ruling 8's auto-stop).
- Whether Glenn places stop orders on Hyperliquid itself.
- How Glenn accesses TXflow, and whether the app exports trade history (CSV).

Commits 0, 1 and 2 do not depend on these.

## Rulings (locked, do not reopen)

1. Holding tag, per position. A new table keyed on the stringified FIFO position_key: the same string /api/spot/pnl emits ("chain address", or the bare uppercase symbol for symbol-only positions). Values: long_term or bot_capital; no row means trading. FIFO math is untouched. Per-transaction tagging with a FIFO split by book is the documented upgrade path, taken only if a position ever mixes trading and long-term lots.
2. Where tagged holdings show:
   - Trade Log and every trading statistic: excluded.
   - Dashboard Spot P&L card: the headline numbers (unrealized, realized sold in 30d, value) cover the trading book only. The card is relabeled "SPOT P&L · TRADING", with one line beneath it: "Long-term & bot: value $X · unrealized $Y".
   - Realized sold in 30d excludes tagged positions.
   - Dashboard 24h movers and Top holdings keep everything, with a small tag chip.
   - Spot page Live Holdings and Trade History show all rows with a tag chip, an All / Trading / Long-term & bot filter, and a per-row tag selector.
   - The Dashboard total, portfolio_total and /api/spot/change-24h are unchanged.
3. Kraken TAO lots (note "Alpha Chasers"): Glenn tags them himself in the UI. If the TAO was bought to fund the bot, tag it bot_capital. If it began as a discretionary trade, first log its result as a closed manual trade at the handover price, then tag it bot_capital, so a trading result is not hidden. No special code.
4. Spot trade = a position cycle. It opens when a position's units go from zero to positive and closes when the remaining units fall to 1% or less of the cycle's peak (dust rule, tunable constant). Adds and partial sells stay inside the cycle; partial sells show as "partly closed". A sell with no open cycle (the zero-basis orphan case) shows flagged and is excluded from R and the gate.
5. Hyperliquid spot fills ("@N" coins) are ignored for trade derivation; spot_transactions stays the only spot source. Backlog, only if Glenn buys spot on Hyperliquid itself: import those fills into spot_transactions so they are not typed twice.
6. Perp trade = a cycle per (wallet, coin). It opens when startPosition is zero and closes when the position returns to zero; partial closes stay inside. A flip fill is split into the close of one trade and the open of the next, with the fee split pro rata by size. A liquidation closes the cycle and flags it.
7. Dollar P/L and R:
   - Spot $ = realized FIFO over the cycle's sells (fees are already inside price_usd). It comes from a new pure module that walks spot_transactions in FIFO's exact order and tolerances. A parity test pins that each position's summed trade P/L equals _calculate_spot_fifo's realized_pnl.
   - Perp $ = sum of closedPnl − sum of fees (builderFee included; a negative fee is a rebate) + sum of funding for that wallet and coin between open and close. Fee inclusion and the funding sign are confirmed from the samples before Commit 3.
   - Open trades: spot unrealized from /api/spot/pnl's price path; perp unrealized from the per-position data the accounts cache already downloads (kept, additive, zero new calls).
   - R = net $ P/L ÷ (|average entry − stop| × peak size). The manual path keeps price-based R (it has no fee data), labeled as such.
8. Stops: every stop records stop_set_at. Perps: auto-filled from the earliest reduce-only trigger order on that coin placed shortly after entry, marked stop_source 'hl_order' and editable. This is contingent on the samples; otherwise perp stops are manual. Spot: one inline field on the open row.
9. Gate (the Sep 13 sizing rule, now origin-agnostic per Glenn's Sep 30 ruling). An eligible trade is closed, has followed_rules = 1, and has a stop recorded while the trade was still open (stop_set_at before the close). Moving from 1% to 2% risk needs at least 20 eligible trades AND an expectancy (mean R over exactly those trades) above zero. There is one combined gate across spot and perps, with a spot/perp breakdown beside it. Deviated trades appear in their own statistics, never in the gate. Trades since Sep 13 are derived and shown with $ P/L; closed trades without a stop recorded while open are visible but not gate-eligible.
10. No idea-source logic. Nothing filters, counts or defaults by source (MHC or any other); origin goes in notes. spot_trade_log.source stays in the table untouched (stored history). The rebuilt UI neither shows nor filters it, and it sends source 'manual' on new manual rows, so the POST route's 'MHC' default is never used by the UI.
11. Architecture: trades are derived at read time from spot_transactions and the stored Hyperliquid fills and funding; nothing derived is stored.
    - A trade_annotations table holds only what cannot be derived: stop, stop_set_at, stop_source, followed_rules, deviation_note, notes, scanner_snapshot_json and the snapshot's captured_at.
    - It is keyed by a stable trade key: for spot, position_key + first buy row id; for perps, wallet + coin + first fill tid.
    - Code never deletes annotations. An annotation whose trade no longer matches (for example, its first buy row was edited away) is listed as "unattached" at the bottom of the Trade Log.
    - Raw fills and funding are stored insert-only, unique on (wallet, tid) and (wallet, time, coin), and never rewritten.
    - Wallet addresses live only in the Railway DB, never in code, tests or docs. Test fixtures use fake addresses and scaled amounts.
12. Manual path: spot_trade_log stays as the manual source for venues without a feed (TXflow now, a CEX later). It gains a market column (spot or perp) through init_db's guarded-ALTER migrations list; existing rows are untouched, and a NULL market reads as spot. The ticker becomes free text with scanner suggestions. The existing routes and their 19 tests keep working. TXflow: manual entry now; a CSV import if the app exports one; revisit when its API ships.
13. Scanner snapshot: captured once, when the sync first sees a trade, with captured_at shown beside the entry time. The ticker is matched to noodle_state.symbol case-insensitively, then with the kilo prefix (BONK to kBONK); otherwise the reason is "not_in_scanner_universe".
14. Everyday use:
    - Open trades show a "needs stop" pill; closed trades show "needs followed/deviated".
    - Notes become a multi-line box (about 6 rows) in an expandable row.
    - Separate Spot and Perps summary panels, plus the gate readout from ruling 9.
    - Nav: Trade Log moves right after Dashboard (Dashboard | Trade Log · Trends | Spot Positions · Token Holdings | MaxFi ...) and carries a count badge of trades needing attention.
    - The Dashboard gains a TRADING card: 30-day net $ for spot and perps, open risk, the needs-attention counts, and a button to the Trade Log.
    - Telegram reminders are backlog.
15. Sync: fills, funding and open orders for trading wallets run in the 2-hour snapshot loop (freshen-hook pattern, never raises), plus a background kick when the Trade Log or Dashboard opens and the last sync is older than 10 minutes.
    - Never on a request path; the routes serve stored rows.
    - Wallets = those showing Hyperliquid activity in the accounts cache, remembered once seen.
    - Concurrency uses an in-flight flag plus a lock (the accounts-cache pattern), and every call goes through _hl_post.

## Commit plan

Every commit uses a fresh land/<topic>-<date> branch cut from origin/main and a draft PR, and Claude Code stops there. Chat then verifies: a diff against the block, the full suite on a fresh clone, a replay on sanitized shapes, and a headless-browser check for frontend commits. Chat merges by fast-forward, and Glenn confirms in production before the next block. Backend and frontend never share a commit, and files are staged by explicit filename.

0. This doc (doc-only).
1. Backend, STOP-gated (new table): the tag table, a GET/PUT route, an additive book field on /api/spot/pnl and /api/spot/history rows, and tests.
2. Frontend: the Spot page tag selector, chips and filter, and the Dashboard spot cards per ruling 2.
3. Backend, STOP-gated (new tables, money path): the Hyperliquid fills/funding store, sync worker and hooks, a pure perp-cycle module, the accounts-cache per-position fields, and tests on sanitized fixtures. Opens only after the samples arrive.
4. Backend, STOP-gated (new table + guarded ALTER, money path):
   - a pure spot-cycle module and the FIFO parity test;
   - trade_annotations and spot_trade_log.market;
   - the unified trades route (GET list with summary and gate, PUT annotation);
   - tests.
5. Frontend: the Trade Log rebuild, the nav move and the badge.
6. Frontend: the Dashboard TRADING card.
7. A doc close-out append with every SHA.

## Gates

- py_compile on every touched .py file.
- python -m pytest tests/ (never with -q; baseline 1989 plus new tests).
- A Babel parse and a raw-byte NUL check on every touched .js file.
- This repo has no npm build step.

## Debt flagged, not fixed here

- price_usd naming (the column holds a total).
- The Dashboard's "Realized · sold in 30d" is the lifetime realized P/L of any position with a sale in the last 30 days (its tooltip says so). The spot-cycle module could later give a true 30-day figure.
- tv-table row borders fall below the 0.25 opacity standard (a site-wide style.css fix, already on record).
- The old /api/spot/trade-log summary's expectancy/gate mismatch. Ruling 9 supersedes it in the unified route, and the old summary is no longer displayed.

## Next

Commit 1 opens in this same chat after this doc lands.
