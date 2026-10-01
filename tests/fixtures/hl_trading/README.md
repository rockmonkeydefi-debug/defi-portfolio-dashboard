Recorded Hyperliquid info-API responses for the trading-performance perp engine (HANDOFF_trading_performance.md, Commit 3). Never regenerate these from live calls inside tests; the Claude Code sandbox has no egress to Hyperliquid.

Accounts: rm = the "Hyperliquid RM" wallet, rabby = the "Rabby (Hyperliquid)" wallet. Captured 2026-09-30 from https://api.hyperliquid.xyz/info with userFillsByTime (aggregateByTime false) and userFunding, both from the Sep 13 2026 window start, plus frontendOpenOrders and historicalOrders.

Files (records):
- rm.fills.json (61), rm.funding.json (162), rm.open_orders.json (0), rm.hist_orders.json (102)
- rabby.fills.json (99), rabby.funding.json (183), rabby.open_orders.json (2), rabby.hist_orders.json (742)
- expected_cycles.json: the golden output of reference_cycles.py over the eight files above (20 cycles: rm 9 closed; rabby 10 closed + 1 open; unattributed funding 0 for both).
- reference_cycles.py: the test oracle that produced expected_cycles.json. Its docstring states rules R1-R9. Production code must not import it.

Sanitized before commit (privacy ruling of Sep 30):
- Prices and sizes were multiplied by undisclosed constants, so no value matches the real market.
- USD amounts (closedPnl, fee, funding usdc) were scaled consistently, so every relationship between fields holds. R multiples are unchanged.
- Timestamps were shifted by an undisclosed whole number of days, so hour and UTC-day boundaries are preserved.
- oids and tids were replaced with order-preserving fakes, consistent across files.
- Transaction hashes were replaced. The all-zero funding hashes were kept.
- No wallet address appears anywhere.

Facts verified on the raw captures, before sanitizing:
- closedPnl EXCLUDES fees. 77 of 78 closing fills equal (px - average entry) x sz exactly; one is 0.07% off, from Hyperliquid's own entry rounding.
- A negative funding usdc means the account PAID funding.
- Older funding arrives as daily totals: nSamples is set, time is the UTC day start, and szi is the day's average size. Recent funding is hourly, with nSamples null.
- There are no spot ("@N") fills, no HIP-3 ("dex:COIN") fills, no flip fills and no liquidations.
- historicalOrders keeps each order's placement record (with triggerPx) plus later status records for the same oid: 'canceled', 'triggered', 'reduceOnlyCanceled', 'siblingFilledCanceled', 'filled'.
- A triggered stop's 'filled' record has isTrigger false and triggerPx "0.0".
- Stops attached at entry also appear as children of the entry order, sometimes carrying the entry's oid. The standalone stop record always exists, so the oracle ignores children.
- Every one of the 20 cycles has a Hyperliquid stop: 17 placed at the entry timestamp, 3 within 7 minutes after.
