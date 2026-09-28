# HANDOFF: Dashboard redesign

**Status:** CLOSED Sep 28, 2026 (after PR 3b lands).

## Goal

The Dashboard is rebuilt per docs/dashboard-build-spec.md on the live complete total (GET /api/portfolio/total), replacing the old snapshot-basis page.

## Rulings

- design-audit.md "Dashboard redesign rulings (Sep 27)" and "Dashboard redesign rulings (Sep 28)". Where the spec differs, the rulings and the code win.
- HANDOFF_total_history.md "Chart route (Dashboard redesign)": the complete-total history the equity chart reads.
- HANDOFF_total_portfolio_value.md: the live total's definition (compose_total, the parts, Hyperliquid treatment).

## Landings (main)

Every landing was verified in chat on a fresh clone before it merged.

**#174 (backend)**
- 4b9e748: history: GET /api/history/portfolio-total-chart. Read-only chart series over portfolio_total_snapshots: points, definition seams, excluded-run counts, BTC/ETH prices from market_snapshots.
- c26a3af: market-data: /api/market-data adds sol_24h_change beside btc/eth_24h_change (additive key).
- c8490c6: maxfi: GET /api/maxfi/advisor?kick=0 skips the three on-view background kicks (metrics refresh, ledger backfill, token-daily).

**#175 (frontend core)**
- a643bbc: docs: build spec (docs/dashboard-build-spec.md) + design-audit.md rulings (Sep 27) + chart route landing SHA.
- 4e5604b: style: Dashboard role tokens (--dash-*) and .dash-* layout and breakpoint rules.
- 100e03c: dashboard: hero card with the live total's parts table, status line, notes, warnings badge, snapshot fallback, hidden-value masking; top-bar Refresh redraws the Dashboard.
- 22c2579: dashboard: equity chart on the complete-total history (seam marked, changes across it on the old basis, 24H/1W/1M/1Y/ALL, default 1M).
- 509d1c4: dashboard: As-of column widened to 118px and kept on one line; below 768px one "as of · source" line with an ellipsis.

**#176**
- a016c99: templates: load Recharts so charts draw (the page pointed at a non-existent Recharts.min.js; the UMD also needs PropTypes).

**#177**
- d41f185: spot: a background price that moves more than 10x from the stored price is confirmed by a second fetch before it replaces it.

**#178**
- 90e0d33: market: BTC 50-day moving average beside the 200-day (market_snapshots.btc_50d_ma, same once-a-day CoinGecko series).

**#179 (PR 3a: right column)**
- 874078c: dashboard: equity chart Y axis uses explicit, evenly spaced round ticks.
- e62cdcb: dashboard: MaxFi advisor card replaces LP HEALTH; right column 3-up at 768–1279, half-width minis below 768.
- 806ce3e: dashboard: BTC Macro Zone card re-laid out (vs 200D and 50D, bar with a 50D tick, zone rule on hover, Fear & Greed promoted, ETH/SOL footer).
- 9610bb8: dashboard: Lending card (lowest health factor, protocol / chain / collateral, net and debt, Zerion "not reported", one line when empty).

**PR 3b (Row 3, Performance, Market Data label, close-out)**
- a2d347c: app: the Dashboard gets the portfolio sub-tab setter so Open Spot lands on Spot Positions.
- de488b1: dashboard: Spot P&L card; Row 3 as a .dash-* grid 55fr/45fr.
- f9c45dd: dashboard: Hyperliquid card from the live total's Hyperliquid part.
- e8a1f79: dashboard: the one-line Lending card keeps its text at the top when the grid stretches it.
- 2e602fa: performance: snapshot-basis caption.
- aa65265: performance: Change % and the Change / Change % sign colors masked when values are hidden.
- d52f700: market data: the btc_200d_ma cell is labeled 200-DAY MA.
- This docs commit.

## What each card reads

| Card | Route · fields | Rules |
|---|---|---|
| Hero | GET /api/portfolio/total → total_usd, as_of, components[] (value_usd, counted, as_of, source, warnings, detail), warnings[] (maxfi_drift). Fallback: GET /api/history/portfolio-total?days=2 | Retried every 10 s while the cache is cold or Hyperliquid is loading (at most 4 requests, 30 s timeout each). Fallback = the latest usable row with definition_version ≥ 1. Stale as-of: parts > 2 h 15 m, Hyperliquid > 30 min, MaxFi fees > 24 h. |
| Parts table | the same components | Order: Wallet tokens, Stablecoins, MaxFi LP, Other LP, LP fees, MaxFi fees, Hyperliquid, Lending (net), GMX. A zero row with no warning is hidden (MaxFi LP always shows). Extras: "↳ Spot positions" = Σ non-null current_value_usd from GET /api/spot/pnl (info only); "Staked / locked" = zerion_staking (not counted). |
| Equity chart | GET /api/history/portfolio-total-chart → points (t, v, total, basis0), seams, excluded, benchmarks | A change across the definition seam is compared on basis0 at both ends. The 24h change = latest vs the last point at least 24 h earlier. Y ticks from _dashNiceTicks (≤ 6 round ticks). |
| MaxFi advisor | GET /api/maxfi/advisor?kick=0 → positions (verdict, flags, symbols, token_id, current_value_usd, current_value_at, run_rate_7d_pct_day, claims_unavailable); GET /api/wallets (maxfi: true); GET /api/maxfi/range/<chain>/<wallet> → positions (token_id, in_range, status) | Wallets flagged maxfi, visible or not. Any flag = No verdict. Range: one wallet at a time, chains in parallel, 20 s abort; failed / timed-out checks = not checked. Fees run rate = Σ run_rate_7d_pct_day / 100 × current value. Stamp = oldest current_value_at (warn after 24 h). |
| BTC Macro Zone | GET /api/market-data → snapshot (btc_price, btc_200d_ma, btc_50d_ma, fear_greed_index, eth/sol price and 24h, timestamp) | Zone from _deriveZone (F&G missing → 50). Bar −30%…+30% around the 200-day. F&G bands ≤25 / ≤45 / ≤55 / ≤75 (Market Data page). |
| Lending | GET /api/portfolio → aave_positions | A position = collateral or debt ≥ $0.01. HF only from rows > 0: > 2 green, > 1.5 yellow, else red. Money without an HF = "not reported (Zerion)". |
| Spot P&L | GET /api/spot/pnl; GET /api/spot/history | Unrealized % = Σ unrealized / Σ cost of the priced positions. "REALIZED · SOLD IN 30D" = Σ lifetime realized_pnl of keys whose last_sell_date is within 30 days. Current value = Σ priced current_value_usd (= the hero's ↳ Spot positions). Movers: top 5 by the size of unrealized %. |
| Hyperliquid | the live total's hyperliquid component → value_usd, counted, as_of, detail.wallets (spot, perp_account_value, open_perps, perp_treatment, stale), detail.wallets_checked | Account value = the counted part. Per wallet VALUE = priced spot + perp only for 'counted' wallets; PERP tagged "in spot" (unified) or "not counted" (unknown mode), never added. Stale stamp after 30 min. |

## Hidden values (R6)

- Masked: every money figure (hero, parts, sub-lines, chart Y labels and tooltip, strip, MaxFi fees, Lending net / debt / collateral, Spot, Hyperliquid), portfolio %, shares, counts (MaxFi in-range, chips, not checked; Lending positions; Hyperliquid open perps and wallets checked; unpriced spot count) and the health factor. Masked values carry no sign or band color (--dash-text; the masked health factor --dash-text3).
- Visible: public market data (BTC / ETH / SOL prices and 24h, both MAs, Fear & Greed, the whole BTC card), timestamps, asset names, pair names, wallet labels, chain names, verdict words.
- Performance page: Change % and the Change / Change % colors are masked (aa65265). Its charts are not (backlog 7).

## Production facts

- Sep 27: Recharts had never drawn in production before a016c99.
- Sep 27: STONK was cached at ~$1,256 instead of ~$0.257 for one refresh, which led to d41f185.
- Sep 27: MaxFi 8 CLOSE / 5 HOLD, fees $39.33/day.
- Sep 27 23:00 UTC: chart series of 1,294 points (1,289 v0 + 5 v1); 1 incomplete run excluded (the Sep 10 dip); seam at 2026-09-27T18:58:44Z with a $109.19 definition step (MaxFi fees).
- Sep 27–28: Hyperliquid: both funded accounts are unified; 15 visible EVM wallets are checked and 2 hold value.
- Sep 27–28: no lending positions (Zerion lists $0 rows).
- Sep 27–28: old-series level shifts of ~$5k lasting days (Jul 20→24, Aug 1→8) and +$13.7k on Aug 8–9. [Inference] Either transfers to untracked accounts or a wallet silently dropping value while its run reports complete.
- Sep 28 15:07 UTC: BTC 82,974; 50D MA 76,463.65; 200D MA 71,121.82.
- Sep 28 15:53 UTC: MaxFi 13 positions (7 HOLD, 6 CLOSE, 0 No verdict), fees $39.04/day.
- Sep 28: /api/maxfi/advisor?kick=0 answered in 212 ms, ~177 KB (entry_candidates are the bulk).

## Verification record

- Gates per commit: Babel parse (@babel/standalone 7.26.4, preset react) of every touched .js file; NUL-byte check; additions-only checks on style.css and the appended docs; top-level name collisions across static/*.js; full `python -m pytest tests/`.
- Chat-side headless Chromium (Playwright) with fetch stubbed from payloads of the real routes: states (loading, error, empty, partial), widths 390 / 800 / 1100 / 1440 (no horizontal scroll, layout per breakpoint, tap targets ≥ 44px below 768), contrast / font audit (≥ 4.5:1, ≥ 11px on every text node), hidden-value masks (no "$digit" or counts in text, titles or aria-labels), keyboard focus rings, zero console errors.
- Glenn's production checks after each deploy (hero total and parts, equity chart drawing, right-column cards, Spot and Hyperliquid cards).

## Backlog (found, not done)

1. Per-position spot 24h from token_snapshots (ruling 4).
2. The stacked-parts equity chart once v1 history covers a chart range.
3. The P/L page's Recharts ReferenceLine defaultProps console error under the React development build.
4. Snapshot cadence: deploys restart the 2-hour loop (HANDOFF_total_portfolio_value.md backlog 6).
5. The old-series level-shift watch item (Jul 20→24, Aug 1→8, +$13.7k Aug 8–9).
6. The Holdings page's own "Total Value" definition.
7. The Performance page's charts (Y axis and tooltips) ignore hidden values.
8. [Inference] The advisor's fees run rate mixes net ledger claims with pre-performance-fee uncollected fees (the headline counts uncollected at 85%).
9. /api/maxfi/advisor has no positions-only mode (~177 KB per Dashboard view, mostly entry_candidates).
10. A true 30-day realized needs per-sale realized from the spot FIFO.
11. Range requests still in flight at Refresh or unmount are not aborted (their results are discarded).
12. _dashNum(null) returns 0 (existing callers may read a null as $0).
13. If the deploy-day 50-day refetch fails, each later market snapshot that day retries once.
14. Two Fear & Greed band sets exist (market.js vs marketdata.js).
15. test_market_btc_50d_ma T6b can fail within 2 s after UTC midnight.

## Operating notes

- The Dashboard starts no background work: the advisor is read with ?kick=0.
- Refresh (the hero button or the top bar) re-runs every card's fetch and the range loop.
- The first view after a deploy shows Hyperliquid loading for ~10–30 s.

## Follow-up (Sep 28)

Rulings: design-audit.md "Dashboard follow-up rulings (Sep 28)".

Landings:
- de8b24a: performance: hidden values mask both charts' Y ticks and tooltips and the closed tables' money (sign colors neutral while hidden; direction and entry/exit prices stay visible).
- c45d08a: performance: legend text in --text2 (the dot keeps the series color) and gridlines at 0.3 opacity.
- abb56eb: dashboard: Hyperliquid wallet title shows label · address; Spot table header reads BY UNREAL. % below 1024px.
- This docs commit.

Backlog 7 (Performance charts ignore hidden values) is done in de8b24a; the closed tables were masked too.

Newly found, not done:
- a. The purple Performance series (Lending Net, LP + Hedge Value, #9b59ff) are 2.75:1 as lines on the card (--panel #103f63). The other series colors measure 3.92–4.0:1 (#f97316, #4caf50, #4e9eff).
- b. The Performance gridlines use --line (#266594, 1.76:1 on --panel), so at 0.3 opacity they meet the alpha floor but stay faint.
- c. The Performance chart tooltips color each item's name and value with its series color (Recharts' default tooltip), so the tooltip text carries the same contrast as (a) on --panel. The legend fix does not cover the tooltip.
- d. From 1024px up to about 1250px the full Spot header "ASSET · BY UNREALIZED %" wraps to two lines (the 2-up Row 3 leaves the first column about 150px wide); the ruling keeps the full label at 1024px and above.
- e. At 768–1023px the Hyperliquid wallet column is about 80px wide, so labels longer than about 10 characters show an ellipsis; the title now carries the full label.
