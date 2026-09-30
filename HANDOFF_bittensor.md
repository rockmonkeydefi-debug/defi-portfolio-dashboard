# HANDOFF — Bittensor (TAO) wallet + Alpha Chasers

Workstream opened Sep 29, 2026 and closed Sep 30, 2026. Goal (Glenn): track the new Bittensor wallet in The Playbook. It holds plain TAO plus the subnet (alpha) tokens that his trading bot, Alpha Chasers, buys and sells. Also measure the bot's result.

## Status

CLOSED. The Bittensor wallet is:
- counted in the Dashboard total, inside Wallet tokens;
- listed on Holdings;
- recorded in snapshot history;
- measured in TAO by the Alpha Chasers card (row 3, under Hyperliquid).

Data source: the Taostats API, account endpoint only. The first snapshot with the wallet ran Sep 29 at 7:38 PM PT. The starting deposit was recorded on the card Sep 30.

## Landings (main)

- bba1043 — Bittensor wallet type (PR #190):
  - SS58 validation: prefix 42, blake2b checksum, stdlib only;
  - classify_wallet_address returns 'bittensor';
  - POST /api/wallets saves type "bittensor", with default label "Bittensor" and a clear checksum error;
  - _wallet_groups: one wallet split for get_portfolio_data and build_custom_token_rows.
- 24bb2f0 — Taostats data path (PR #191): src/connectors/taostats.py, the bittensor_balance_snapshot table, a 15-min background cache, token rows, and the portfolio["bittensor"] status.
- b82eb84 — History rules (PR #191): a Wallet tokens warning clause (ruling 9 in portfolio_total.py); an unavailable wallet's snapshot row is marked failed.
- ae32463 — Frontend only (PR #192): the Dashboard "incl. Bittensor $X" sub-line under Wallet tokens, the Holdings "stale" chip, and the Settings placeholder.
- 0726fd5 — Alpha Chasers backend (PR #193): bittensor_performance.py (pure), the bittensor_flows table, GET /api/bittensor/performance, and POST/DELETE /api/bittensor/flows.
- 5e4a258 — The Alpha Chasers Dashboard card (PR #193, frontend only).
- Tests: 1923 at the start; 1936 after bba1043; 1964 after b82eb84; 1989 after 0726fd5. The frontend commits add none.

## Rulings (Glenn, Sep 29–30)

1. **Data source:** the Taostats API. Glenn created a free key and set it in Railway as TAOSTATS_API_KEY. The key is never pasted into chat, logged, stored or committed.
2. **Fetching:** a background cache with a 15-min TTL, never on a request path.
   - Kicked from GET /api/portfolio, GET /api/portfolio/total, and when a Bittensor wallet is added.
   - Freshened inline before scheduled and manual snapshots.
   - No boot warm-up: after a restart, the last good read from the database is used.
3. **One call per refresh:** GET /api/account/latest/v1 only, so all amounts come from one consistent block (about 14 min behind). The stake-balance endpoint is not used.
4. **Rows** (chain "Bittensor", ASCII symbols, no contract):
   - TAO (free), TAO reserved, TAO root, TAO liquidity;
   - SN<netuid> alpha, one per subnet, summed across hotkeys;
   - TAO other, only when Taostats' total exceeds the parts by more than 0.001 TAO.

   Reserved TAO is counted.
5. **TAO dollar price:** CoinGecko ("bittensor"), fetched in the worker; if missing, the 3-hourly market snapshot at most 6 h old. Alpha rows are valued at balance_as_tao × the TAO price, which is the pool price, not what a sale would return.
6. **Freshness, by Taostats' own timestamp:**
   - up to 1 h old: counted normally;
   - up to 24 h old: counted and flagged "stale";
   - older than 24 h, no data yet, or no TAO price: unavailable. No rows, not counted, and one clause in the Wallet tokens warning line.
7. **Never in api_failures,** because that would mark every wallet's snapshot row partial. Instead, an unavailable Bittensor wallet's portfolio_snapshots row is marked failed, so the run is left out of the Dashboard chart: a gap, not a false dip.
8. **Definition version unchanged (2):** a new wallet is a new holding, not a definition change.
9. **Wallet validation:** the full SS58 checksum is checked in Settings. The wallet split is NOT a strict 0x allowlist: a wallet saved without a type keeps its old grouping.
10. **The bot's trades stay out of the Spot book.**
    - Glenn's Kraken TAO buys stay open on the Spot list, with the note changed to "Alpha Chasers". A transfer is not a sale.
    - Spot positions are never added to the Dashboard total, so there is no double count.
    - The Spot TAO line now acts as the "just held TAO" benchmark.
11. **Alpha Chasers card, measured in TAO:**
    - result = TAO-equivalent now − net TAO deposited;
    - simple % = result ÷ net deposited;
    - dollar gain vs holding TAO = result × today's TAO price.

    Deposits and withdrawals are entered by hand on the card (Deposit/Withdrawal plus a positive amount) and stored as signed whole rao. The card sits under Hyperliquid in row 3.
12. **Hidden values mask every amount on the card:** TAO, dollars and %. The trend line has no numbers and stays visible.
13. **Test data (Sep 30):** public Substrate dev addresses only, and from now on test amounts are scaled, never Glenn's real balances. The Taostats fixture and a few tests merged before this ruling hold real balances and a block number (with swapped addresses). Accepted as-is and not rewritten; git history would keep them anyway.
14. **Trend-line scaling:** left as built (the deposit line is included in the scale). Glenn decides after a few days of data.

## Taostats API: verified facts (live responses, Sep 29–30)

- **Base and auth:** https://api.taostats.io, header "authorization: <raw key>" (no "Bearer").
- **Rate limits:** no rate-limit headers are returned. Free plan: 5 credits/min and 10,000/month (taostats.io/pro). One call per refresh at a 15-min TTL uses at most about 2,900 credits a month.
- **account/latest/v1?address=<ss58>** returns {"pagination", "data": [one account]}. Amounts are strings in rao (1 TAO = 10^9 rao), parsed as int.
- **Identities that held exactly on the real sample:**
  - balance_total = free + staked + reserved + liquidity;
  - staked = alpha_as_tao + root;
  - the sum of alpha_balances[].balance_as_tao = balance_staked_alpha_as_tao.
- **alpha_balances[] entries:** balance (alpha, rao), balance_as_tao (rao), hotkey, coldkey, netuid.
- **Lag:** the account timestamp ran about 11–14 min behind the request. The stake-balance endpoint runs about 30 s behind, but has no free or reserved balance.
- **Reserved balance:** a small one appeared once the bot started. [Inference] A refundable deposit for the bot's permissions.
- **price/latest/v1?asset=tao** works but is not used.
- **Docs:** docs.taostats.io is a JavaScript app that fetchers can't read. The response shapes came from Glenn's PowerShell probe, with the key typed locally and never shared.

## How it's built

- **Wallet split:** _wallet_groups(addresses, wallet_config) returns evm / solana / bitcoin_xpub / bittensor. Bittensor wallets never reach Zerion, custom-token balanceOf reads or GMX.
- **Cache block in web_portfolio.py:**
  - _TAO_CACHE;
  - _tao_refresh_worker: the CoinGecko price first, then one Taostats call per wallet, 13 s apart;
  - _maybe_kick_tao_refresh, _tao_state_for_snapshot, _bittensor_rows.

  Each successful read is upserted into bittensor_balance_snapshot (one row per wallet; not history).
- **get_portfolio_data** appends the rows and a portfolio["bittensor"] status: {wallets: {state, reason, as_of, age_hours, tao_amount, value_usd, price_usd, diff_tao, ...}}. No network call on page loads.
- **Snapshot runs:** _get_portfolio_data_for_snapshot freshens the cache inline, then builds. take_portfolio_snapshot marks an unavailable Bittensor wallet's row failed.
- **portfolio_total.compose_total:**
  - the rows count in Wallet tokens;
  - detail["bittensor"] carries the statuses;
  - ruling 9 adds one clause to the Wallet tokens line (stale / not counted / parts differ).
- **Alpha Chasers:**
  - bittensor_performance.py is pure. TAO-equivalent per snapshot run = the sum of the wallet's row values ÷ that run's TAO price. This is exact, because every row in a run was valued at one price. Alpha-only runs use the market price within 6 h.
  - GET /api/bittensor/performance is read-only and cache-only. Rows from failed runs are excluded.
  - bittensor_flows: id, wallet, flow_at (a date is stored as T00:00:00+00:00 UTC), amount_rao (signed), note, created_at.
- **Frontend:**
  - Dashboard sub-line: _dashBtSub;
  - card: DashAlphaChasersCard / DashAcWalletCard;
  - Holdings "stale" chip on source "taostats" rows with tao_stale.

## Operating notes

- **Adding the wallet:** add a Bittensor wallet in Settings (the address starts with "5"; the checksum catches typos). Adding it kicks the first Taostats read. Click Refresh about 30 s later.
- **When data appears:** new Taostats data reaches Holdings and the total on the next portfolio rebuild (Refresh, or the 2-hour snapshot), not on every page load.
- **"Bittensor not counted — no Taostats data yet":** the first read hasn't landed, TAOSTATS_API_KEY is missing, or Taostats is failing. GET /api/portfolio → "bittensor" shows the state, reason and error.
- **Deposits:** record every TAO deposit or withdrawal on the Alpha Chasers card, or it counts as bot performance. Deposits should add up to what actually arrived in the wallet; the wallet's taostats.io page lists incoming transfers.
- **Return %:** the simple % is exact for one deposit. With several deposits, late ones get full credit; a time-weighted return is a later option.
- **Valuation:** alpha rows are valued at the pool price. A sale would realize somewhat less, more so on thinly traded subnets.

## Verification record

- Every PR was verified by chat on a fresh clone: the diff against the block, the full suite, then a fast-forward of main to the reviewed head, with main's tree equal to the reviewed tree.
- Replays:
  - the parser and rows on the real account response (7 rows summing exactly to Taostats' total);
  - the stale and unavailable states;
  - the performance route on real-shaped snapshot rows (failed run excluded; the deposit stored in whole rao).
- Headless browser checks against the real static files: the sub-line, the Holdings chip, and the card in six states, with hidden values and an 11px minimum text size.
- Production:
  - the live report showed state "fresh" and 7 rows summing to the status value within $1;
  - the Dashboard sub-line and the card rendered as expected;
  - the card's result matched hand calculation.

## Backlog (found, not done)

- **Trend-line scaling:** Glenn decides after a few days of data (keep the deposit line in the scale, or scale to the trend only).
- **Time-weighted return,** if deposits become frequent.
- **Alpha Chasers API/export:** Glenn asked the developer (reply pending). It would allow a cross-check against the bot's own numbers.
- **Automatic deposit detection** from Taostats transfer history. Needs a sample response and uses extra credits.
- **tests/conftest.py:** a suite-wide no-op guard for the Taostats refresh thread, like the DexFi and Hyperliquid guards.
- **Dashboard:**
  - loadBtPerf has no guard against an older response arriving last;
  - the Spot P&L card stretches to the taller row-3 right column;
  - mixed minus signs on the card's result line (hyphen vs U+2212).
- **Holdings:**
  - a React "unique key" warning from a fragment without a key in TokenHoldings' grouped.map. It predates this work;
  - the "custom" chip is 10px, below the 11px minimum;
  - the stale chip's hover text shows a raw ISO time.
- **Wallet handling:**
  - _maxfi_tracked_wallets ignores the wallet type (a Bittensor wallet flagged maxfi would be scanned as EVM);
  - POST /api/wallets returns 500 instead of 400 on a request with no JSON body.
- **Taostats worker:**
  - it fetches the CoinGecko TAO price even when TAOSTATS_API_KEY is missing;
  - the /api/portfolio kick reads wallet_config.json on every call.
