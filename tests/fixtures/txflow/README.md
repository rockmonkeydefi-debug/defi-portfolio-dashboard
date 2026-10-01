Recorded TxFlow info-API responses for the open-perps view and, later, the Trade Log (HANDOFF_trading_performance.md). Never regenerate these from live calls inside tests; the test sandbox has no egress to TxFlow.

Account: one TxFlow trading wallet (shown as "TxFlow"). Captured 2026-10-01 with POST https://api.txflow.com/info (JSON body, no signing) while one position was open with a position stop and a partial position take-profit.

Files (request body type -> file):
- clearinghouseState {"type","user"} -> clearinghouseState.json: one open long, its tpsl list (one stop covering the whole position, one take-profit covering a quarter of it) and the account summaries.
- userFills {"type","user"} -> userFills.json (5 fills, newest first: one closed long of two opening and two closing fills, plus the opening fill of the open long).
- historicalOrders {"type","user"} -> historicalOrders.json (5 records).
- openOrders {"type","user"} and frontendOpenOrders {"type","user","exchangeId":0} -> both [] although the stop and take-profit above were live.
- userFunding {"type","user","startTime"} and userFillsByTime {"type","user","startTime"} -> HTTP 403 with {"message":"This action is not allowed."}.
- geoCheck {"type"} -> {"geoBlock":false}.

Sanitized before commit (privacy ruling of Sep 30):
- Prices and sizes were multiplied by undisclosed constants, so no value matches the real market.
- USD amounts (positionValue, unrealizedPnl, marginUsed, cumFunding, cumFee, closedPnl, fee, pnl, filledAmount and the account summaries) were scaled consistently, so every relationship between fields holds. Ratios (returnOnEquity, roe, marginRatio) are unchanged.
- Timestamps were shifted by an undisclosed whole number of days.
- oids and tids were replaced with order-preserving fakes, consistent across files; transaction hashes were replaced.
- No wallet address appears anywhere.

Facts verified on the raw captures, before sanitizing:
- Position coin names carry the quote ("HYPE-USDC"); fills and orders use the bare coin ("HYPE") plus a symbol field ("HYPE-USDC").
- Position stops and take-profits live on the position: assetPositions[i].tpsl, a sibling of "position". Each entry has slTriggerPrice / tpTriggerPrice ("" when that side is unset) and a quantity in coin units. They are NOT returned by openOrders or frontendOpenOrders.
- markPx is returned on the position; positionValue / |szi| equals it to within the API's rounding. accountValue = totalRawUsd + unrealizedPnl.
- leverage.type is capitalized ("Cross").
- cumFee is negative for a fee paid. The sign of cumFunding.sinceOpen is NOT yet confirmed.
- Fill dir is "Buy" / "Sell" (not "Open Long" / "Close Long"); startPosition is the position before the fill, reduceOnly marks the closing fills.
- A closing fill's closedPnl is NET of that fill's fee: closedPnl = (px - average entry) x sz - fee, exactly, for both closing fills. Opening fills have closedPnl 0. (Hyperliquid's closedPnl excludes fees.)
- historicalOrders keeps a position stop as its own order record: isTrigger true, isPositionTpsl true, reduceOnly true, orderType "Market", triggerCondition "Price below <triggerPx>" for a long's stop. A filled order's "pnl" is the gross P&L before fees.
- Funding history is not available from this API (403 above), so closed trades' funding cannot be rebuilt from it.
