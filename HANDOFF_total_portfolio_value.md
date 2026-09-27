# HANDOFF — Total portfolio value

Workstream opened and closed Sep 27, 2026. Goal (Glenn): one total covering every wallet holding, LP position and borrow/lend position.

## Status

CLOSED. The Dashboard headline is the live total from GET /api/portfolio/total, with its parts as pills. History (portfolio_snapshots, the equity chart, the 24h change, History/Performance pages, Telegram digest) keeps the snapshot definition by ruling.

## Landings (main)

- 27e2fe7 — /api/portfolio gains staking_positions (Zerion's staked/locked/deposit/reward bucket, previously dropped), counted in no total. PR #167.
- e7f6e04 — GET /api/portfolio/total (read-only, cache-only) plus portfolio_total.py (pure composer) and the Hyperliquid accounts cache. PR #167, fast-forward.
- 1576659 — Dashboard headline stopped counting wallet stablecoins twice (hero = snapshot total; Spot pill = tokens minus Cash). Landed from PR #166 (head 9b0ded7), stacked on #167 and pushed in one fast-forward; #166 closed with a pointer.
- fe8a42e — Dashboard headline shows the live total; pills from its parts; Spot positions sub-pill; not-counted staking note; warnings badge; falls back to the snapshot headline when the live total is unavailable. PR #168, fast-forward.
- 46b5bfc — headline shows "…" until the live total first answers (no snapshot-then-live jump on page load); the Hyperliquid-loading item is kept out of the warnings badge.
- Tests: 1653 at the start, 1688 after e7f6e04; frontend commits add none.

## Rulings (Glenn, Sep 27)

1. Fix the headline double count first, as its own frontend commit.
2. Architecture: a new read-only aggregator route with per-part provenance (not an extension of get_portfolio_data, not frontend-only, not snapshot columns).
3. MaxFi principal comes from Zerion's own LP rows for the MaxFi vault (protocol "snuggle"). maxfi_positions supplies only MaxFi uncollected fees.
4. MaxFi uncollected fees count at 85% (MaxFi's 15% performance fee; Glenn's wallets verified 85/15/0 on-chain, no referrer). Rows whose ledger lineage head is withdrawn are excluded; values older than 24 h are flagged but counted.
5. Lending counts NET (collateral minus debt); gross collateral and debt are shown beside it.
6. Hyperliquid: every visible EVM wallet is checked from a 15-minute in-memory cache refreshed in the background on view (no per-wallet flag).
7. Zerion's staking bucket is reported, not counted.
8. History keeps today's definition; the complete total is live-only. Snapshot columns for the new parts were deferred.
9. Headline = live total; the 24h change keeps its snapshot basis with a tooltip.
10. Pills: Spot, Cash, DeFi LP, Fees and Hyperliquid always; Lending and GMX only when not zero; staking as a "not counted" note.
11. Spot = every non-stablecoin token in every visible wallet (all chains, BTC, SOL, custom tokens). Cash = wallet stablecoins. A "↳ Spot positions" sub-pill shows the Spot Positions page's Current Value exactly; it is informational and never added.

## Ground truth measured in production (Sep 27)

- Headline before the fix: $91,845.34 = snapshot total $80,394.12 + stablecoins $11,451.22. The same stablecoins sat inside the snapshot's tokens_value, so they were counted twice. No hidden or removed wallet held stablecoins.
- Zerion indexes Robinhood chain (33 token rows at the time), and reports MaxFi vault positions as LP groups with protocol "snuggle". Those rows are the whole of total_lp_value. Zerion does not list MaxFi positions on Base.
- Same-moment comparison, Zerion snuggle rows vs maxfi_positions.last_value_usd: every paired position agreed within about $15. Zerion labels an out-of-range position by the one token it holds (the "WETH" row was TAO/WETH).
- An apparent 11-position gap on CB RM was timing, not a bug: the portfolio cache predated Glenn's closes; the scan came after. Zerion MaxFi rows are only as fresh as the portfolio cache.
- Hyperliquid (HyperCore) balances were read nowhere before this work. Rabby (Hyperliquid) and Hyperliquid RM held about $8.0k (spot USDC plus perp equity). MAX on Hyperliquid is priced at about $0.0000002, so it is worth nothing.
- No borrow/lend positions (Zerion lists Morpho, HyperLend and HypurrFi rows at $0). No GMX positions.
- After the fix and the new route (14:58 UTC): snapshot headline $79,363.26; live total $87,434.05 = wallet tokens 62,749.22 + stablecoins 11,458.94 + MaxFi LP 5,155.10 + MaxFi uncollected 109.19 + Hyperliquid 7,961.59. Staking (not counted) $19.30, all locked SOL on the two Solana wallets. Zero warnings. The non-Hyperliquid, non-MaxFi-fee parts equal get_portfolio_data's total_value exactly.

## How the total is built

GET /api/portfolio/total reads only in-memory and DB state: the get_portfolio_data cache (never builds it; a cold cache answers {"status": "cache_cold"}), open maxfi_positions rows of visible MaxFi wallets, the ledger's withdrawn-head state, and the Hyperliquid cache. It makes no network call and writes nothing. Hyperliquid calls run only in a background thread, through _hl_post (shared 55/min budget).

Parts (portfolio_total.compose_total), each with value, counted flag, as-of, source and warnings:

- wallet_tokens — non-stablecoin wallet tokens (portfolio cache).
- stablecoins — STABLECOIN_SYMBOLS, one tuple shared with /api/spot/stablecoins.
- maxfi_lp — Zerion "snuggle" LP rows.
- other_lp — every other LP row.
- lp_uncollected — total_fees_usd over all LP rows.
- maxfi_uncollected — last_uncollected_usd x 0.85, guarded as in ruling 4.
- hyperliquid — perp accountValue + spot balances priced from Hyperliquid's USDC pairs; not counted until the cache has data ("Hyperliquid loading").
- lending_net — collateral minus debt.
- gmx — collateral only when it is a stablecoin (see backlog).
- zerion_staking — reported, never counted.

Also returned: maxfi_drift (per wallet/chain: Zerion rows vs our open rows, with count, value and "portfolio data predates your last MaxFi scan — press Refresh" warnings).

## Double-count guards

- Stablecoins are split out of wallet tokens, never added on top.
- MaxFi principal has one source (Zerion). Its rows and the wallet tokens come from the same fetch, so a close cannot be counted both as an open position and as returned funds.
- MaxFi uncollected is skipped for any wallet/chain where Zerion starts reporting fees on snuggle rows.
- Withdrawn MaxFi lineages (ledger_head_closed) contribute no uncollected fees.
- Hyperliquid (HyperCore) and Zerion's HyperEVM token rows are separate ledgers. [Unverified] an account in Hyperliquid unified-margin mode might report spot collateral inside accountValue; both current accounts show accountValue below their spot USDC, so no overlap today.

## Operating notes

- After closing MaxFi positions: open the MaxFi page and let valuations finish before closing (the scan copies the last valuation as the closing value), then press Scan, then press Refresh on the Dashboard. Otherwise the portfolio data keeps showing closed positions until the next 2-hour snapshot, and the drift check will say "press Refresh".
- The first Dashboard view after a deploy shows Hyperliquid as loading for roughly 10-30 s; the page re-checks every 10 s, up to four requests.
- If /api/portfolio/total fails, the headline falls back to the snapshot total with a "Live total unavailable" note.

## Verification record

- Every landing verified in chat on a fresh clone: diff against the spec, full suite, the real get_portfolio_data run on old and new main with Zerion stubbed (identical output apart from staking_positions), Hyperliquid parsing against the real API's response shapes, and chat-side headless-Chromium checks of every Dashboard change against payloads built from the real routes (normal, loading, cold cache, route failure, warnings, hidden values, keyboard Refresh, zero console errors).
- Production: console snippets measured the before/after headline and the live total's parts; Glenn eyeballed the headline after each deploy.

## Backlog (found, not done)

1. History excludes Hyperliquid and MaxFi fees: adding them to portfolio_snapshots would put a one-time step in the chart and the 24h change (deferred by ruling 8).
2. The Holdings page "Total Value" still uses its own definition (visible non-dust tokens + total_lp_value; no fees, Hyperliquid or lending).
3. gmx_v2 collateral_amount is in token units, but get_portfolio_data's total_value adds it as USD (latent: no GMX positions). The new total counts only stablecoin collateral.
4. total_lp_value is accumulated separately from lp_positions; archived (zerion_lp_hidden) LPs stay in total_lp_value but drop out of lp_positions and the snapshot.
5. A single failed LP lookup marks the whole snapshot run partial, so the snapshot headline and chart silently stay on the previous run; a failed BTC or GMX fetch does the opposite (drops value, run still "completed").
6. The 2-hour snapshot loop sleeps before its first run and restarts on every deploy, so most snapshots come from Refresh.
7. The snapshot fallback path's "Updated" label and the 24h window read naive UTC timestamps as local time (7-hour skew). The live "As of" label reads them correctly.
8. api_spot_price_diagnose keeps its own copy of the stablecoin tuple; bridged stablecoins (USDC.e, USDbC, USDG, USDT0) are in no stablecoin list.
9. get_portfolio_data's fetched_at is a naive server time; the drift check assumes the server clock is UTC.
10. Zerion lending rows default health_factor to 0 rather than none.
11. Zerion does not list MaxFi positions on Base; any Base MaxFi position is missing from the total (none open at close).
12. The weekly manual P/L wallet totals (pl_snapshots.wallet_total_usd) could be filled from the live total.

## Correction — Hyperliquid perp counted twice (found Sep 27, after close)

- Both Hyperliquid accounts hold their perp equity inside spot USDC (unified mode). Probe, 16:48 UTC: Hyperliquid's own total was 1448.23 (Rabby) and 5919.99 (RM), equal to spot USDC, not perp + spot. Hyperliquid docs: "unified account and portfolio margin show all balances and holds in the spot clearinghouse state."
- Effect: the headline and the Hyperliquid pill overstated the total by the perp equity (about $654 at 16:17 UTC). The "Hyperliquid 7,961.59" figure under Ground truth included it. The double-count guard's [Unverified] unified-margin note tested the wrong direction.
- Fix: the account mode is read with userAbstraction. unifiedAccount / portfolioMargin count spot only; disabled counts perp + spot; any other value or a failed read counts spot only, with a warning. Perp stays reported per wallet.
