# HANDOFF — MaxFi Ledger (vault-event indexer for basis / claims / exit)

Rulings locked 2026-09-19. Baseline at lock: main @ 50d127e970a81c4eec1bffd5211cd2a0b8afa9ca, 1138 tests. Parent context: MaxFi auto-tracking scoping (Sep 18) — Glenn wants basis, claims, and exit value derived from on-chain vault events instead of hand-entered, motivated by the expectation that he will forget to log them. The "pre-tracking era unattributable" ruling is REOPENED on evidence from a community tool (MaxFi Position Ledger, portfolio.passivista.com) that reconstructed 59 positions / 47 closed for wallet 0xaB7A…6743 purely from indexed vault events — it was unattributable from this project's DB, not from the chain. HANDOFF_scheduler.md (landed cf87c9b, re-ranked 50d127e) is NOT a precondition for this — event data doesn't depend on the app observing on a cadence, and this doc does not sequence behind it.

## Purpose

Build an event-sourced ledger for MaxFi positions — deposits, fee claims, rebalance compounding, closes — derived from indexed vault/pool events rather than inferred from periodic state snapshots or typed by hand. The ledger becomes the source Commit-1-and-later feed `maxfi_claims` / `maxfi_initial_value` from, so the advisor's existing reads stay correct without depending on Glenn remembering anything.

## Session-1 probe: what this scoping chat could and could not establish

HARD CONSTRAINT compliance note first: this session's sandbox blocks network egress to every RPC/explorer/DeFi-data domain tried — `rpc.mainnet.chain.robinhood.com`, `robinhoodchain.blockscout.com`, `api.etherscan.io`, and (via WebFetch, which routes differently) even `en.wikipedia.org` all returned a policy-denial 403 from the egress proxy (confirmed via `/__agentproxy/status`: "organization policy... do not retry"). The local `data/portfolio.db` in this sandbox has zero rows in `maxfi_positions` — it's a fresh/empty dev DB, not a production mirror. So this was NOT the live feasibility probe the opening brief asked for; it's the codebase- and web-search-grounded portion only. **The actual live-chain probe (items a/c/e below, and (b)'s real block-range number) has NOT run and is carried forward as Commit 1's own gating step-1, not assumed here.**

### Established from the codebase (high confidence, cite-and-verify only)

- **Zero event/topic infrastructure exists for MaxFi.** `maxfi_client.py` (1435 lines) is 100% raw `eth_call`-via-`requests`, hand-rolled 32-byte-word ABI encode/decode, no web3.py `Contract` object, no event ABI, no topic constant anywhere. Its 12 function selectors (`SEL_LENS_VAULT`, `SEL_POSITIONS`, `SEL_POOL_SLOT0`, etc.) are all *read* calls. It does already have `eth_block_number(chain)` (raw JSON-RPC, reusable for block-range math) and `rpc_call`'s per-chain `requests.post` pattern is the template any new raw `eth_getLogs` helper should mirror if this module stays dependency-free (a choice to make in Commit 1, not here).
- **`w3.eth.get_logs` / topic-based log fetching already exists, but for a different feature on different chains.** `web_portfolio.py` (~831-940, ~1016-1140) fetches `Transfer` (mint) and `Collect` events for generic Uniswap-V3-position tracking on chains 1/42161/8453 (Ethereum/Arbitrum/Base) — never chain 4663 (Robinhood). Pattern: Etherscan V2 API first when `ETHERSCAN_API_KEY` + a supported chain ID, falling back to `w3.eth.get_logs` with chain-aware chunked block scanning (lookback + chunk_size per chain). `src/connectors/uniswap_v4.py` documents the same "bounded chunked RPC get_logs scan" discipline at its header. Both are real, reusable PATTERNS — chunking discipline and `Web3.keccak(text=...)` topic encoding — even though neither is wired to the MaxFi vault or Robinhood chain today.
- **MaxFi positions are confirmed standard Uniswap V3**, not V4: `maxfi_client.py` calls the standard NPM's `positions(uint256)`, `factory.getPool(token0,token1,fee)`, pool `slot0`/`ticks` — the exact shape `uniswap_v3`-style tooling expects. This matters: the `Collect(uint256,address,uint256,uint256)` event `web_portfolio.py` already fetches for the *other* feature (~1029, `collect_topic = Web3.keccak(text="Collect(uint256,address,uint256,uint256)")`) is the STANDARD NPM event fired whenever fees are collected from any V3 position — vault-owned positions included, if the vault calls the standard NPM's `collect()` internally. That's a promising, code-grounded lead for probe item (a) — a well-known, publicly-documented event on the standard `position_manager` address already in `CHAINS[chain]["position_manager"]`, as a probable cross-check against the vault's own custom `FeesHarvested` (whose exact field layout is still unconfirmed). Not proven; Commit 1 step-1 confirms whether the vault actually routes through the standard NPM's `collect()` or handles it internally.
- **Pricing math for a Swap-log-derived price already exists and is reusable as-is.** `maxfi_math.sqrt_price_x96_to_price(sqrt_price_x96, decimals0, decimals1)` decodes a `sqrtPriceX96` fixed-point value to a token1-per-token0 price using `Decimal` throughout (precision-safe for on-chain magnitudes) — this is the exact field format a Uniswap `Swap` event carries, so the pricing engine's core math is zero-new-code, not a new module to write from scratch. `SEL_ERC20_DECIMALS` already exists for the decimals side of the same call.
- **Rebalance semantics are already partially solved in this codebase — by inference, not events.** `maxfi_orchestration.py`'s `run_scan_and_persist` (C1.2/C1.4) already detects a "rebalance" purely by diffing consecutive position scans: a `token_id` change at the same `array_index` within one pass. On detection it (1) stamps `last_rebalanced_at`, and (2) if the OLD row's `last_uncollected_usd` (a scan-time valuation snapshot, not a chain fact) was a finite positive number, zeroes it and inserts a `maxfi_claims` row with `set_by='system'`, `note='auto: rebalance sweep, estimated from last_uncollected_usd'`. This is a real, working ESTIMATE this project already ships — and exactly what the event ledger should supersede with an exact, event-derived figure. It's also the natural reconciliation target: once the ledger exists, every `set_by='system'` estimate row should be diffable against what the actual rebalance-tx events say.
- **Chain config**: Base RPC via `BASE_RPC_URL` (Alchemy); Robinhood via a single public RPC URL literal, already flagged in `HANDOFF_scheduler.md`'s ground truth as "documented as shared/rate-limited — not for production traffic." That caveat matters more here than it did for the scheduler's light diagnostic-call volume: a log-heavy historical backfill against the public RPC is a worse idea than against it for a handful of `eth_call`s. Prefer Blockscout's HTTP API for backfill; the RPC only for narrow, incremental go-forward tailing if events prove cheap to poll that way.
- **`maxfi_schema.py` uses its own migration mechanism** — inline `ALTER TABLE ... ADD COLUMN` wrapped in try/except per column, directly in `init_db()`, NOT `portfolio_db.py`'s centralized `migrations` list. A new ledger table follows this module's own `CREATE TABLE IF NOT EXISTS` convention (same file), not the other module's.
- **Existing tables to reconcile with, exact columns confirmed live in this repo**: `maxfi_positions` (id, chain, wallet, token_id, array_index, pool_address, token0/1_address, fee_tier, status, first_seen_at/_source/_block, last_scan_at, closed_at, + additive last_value_usd/last_uncollected_usd/last_rebalanced_at), `maxfi_initial_value` (position_id PK, source, initial_value_usd, set_at, set_by — "100% manual_override today" per the opening brief, not contradicted by anything found here), `maxfi_claims` (id, position_id, claimed_at, token0/1_symbol/amount, sold_at, proceeds_usd, note, set_at, set_by — no FK, no unique constraint, by design, duplicates on one day are legitimate), `maxfi_position_lineage` (auto-splits only — departing/arriving position_id, split_group_id, arriving_current_value_usd, created_at — confirmed NOT a rebalance-history table, a different mechanism entirely for a different event: N-departing/M-arriving compaction splits, not 1:1 rebalances).

### Established from WebSearch (external, not independently chain-verified)

- MaxFi is a real, live protocol (Robinhood Chain, Base, Arbitrum) charging a "15% performance fee on LP earnings only, never on principal" — consistent with the Guide's 85/12/3 split (which sums to 15%). Uses "zero-swap" / single-sided rebalancing (no swap occurs on rebalance) — consistent with the Guide's "no swap occurs" rebalance rule.
- Robinhood Chain's Blockscout `eth_getLogs` is capped at **1,000 log records per call** (a Sep 2026 Blockscout blog post, described as a recent rate-limit tightening "to improve overall responsiveness for all users" — a real, current number, not the Guide's own claim). Blockscout's Pro API base is `https://api.blockscout.com` with a `chain_id=4663` query param; the free-tier explorer itself is at `robinhoodchain.blockscout.com` with API docs at `/api-docs`. An API key is optional but raises rate limits.
- No public source surfaced the MaxFi vault's actual contract address, its verified ABI, or the `FeesHarvested` event's exact field layout. That information — the load-bearing fact this whole workstream depends on — is not publicly documented and was not retrievable in this session. It has to come from Blockscout's verified-contract endpoint for the LIVE-RESOLVED vault address (`get_vault(chain)` in `maxfi_client.py` resolves it via `lens.vault()`, but the actual RPC call itself was blocked here too).

### Genuinely unresolved — carried forward as Commit 1's own gating step-1, not decided here

(a) The vault's actual emitted events (confirmed field-by-field, not inferred) — needs a live call this session couldn't make.
(b) The real historical block range for wallet 6743's full MaxFi activity on both chains, and how many chunked `eth_getLogs` calls that costs against the confirmed 1,000-record cap — needs `first_seen_block` data this session had none of (empty local DB) plus a live `eth_blockNumber`/historical-lookup call.
(c) Whether claim-day prices are reconstructable from `Swap` event logs alone (any full node suffices) or require historical pool STATE at a past block (an archive node) — the single biggest cost fork per the opening brief, and this session could not test either path.
(d) Confirmed from the codebase (see above) as much as inference-without-events allows; the event-level confirmation (does a compounding rebalance appear as an NPM burn+mint, a vault-internal event, or something else) is still open.
(e) The reconciliation baseline (one closed position Glenn knows cold, diffed against events) — needs both live chain access and a wallet Glenn identifies; neither was available here.

## Why "beside" not "replace" (ruled — do not reopen)

The event ledger runs alongside `maxfi_claims`/`maxfi_initial_value` in v1, syncing INTO them rather than replacing them or having the advisor read the raw ledger directly. Two independent reasons, both grounded in what this session actually found: (1) the existing C1.4 rebalance-sweep estimate is production code the advisor already depends on — an untested direct swap for event-derived numbers is exactly the kind of change that needs a clean-diff proof before it's trusted, not a leap of faith; (2) the live-chain unknowns above (a/b/c) are large enough that "replace" could turn out to be infeasible in v1 for cost or archive-node reasons neither this session nor the opening brief could rule out. "Beside first" costs nothing if the live probe comes back easy, and is the only responsible choice if it doesn't.

## Deferred / explicitly NOT this workstream

- Any code. This is a scoping doc; Commit 1 starts in a fresh chat.
- Replacing the advisor's read path (`maxfi_claims`/`maxfi_initial_value` reads) with direct ledger queries — a later promotion, only after one full reconciliation pass on production is reported clean (mirrors the scheduler doc's own ruling-7 production-diff discipline).
- The scheduler's incremental-ingest-as-a-timer-job idea — real, but only after both this ledger and the scheduler exist independently and have each been observed for a few cycles.
- Any change to `maxfi_position_lineage` or the auto-split mechanism — a different event entirely (N-departing/M-arriving compaction), out of scope here.
- Trusting the MaxFi Position Ledger tool (portfolio.passivista.com) as a data SOURCE. It's a spec to mirror and a number to sanity-check against, never queried live, never assumed authoritative without this project's own independent event read.

## Rulings (locked, do not reopen)

1. **Source of truth**: event index runs BESIDE `maxfi_claims`/`maxfi_initial_value` in v1 (reconciliation view), not a replacement. Promotion to "advisor reads the ledger directly" is a later, separate ruling gated on one clean production reconciliation pass.
2. **Storage**: a new raw-events table (chain, block, tx_hash, log_index, event_type, token_id/position identifier, raw on-chain amounts, the derived 85/12/3 split, price_at_block, price_source) plus a derived per-position ledger computed FROM those raw events, never hand-written — mirrors `maxfi_schema.py`'s own `CREATE TABLE IF NOT EXISTS` + inline-ALTER convention, not `portfolio_db.py`'s centralized migrations list. A sync step feeds `maxfi_claims`/`maxfi_initial_value` FROM the derived ledger; the advisor's own read path is untouched in v1.
3. **Pricing engine**: its own pure module, decoding `Swap` event `sqrtPriceX96` via the ALREADY-EXISTING `maxfi_math.sqrt_price_x96_to_price` — reused, not reimplemented. A parity harness against the Ledger tool's displayed numbers for a handful of positions is Commit 1's own proof step, run only after probe item (c) confirms the Swap-log-vs-archive-node question — this ruling does NOT presume the answer.
4. **Backfill**: in scope (the reopened ruling means history matters), attempted first for wallet-scope only (not every MaxFi wallet or every other user), as Commit 1 step-1's own deliverable. Go-forward-only is the explicit fallback if the live probe shows backfill is too expensive (log-call budget, archive-node requirement) — not the starting assumption, and not decided here.
5. **Fee basis**: "Claimed" (fee value at claim-day price, no sale-matching) is what the advisor's run-rate consumes in v1 — matches "what the pool paid," needs no sale-matching to be useful. "Locked" (post sale-matching) is a v2 display-only addition once the Claimed path is proven.
6. **Cadence**: on-view / manual-button in v1, same as every other MaxFi diagnostic route today. Does NOT wait on `HANDOFF_scheduler.md` landing, and does not need to — event data doesn't depend on the app observing on a cadence. Incremental event-ingest as a scheduler job is an explicit, named v2 follow-on, only after both workstreams exist independently.
7. **Reconciliation target**: every `maxfi_claims` row with `set_by='system'` (today, only the C1.4 rebalance-sweep estimate) is the first thing the ledger's output gets diffed against once it exists — a concrete, in-production accuracy check that doesn't require Glenn to remember anything either.
8. **Commit plan**: Commit 1 is READ-ONLY chain probing to close items (a)/(b)/(c)/(e) above — it changes no schema and writes nothing; it must run wherever it has real RPC/Blockscout egress (this scoping session did not) and a wallet Glenn can eyeball. Only after that report lands does architecture get finalized in a follow-up scoping pass (raw-event table's exact columns depend on the ACTUAL event fields, not guessed ones) — implementation Commits proper (schema + backfill + sync-into-existing-tables + advisor-facing display) are numbered from there once that pass locks them.

## Next

A fresh chat pointed at this doc opens with the still-open live probe (a)/(b)/(c)/(e) from the Session-1 section above, in an environment with real network egress to Blockscout/RPC endpoints (or with Glenn running a handful of curl/Blockscout-API calls by hand and pasting the results in) and, ideally, a production DB snapshot with real `maxfi_positions` rows to reconcile against — neither of which this scoping session had. That probe's findings get appended to this doc (not silently assumed), and only then does the schema for the raw-events table get finalized and the first implementation commit start.

## Live-chain ground truth (2026-09-18/19, verified from Blockscout on Base — closes probe items a, d; narrows b, c; e still open)

Source: Base vault proxy 0x7D27CDfBFcC878F7E7349e216d44204BFd2AFd55 → implementation `SnuggleVaultUpgradeable` 0x359F90EE4c2e21Cbf6e32c5a062Eeef306822D28 (verified source + ABI pulled), one deposit tx (0xa8544cd3…8520c, block 51494861) and one harvest tx (0x8e94acf7…034c4, block 51497380), both on wallet 0xaB7A…6743, tokenId 6039568. Robinhood Chain vault is 0x8eABB4E117fB70b346592e013855f6d825F50af1; its implementation ABI was NOT pulled (RH Blockscout bot-blocks automated fetches) — same codebase is the working assumption, to be confirmed in step 1 via the api.blockscout.com free-key route (chain_id 4663) or a browser paste.

**Contract shape.** MaxFi = "Snuggle" (snuggle.fi). Vault is a TransparentUpgradeableProxy (upgradeable ⇒ key on the proxy address, store raw topics beside decoded fields). Uniswap V3 NPM on Base = 0x03a520b32C04BF3bEEf7BEb72E919cf822Ed34f1. Token flow passes through a per-pool `positionAdapter` contract (0xca4cF963… on Base) between vault and NPM — not needed for the ledger. Vault init: `performanceFeeBps=1500`, `referralFeeBps=300`; `feeExempt` users pay 0%.

**The NFT is minted TO THE VAULT, never to the wallet.** Ownership lives only in vault events (`owner` indexed). Wallet-scoped backfill = `eth_getLogs` on the vault filtered by owner topic — cheap, exact, and not a wallet-transfer scan.

**Event contract (vault, all decode by name):**
- `PositionCreated(uint256 indexed tokenId, address indexed owner, bytes32 indexed poolId, int24 tickLower, int24 tickUpper, uint128 liquidity, bool autoSnuggleEnabled)` — open. NOT emitted for rebalance-minted tokenIds (see SnuggleRebalanced).
- `PositionWithdrawn(uint256 indexed tokenId, address indexed owner, uint256 amount0, uint256 amount1)` — close. Amounts are NET (what the wallet received) and INCLUDE the net fees harvested in the same tx (withdraw also emits FeesHarvested). Exit principal = PositionWithdrawn − (FeesHarvested × 0.85) from the same tx; do not double-count.
- `FeesHarvested(uint256 indexed tokenId, address indexed owner, uint256 fees0, uint256 fees1)` — GROSS trading fees. Emitted on harvest, withdraw, claimStakingRewards, and inside every executed rebalance; also on a skipped rebalance's unstake-fees path.
- `SnuggleRebalanced(uint256 indexed oldTokenId, uint256 indexed newTokenId, address indexed owner, int24 newTickLower, int24 newTickUpper, uint256 protocolFee0, uint256 protocolFee1, bool wasManual, uint32 totalRebalances)` — lineage old→new. `protocolFee*` = the 15% taken. Rebalance = decreaseLiquidity + collect + mint new + burn old, no swap; dust returned to owner. Position identity across rebalances is THIS chain of events — it supersedes maxfi_position_lineage's auto-split-only coverage.
- `RebalanceSkipped(tokenId, tickLower, tickUpper, reason)`; `ParametersUpdated`; `OutOfRangeStatusUpdated`; `ReferrerSet`; `ReferralPaid`; `StakingRewardsClaimed`; `PerformanceFeeCollected` (reward tokens only, not trading fees).
- `positions(tokenId)` view carries `cumulativeFees0/1` (lifetime gross) and `depositTimestamp` — a cheap cross-check for the derived ledger.

**Events on the StakingManager contract (0x4994743d7183d2ea5c651292A9Dab2C781020638 on Base — a separate emitter the indexer MUST also read):**
- `ProtocolFeesDistributed(uint256 indexed tokenId, uint256 treasury0, uint256 treasury1, uint256 referral0, uint256 referral1)` — the actual split per harvest. Net to user = FeesHarvested − treasury − referral. Read this, never assume 85/12/3.
- `FeesCompounded(tokenId, owner, amount0, amount1)` — the reinvested side on a compounding rebalance → PRINCIPAL, never fees (the Guide's rule, now event-backed).
- `FeesHarvestedDirect(tokenId, owner, amount0, amount1)` — the side sent to the wallet on a rebalance.

**Split verified to the wei (harvest tx):** FeesHarvested gross 242,214,271,699 wei WETH / 583 µUSDC; treasury 36,332,140,754 / 87 (=15%); wallet received 205,882,130,945 / 496 (=85%); referral 0/0. Glenn's wallet has NO referrer ⇒ his split is 85/15/0. The Ledger Guide's 85/12/3 is the referred-user case only.

**Basis is exact, not inferred.** Deposit tx carries NPM `IncreaseLiquidity(tokenId, liquidity, amount0, amount1)` (0.001905 WETH + 5.000000 USDC) plus an in-tx dust refund vault→wallet (0.0000032 WETH). Block timestamp = mint time. Only pricing at that block remains. Ruling 3's "snapshot-inference fallback" is needed only for positions with no reachable mint event.

**poolId is a bytes32 hash, not the pool address.** Pool address is derivable per tx from the `Mint`/`Collect` emitter (0xd0b53D92… here) and from `PoolAdded(poolId, pool, token0, token1, fee, …)` on the vault — index PoolAdded once to build the poolId→pool/token0/token1 map.

**Still open → Commit 1's read-only deliverable:** (b) getLogs depth/cost on RH via the free-key route (Base served unauthenticated; RH bot-blocks direct); (c) Swap-log pricing unexercised (no swap in either tx — structurally sound, verify one pool's Swap log carries sqrtPriceX96 as expected); (e) reconciliation baseline against maxfi_claims / maxfi_initial_value rows for 6743.

## Live-chain ground truth — Sep 19 addendum (RH vault, multi-NPM key, pricing, explorer caps, fixtures)

**Correction — RH addresses in the Sep 18 section were wrong.** `0x8eABB4E117fB70b346592e013855f6d825F50af1` is LI.FI's `Permit2Proxy` (constructor points at LiFiDiamond `0xB477751B76CF82d00a686A1232f5fCD772414Af3`), not a MaxFi vault, and RH tx `0xcc928b03…78383` (block 66,666,962, 2026-09-19 00:50 UTC) was a Jumper/Across bridge of 50 USDG → 49.966423 USDC to Base for wallet 0xaB7A…6743, not a deposit. The Sep 18 RH "vault" line and "deposit tx" reference are superseded by this section.

**RH vault verified (harvest tx `0x8b85529ed2b5865081c8aa5c46ed847958f53ab01a946ecf33b4a27bb8d6b429`, block 66,753,780, 2026-09-19 03:16 UTC, tokenId 908769, WETH/ChumpCoin pool `0x714442e9A611f8561A7dF108D6d925132937cFb8`):**
- RH vault (proxy, key on this): `0x1195C074F898b7644bA732407619c9804dFE6DCE` → implementation `SnuggleVaultUpgradeable` `0x999A74ddFde1575C4db454A0300d5F0351A891dE` (verified). Same codebase as Base: `FeesHarvested` topic0 `0x452b22f6…` identical.
- RH StakingManager: `0xBfD8cf8094feee44C314B3d5ec49ccDfd80caBAe` (emits `ProtocolFeesDistributed`, topic0 `0x017fe984…`, identical to Base).
- RH Uniswap V3 NPM: `0x73991a25C818Bf1f1128dEAaB1492D45638DE0D3` (fresh deployment; tokenIds are 6-digit).
- RH WETH: `0x0Bd7D308f8E1639FAb988df18A8011f41EAcAD73` (an `aeWETH` proxy — never hardcode the mainnet WETH9 address).
- Split verified to the wei on RH: gross 1,920,374,570,879,319 wei WETH → treasury 288,056,185,631,897 (15.00%, floored) + wallet 1,632,318,385,247,422 (85%), referral 0; same 15/85/0 on the CHUMP side (24.646 of 164.308). NPM `Collect` amounts == vault `FeesHarvested` amounts. 85/15/0 now holds on both chains.
- RH block time ≈ 0.1 s (block 66.75M at the same hour Base was at 51.5M): a chunk size expressed in blocks covers ~20× less wall-clock on RH than Base — chunk size must be chain-aware (see `src/connectors/uniswap_v4.py` chain config).

**Base backfill cost (measured, Sep 19):** owner-topic-filtered `PositionCreated` on the Base vault from block 0 returned **13 events in one page**, blocks 44,609,025 → 51,494,861 (2026-04-11 → 2026-09-18). Wallet-scoped backfill is trivially cheap on Base.

**RULING 9 — ledger key is `(chain, vault, npm, token_id)`, not `(chain, token_id)`.** The 13 Base `PositionCreated` tokenIds are 4,954,839 / 4,956,448 / 5,884,225 / 5,972,982 / 5,973,070 / 5,973,556 / 5,973,562 / 6,039,568 (Uniswap V3 NPM `0x03a520b3…`) and 67,658,300 / 67,661,111 / 67,701,581 / 67,833,581 / 67,834,188 (April 2026, poolIds `0xf96a2bd0…` and `0x2432c262…`) — the latter are a **different position manager** (vault is multi-DEX via `allowedPositionManagers` / per-pool `positionAdapter`). tokenId is unique only per NPM. Resolve the NPM per pool: `PoolAdded` → `positionAdapter` → `positionManager()`, and read `IncreaseLiquidity` / `Collect` / `Transfer` from that NPM, never from a single hardcoded one.

**RULING 10 — claim-time pricing = last `Swap` log at or before the target block on the position's pool; exact, not approximate.** A V3 pool's `sqrtPriceX96` changes only on `Swap` (mint/burn/collect do not move price), so the most recent Swap ≤ B is the pool price at B regardless of how far back it is; the only fallback is the pool's `Initialize` event for a never-swapped pool. `Swap` data layout (non-indexed words, in order): `amount0 (int256), amount1 (int256), sqrtPriceX96 (uint160), liquidity (uint128), tick (int24)`; topics 1–2 are `sender`, `recipient`. Decode with `maxfi_math.sqrt_price_x96_to_price` and the pool's token decimals. Verified on Base ETH/USDC 0.05% `0xd0b53D9277642d899DF5C87A3966A349A798F224` at block 51,494,865: tick −197,610 → ≈ $2,621/ETH, matching the swap's own amounts (24.874 USDC for 0.009490 WETH). Non-stable pairs (meme/WETH, e.g. RH tokenId 908769) need a second hop through the chain's WETH/USDC pool at the same block. Pricing never range-scans a pool: walk backward from B in small chunks and stop at the first Swap.

**Explorer limits (measured):** both `base.blockscout.com` and `robinhoodchain.blockscout.com` cap `getLogs` at 1,000 rows and **truncate silently** — Base returned `status:"1"` with no warning for a 51,494,861–51,497,380 Swap query and stopped at 51,496,256 (the ETH/USDC pool does ~1,000 swaps per ~45 min). RH's Etherscan-compatible `module=logs` returns `"Unknown module"` (not served). RH Blockscout also bot-blocks automated fetches; `api.blockscout.com?chain_id=4663` (free key) is the only RH explorer route worth trying from Railway.
**RULING 11 — ingest uses RPC `eth_getLogs` on both chains** via the `uniswap_v4.py` bounded/chunked pattern (RPC errors loudly on oversize ranges; the explorer truncates quietly). Explorer APIs are chat-probe and fixture-capture tools only.

**Bridge classification:** Across `FundsDeposited` (SpokePool `0xD29C85F15DF544bA632C9E25829fd29d767d7978` on RH) and LI.FI `LiFiTransferStarted` are cross-chain transfers of principal — the ledger must classify them as transfers, never as position exits or claims. The Sep 19 USDG→USDC bridge is the wallet-hygiene case in practice (`pl_flows`).

**RULING 12 — fixture-based tests.** Commit 1's ingest/decoding is built and tested against recorded JSON under `tests/fixtures/maxfi_ledger/`, never live calls: the Claude Code sandbox has no egress to RPC/Blockscout (hard org-policy denial), Railway does. Seed fixtures from this session's captured responses: Base `PositionCreated` (13 rows), Base Swap page (first ~20 rows suffice), Base harvest tx logs (tokenId 6039568), RH harvest tx logs (tokenId 908769), RH bridge tx logs (negative case).

**Still open for Commit 1:** (e) reconciliation baseline — `maxfi_claims` and `maxfi_initial_value` rows for Base tokenId 6039568 and one closed RH position — owed by Glenn; Commit 1's derived-ledger schema is not final until it is seen. Probe items (a)–(d) are CLOSED by this addendum.

## Reconciliation baseline — Sep 19 (probe item (e) CLOSED)

**Source:** production `GET /api/maxfi/positions/<chain>/<wallet>` and `GET /api/maxfi/positions/<id>/claims` for wallet 0xaB7A…6743 (route lookup in cda8823: the claims route returns raw `maxfi_claims` rows; the positions route returns raw `initial_value_usd` / `initial_value_source` and derived `claimed_usd`). The `<id>` in the claims route is the `maxfi_positions` primary key, not the NFT tokenId.

**What a manual claim row holds (schema fact):** `claimed_at` is a bare DATE (no time, block, or tx hash); `proceeds_usd` is one USD number; `token0_amount`, `token1_amount`, `token0_symbol`, `token1_symbol`, `sold_at` are NULL on every observed row; `set_by='glenn'` on all three. There is nothing to join on except position and date.

**RULING 13 — reconciliation match key is `(position_id, claimed_at ± 1 day)`, compared on USD within tolerance.** Never on tx hash or token amounts (the manual side has neither). The ledger's claim rows carry strictly more than the manual rows — block, tx hash, gross and net per token, price at block — which is the promotion argument. Tolerance and the "unmatched on either side" report shape are Commit 2 decisions.

**RULING 14 — `first_seen_block` / `first_seen_at` on `maxfi_positions` are scan-observation values, not mint values,** and the reconciliation view must never flag their disagreement with the ledger's `PositionCreated` block/timestamp as an error. Evidence: 20 August RH rows carry `first_seen_block` 47,834,178–47,834,373 (~200 RH blocks ≈ 20 s) while `first_seen_at` spans Aug 16–28; Base id 132 shows 51,499,351 vs its true mint block 51,494,861.

**Baseline cases (test fixtures for Commit 2's reconciliation view):**
- **Base id 132, tokenId 6039568 (WETH/USDC 0.05%, open):** DB `initial_value_usd` NULL, claims `[]`, `claimed_usd` 0. Chain: exact basis at block 51,494,861 (0.001905 WETH + 5.000000 USDC, `IncreaseLiquidity`), harvest at 51,497,380 (gross 242,214,271,699 wei WETH + 583 µUSDC; wallet net 85%). Expected reconciliation output: ledger-only basis, ledger-only claim, no manual counterpart.
- **RH id 1, tokenId 891560 (WETH/HMM 1%, closed 2026-09-08 via manual_ui, `closing_value_usd` NULL, basis $210 manual_override):** one manual claim id 18, $239.00, `claimed_at` 2026-09-07. [Speculation] A single claim above basis the day before a close with no recorded exit value may be withdrawal proceeds logged as a claim. Ledger test: if `PositionWithdrawn` for 891560 exists in that window, split it as exit principal = `PositionWithdrawn − FeesHarvested×0.85` and report the manual $239 as "matches withdrawal, not fees"; the advisor's `claimed_usd` for this position would then be overstated.
- **RH id 112, tokenId 1063377 (cbBTC/MSTR 0.3%, closed 2026-09-12, `closing_value_usd` 268.44 manual, basis $284 manual_override):** one manual claim id 31, $19.86, `claimed_at` 2026-09-09. Clean case: ledger should reproduce a ~$19.86 claim (within pricing tolerance) and an exit value near $268.44 independently.

**Also visible in the dump (lineage evidence):** Base tokenIds 5890746 (id 29) and 5984382 (id 113) are in the DB but absent from the on-chain `PositionCreated` list for this wallet → rebalance-minted children with no recorded parent. Only `SnuggleRebalanced` lineage attaches their basis to the originating deposit; `maxfi_position_lineage` does not cover them.

**Status:** probe items (a)–(e) all CLOSED. Commit 1 (raw-events + derived-ledger tables, fixture-tested, no writes to `maxfi_claims` / `maxfi_initial_value`) is unblocked and runs in a fresh chat pointed at this document.

## Commit 1 landing note — two open items for the ingest commit (Sep 2026)

Commit 1 (raw-events + derived-ledger schema, `maxfi_ledger.py`,
fixture-tested) landed on main at `1e1b65aecd130b8d0d467a56ed18ad00d3259399` — 31 new tests
(1138 → 1169), zero diff on `maxfi_claims`/`maxfi_initial_value`/
`maxfi_positions`. Two gaps surfaced during that commit's own build,
recorded here rather than silently carried forward:

**`PoolAdded` is NOT decoded — 8-of-9 tracked vocabulary, not 9-of-9.**
This event's signature in this doc's own "Event contract" section ends
in an ellipsis (`PoolAdded(poolId, pool, token0, token1, fee, …)`) — the
full field list was never captured live, so Commit 1 could not compute a
verifiable topic0 without guessing. `maxfi_ledger.py`'s decode dispatch
table has no entry for it. Whoever needs the poolId→pool/npm mapping
(ruling 9's NPM resolution depends on this) must first pull the full
verified signature from Blockscout's contract ABI for the vault
(`SnuggleVaultUpgradeable`, Base `0x359F90EE4c2e21Cbf6e32c5a062Eeef306822D28`)
before a decoder can be written and tested.

**`FeesCompounded`/`FeesHarvestedDirect` topic0s are `[Inference]`, not
fixture-verified.** This doc's own event contract gives only field NAMES
for these two StakingManager events (`tokenId, owner, amount0, amount1`),
never types or indexed-ness. Commit 1 inferred
`(uint256 indexed tokenId, address owner, uint256 amount0, uint256 amount1)`
by strict analogy to `ProtocolFeesDistributed`'s tokenId-only-indexed
shape (same contract, same StakingManager). No fixture contains either
event — Commit 1's fixture set has no real SnuggleRebalanced/compounding
transaction — so this is untested against real chain data, only against
synthetic scenarios in `tests/test_maxfi_ledger_derive.py`. A wrong hash
here fails silently (`decode_log` returns `None` forever on real logs of
that type, no exception) — currently harmless because nothing calls
`maxfi_ledger.py` from a live path yet, but it becomes load-bearing the
moment an ingest commit wires it in. **Before that commit trusts these
two decoders, pull one real compounding-rebalance transaction's logs
from Blockscout and confirm the topic0s and field layout match the
inference exactly** — do not promote this from inference to fact without
that check.

**Also noted (not a gap, a batching constraint):** `derive_all()` only
correlates a StakingManager event (`ProtocolFeesDistributed`/
`FeesCompounded`/`FeesHarvestedDirect`) with its vault-emitted sibling
within the single batch of events passed to it in one call. A future
ingest commit that could split one transaction's vault-emitted and
StakingManager-emitted logs across two separate `derive_all()` calls
would silently drop the StakingManager side. Whoever writes ingest must
batch by transaction (or wider), never split a single tx across calls.

## Commit 2 landing note — reconciliation route + baseline case-1 seed (Sep 2026)

Two new routes in `web_portfolio.py`, no changes to `maxfi_ledger.py` or
`maxfi_schema.py`: `POST /api/maxfi/ledger/seed-case1-base-6039568` (writes,
one-off, STOP-gated) and `GET /api/maxfi/ledger-reconciliation` (read-only,
all wallets/chains). `MAXFI_LEDGER_RECONCILE_USD_TOLERANCE_USD = 1.00`
added as a new module-level constant next to
`MAXFI_TOKEN_DAILY_LIQUIDITY_FLOOR_USD` (`web_portfolio.py` ~L21107) -
**not** next to `MAXFI_CRASH_BADGE_DROP_PCT`, which turned out to live in
`static/maxfi.js`, not `web_portfolio.py`; the opening task block's
citation was wrong on this point and the actual backend judgment-set
constant was used as the placement precedent instead.

**Seed's ground-truth cross-check: PASSED.** Run live (dry_run) against
this session's own (empty) dev DB - decoded `FeesHarvested` for Base
tokenId 6039568: `fees0=242214271699`, `fees1=583`, matching this doc's
"Split verified to the wei" figures exactly. Derived `claimed_net0_wei
=205882130945` / `claimed_net1_wei=496` (85% net, treasury 15%, referral
0) also matches. `opened_at`/`opened_block` from the real
`base_position_created.json` fixture: `2026-09-19T00:51:09.000000Z` /
block `51494861`, matching this doc's Sep 18 ground-truth block number.

**Three findings from Commit 2's own step-1 re-confirmation:**

1. **The USD-pricing blocker is structural, not just an ingest gap.**
   `basis_price_usd` and `exit_price_usd` are hardcoded `None` in
   `derive_position_ledger`'s return dict (`maxfi_ledger.py` L586, L600 -
   confirmed by direct grep this session, not assumed). There is no
   per-claim USD field anywhere in `maxfi_ledger_positions` or
   `maxfi_ledger_events.decoded_json` either. Every one of these is
   downstream of `pool_address` also always being `None` on every derived
   row (`PoolAdded` decode deferred - `maxfi_ledger.py` L19-27, confirmed):
   without a pool address, a ledger position can never be correlated to
   its pool's `Swap` logs for `price_at_or_before`, regardless of whether
   ingest ever runs. Glenn's RULED (A) response - ship presence/status
   reconciliation now, with the USD-tolerance branch written and
   fixture-tested so it activates automatically once pricing lands - is
   the correct scoping given this. Production output today: `basis` and
   `exit` resolve to `ledger_unpriced` for every position with any ledger
   data; `claims` resolves the same way whenever a manual claim pairs
   with a ledger event, since the pricing seam
   (`_maxfi_ledger_claim_usd`, `web_portfolio.py`) returns `None`
   unconditionally - the ONE place a future pricing commit may attach a
   USD figure to a `FeesHarvested` event, and it must compute that value
   from a derived source (Swap-log pricing, once `PoolAdded` decode
   resolves `pool_address`), never by writing a USD key into
   `maxfi_ledger_events.decoded_json` - that table is raw and
   append-only.
2. **Join-key limitation for rebalanced positions is real and
   undetectable from inside this commit's own data.** `maxfi_positions`
   updates `token_id` in place on a rebalance; the ledger produces a
   separate row per `token_id` (`_ledger_keys_for_event`'s old/new
   split). The reconciliation route's `(chain, token_id)` join means a
   rebalanced position only ever sees its CURRENT segment's ledger data -
   an older segment is silently invisible, not flagged. Verified by a
   dedicated test
   (`test_rebalanced_position_old_ledger_segment_is_invisible_not_a_false_match`
   in `tests/test_maxfi_ledger_reconciliation.py`) rather than left as an
   assumption. None of the three baseline cases have rebalanced, so this
   doesn't block today - it will need real handling before this route is
   trusted for a wallet with rebalance history.
3. **Per-claim vs aggregate granularity for claims matching, and a
   real pairing defect caught before landing.** `maxfi_ledger_positions`
   carries only one aggregated `claimed_net0_wei`/`claimed_net1_wei`
   running total per token_id, no per-claim timestamp. Ruling 13's match
   key needs the RAW `maxfi_ledger_events` rows
   (`event_type = 'FeesHarvested'`), each with its own `block_timestamp` -
   the reconciliation route reads both tables for this reason, and the
   aggregated wei total is surfaced only as informational context,
   verified never to influence the claims status
   (`test_claims_never_compares_against_aggregated_wei_total`). The
   window itself is a CALENDAR-DAY comparison
   (`abs((a.date() - b.date()).days) <= 1`), not a 24h/86400s delta -
   production `maxfi_claims.claimed_at` is a bare DATE, and
   `maxfi_advisor.parse_utc` gives it midnight UTC, so a harvest the next
   calendar day past 24h was missed by the original window. Matching
   itself is GREEDY 1:1 NEAREST-TIMESTAMP PAIRING between manual claims
   and ledger `FeesHarvested` events (`_maxfi_ledger_claims_status`,
   `web_portfolio.py`), not a cross-product - the first draft paired
   every manual claim against every in-window ledger event, so one claim
   near two events produced two pairs (one bad pair could flip an entire
   position to `mismatch`), and an unpaired claim beside a matched one
   silently vanished behind a single `matched` string. The corrected
   version returns a per-claim breakdown plus a list of unpaired ledger
   events, and adds a dedicated `unmatched` status (position-level and in
   `summary.claims`) for "something on either side never paired" -
   distinct from `no_data` (both sides empty), `manual_only` (zero ledger
   events at all), and `ledger_only` (zero manual claims at all).

**Flagged smell, not fixed:** the seed route is a live production Flask
route that reads `tests/fixtures/maxfi_ledger/*.json` at request time.
`tests/` is tracked in git and deployed, so it works, but this is
backwards for a production code path. Noted in the route's own docstring
as a candidate for deletion (same precedent as the Phase D repair-route
removal in `966b59f`) once Glenn confirms the seed landed in production -
not deleted here.

**Also noted (a task-block gap, not a file disagreement):** the opening
task block's bulk-load list for the reconciliation route omitted
`maxfi_position_user_data` (the only source of the manual `exit` USD
figure, `closing_value_usd` - `maxfi_schema.py` L173-180), even though
this doc's own baseline cases reference it directly (e.g. RH id 112's
"closing_value_usd 268.44 manual"). Added as a 6th bulk-loaded table so
the `exit` category's manual side is actually reachable.

**Also caught: a real idempotency bug in this commit's own first draft,
not a bug in Commit 1.** `maxfi_ledger_positions`' PRIMARY KEY includes
`npm`, which is always `NULL` this commit (ruling 9). SQLite never
treats two `NULL`s as equal for a PK/UNIQUE conflict check, so a plain
`INSERT OR REPLACE` never detects the "conflict" on an `npm = NULL` row -
re-running the seed route would have silently inserted a second
`maxfi_ledger_positions` row every time instead of replacing the first.
Caught by this commit's own idempotency test
(`test_real_run_twice_does_not_duplicate`) before landing, not after.
Fixed in the seed route only (an explicit `DELETE` matching `npm` via
`IS`, then `INSERT`) - `maxfi_schema.py`'s table definition is unchanged,
since the schema itself isn't wrong, `INSERT OR REPLACE` was just the
wrong tool for a nullable PK column.

Chat review (before this commit's own first "Y") caught two more real
defects on the reconciliation side before they landed: the claims
cross-product/`no_data` pairing defect and the 24h-vs-calendar-day
window described in finding 3 above. Both were corrected in the same
uncommitted diff, not in a follow-up commit.

## Commit 2 production run — Sep 19

The seed route (`POST /api/maxfi/ledger/seed-case1-base-6039568`) and the
reconciliation route (`GET /api/maxfi/ledger-reconciliation`) were both
run against production on Sep 19, 2026. Results below are the verified
production output, reproduced independently from the same fixtures in
chat review.

**Seed run** (dry_run, then real): `inserted_events` 3, `skipped_events`
0. Derived `maxfi_ledger_positions` row, `computed_at`
`2026-09-19T13:54:35.601704+00:00`, key `(chain=base, vault=
0x7d27cdfbfcc878f7e7349e216d44204bfd2afd55, npm=NULL, token_id="6039568")`:
`opened_block` 51494861, `claimed_gross` 242214271699 / 583,
`claimed_net` 205882130945 / 496 — identical between the dry run, the
real run, and an independent reproduction from the same fixtures.

**Reconciliation run**, `as_of` `2026-09-19T13:55:13+00:00`, 121
positions. Summary:
- `basis`: `manual_only` 119, `ledger_unpriced` 1, `no_data` 1.
- `claims`: `manual_only` 34, `no_data` 86, `ledger_only` 1, `unmatched` 0.
- `exit`: `manual_only` 56, `no_data` 65.

**Base tokenId 6039568 (position id 132)**, the seeded row:
- `basis`: `ledger_unpriced` (ledger data present true, `manual_usd` 10.0).
- `claims`: `ledger_only` — one unpaired ledger `FeesHarvested` event at
  `2026-09-19T02:15:07+00:00` (`ledger_usd` null), plus the aggregated
  net-wei figure surfaced in `ledger_context` (informational only, per
  finding 3 above — never compared against the claims status).
- `exit`: `no_data`.
- `first_seen_block` 51499351 vs. `ledger_opened_block` 51494861 —
  surfaced as informational only (ruling 14), not treated as a mismatch
  or a defect.

Note for anyone reading id 132's `claims` status: it resolves to
`ledger_only`, **not** `ledger_unpriced`. This is correct per
`_maxfi_ledger_claims_status`'s precedence, not a bug — with zero manual
claims, `ledger_only` is returned before the unpriced check ever runs.
Recorded here so it isn't mistaken for one.

**[Unverified] provenance note on id 132's $10 basis:** the Sep 19
baseline recorded `initial_value_usd` as NULL at seed time; by
reconciliation time it reads 10.0. Every `maxfi_initial_value` row is
`source='manual_override'` by construction — the `/initial-value` route
is the sole write site (invariants ground truth) — so the $10 can only
have arrived through the UI basis editor, i.e. a human entry made after
the baseline, not a system write. Glenn believes he entered it but is
not certain. Record this as "$10 basis present at reconciliation,
entered via the manual route after the baseline; Glenn to confirm" — not
as ground truth.

**Baseline cases 2 and 3** both read `manual_only` across the board,
matching their known figures: case 2 (position id 1, tokenId 891560) —
$239 claim / $210 basis; case 3 (position id 112, tokenId 1063377) —
$19.86 claim / $284 basis / $268.44 exit.

**Seed route deleted, this commit.** `api_maxfi_ledger_seed_case1_base_6039568`
and its `@app.route('/api/maxfi/ledger/seed-case1-base-6039568', ...)`
decorator have been removed from `web_portfolio.py`, along with
`tests/test_maxfi_ledger_seed_case1.py` — same precedent as the Phase D
repair-route deletion in `966b59f`: the route did its one job (writing
the case-1 seed rows above into production), the seeded
`maxfi_ledger_events`/`maxfi_ledger_positions` rows stay in production as
the audit trail, and the route itself is gone. The now-unused
`import maxfi_ledger` at the top of `web_portfolio.py` was removed in the
same commit; every other `maxfi_ledger` reference in the file was a
comment/docstring mention, not a live call, and was left alone.

**Next step, fresh chat, own step 1:** PoolAdded decode + Swap-log
pricing (the ingest/backfill commit). Today `basis_price_usd` and
`exit_price_usd` are hardcoded `None` in `maxfi_ledger.py`'s
`derive_position_ledger`, and `_maxfi_ledger_claim_usd` always returns
`None` — that's why `basis`/`exit`/`claims` resolve to
`ledger_unpriced`/`ledger_only` instead of `matched`/`mismatch` above.
The matched/mismatch tolerance branch in `_maxfi_ledger_reconcile_status`
is already written and fixture-tested; it activates automatically once a
pricing commit resolves `pool_address` (via a `PoolAdded` decoder) and
prices each event at its block via `maxfi_ledger.price_at_or_before`. No
reconciliation-route code should need to change for that to happen.

## Commit 3a landing note — PoolAdded decode, IncreaseLiquidity basis, pool_address map

**Not yet committed** — reported here for chat review, per this repo's
money-path (basis derivation) STOP-BEFORE-COMMIT gate.

**PoolAdded topic0 is derived from a verified ABI, not an inference.**
The sourcify-verified `SnuggleVaultUpgradeable` ABI (Base
`0x359f90ee4c2e21cbf6e32c5a062eeef306822d28`) gives PoolAdded's full
signature — `PoolAdded(bytes32 indexed poolId, address pool, address
token0, address token1, uint24 fee, address positionAdapter, address
rewardAdapter)`. `maxfi_ledger.py`'s own `_topic0()` routine was run
against `IncreaseLiquidity(uint256,uint128,uint256,uint256)` first and
reproduced the already-known real topic0
(`0x3067048beee31b25b2f1681f88dac838c8bba36af25bfb2b7cf7473a5847e35f`)
exactly, confirming the routine before trusting its `PoolAdded` output
(`0x426a7ce7cf7be1d1fc555de915950cc02ce86ae06a550e1a3847edc4fcb72c22`) —
unlike Commit 1's FeesCompounded/FeesHarvestedDirect (field names only,
types guessed), this is not a guess.

**IncreaseLiquidity decoder added; basis now populates from it.**
`_decode_increase_liquidity` + a new `IncreaseLiquidity` branch in
`derive_position_ledger` fill `basis_liquidity_wei`/`basis_amount0_wei`/
`basis_amount1_wei`/`basis_block`/`basis_at` from the group's own
IncreaseLiquidity event, grounded in the real Base tokenId 6039568 mint
tx (`0xa8544cd39a163083f5eeb69bd9643dc62150cbd44136ca1c66f095e18028520c`,
block 51494861, log index 304: `liquidity=3473656907099`,
`amount0=1905032765586610`, `amount1=5000000` — matches this doc's
"0.001905 WETH + 5.000000 USDC" narrated basis exactly). A group with no
IncreaseLiquidity event keeps all five at `None`, same as before.
`basis_price_usd`/`basis_price_source` remain hardcoded `None` — Swap-log
pricing is Commit 3b's job, not this one.

**Addendum (closed the gap above):** `tests/fixtures/maxfi_ledger/base_mint_6039568.json`
has been added and is now exercised directly — `_decode_increase_liquidity`
and `_decode_position_created` are each verified against this tx's own
real log data (topic0-vs-fixture cross-check plus exact-wei/exact-field
real-data assertions, `tests/test_maxfi_ledger_decode.py`), not only the
synthetic scenario in `tests/test_maxfi_ledger_derive.py`.

**This fixture is a 14-item SUBSET of tx
`0xa8544cd39a163083f5eeb69bd9643dc62150cbd44136ca1c66f095e18028520c`'s
full log list (indices 294–299, 302–309), not the complete response.**
Indices 300 and 301 — both plain WETH/USDC `Transfer` logs into the pool
via the position adapter, already covered narratively in this doc's own
dust-refund section above — are absent. Recorded here so this fixture
isn't later mistaken for a complete capture of the tx's logs; the two
events this commit actually needs (`IncreaseLiquidity` at index 304,
`PositionCreated` at index 309) are both present and independently
verified twice (hand word-split, then `decode_log()`) before being
committed.

**`pool_address` now populated via a batch-wide `pool_id` map.**
`build_pool_map(events)` collects `{pool_id: pool}` from every `PoolAdded`
event in a batch; `derive_all()` applies it to each derived row AFTER
grouping, keyed on the row's own `pool_id` (already populated from its
`PositionCreated` event) — `PoolAdded` itself is excluded from
per-position grouping (extends the existing `Swap` skip in `derive_all()`,
same conditional, not a second check) since it has no tx_hash/token_id
correlation to any one position. A position whose `PoolAdded` event isn't
in the same input batch correctly keeps `pool_address = None` — a real,
documented scope limit carried forward to Commit 3b (whose ingest must
include historical `PoolAdded` events in whatever batch it hands to
`derive_all`, or positions stay unpriceable), not a bug to route around
here.

**`npm` deliberately still `None` everywhere, including on
`IncreaseLiquidity`.** `IncreaseLiquidity`'s own emitting
`contract_address` IS literally the NPM address — but
`_decode_increase_liquidity`'s `ledger_fields["npm"]` is set to `None`
anyway, matching every other decoder. If it were set to the real NPM
address instead, `derive_all()`'s `_ledger_keys_for_event()` would group
the same real position's `PositionCreated`/`PositionWithdrawn`/
`SnuggleRebalanced` events (key `npm=None`) separately from its
`IncreaseLiquidity` event (key `npm=<address>`) — splitting one position's
lifecycle across two ledger rows that never join, so basis would silently
never reach the row a caller actually reads. This reasoning is recorded
in `_decode_increase_liquidity`'s own docstring so it isn't "fixed" later
without re-deriving why it's this way.

**Dust-refund correction:** the deposit tx's dust refund is
adapter → vault → wallet, TWO hops, not the one hop (`vault→wallet`)
this doc's own Sep 18 ground-truth section (line 88 as of Commit 2)
currently states. Recorded here as a correction to that line; the line
itself is not rewritten in this commit (out of this commit's own scope —
decode/derive code and fixtures only), so a reader of the Sep 18 section
should treat its "vault→wallet" dust-refund wording as superseded by this
note until that section itself is corrected.

## Commit 3b.1 landing note — RPC ingest infrastructure + NPM resolution

**Not yet committed** — reported for chat review, per this repo's
money-path (first-ever write of live-derived on-chain data into
`maxfi_ledger_positions`, plus a new live RPC dependency) STOP-BEFORE-COMMIT
gate.

**Scope:** RPC `eth_getLogs`/`eth_call` ingest infrastructure, owner/
token_id-filtered two-pass scanning, and NPM resolution (ruling 9) only.
Swap-log USD pricing (3b.2) and per-claim USD storage (3b.3) remain out of
scope — nothing in this commit prices anything.

**New file, `maxfi_ledger_ingest.py`** — kept separate from `maxfi_ledger.py`
specifically so that module's own "no network, no RPC, no sqlite" docstring
stays true; mirrors `maxfi_client.py`'s hand-rolled `requests`-based
JSON-RPC conventions (`MaxFiRpcError`, `rpc_call`'s
`"[{chain}] ... calling {target} ({selector})"` message shape), not
`web3.py`'s `HTTPProvider`.

**Contract registry** (addresses copied verbatim from this doc's own
lines 67/81/99/100, lowercased at registry-definition time):

| Chain | Vault | StakingManager |
|---|---|---|
| Base | `0x7D27CDfBFcC878F7E7349e216d44204BFd2AFd55` | `0x4994743d7183d2ea5c651292A9Dab2C781020638` |
| Robinhood | `0x1195C074F898b7644bA732407619c9804dFE6DCE` | `0xBfD8cf8094feee44C314B3d5ec49ccDfd80caBAe` |

`BASE_RPC_URL` (existing env var, reused) and `RH_RPC_URL` (new — Alchemy
now supports Robinhood Chain under Glenn's existing account,
`https://robinhood-mainnet.g.alchemy.com/v2/<key>` format). Neither URL
nor key is hardcoded anywhere; only the env var *names* are read. Missing
either raises the same `MaxFiRpcError("no RPC URL configured...")` shape
`maxfi_client.rpc_call` already raises for a missing `BASE_RPC_URL` — no
silent fallback to the old public `robinhood.com` endpoint.

**Owner/token_id topic-position table** (re-verified against the current
`maxfi_ledger.py` decoders before writing any filter code, per this
commit's own step 1 — matched the task's stated layout exactly, no
discrepancy found):

| Event | Emitted by | Owner topic | token_id topic |
|---|---|---|---|
| PositionCreated | vault | topics[2] | topics[1] |
| PositionWithdrawn | vault | topics[2] | topics[1] |
| FeesHarvested | vault | topics[2] | topics[1] |
| SnuggleRebalanced | vault | topics[3] | topics[1]/[2] (old/new) |
| ProtocolFeesDistributed | StakingManager | *(none)* | topics[1] |
| FeesCompounded | StakingManager | *(none — in `data`)* | topics[1] |
| FeesHarvestedDirect | StakingManager | *(none — in `data`)* | topics[1] |
| IncreaseLiquidity | NPM | *(none)* | topics[1] |
| PoolAdded | vault | *(none)* | *(none)* |

**Ordering correction (resolved by dependency logic, not the literal task
text):** the task's own atomic steps listed "pass 3 → PoolAdded unfiltered
→ NPM resolution," which is impossible as written — pass 3's query
*target* is the NPM address that only NPM resolution produces, so
resolution must complete first. Constraint #1's own wording ("fetch in a
THIRD pass against the **resolved** NPM address(es)") already implied
this. Actual implemented order: pass 1 (vault, owner-filtered, incl.
SnuggleRebalanced) → PoolAdded (unfiltered) → NPM resolution → pass 2
(StakingManager, token_id-filtered — independent of NPM, could run
anytime after pass 1) → pass 3 (NPM, token_id-filtered). See
`maxfi_ledger_ingest.scan_chain`'s own docstring for the full reasoning.

**`positionManager()` selector — [Inference], NOT ABI-verified** the way
`PoolAdded`'s signature is. Computed via the same local `keccak()`
technique as `maxfi_ledger.py`'s topic0 constants
(`maxfi_ledger_ingest.SEL_POSITION_MANAGER`), but no sourcify-verified ABI
confirms `positionAdapter` actually implements this signature. Every
`npm_resolutions` pair the backfill response returns should be eyeballed
against the known Base NPM
(`0x03a520b32C04BF3bEEf7BEb72E919cf822Ed34f1`) on the first live dry-run
before this is trusted.

**No-cursor, full-rescan model — accepted risk.** Every invocation
re-fetches full history from each chain's documented start block (Base:
`44,609,025`, evidence-based per HANDOFF line 106, not a confirmed deploy
block; Robinhood: block `1`/genesis, since owner-topic filtering keeps the
scan cheap regardless of range). `maxfi_ledger_events`' existing UNIQUE
INDEX `(chain, tx_hash, log_index)` + `INSERT OR IGNORE` makes a re-run
idempotent. `maxfi_ledger_ingest.scan_logs_chunked`'s per-pass `chunk_stats`
are surfaced in the backfill response specifically so an unexpectedly
large chunked-call count on the first live run is visible — that's the
signal a resumable cursor becomes worth building later, not something to
pre-build now.

**Real bug caught before landing, not a bug in Commit 1/3a's schema.**
The task's own constraint #6 asked for a plain
`INSERT ... ON CONFLICT(chain, vault, npm, token_id) DO UPDATE` "UPSERT."
`maxfi_ledger_positions`' primary key includes `npm`, which is always
`NULL` under ruling 9 (every decoder sets it to `None`). SQLite never
treats two `NULL`s as equal for a PK/UNIQUE **conflict check either** —
so `ON CONFLICT(...)` silently never detects a "conflict" on an
`npm = NULL` row, and a re-run would INSERT a second row every time
instead of updating the first. This is the *exact same* landmine the
since-deleted Commit 2 seed route already hit and fixed the same way (see
that commit's own landing note) — fixed here identically: an explicit
`DELETE` (matching `npm` via `IS`, not `=`) then `INSERT`, not
`ON CONFLICT`. Caught by this commit's own idempotency test
(`test_rerun_is_idempotent_and_reports_duplicates`,
`tests/test_maxfi_ledger_backfill_route.py`) before landing — a real
regression the test suite was written specifically to catch, not a
hypothetical.

**Wallet enumeration:** the task described "whatever existing helper
already enumerates the maxfi:true wallet subset for a chain (used by the
valuation/scan routes)" — no such helper actually existed. The `maxfi`
flag itself was already established (`api_get_wallets`/`api_update_wallet`,
`wallet_config.json`), but only ever read to populate a UI toggle, never
to build a scan list. A new, minimal function,
`web_portfolio._maxfi_tracked_wallets()`, was added wired to that SAME
existing flag — not a new concept, not Glenn's two known addresses
hardcoded.

**`source_event_ids` stays `None`** on every upserted row this commit,
same as Commit 1/3a. Wiring it up (capturing `maxfi_ledger_events.id` per
contributing row, distinguishing a freshly-inserted id from a
pre-existing duplicate's) is real scope this commit's own steps never
asked for — left as a documented gap, consistent with
`derive_position_ledger()`'s own docstring.

**Route:** `POST /api/maxfi/ledger/backfill/<chain>` — dry_run via
`?dry_run=true` or `{"dry_run": true}`, guarded by `_LEDGER_BACKFILL_LOCK`
(a `threading.Lock`, shared across chains, mirroring
`_METRICS_REFRESH_LOCK`'s single-flight-across-chains behavior), 409
`RefreshBusy` on contention, 502 `MaxFiLedgerIngestError` on any
`maxfi_ledger_ingest.MaxFiIngestError`. All RPC I/O completes before the
DB connection opens.

**Next step:** Commit 3b.2 (Swap-log USD pricing) + 3b.3 (per-claim USD
storage), fresh chat, own step 1.

## Hotfix 3b.1.1 — Alchemy HTTP-400 oversize-range classification

**Symptom:** the first production Base `dry_run` failed on the very first
`eth_getLogs` chunk (`[base] HTTP 400 calling eth_getLogs
(0x7d27cdfb..., blocks 44609025-44659024)`) — `scan_logs_chunked()`'s
adaptive halving never fired at all.

**Root cause:** `eth_get_logs()` raised a generic `MaxFiRpcError` on any
non-200/non-429 HTTP status *before* ever parsing the response body.
Alchemy delivers an oversize-block-range rejection as **HTTP 400 with a
JSON-RPC error body** — not the 200-with-error-object shape
`_looks_like_oversize_range_error()`'s own (wrong) docstring assumed —
so the rejection never reached that classifier, and the 50k-block first
chunk was treated as an unrecoverable failure instead of a halve-and-retry
signal.

**Fix:** `eth_get_logs()` now parses the response body for ANY HTTP
status (not only 200) before deciding how to classify a failure. A body
carrying an `"error"` object is classified by its message text exactly as
before (oversize-range → `MaxFiRpcOversizeRange`, same message format;
anything else → `MaxFiRpcError`, now including both the HTTP status and
the provider's message text). Only a non-200 response whose body is
non-JSON or carries no `"error"` key falls through to the old generic
`"HTTP {status} calling eth_getLogs"` message. HTTP 429 is unchanged —
still classified by status alone, before any body parsing, since a 429
carries no comparable JSON-RPC error body. `_looks_like_oversize_range_error()`
gained a few more Alchemy-specific phrasings (`"up to a"`,
`"block range should work"`, `"log response size exceeded"`,
`"query exceeds"`) and its docstring now states the HTTP-400 reality
instead of the wrong "always 200" premise. `scan_logs_chunked()` itself,
`DEFAULT_CHUNK_SIZE`, `MIN_CHUNK_SIZE`, and the halving arithmetic are
all untouched — this was purely a classification bug in `eth_get_logs()`.

**Still owed:** Base's live `dry_run` (the one that surfaced this bug)
has not yet been re-run post-hotfix. Robinhood's first run remains held
pending review of Base's `final_chunk_size` (ruling A — RH's
`start_block` is set from evidence in a follow-up, not run blind).

## Hotfix 3b.1.2 — adapt raw RPC log shape before decode_log

**Symptom:** the first real production Base `dry_run`, run after hotfix
3b.1.1, completed EVERY RPC pass cleanly (the Alchemy call budget is
fine) and then 500'd with `{"error": "'timeStamp'"}` — a `KeyError`
raised during decode, after all the network work had already finished.

**Root cause:** `maxfi_ledger._normalize_log` handles exactly two log
shapes — Etherscan (`blockNumber` hex + `timeStamp` hex) and Blockscout
(`block_number` int + `block_timestamp` ISO). A raw `eth_getLogs` log has
`blockNumber` (hex), so it takes the Etherscan branch and reads
`log["timeStamp"]` — a field standard JSON-RPC log output does not carry
at all. Alchemy adds a **non-standard** `blockTimestamp` field (hex unix
seconds, e.g. `"0x69dbb8e5"`); a plain node returns no timestamp on a log
at all. Raw RPC logs are a **third shape** that nothing in Commit 3b.1
ever exercised — every ingest test used fixture-shaped fakes, which are
already Etherscan-shape and never exposed this gap.

**Fix, confined to the ingest (network) layer — `maxfi_ledger.py` stays
pure and untouched,** matching its own docstring ("no network") and this
commit's original module-docstring intent ("returns raw logs in the same
shape `decode_log` already accepts") — an intent 3b.1 stated but never
actually verified against a real RPC response.

- `rpc_log_to_etherscan_shape(log, block_timestamp_hex=None)` — pure
  function, new dict, copies `address`/`topics`/`data`/`blockNumber`/
  `transactionHash`/`logIndex` verbatim (hex strings untouched). Sets
  `timeStamp` from `blockTimestamp` if present, else the
  `block_timestamp_hex` argument, else raises `ValueError` naming the
  block — never guesses.
- `eth_get_block_timestamp(chain, block_number)` — the fallback for a
  node with no `blockTimestamp` at all: one `eth_getBlockByNumber`
  call, same `requests`/`MaxFiRpcError` conventions as `eth_call`/
  `eth_get_logs`.
- `scan_chain()` now adapts every batch of raw logs immediately after
  collecting it from `scan_logs_chunked()` (all five call sites: pass 1
  vault, pass 1 SnuggleRebalanced, PoolAdded, pass 2, and each pass 3
  NPM-address iteration), via a new per-invocation
  `{block_number: timestamp_hex}` cache shared across every pass — a
  block with several logs (the routine case; see the fixture below,
  where 5 of 6 entries share one block) triggers the fallback at most
  once, not once per log. The response gains an additive
  `block_timestamp_lookups` key (`len(cache)`) so an unexpectedly large
  fallback count is visible, not assumed — on Alchemy today this is
  always `0`, since every log already carries `blockTimestamp`.

**Fixture provenance:** `tests/fixtures/maxfi_ledger/base_rpc_getlogs_page.json`
is real Alchemy `eth_getLogs` output for the Base vault
(`0x7d27cdfbfcc878f7e7349e216d44204bfd2afd55`), captured live in chat Sep
19, blocks `0x2a8ae01`–`0x2a8b1e8`. **The page was truncated mid-way
through a seventh entry in that capture — only the six complete entries
in the fixture are real.** This is not a full page; nothing was padded
or guessed to make it look like one.

**Correction to this hotfix's own task text:** the task described the
fixture's `FeesHarvested` entry (index 5) as decoding to token_id
`66312213`. Independently recomputed against the fixture's own
`topics[1]` (`0x...03f1d815`) before writing the decode test:
`int("3f1d815", 16)` is **`66181141`**, not `66312213` (which is hex
`0x3f3d815` — a one-digit transposition, `1`↔`3`, from the real value).
The fixture itself is used byte-for-byte exactly as given; only the
task's *stated* expected value was wrong, and the test asserts the
independently-verified correct one instead of encoding the typo as
ground truth.

**Still owed, unchanged from 3b.1.1's note:** Base's live `dry_run` has
still not completed successfully end-to-end — this hotfix fixes the
decode-time 500 that stopped the most recent attempt, but that attempt
itself has not yet been re-run. Robinhood remains held pending review of
Base's `final_chunk_size` on a clean run (ruling A).

## Hotfix 3b.1.3 — per-log soft isolation around decode_log + failure diagnostics

**Symptom:** the first real Base `dry_run` after hotfix 3b.1.2 again
completed every RPC pass cleanly and then 500'd during decoding, this
time with `{"error": "list index out of range"}` — a bare `IndexError`.
The only index reads on this path are inside `maxfi_ledger.py`'s
decoders (`topics[N]` / `words[N]`); `maxfi_ledger_ingest.py` has none.
The global `@app.errorhandler(Exception)` prints only `str(e)` with no
traceback, so Railway logs alone couldn't say which log tripped it.

**Working hypothesis — `[Inference]`, NOT acted on in code this
commit:** the vault is an upgradeable proxy, and a `topic0` hash only
encodes parameter **types**, never indexed-ness. An older vault
implementation could in principle have emitted an event sharing today's
`topic0` but with fewer indexed parameters (same signature types, fewer
topics), which is exactly the shape that trips a decoder's fixed
`topics[N]` read. This is a hypothesis to be confirmed by this hotfix's
own diagnostic output on the next real run, not something this commit
treats as established or fixes preemptively — no decoder in
`maxfi_ledger.py` was touched.

**Fix — structural, precedented by LP Advisor Phase B1.1's**
`decode_positions_and_pools_soft` (`web_portfolio.py`): a single bad unit
must never abort a whole production run. `decode_log()` was being called
with no per-log isolation in three places inside
`maxfi_ledger_ingest.scan_chain()` (token_id/pool_id discovery,
`PoolAdded` lookup, and `event_type_counts`) and once in
`web_portfolio._run_ledger_backfill()`'s main decode loop — any one of
those four call sites could raise and abort the whole backfill on a
single malformed log.

- **`safe_decode_log(raw_log, failures, sample_limit=10)`** — the one
  new helper (no second try/except anywhere in this diff). Calls
  `maxfi_ledger.decode_log(raw_log)` inside `try/except Exception`; on a
  real exception, appends a diagnostic dict — `{tx_hash, log_index,
  block_number, contract_address, topic0, topic_count, data_word_count,
  error}` — read entirely defensively from the RAW log (never
  int-converted, never dependent on anything `decode_log()` may have
  partially computed), so building the diagnostic itself cannot raise.
  A legitimate `decode_log() -> None` (topic0 outside the tracked
  vocabulary — not a failure) still returns `None` with nothing
  appended.
- All four call sites use it. Internal collection uses a large,
  effectively-unbounded `sample_limit` (`_UNBOUNDED_FAILURE_LIMIT`) so
  no failure is lost to premature truncation before the response
  boundary — "keep a separate integer count of ALL failures" is
  satisfied by simply never dropping one early, not by tracking a count
  apart from the list.
- **Two-level dedup, both by `(tx_hash, log_index)`.** Within
  `scan_chain()` itself: the same physical log is touched by more than
  one of its three internal loops (every `pass1_logs` entry is also
  part of the `raw_logs` the `event_type_counts` loop walks), so one bad
  log can generate more than one raw diagnostic before `scan_chain()`
  ever returns — `_dedupe_failures()` collapses that down to one entry
  per distinct bad log before `scan_chain()`'s own `decode_failed`/
  `decode_failures` are set. Then again at the route: `_run_ledger_backfill`
  starts from `scan_chain()`'s own (already-deduped) `decode_failures`,
  appends its own re-decode failures onto that same list (the same log
  legitimately fails again there — it's a full independent re-decode of
  `raw_logs`), and dedupes the merged list a second time before building
  the response's `decode_failed`/`decode_failed_sample` (≤10).
- **Response, additive:** `decode_failed` (int, final deduped total) and
  `decode_failed_sample` (list, ≤10). When `decode_failed > 0`, the
  response also carries `warning`. A skipped log is never written to
  `maxfi_ledger_events` — `decoded_events` only ever collects non-`None`
  records, so a failed log is automatically excluded from the insert
  loop with no extra code needed for that.

**Test-fixture note:** `tests/test_maxfi_ledger_backfill_route.py`'s
`_empty_scan()` helper (a stand-in for `scan_chain()`'s return shape)
needed `decode_failed`/`decode_failures` added to its default dict —
`_run_ledger_backfill` now reads `scan["decode_failures"]` directly, so
any stub missing that key raised `KeyError` before this fix was even
exercised. Same precedent as hotfix 3b.1.2's `block_timestamp_lookups`
addition to the same helper and to `test_scan_chain_no_wallets_returns_empty_without_any_rpc_call`'s
exact-dict assertion (`tests/test_maxfi_ledger_ingest.py`), which now
also asserts `decode_failed: 0, decode_failures: []`.

**Decision the next Base `dry_run` settles:** whatever
`decode_failed_sample` reports (topic0, topic_count, data_word_count,
the exact error) is the actual diagnostic this hotfix exists to produce
— it, not this commit's own `[Inference]` hypothesis above, decides
whether a decoder needs a real fix, and what shape that fix takes.

## Hotfix 3b.1.4 — PoolAdded scans from genesis; chunk size 2M under PAYG

**The first successful Base `dry_run`** (after hotfixes 3b.1.1–3b.1.3):
139 `eth_getLogs` calls per pass, 0 chunk halvings, 0 HTTP 429s. Decoded
13 `PositionCreated`, 37 `SnuggleRebalanced`, 12 `PositionWithdrawn`, 24
`FeesHarvested` = 24 `ProtocolFeesDistributed`. 50 positions derived and
upserted into `maxfi_ledger_positions`. 3 `ignored_duplicate` — the
Commit 2 fixture seeds, correctly recognized as already-present via the
`(chain, tx_hash, log_index)` UNIQUE INDEX, not re-inserted.

**But it exposed a real spec error:** `npm_resolutions` came back empty,
so pass 3 (`IncreaseLiquidity`) never ran, so none of the 50 derived
positions got a `basis_*` value. Root cause: the `PoolAdded` scan reused
`cfg["start_block"]` — this wallet's own earliest tracked event (Base
`44,609,025`) — but `PoolAdded` fires once, at admin-approval time,
**before** any user ever opens a position in that pool. A wallet-scoped
start block can only miss it. **Fix:** `PoolAdded` now scans from a new
`POOL_ADDED_START_BLOCK = 0` (genesis), completely independent of
`cfg["start_block"]` — every other pass (`pass1_vault`,
`pass1_snuggle_rebalanced`, `pass2_staking_manager`, `pass3_npm`) is
unchanged. Its `chunk_stats` entry now carries `from_block` explicitly so
this is visible in the response, not assumed.

**Chunk size raised:** `DEFAULT_CHUNK_SIZE` `50_000` → `2_000_000`, now
that this same successful dry_run confirms Alchemy PAYG imposes **no**
`eth_getLogs` block-range cap — only a 150 MB response-size cap, which is
what the existing adaptive halving now guards against (unchanged
arithmetic, unchanged `MIN_CHUNK_SIZE`). The Free-tier 10-block limit
hotfix 3b.1.1 found is why the halving path is kept at all — a future
run against a Free-tier key, or any provider with a real range cap,
still needs it. At the new default, Base's own scan drops from 139
calls/pass to a small handful; Robinhood (whose `PoolAdded`/wallet-event
ranges are far larger) sees a proportionally bigger drop.

**Explicitly OUT of scope — a separate, review-gated 3b.1.5:** the same
dry_run's 26 `decode_failed` entries are real `FeesCompounded`/
`FeesHarvestedDirect` logs, not a symptom this hotfix touches —
`maxfi_ledger.py` is untouched here. Their `topic0`s are confirmed by
live match to be the exact keccaks of Commit 1's inferred signatures
(`FeesCompounded(uint256,address,uint256,uint256)` /
`FeesHarvestedDirect(uint256,address,uint256,uint256)`), so the
**parameter TYPE list** in that original inference is now confirmed by
real on-chain data, not just plausible. What each of the 26 failing logs
actually carries is **3 topics + 2 data words** — `owner` indexed at
`topics[2]`, both amounts in `data` — a different indexed/non-indexed
split than Commit 1's decoders currently assume. A decoder fix plus a
real captured fixture (not another inference) is owed in 3b.1.5, under
the same money-path review gate as every other decode-affecting change
in this workstream.

## Commit 3b.1.5 — StakingManager fee-event layout fix (review-gated, closes Commit 1's open item)

**Symptom:** two production Base `dry_run`s (post-3b.1.3/3b.1.4) each
reported `decode_failed = 26`, all `FeesCompounded`/`FeesHarvestedDirect`,
all a bare `IndexError` — `owner`'s data word overran the log's actual
`data` length.

**Live-match verification:** both topic0s were recomputed independently
(`_topic0()` against the exact signatures Commit 1 inferred —
`FeesCompounded(uint256,address,uint256,uint256)` and
`FeesHarvestedDirect(uint256,address,uint256,uint256)`) and matched byte-
for-byte against the real failing logs' own `topics[0]`. This confirms
Commit 1's parameter **type list** against live chain data — it was never
a guess to begin with, only untested. What was wrong is the indexed
layout: real logs carry **3 topics** (`topic0`, `tokenId` indexed,
`owner` indexed) and **2 data words** (`amount0`, `amount1`) — not
`owner` as data word 0 the way Commit 1 assumed by analogy to
`ProtocolFeesDistributed`.

**Fix:** `_decode_fees_compounded`/`_decode_fees_harvested_direct` in
`maxfi_ledger.py` now read `token_id` from `topics[1]` and `owner` from
`topics[2]`, and only `amount0`/`amount1` from `data`. `decoded_json`
field names (`token_id`, `owner`, `amount0`, `amount1`) are unchanged.
Both decoders now raise a `ValueError` naming the event and the actual
topic/data-word count — never a bare `IndexError` — if a log arrives
with fewer than 3 topics or 2 data words, so a future layout drift
surfaces readably in `decode_failed_sample` instead of crashing the scan.
The module docstring and both `TOPIC_*` constants' comments were
rewritten to record this verification; the 85/15 net-claim semantics
notes in `_tx_net_claim()` are untouched.

**Fixture provenance:** a real 11-log StakingManager page captured live
via Alchemy, Base block `0x2a9d8a6`, tx
`0x05e6a1113258f96f376e353384c5651e0b133f7d385b8db129a3128f1d003231` — a
keeper batch touching three owners' positions (tokenIds `4961418`
(`0x4bb48a`), `4956448` (`0x4ba120`, Glenn's own — owner
`0xab7a515c6e2eea5140ed8a5b09a7d782f3b26743`), and `1916844`
(`0x1d3fac`)) — checked in verbatim as
`tests/fixtures/maxfi_ledger/base_staking_manager_page_0x2a9d8a6.json`.
Exercised by `tests/test_maxfi_ledger_decode.py`, including a regression
pin through `derive_position_ledger()` confirming the corrected layout
flows into `compounded0_wei`/`compounded1_wei` (and confirming, as
pre-existing and unmodified behavior out of this commit's scope, that a
tx with only `FeesHarvestedDirect` and no `FeesHarvested` leaves
`claimed_gross`/`claimed_net` at 0 — there is no `FeesHarvestedDirect`
branch in `derive_position_ledger()`'s loop; it only affects
`claimed_net` indirectly via `_tx_net_claim()`, itself only reachable
from a `FeesHarvested` event).

**Correction to this doc's own prior assumption:** the fixture's topic0
`0x017fe984d1819581b329031cba1c4df3f1d1d987e4e814dbded3d20ebd651441`
(3 of the 11 logs) is **not** one of the unidentified StakingManager
topic0s — it is `TOPIC_PROTOCOL_FEES_DISTRIBUTED`, already tracked and
decoded by an existing decoder. The genuinely still-unidentified
topic0s in this fixture, noted and explicitly **not** scoped to this
commit, are:
- `0xe6d1ff392bdc1cf53105ebfcb0e3f7b024a8b0915b1f131907da7a9f84f52b86`
- `0xdd8df9cdfbfa0633e022e142f0da49c4cb7f22a3cf1c8a632425282652aefeff`
- `0x627009b4f6918ee0f41065d4adffdb5142a9ef54c66cc350bb8396c1c82a409c`

**Test-file scope note:** fixing the decoders' `ValueError` guards broke
`tests/test_maxfi_ledger_ingest.py::test_scan_chain_counts_fees_compounded_and_fees_harvested_direct`,
whose own synthetic log builders (`_fees_compounded_log`,
`_fees_harvested_direct_log`) built the old, now-incorrect 2-topic/
owner-in-data-word-0 shape. Rather than leave a known-broken quality
gate, those two helpers were updated in this same commit to the
corrected 3-topic/2-data-word shape (production `maxfi_ledger_ingest.py`
itself is untouched — zero diff, confirmed). This widens this commit's
file footprint by one test file beyond the four originally named; flagged
here explicitly rather than silently landed, for review before merge.

**PoolAdded / ruling 9, still open:** unchanged by this commit.
`PoolAdded` still decodes (Commit 3a), but ruling 9's NPM resolution
still depends on the poolId→pool/npm mapping it carries — Glenn's ruling
is that ruling 9 is amended to receipt-based NPM resolution in a future
3b.1.6, not addressed here.

## Commit 3b.1.6 — Ruling 9 amended: receipt-based NPM resolution + IncreaseLiquidity

**Symptom:** two production Base `dry_run`s (post-3b.1.4/3b.1.5) proved
the `PoolAdded -> positionAdapter -> positionManager()` chain dead for
this vault. Zero `PoolAdded` events from genesis, AND a poolId-in-
`topics[1]` search from genesis also returned `[]` - the pools this
wallet set actually uses were never registered by any event this ledger
can see. So NPM resolution never had a `PoolAdded` record to start from,
pass 3 (`IncreaseLiquidity`) never ran, and every derived position had
`basis_liquidity_wei`/`basis_amount0_wei`/`basis_amount1_wei`/
`basis_block`/`basis_at` stuck at `None` - not a decode bug, a dead
resolution mechanism.

**Ruling 9, AMENDED (Glenn's ruling, this commit):** receipt-based
resolution, option A. Every `PositionCreated` and `SnuggleRebalanced` tx
(pass 1's own logs) ALSO contains the NPM's `IncreaseLiquidity` log for
the minted tokenId (a mint, or a rebalance-minted child).
`eth_getTransactionReceipt(tx_hash)` returns that tx's COMPLETE log list
with no block-range limit of any kind - unlike `eth_getLogs`, there is
nothing to chunk or halve. The kept log's own **emitter address** is the
NPM - no inferred `positionManager()` selector, no `PoolAdded`
dependency, and Base's second NPM resolves automatically (grouped by
emitter, never assumed singular). The old
`positionManager()` selector (`SEL_POSITION_MANAGER`) was itself still
unverified against any real ABI (unlike `PoolAdded`'s sourcify ABI) -
retired unverified, not superseded by a verified version.

**New pass structure** (`maxfi_ledger_ingest.scan_chain()`):
1. Pass 1 (vault, owner-filtered) - unchanged: `PositionCreated`/
   `PositionWithdrawn`/`FeesHarvested` plus `SnuggleRebalanced`, yields
   the wallet set's token_id set.
2. Receipt walk (new, replaces `PoolAdded` + NPM resolution + pass 3):
   one `eth_getTransactionReceipt` per DISTINCT pass-1 `transactionHash`
   (fetched once per tx, never once per log). Keeps only the
   `IncreaseLiquidity` logs whose `tokenId` is in step 1's token_id set;
   each kept log is adapted via `rpc_log_to_etherscan_shape()` using the
   block timestamp **already known** from its pass-1 sibling log in the
   same tx (a receipt carries no `blockTimestamp` of its own) - the
   `eth_getBlockByNumber` fallback is never invoked for a receipt log,
   pinned by its own test
   (`test_scan_chain_receipt_walk_never_uses_block_by_number_fallback`).
3. Pass 2 (StakingManager, token_id-filtered) - unchanged.

**Removed** from `maxfi_ledger_ingest.py`: the `PoolAdded` pass,
`pool_added_by_pool_id`/`pool_ids_seen`, `resolve_npm_address()`,
`SEL_POSITION_MANAGER`, `_selector()`, `_decode_eth_call_address()`,
`_NPM_RESOLUTION_CACHE`, `POOL_ADDED_START_BLOCK`, and the now-unused
`from web3 import Web3` import. `eth_call` itself is kept (a general
transport primitive, not specific to NPM resolution, and not named for
removal). `maxfi_ledger.py` (its `PoolAdded`/`IncreaseLiquidity`
decoders, `derive_all()`, `derive_position_ledger()`) is **zero diff** -
confirmed by `git diff origin/main -- maxfi_ledger.py` returning empty;
`npm` in the ledger key stays `None`, per the existing docstring.

**Response/stats shape:** `npm_resolutions` is now
`[{"npm_address", "token_ids": [...]}, ...]`, grouped by emitter address
(sorted, deterministic) - not the retired `{"pool_id", "npm_address"}`
shape. `chunk_stats` drops `"pool_added"` and `"pass3_npm"`, gains
`"receipts": {"txs", "calls", "null_receipts",
"increase_liquidity_kept", "increase_liquidity_dropped"}`. Everything
else in the response is unchanged. `web_portfolio.py` needed no change -
it only ever passed `scan["npm_resolutions"]` and `scan["chunk_stats"]`
through verbatim, with no dependency on either shape - confirmed **zero
diff** by grep before editing anything (atomic step 2 of this commit).

**New RPC primitive:** `eth_get_transaction_receipt(chain, tx_hash)` -
same `requests`/`MaxFiRpcError`/429 conventions as `eth_get_logs`/
`eth_call`. Returns the receipt dict, or `None` on a null result
(counted via `chunk_stats["receipts"]["null_receipts"]`, never raised).

**Deleted tests** (the one sanctioned exception to "no existing test's
behavior may change" - the mechanism they tested no longer exists),
all in `tests/test_maxfi_ledger_ingest.py`:
- `test_resolve_npm_address_caches_after_success`
- `test_resolve_npm_address_failure_is_not_cached`
- `test_resolve_npm_address_zero_address_is_not_cached`
- `test_pool_added_call_uses_genesis_every_other_call_uses_start_block`
- `test_pool_added_before_start_block_is_decoded_and_resolves_npm`
- `test_scan_chain_two_pass_token_id_handoff_and_npm_resolution`
- `test_scan_chain_no_pool_added_event_skips_pass3_and_leaves_npm_unresolved`

Also removed the now-unused `_pool_added_log`/`_increase_liquidity_log`
test helpers and the `_clear_npm_cache` autouse fixture (the cache it
cleared no longer exists). Three more existing `scan_chain()`-calling
tests were **updated, not deleted**, to add an
`eth_get_transaction_receipt` stub (the receipt walk now runs
unconditionally whenever pass 1 finds logs, so any such test needs one):
`test_scan_chain_falls_back_to_eth_get_block_timestamp_once_per_shared_block`,
`test_scan_chain_isolates_one_bad_log_and_still_discovers_the_good_token_id`,
`test_scan_chain_counts_fees_compounded_and_fees_harvested_direct`. The
empty-wallets shape pin and the route file's `npm_resolutions`
pass-through test were updated to the new shapes, not deleted, per this
commit's own instruction.

**1263 (Commit 3b.1.5's landed count) → 1272**: net +9 in
`tests/test_maxfi_ledger_ingest.py` (8 new: 4 for
`eth_get_transaction_receipt`, 4 for the receipt walk - minus 7
deleted, listed above) + 1 new end-to-end test in
`tests/test_maxfi_ledger_backfill_route.py` (`scan_chain()` run for
real against stubbed RPC functions rather than mocked wholesale,
proving `IncreaseLiquidity` reaches `fetched` and the derived tokenId-100
position carries a non-null basis - the mocked-`scan_chain()` tests
elsewhere in that file only prove pass-through, not that the real
receipt walk produces a usable basis).

**Post-merge plan:** Base `dry_run` first (expect `npm_resolutions`
populated, `IncreaseLiquidity` in `fetched`, `decode_failed: 0` now that
3b.1.5 is landed), then a Base **real** run, then Robinhood `dry_run`
then real run - Robinhood's `start_block = 1` is fine under this
mechanism (2M-block chunks under PAYG ⇒ roughly 34 `eth_getLogs` calls
per pass to genesis; the receipt walk itself is never chunked). The
derive-side rebalance-tx branch in `maxfi_ledger._tx_net_claim()`
(still marked `[Inference], no rebalance-tx fixture exists to verify
this branch` in that function's own docstring) gets its first real
exercise on the Base real run - the 37 rebalance-minted children's
basis is the thing to eyeball first.

## 3b.1 series — production close-out (Sep 20)

**a. Landing SHAs** (1212 → 1272 tests across the series):
- 3b.1 `7037edd`
- 3b.1.1 `318a049`
- 3b.1.2 `cf4a9b0`
- 3b.1.3 `30a8443`
- 3b.1.4 `e562d24`
- 3b.1.5 `7daa5b8`
- 3b.1.6 `2645854`

**b. Infra facts of record:** Alchemy Free tier caps `eth_getLogs` at a
10-block range on both Base and Robinhood (hotfix 3b.1.1's finding);
the account was upgraded to PAYG, which removes that range cap entirely
(only a 150 MB response-size cap remains, guarded by
`scan_logs_chunked()`'s existing adaptive halving). `DEFAULT_CHUNK_SIZE`
is `2_000_000` (hotfix 3b.1.4). `RH_RPC_URL` is the Robinhood chain's
env var (mirroring `BASE_RPC_URL`). Both chains are served by one
Alchemy app/key, distinguished by subdomain
(`base-mainnet`/`robinhood-mainnet`) - not two separate Alchemy apps.

**c. Production run results (Sep 20):**

Base (real run, 2026-09-20 14:22 UTC): 4 `eth_getLogs` calls/pass, 62
receipt calls, `decode_failed: 0`. Event counts: `PositionCreated` 13,
`SnuggleRebalanced` 37, `PositionWithdrawn` 12, `FeesHarvested` 24 =
`ProtocolFeesDistributed` 24, `FeesCompounded` 13 =
`FeesHarvestedDirect` 13, `IncreaseLiquidity` 50. 50 positions derived
and upserted; 3 `ignored_duplicate` - the Commit 2 fixture seeds,
correctly recognized as already-present via the UNIQUE INDEX.

Robinhood (`dry_run` at 14:26, real run(s) completed by 14:42 - the
pasted real-run response showed all 1,776 events already present,
proving a full idempotent re-run: zero duplicates inserted, 326
positions re-derived from the existing rows): 35 `eth_getLogs`
calls/pass, 478 receipt calls, `decode_failed: 0`. Event counts:
`PositionCreated` 121, `SnuggleRebalanced` 205, `PositionWithdrawn` 91,
`FeesHarvested` 339 = `ProtocolFeesDistributed` 339, `FeesCompounded`
168, `FeesHarvestedDirect` 187 (NOT 1:1 with FeesCompounded - direct-
only compounds exist, i.e. a `FeesHarvestedDirect` with no accompanying
`FeesCompounded` in the same tx), `IncreaseLiquidity` 326.

**d. NPM findings:** Base has **two** NPMs -
`0x03a520b32c04bf3beef7beb72e919cf822ed34f1` (29 positions, tokenIds
~4.95M-6.04M) and `0x827922686190790b37229fd06084350e74485b72` (21
positions, tokenIds ~67.66M-71.12M, April through recent). Their
tokenId ranges are disjoint, so leaving `npm=None` in the ledger key
(module docstring's existing design) stays collision-free - a
different-NPM position never collides with another position's ledger
row under the same `(vault, None, token_id)` key, since token_ids never
overlap between the two NPMs in this data. Robinhood has a single NPM:
`0x73991a25c818bf1f1128deaab1492d45638de0d3`. `PoolAdded` never fired
on either vault's full history - confirms 3b.1.6's Ruling 9 amendment
(receipts as the NPM source) was the correct fix, not a workaround for
a Base-only quirk.

**e. RH same-codebase assumption CONFIRMED:** `decode_failed: 0` across
all 1,776 Robinhood events - every topic0 and layout verified against
Base (Commits 3a/3b.1.5/3b.1.6) holds identically on Robinhood. No
Robinhood-specific decoder branch has ever been needed.

**f. Reconciliation spot-checks (Base):**
- TokenId 6039568: exact to the wei on both basis and the 85/15 harvest
  split; `opened_block` matches the true mint block.
- TokenId 5890746 (a rebalance-minted child): the derive rebalance-tx
  branch in `maxfi_ledger._tx_net_claim()` - still marked
  `[Inference], no rebalance-tx fixture exists to verify this branch`
  in that function's own docstring - produced correct basis on real
  data (100,024,012 USDC single-sided, vs. a $100 manual estimate).
  **That `[Inference]` marker can now be revised to "exercised on
  production data Sep 20"** - deferred to the next commit that touches
  `maxfi_ledger.py` (a docstring-only change, item h.5 below), not done
  here since this commit is doc-only.
- TokenId 5984382: the app records a $1,321 close, but the chain shows
  no `PositionWithdrawn` for it - the rebalance-recorded-as-a-close
  pattern (Symptom A) is now provable on-chain, not just suspected.
  Its `claimed_net0 = 0` with `claimed_gross0 > 0` is correct behavior:
  the token0 side was fully compounded (no net wallet-side claim on
  that side), not a bug.
- Robinhood tokenId 891560: the $239 Sep 7 manual claim date-matches a
  real on-chain harvest; the withdrawal's token0 side equals
  `exit_net_fee0` exactly, with all principal on token1 - whether that
  split is fee vs. principal by price is a 3b.2 (USD pricing) question,
  not resolvable from wei amounts alone.
- Robinhood tokenId 1063377: the manual claim is dated Sep 9, but the
  only on-chain harvest for this tokenId is Sep 12 - unmatched, with
  one unpaired ledger event on the chain side. Either a manual-entry
  date error, or a harvest the manual record never saw.
- Robinhood tally over the app's 117 tracked positions: 59 fully
  ledger-backed with exits, 7 unmatched manual claims, 2 manual claims
  with no on-chain harvest for that tokenId, 7 with no on-chain
  activity at all.

**g. Two-era note:** the ledger now holds 50 Base / 326 Robinhood
positions, against the app's 4 / 117 tracked positions - the existing
reconciliation route is app-position-centric by design (it walks the
app's own tracked list), so it only ever surfaces the overlap. A
ledger-only position listing (everything the chain shows, independent
of what the app happens to track) is a real gap, adjacent to but not
required by 3b.3 - noted here, not scoped to any commit yet.

**h. Carried items:**
1. **3b.2 next** - Swap-log USD pricing. Robinhood's hop pool is
   WETH/USDG (not USDC) - self-resolvable via
   `maxfi_client.get_pool`/`npm.factory()`, not a blocker. Base's
   ETH/USDC 0.05% pool is `0xd0b53D9277642d899DF5C87A3966A349A798F224`.
   Pricing walks backward in small chunks from a known point, never a
   full range-scan.
2. **3b.3** - the per-claim USD table; also expose `compounded0`/
   `compounded1` in the reconciliation route's output (currently
   derived but not surfaced there).
3. **Three still-unidentified StakingManager topic0s** (from the
   3b.1.5 fixture): `0xe6d1ff392bdc1cf53105ebfcb0e3f7b024a8b0915b1f131907da7a9f84f52b86`,
   `0xdd8df9cdfbfa0633e022e142f0da49c4cb7f22a3cf1c8a632425282652aefeff`,
   `0x627009b4f6918ee0f41065d4adffdb5142a9ef54c66cc350bb8396c1c82a409c` -
   out of this module's tracked vocabulary, skipped by design
   (`decode_log()` returns `None` for them), not an error.
4. **`unverified_event_types` key rename** - the key name itself
   (`unverified_event_types`, now a slight misnomer since 3b.1.5
   verified both layouts) rides with 3b.3 rather than changing here;
   renaming a response key is a shape change, out of scope for this
   doc-only close-out.
5. **`maxfi_ledger.py` rebalance-branch `[Inference]` marker revision**
   (item f above) - a docstring-only change, deferred to the next
   commit that touches the pure module, so this close-out stays
   doc-only as instructed.

## Commit 3b.2 — Swap-log USD pricing (basis/exit/claim)

**What was built.** `basis_price_usd`/`exit_price_usd` had sat hardcoded
`None` in `derive_position_ledger()`'s return dict since Commit 1 -
`maxfi_ledger.py` already had `TOPIC_SWAP`/`decode_swap()`/
`price_at_or_before()`/`build_pool_map()`, all real, all unused in
production. This commit prices them, and per-claim USD, for real:

- **`maxfi_ledger.py`** (pure, zero network/RPC, unchanged elsewhere):
  two new functions, `usd_price_at_or_before(swap_logs, target_block,
  decimals0, decimals1, anchor_is_token1, anchor_usd)` and
  `position_usd_value(amount0_wei, amount1_wei, decimals0, decimals1,
  token0_usd, token1_usd)`. Built on the existing `price_at_or_before`/
  `decode_swap`/`sqrt_price_x96_to_price`/`invert_price` primitives,
  not reimplemented. `derive_position_ledger()`/`derive_all()`
  themselves are untouched - `git diff origin/main -- maxfi_ledger.py`
  shows only these two additions.
- **`maxfi_ledger_pricing.py`** (new module, RPC): per-tokenId pool
  resolution (`resolve_position_pool()` - generalizes
  `maxfi_client.position_diagnostic()`'s proven `npm.positions() ->
  factory() -> getPool()` pattern to a per-tokenId NPM, since Base has
  TWO NPMs, 3b.1.6's finding), the Robinhood WETH/USDG hop-pool
  fee-tier probe (`resolve_rh_hop_pool()`, ruling B), ERC20
  `decimals()`, and the backward-chunked Swap-log walk
  (`swap_logs_backward()` - never a full range-scan, ruling 10; 10,000-
  block windows, capped at 30, reuses
  `maxfi_ledger_ingest.scan_logs_chunked()`'s own 429/oversize-range
  backoff for each window rather than reimplementing it).
  `token0_token1_usd_at_block()` orchestrates the two: direct-stable
  (the position's pool has USDC/USDG on one side, anchor_usd=1.0) or
  one hop via WETH/aeWETH (neither side is a direct stable, but one
  side is WETH-like - two `usd_price_at_or_before()` calls composed,
  "multiply/divide two pool prices at their own nearest-at-or-before
  blocks"). A pool with neither a direct stable nor a WETH-like side
  has no priced path (a second hop is out of scope) and prices as a
  soft failure, same as any other pricing miss.
  **Selectors copied from `maxfi_client.py` after reading that file
  first** (`SEL_POSITIONS "0x99fbab88"`, `SEL_NPM_FACTORY "0xc45a0155"`,
  `SEL_FACTORY_GET_POOL "0x1698ee82"`, `SEL_ERC20_DECIMALS
  "0x313ce567"`), not retyped from memory. `maxfi_client.py` itself is
  NOT imported (hard constraint: it hardcodes one NPM per chain, which
  doesn't fit per-tokenId resolution); `maxfi_pricing.py` (the
  pre-existing CURRENT-price live-valuation module) is also not
  imported - a related but distinct problem (today's slot0 vs. a
  historical Swap-log walk). Both transport (`eth_call`,
  `scan_logs_chunked`, `MaxFiRpcError`) and the raw-RPC-log adapter
  (`rpc_log_to_etherscan_shape`/`_adapt_rpc_logs`) are reused from
  `maxfi_ledger_ingest.py` by import, not duplicated - `git diff
  origin/main -- maxfi_ledger_ingest.py` shows zero diff.
  **A real bug this caught before landing:** `swap_logs_backward()`'s
  first draft handed `eth_get_logs()`'s raw output straight to
  `maxfi_ledger.decode_log()` - exactly hotfix 3b.1.2's own
  `KeyError: 'timeStamp'` failure mode, since a real RPC log carries no
  `timeStamp` field, only Alchemy's non-standard `blockTimestamp` (or
  neither). Fixed by adapting through `_adapt_rpc_logs()` before
  returning, with a regression test
  (`test_swap_logs_backward_adapts_raw_rpc_shape_logs`) built from the
  genuinely raw shape, not the already-adapted test doubles every other
  test in that file uses for convenience.
- **`web_portfolio.py`**: `_run_ledger_backfill()` now re-derives
  (`derive_all()`) and prices BEFORE the DB connection opens (matching
  that function's own existing "all RPC I/O completes before the DB
  connection opens" convention), building `npm_by_token_id` from
  `scan["npm_resolutions"]` (3b.1.6's receipt walk) and pricing each
  row's `basis_block`/`closed_block` (when present) via
  `token0_token1_usd_at_block()` + `position_usd_value()`. Soft-
  isolated per position (3b.1.3 precedent) - a pool/decimals RPC
  failure or "no Swap found within the walk's cap" is counted
  (`pricing_priced`/`pricing_failed`/`pricing_failed_sample`, new
  response keys) and skipped, never aborting the batch. `basis_price_
  source`/`exit_price_source` are set to `"swap_log"` only when a price
  was actually found. `pool_address` on the ledger row itself is
  **deliberately left unpopulated this commit** - resolving it was not
  asked for, and adding it would have been unauthorized scope creep on
  a money-path commit; noted below as a natural, low-risk follow-up.
  `_maxfi_ledger_claim_usd(chain, decoded, block_number)` (ruling D:
  computed on READ, never persisted, unlike basis/exit) widened from
  its old 1-arg `decoded`-only signature; it resolves the position's
  pool from `maxfi_ledger_pricing._POOL_RESOLUTION_CACHE` alone - an
  **opportunistic, documented limitation**: it does no fresh NPM lookup
  of its own (no `npm_resolutions` data reaches a read-only route), so
  a claim for a token_id this process has never backfilled returns
  `None`, same as before this commit. In practice every token_id the
  reconciliation route can meaningfully report on has already been
  backfilled at least once in the same process.

**RH hop pool: NOT resolved this session.** This sandbox has no live
RPC egress (standing constraint) - `resolve_rh_hop_pool()`'s fee-tier
probe (100/500/3000/10000 against aeWETH/USDG) is built and fully
mock-tested, but has never actually run against live Alchemy. Per
ruling B, Glenn does not need to paste anything unless a real run
shows all four probes returning the zero address - the probe resolves
and caches the real address automatically at the next real ingest run
against either chain (RH's own NPM factory).

**Still owed** (unchanged from 3b.1's own close-out list where it
overlaps):
1. Real Base `dry_run` against this commit (expect `pricing_priced` >
   0, `basis_price_usd` populated on priced rows, `pricing_failed`
   sample showing exactly what's still unpriceable), then a real Base
   run, then Robinhood `dry_run` (this is where the RH hop-pool probe
   gets its first live exercise) then a real Robinhood run.
2. Alchemy key rotation - still owed, per the standing note (outside
   this document's own history so far).
3. `pool_address` on `maxfi_ledger_positions` rows - available for free
   from the same pool resolution pricing already does
   (`resolve_position_pool()`'s own return), not populated this commit
   (see above) - a natural, low-risk follow-up.
4. 3b.3 - the per-claim USD table (persisting what `_maxfi_ledger_claim_
   usd` computes on read today), and exposing `compounded0`/
   `compounded1` in the reconciliation route.
5. A genuine 2-hop pricing path (neither side stable nor WETH-like) is
   out of scope - `token0_token1_usd_at_block()` returns unpriced for
   that shape by design, not a bug.

**Amendment before landing (PR #145 review):** exit pricing is
principal-only. `PositionWithdrawn`'s amounts are NET and INCLUDE any
same-tx harvested fees (this doc's own verified ground truth: "exit
principal = PositionWithdrawn − FeesHarvested ×0.85, don't
double-count") - the pricing block's first draft priced
`exit_amount0_wei`/`exit_amount1_wei` as-is, so any exit with a same-tx
harvest read high by the claimed amount (e.g. RH 891560, whose
`exit_amount0` equals `claimed_net0` exactly - reconciliation's `exit`
category compares against `closing_value_usd`, a principal-only app
snapshot, so this was a guaranteed false mismatch on every such exit).
Fixed: `exit_price_usd` now prices `exit_amount{0,1}_wei −
exit_net_fee{0,1}_wei` per side - `derive_position_ledger()`'s own
already-computed net-fee fields (set in the same `PositionWithdrawn`
branch as `closed_block`, via `_tx_net_claim()`, so non-None whenever
`closed_block` is; a `None` here is defensive only, treated as 0). A
negative principal on either side (impossible on real chain data) is
never priced - counted as `pricing_failed` with reason
`"net_fee_exceeds_withdrawal"` instead. `exit_price_source` stays
`"swap_log"`; no new column or source string. Caught in chat review of
PR #145 before merge, not after - the two-test fixture proving it
(principal-only vs. the gross value the bug would have produced, and
the negative-principal guard) is synthetic: no real
`PositionWithdrawn`+`FeesHarvested`+`ProtocolFeesDistributed` same-tx
fixture exists in this repo yet.

**Two flags of record, carried forward:**
- The claim-USD seam (`_maxfi_ledger_claim_usd`) prices only from the
  in-process pool-resolution cache warmed by a backfill in the SAME
  deploy - operational rule until 3b.3 persists pool resolution
  somewhere a read-only route can reach it: backfill both chains, then
  read reconciliation, in the same deploy, for claim pricing to have
  any chance of firing.
- The backward Swap-log walk's cap (`DEFAULT_SWAP_WALK_WINDOW` = 10,000
  blocks × `DEFAULT_SWAP_WALK_MAX_WINDOWS` = 30) is **not chain-aware**:
  roughly a week of reach on Base's ~2s blocks, but only on the order of
  8 hours on Robinhood's ~0.1s blocks. Deliberately left as-is (Glenn's
  ruling B, this landing) - the first real Robinhood run's
  `pricing_failed_sample` is what decides whether this actually needs
  chain-specific tuning, not a guess made ahead of that evidence.

## Commit 3b.2.1 — pool address from the mint receipt (burned-NFT fix) + pricing failure reasons

**Symptom.** The first post-3b.2 Base `dry_run` (Sep 20 16:37 UTC): ingest
identical to the prior run (50 positions, 13 mints + 37 rebalance
children, `decode_failed` 0, both NPMs resolved) but `pricing_priced` 1 /
`pricing_failed` 61 of 62 lookups, completing in seconds (no Swap walk
ever ran), every sample `{"field", "token_id"}` with no error/reason.

**Root cause (spec error #25, chat).** `maxfi_ledger_pricing.
resolve_position_pool()`'s only path was `npm.positions(tokenId)` at
`"latest"`. A burned NFT's `positions()` **reverts** (the B1.1 catalogue
invariant), and `get_npm_position_tokens()` swallowed that
`MaxFiRpcError` into a bare `None` - the row landed unpriced with no
reason. The arithmetic checks out exactly: 50 positions − 37
rebalanced-away − 12 withdrawn = exactly 1 live NFT = exactly the 1
priced row. The ledger is mostly history by construction (every
rebalance and every withdrawal burns the old NFT), so `positions()` at
`"latest"` was the wrong primitive for it from the start.

**Fix (Glenn's ruling B).** The pool address is derivable per-tx from the
mint/rebalance receipt's own Uniswap V3 pool `Mint` log (this doc's own
"pool address is derivable per tx from the Mint/Collect emitter" line) -
already present in every receipt `maxfi_ledger_ingest.scan_chain()`'s
receipt walk fetches. `Mint(address sender, address indexed owner, int24
indexed tickLower, int24 indexed tickUpper, uint128 amount, uint256
amount0, uint256 amount1)` - standard, immutable; topic0
`0x7a53080ba414158be7ec69b987b5fb7d07dee101fe85488f0853ae16239d0bde`,
computed via `maxfi_ledger._topic0()` from that exact signature, cross-
checked against the real Base tokenId 6039568 mint tx
(`tests/fixtures/maxfi_ledger/base_mint_6039568.json`, item index 302):
that item's own `topics[0]` and Blockscout `method_id` (`"7a53080b"`)
match exactly, byte for byte - independently verified from the raw data
hex before writing any test, not trusted from Blockscout's own decoded
field (word[1]/[2]/[3] = 3473656907099 / 1905032765586610 / 5000000,
exactly the task's stated values and exactly IncreaseLiquidity's own
liquidity/amount0/amount1 for the same tx).

A keeper batch's receipt carries SEVERAL users' Mints, so a kept
`IncreaseLiquidity` log is paired to its Mint **by value** -
`(amount, amount0, amount1) == (liquidity, amount0, amount1)` - never by
log order or adjacency. Exactly one match pairs; zero or multiple
matches record nothing (counted as `pool_mint_unpaired`/
`pool_mint_ambiguous`, never a guess). `token0()`/`token1()` on the pool
contract itself (selectors `0x0dfe1681`/`0xd21220a7`, computed via
`Web3.keccak`, never guessed) then resolve the two tokens - the pool
contract never burns, unlike an NFT position.

**What changed:**
- `maxfi_ledger_ingest.py`: `scan_chain()`'s receipt walk now also
  collects pool Mint logs per receipt and pairs them to kept
  `IncreaseLiquidity` logs by value. Return gains the additive
  `"pool_by_token_id"` key (`str(token_id) -> pool_address`) and four
  new `chunk_stats.receipts` counters (`pool_mint_paired`/`_unpaired`/
  `_ambiguous`/`_malformed`). Nothing existing changes shape.
  `maxfi_ledger.py` is untouched - the Mint log is a resolution input
  only, never written to `maxfi_ledger_events`, never added to that
  module's decode vocabulary.
- `maxfi_ledger_pricing.py`: new `get_pool_tokens(chain, pool_address)`
  (cached). `resolve_position_pool()` gains an optional `pool_address`
  parameter - when given, resolves via `get_pool_tokens()` alone (no
  `positions()`/`factory()`/`getPool()` call at all) and reports
  `"pool_source": "mint_receipt"`; when omitted, falls back to the
  original `npm.positions()` path (kept, still correct for a live NFT),
  reporting `"pool_source": "npm_positions"`. Cache key stays `(chain,
  token_id)` regardless of path. Return shape changed to `(pool_or_None,
  reason_or_None)` - every failure now names one of
  `"pool_tokens_unresolved"` / `"pool_unresolved"` / `"decimals_
  unresolved"`. `token0_token1_usd_at_block()` gained the same
  `pool_address` passthrough and now populates `stats["reason"]` on
  every failure path, adding `"hop_pool_unresolved"` / `"no_swap_in_
  reach"` / `"unpriceable_pair"` to the vocabulary. Also fixed a cosmetic
  bug: `swap_logs_backward()`'s `stats["found_at_block"]` was the
  window's own start block, not the Swap actually found - now the
  selected Swap's real block.
- `web_portfolio.py`: the pricing block passes `pool_by_token_id.get
  (row["token_id"])` into both the basis and exit resolution calls, and
  now writes the resolved `pool_address` into the row (populated
  whenever resolution succeeded, priced or not - this column had sat at
  `None` since Commit 1). Every `pricing_failed_sample` entry now
  carries `"reason"` - from `stats["reason"]`, from the 3b.2 amendment's
  own `"net_fee_exceeds_withdrawal"`, or `"rpc_error: <message>"` for an
  `MaxFiIngestError` that escaped the whole attempt. Response gains
  `"pool_resolved"` (count of rows whose pool resolved this run) beside
  `pricing_priced`/`pricing_failed`. The exit principal-only amendment
  itself (subtract same-tx net fees) is untouched by this commit.

**Reason vocabulary** (surfaces in `pricing_failed_sample[].reason`):
`pool_tokens_unresolved`, `pool_unresolved`, `decimals_unresolved`,
`hop_pool_unresolved`, `no_swap_in_reach`, `unpriceable_pair`,
`net_fee_exceeds_withdrawal`, `rpc_error: <message>`.

**Zero diff confirmed** on `maxfi_ledger.py`, `maxfi_schema.py`,
`maxfi_client.py`.

**Still owed:** `pool_address` is populated from this commit on - a
future 3b.3 note: the claim-USD seam (`_maxfi_ledger_claim_usd`) can now
resolve a position's pool from the PERSISTED `maxfi_ledger_positions.
pool_address` row instead of the in-process pool-resolution cache
(today's opportunistic, same-deploy-only limitation, previous section) -
not done here, this commit stays scoped to the burned-NFT fix and the
reason vocabulary. Real Base `dry_run` against this commit next (expect
`pool_resolved` near 50, most `pricing_failed_sample` entries now naming
a real reason instead of none), then the real run, then Robinhood.

## Commit 3b.2.2 — pricing failure samples carry pool_address/token0/token1

**Symptom.** The first Base `dry_run` on 3b.2.1 (Sep 20 17:16 UTC):
`pool_mint_paired` 50/50, `pool_resolved` 50, `pricing_priced` 41 /
`pricing_failed` 21, every failure `reason` `"unpriceable_pair"` (the
pool has neither the chain's stable anchor nor WETH on either side). The
sample entries carried only `token_id`/`field`/`reason` - `token0`/
`token1` are never persisted anywhere, so the 21 couldn't be diagnosed
from the response alone.

**Fix.** The resolution dict (`pool_address`, `token0`, `token1`,
`decimals0`, `decimals1`) is already in hand at the point each basis or
exit `pricing_failed_sample` entry is built. Whenever that dict is
non-`None`, its `pool_address`/`token0`/`token1` (lowercased) are now
added to the sample entry - for every reason, not just
`unpriceable_pair` (a `no_swap_in_reach` entry benefits equally). The
`pool_unresolved`/`rpc_error` paths, where no resolution dict exists (or
may be stale from a prior row), are unchanged. Pricing logic itself,
reason strings, counts, and what's written to `maxfi_ledger_positions`
are all untouched.

**Scope.** `web_portfolio.py` (3b.2 pricing block only) +
`tests/test_maxfi_ledger_backfill_route.py` (two existing sample-shape
assertions gained the new optional keys; two new tests added covering
`unpriceable_pair` gaining the keys and `pool_unresolved` not gaining
them). Zero diff on `maxfi_ledger.py`, `maxfi_ledger_pricing.py`,
`maxfi_ledger_ingest.py`, `maxfi_schema.py`, `maxfi_client.py`.

## Commit 3b.2.3 — budgeted resumable pricing, carry-forward, per-chain walk window, persisted last-run

**Symptom (Sep 20, 17:28 UTC).** The first post-3b.2.1 Robinhood
`dry_run` died mid-request: the previous deployment's own log shows a
SIGTERM at 17:28 UTC - the 3b.2.2 auto-deploy stopped the container
while that request was still in flight, not a timeout. The re-run
~2h later, with no redeploy in between, returned a 409 (`RefreshBusy` -
a prior run still holding `_LEDGER_BACKFILL_LOCK`), then, once clear, a
502 "upstream error" after a few minutes. Conclusion: a full 326-
position Robinhood pricing pass (up to 417 lookups × 1-2 backward
Swap walks × up to 30 windows each) does not reliably fit inside one
HTTP request/proxy window - Base (50 positions) fits today only by
luck. **Standing rule from this finding: never land a deploy while a
backfill is in flight** - the SIGTERM is exactly what a mid-request
deploy does to this route.

**Fix - four pieces, all landed together (Glenn's ruling A/A/B: this
commit, ~600 RPC calls/invocation, no further log forensics first).**

1. **Per-chain Swap-walk window** (`maxfi_ledger_pricing.py`) -
   `SWAP_WALK_WINDOW_BLOCKS = {"base": 10_000, "robinhood": 200_000}`;
   `swap_logs_backward()` resolves its window from `chain` when the
   caller passes none (an explicit `window=` still always wins).
   `max_windows` stays 30 on both chains (~7 days of reach). Robinhood's
   own evidence for the wider window arrived alongside the 502 above -
   folded into this same commit rather than a fifth piece.

2. **RPC call accounting** (`maxfi_ledger_pricing.py`) -
   `token0_token1_usd_at_block()`'s `stats` gains `"rpc_calls"`: EVERY
   eth_call/eth_get_logs this invocation actually caused - pool/hop-pool
   resolution and decimals lookups (previously uncounted; only the Swap
   walk's own calls were) PLUS the walk's own `swap_walk_calls` - a
   cache hit anywhere costs 0. Threaded through `resolve_position_pool`/
   `get_decimals`/`get_factory`/`get_pool`/`get_pool_tokens`/
   `resolve_rh_hop_pool` via an internal `_counter` kwarg (default
   `None`, so every existing direct call to these functions is
   unaffected); the public `token0_token1_usd_at_block()` signature
   itself is unchanged.

3. **Price carry-forward** (`web_portfolio.py`) - a READ-ONLY lookup
   inserted between derive and price: unless `?reprice=true` (or body
   `{"reprice": true}`, same parsing convention as `dry_run`, applies to
   `dry_run` too), each already-priced row from the LAST run for this
   chain (keyed by `(vault, npm, token_id)`, `npm` compared the same
   `IS`-based way the DELETE below it already does) has its
   `pool_address`/`basis_price_usd`/`basis_price_source`/
   `exit_price_usd`/`exit_price_source` copied onto the matching
   freshly-derived row BEFORE pricing; the pricing loop then skips
   re-pricing whatever arrived already priced. `pool_address` carries
   forward even when the price didn't (a resolved pool stays valid even
   if its Swap walk failed). The write itself is UNCHANGED - still a
   full DELETE-then-INSERT every run; carry-forward only changes what
   the loop re-attempts, never the write shape. Response gains
   `"pricing_carried_forward": {"basis", "exit", "pool_address"}` and
   `"reprice": bool`.

4. **Budget** (`web_portfolio.py`) -
   `MAXFI_LEDGER_PRICING_CALL_BUDGET = 600` (overridable via
   `?max_pricing_calls=N` / body key, positive int required, else 400,
   validated in the route before `_run_ledger_backfill`'s own lock is
   ever reached). The pricing loop tracks `pricing_calls_used` from each
   lookup's own `stats["rpc_calls"]`; once `>= budget`, a row's
   remaining lookups are deferred (never attempted - reported in
   `"pricing_deferred": {"basis", "exit"}`) rather than spending an
   unknown number of calls past the cap. A lookup already under budget
   when it starts is allowed to finish even if it overshoots - the walk
   itself is already bounded, never aborted mid-walk. Deferred rows keep
   whatever they already had (carried-forward or `None`) and are STILL
   upserted - the budget never skips the write. Response also gains
   `"pricing_calls_used"`/`"pricing_call_budget"`.

5. **Persisted last-run** (`web_portfolio.py`) -
   `LEDGER_BACKFILL_LAST_RUN_PATH = "data/ledger_backfill_last_run_
   {chain}.json"`; the full response (dry_run or not) is written there,
   atomically (temp file + `os.replace`), after every run - best-effort,
   any `OSError` is logged and swallowed, never fails the request. New
   `GET /api/maxfi/ledger/backfill/<chain>/last-run` reads it back (200
   + the JSON, or 404 `{"error": "no run recorded"}` before any run, or
   400 for an unknown chain) - same auth gate as the backfill route (no
   per-route decorator; both rely on the app-wide `@app.before_request`
   login gate). This is the recovery path for a dropped response: the
   run itself keeps executing server-side regardless of what happens to
   the caller's own HTTP connection.

**Re-fire operating procedure** (the actual fix for the 502): POST the
same backfill repeatedly (no `reprice`) until `pricing_deferred` is `0`
for both `basis` and `exit` - carry-forward means each subsequent POST
only spends its budget on rows the previous one didn't reach, so the
whole backfill converges over a handful of calls even though no single
call can safely do all ~417 Robinhood lookups. If the browser/caller
lost the response entirely (the 502 case itself), read
`GET .../last-run` instead of re-POSTing blind - the run already
completed server-side.

**Scope.** `maxfi_ledger_pricing.py`, `web_portfolio.py`,
`tests/test_maxfi_ledger_backfill_route.py`,
`tests/test_maxfi_ledger_pricing.py`. No schema change, no new table, no
new columns. Pricing MATH untouched (`maxfi_ledger.py` zero diff -
`usd_price_at_or_before`/`position_usd_value` unchanged; the exit
principal-only amendment byte-identical). Zero diff on `maxfi_ledger.py`,
`maxfi_ledger_ingest.py`, `maxfi_schema.py`, `maxfi_client.py`. A handful
of existing stubbed `stats` dicts (both pricing and route test files)
gained the additive `"rpc_calls"` key; documented at each site, no
existing assertion's OWN expected value changed.

**Still owed:** this commit does not itself run the recovery procedure
against production - next is re-firing the real Robinhood backfill
(POST, no reprice, repeatedly) until `pricing_deferred` reads `0/0`,
confirmed via `GET .../last-run` if any response drops again.
