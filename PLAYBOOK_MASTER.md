# The Playbook — Master Build Instructions

## What This Is

A complete frontend rebuild of the DeFi portfolio dashboard. The backend (`web_portfolio.py`) is **never touched**. All existing Flask API routes are reused as-is. The frontend is replaced from scratch using the Playbook design system.

## Repository

- Repo: [https://github.com/rockmonkeydefi/defi-portfolio-dashboard](https://github.com/rockmonkeydefi/defi-portfolio-dashboard)  
- Branch: main (commit directly, no PRs, no branches)  
- Local path: E:\\Projects\\portfolio-dashboard  
- Deploy: Railway auto-deploys on push to main

## Stack

- Python/Flask backend — unchanged  
- Frontend: vanilla HTML \+ React 18 via CDN \+ Babel standalone (no bundler, no build step)  
- All JS in `static/`, all HTML in `templates/`  
- Entry point: `templates/index.html`

## Protected Files — Never Modify

- `entrypoint.sh` — `CONFIG_DIR=/app/data` is critical; upstream version breaks Zerion auth  
- `web_portfolio.py` — backend is read-only for this entire project  
- `requirements.txt`

## Design System Reference

The design handoff zip lives at: `E:\Projects\portfolio-dashboard\design_handoff_playbook\` Open `index.html` in a browser to view all screens interactively.

---

## Design Tokens (implement as CSS variables in index.html `<style>`)

:root {

  \--bg:         \#0a2a47;

  \--panel:      \#103f63;

  \--panel2:     \#154a72;

  \--panel3:     \#1c5a85;

  \--line:       \#266594;

  \--line-soft:  rgba(255,255,255,0.12);

  \--text:       \#ffffff;

  \--text2:      \#eef4fd;

  \--text3:      \#d7e5f6;

  \--text4:      \#b6cbe8;

  \--accent:     \#ffb52e;

  \--accent-soft: rgba(255,181,46,0.18);

  \--accent-line: rgba(255,181,46,0.5);

  \--ok:         \#4fdd8e;

  \--ok-soft:    rgba(79,221,142,0.18);

  \--warn:       \#ffd23f;

  \--warn-soft:  rgba(255,210,63,0.16);

  \--fail:       \#ff8a8a;

  \--fail-soft:  rgba(255,138,138,0.18);

  \--adapt:      \#2fb4e8;

  \--adapt-soft: rgba(47,180,232,0.2);

}

## Typography

- Body: `font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif`  
- Numbers/prices/addresses: `font-family: 'Fira Code', monospace` — apply via class `tv-num`  
- Uppercase labels: `font-size: 11px; font-weight: 600; letter-spacing: 0.06em; text-transform: uppercase` — class `tv-label`

Load both fonts from Google Fonts in `<head>`.

## Shared CSS Classes

.tv-frame     { background: var(--bg); min-height: 100vh; }

.tv-card      { background: var(--panel); border: 1px solid var(--line); border-radius: 12px; padding: 16px; }

.tv-card-2    { background: var(--panel2); border: 1px solid var(--line); border-radius: 12px; padding: 16px; }

.tv-btn       { border: 1px solid var(--line); border-radius: 8px; padding: 8px 14px; font-size: 13px;

                color: var(--text3); background: transparent; cursor: pointer; }

.tv-btn:hover { background: var(--panel2); }

.tv-btn.primary { background: var(--accent); color: var(--bg); font-weight: 700; border-color: var(--accent); }

.tv-btn.danger  { border-color: var(--fail); color: var(--fail); }

.tv-chip      { border-radius: 6px; padding: 2px 8px; font-size: 11px; border: 1px solid; display: inline-flex; align-items: center; gap: 4px; }

.tv-chip.ok   { color: var(--ok); border-color: var(--ok); background: var(--ok-soft); }

.tv-chip.fail { color: var(--fail); border-color: var(--fail); background: var(--fail-soft); }

.tv-chip.warn { color: var(--warn); border-color: var(--warn); background: var(--warn-soft); }

.tv-chip.accent { color: var(--accent); border-color: var(--accent-line); background: var(--accent-soft); }

.tv-chip.adapt  { color: var(--adapt); border-color: var(--adapt); background: var(--adapt-soft); }

.tv-dot       { width: 6px; height: 6px; border-radius: 50%; display: inline-block; }

.tv-num       { font-family: 'Fira Code', monospace; }

.tv-label     { font-size: 11px; font-weight: 600; letter-spacing: 0.06em; text-transform: uppercase; color: var(--text3); }

---

## Navigation Architecture

### Top Nav

- Height: 48px  
- Background: `var(--panel)` (\#103f63)  
- Bottom border: `1px solid var(--line)`  
- Active tab: `border-bottom: 2px solid var(--accent)`, `font-weight: 600`  
- Hover: `background: var(--panel2)`  
- Font: 13px, color `var(--text3)`, active `var(--text)`

**8 nav items:**

1. Dashboard  
2. Portfolio (sub-tabs: Token Holdings | DeFi Positions | LP Tools)  
3. Spot P\&L (sub-tabs: Live Holdings | Trade History | Transactions)  
4. Performance  
5. Market Data  
6. AI Brief  
7. Trading Tools (dropdown → Scanner | Validator | Journal | Reports | Concepts | Quiz | Trading Settings)  
8. Settings

### Sub-nav (Trading Tools screens only)

- Strip below main nav, background `var(--panel2)`, border-bottom `1px solid var(--line)`, padding `0 22px`  
- Items: Scanner | Validator | Journal | Reports | Concepts | Quiz | Trading Settings  
- Active: `border-bottom: 2px solid var(--accent)`, `font-weight: 600`  
- "Trading Tools" in main nav stays highlighted when any sub-screen is active

### Sub-tabs (Portfolio, Spot P\&L)

- Rendered inside the page content area (not a second nav strip)  
- Segmented control style: pill buttons, active \= `background: var(--panel3)`, border `var(--accent-line)`

---

## Global State

// Persist to localStorage, read on app init

const globalState \= {

  hideValues: false,    // masks all financial figures with ••••

  activeTab: 'dashboard',

  activeSubTab: {},     // e.g. { portfolio: 'tokens', spotpnl: 'live' }

}

**`mask(value, hidden)`** utility — returns `'••••'` when `hidden=true`, else the formatted value. Apply to ALL portfolio balances, P\&L figures, position values, cost basis, etc. Market data, quiz scores, and macro indicators are NOT masked.

---

## API Endpoint Reference (all existing, backend unchanged)

### Portfolio & Wallets

- `GET /api/portfolio` — full portfolio data (tokens, LP positions, lending positions, totals)  
- `GET /api/wallets` — wallet list with labels, visibility flags  
- `POST /api/wallets` — add wallet `{address, label}`  
- `PUT /api/wallets/<address>` — update wallet `{label, visible, color}`  
- `DELETE /api/wallets/<address>` — remove wallet  
- `GET /api/config` — app config (RPC endpoints, dust threshold, lending threshold, etc.)  
- `POST /api/config` — save config

### Manual LP Positions

- `GET /api/manual-positions` — active manual LP positions  
- `POST /api/manual-positions` — add position (fields: chain, protocol, token0, token1, amount0, amount1, range\_lower, range\_upper, fee\_tier, price0\_override?, price1\_override?, notes?)  
- `PUT /api/manual-positions/<id>` — update/close/edit (action: 'close' | 'edit' | patch fields)  
- `DELETE /api/manual-positions/<id>` — delete

### Manual Hedges

- `GET /api/manual-hedges` — active hedges  
- `POST /api/manual-hedges` — add hedge  
- `PUT /api/manual-hedges/<id>` — update

### Spot P\&L

- `GET /api/spot/transactions` — all transactions  
- `POST /api/spot/transactions` — create `{date, symbol, side, units, price_usd, platform?, notes?}`  
- `PUT /api/spot/transactions/<id>` — update transaction  
- `DELETE /api/spot/transactions/<id>` — delete transaction  
- `POST /api/spot/import-csv` — CSV import  
- `GET /api/spot/pnl` — FIFO P\&L calculation (live holdings \+ unrealized)  
- `GET /api/spot/history` — closed positions / realized P\&L  
- `GET /api/spot/stablecoins` — stablecoin balances (dry powder)  
- `GET /api/spot/token-config` — per-token price source config  
- `POST /api/spot/token-config` — upsert token config  
- `DELETE /api/spot/token-config/<symbol>` — remove token config  
- `GET /api/spot/price-test/<symbol>` — test price lookup for a token

### Market Data

- `GET /api/market-data` — cached market data (BTC/ETH prices, Fear & Greed, macro indicators)  
- `POST /api/market-data/refresh` — force refresh  
- `GET /api/market/macro` — BTC macro cycle indicators (MVRV, NUPL, PI Cycle, etc.)  
- `GET /api/market/lending-rates` — DeFi lending rates table  
- `GET /api/market/stablecoin-7d` — stablecoin 7d data  
- `GET /api/market/stablecoin-supply` — stablecoin supply data

### Performance / History

- `GET /api/history/portfolio-chart` — portfolio value timeseries for equity curve  
- `GET /api/history/portfolio` — portfolio history records  
- `GET /api/history/closed-positions` — closed LP and hedge positions (params: days, from, to)  
- `GET /api/history/positions` — position history  
- `GET /api/history/latest` — latest snapshot data  
- `GET /api/history/wallets` — wallet value history  
- `POST /api/snapshot` — trigger manual snapshot

### AI

- `GET /api/ai/config` — current AI provider \+ model config  
- `POST /api/ai/config` — save AI config  
- `GET /api/ai/models/<provider>` — available models for provider (anthropic | openai)  
- `POST /api/ai/generate` — generate AI report  
- `POST /api/ai/digest` — generate AI daily digest  
- `GET /api/ai/digest/latest` — latest digest  
- `GET /api/ai/reports` — list saved reports  
- `GET /api/ai/reports/<id>` — get report detail

### Strategy Documents

- `GET /api/strategies` — list uploaded strategy docs  
- `POST /api/strategies/upload` — upload doc (multipart, fields: file, regime, doc\_type)  
- `DELETE /api/strategies/<id>` — delete doc  
- `GET /api/strategies/for-ai/<regime>` — get docs for a regime (for AI injection)

### LP Optimizer

- `POST /api/optimizer/pools` — search pools  
- `POST /api/optimizer/run` — run optimization  
- `GET /api/optimizer/regimes` — market regimes  
- `GET /api/optimizer/portfolio-positions` — current positions for optimizer context

### Settings

- `GET /api/settings/display` — display preferences (hide values, dust threshold, etc.)  
- `POST /api/settings/display` — save display preferences  
- `GET /api/settings/telegram` — Telegram notification config  
- `POST /api/settings/telegram` — save Telegram config  
- `POST /api/settings/telegram/test` — send test message  
- `POST /api/change-password` — change login password  
- `GET /api/backup/db` — download DB  
- `POST /api/backup/db` — import/restore DB  
- `GET /api/backup/config` — export config JSON  
- `POST /api/backup/config` — import config JSON  
- `GET /api/validate-token/<symbol>` — check token symbol \+ get price

### NEW Endpoints (Phase 1 backend additions — see below)

- `GET /api/defi-journal/<position_type>/<position_id>` — journal entries for any DeFi position  
- `POST /api/defi-journal` — add journal entry  
- `PUT /api/defi-journal/<id>` — update entry  
- `DELETE /api/defi-journal/<id>` — delete entry  
- `POST /api/lp/fee-claim` — record a fee claim event for an LP position  
- `GET /api/lp/fee-claims/<position_id>` — fee claim history for an LP position  
- `GET /api/defi-staking` — custom staking/DeFi app positions  
- `POST /api/defi-staking` — add staking position  
- `PUT /api/defi-staking/<id>` — update staking position  
- `DELETE /api/defi-staking/<id>` — delete staking position

---

## NEW Backend Requirements (add to web\_portfolio.py before Phase 2\)

### 1\. DeFi Position Journal

A unified journal for LP positions, lending positions, and custom staking positions.

**New DB table** (add to `init_db()` in `src/storage/portfolio_db.py`):

CREATE TABLE IF NOT EXISTS defi\_journal (

    id INTEGER PRIMARY KEY AUTOINCREMENT,

    position\_type TEXT NOT NULL,  \-- 'lp' | 'lending' | 'staking'

    position\_id TEXT NOT NULL,    \-- references lp\_positions.id, or Zerion position key, or staking.id

    action TEXT NOT NULL,         \-- free text or dropdown: 'note' | 'rebalance' | 'added' | 'removed' | 'collected\_fees' | 'other'

    details TEXT,

    created\_at TIMESTAMP DEFAULT CURRENT\_TIMESTAMP

);

**Routes** (add to `web_portfolio.py`):

GET  /api/defi-journal/\<position\_type\>/\<position\_id\>

POST /api/defi-journal  {position\_type, position\_id, action, details}

PUT  /api/defi-journal/\<id\>  {action?, details?}

DELETE /api/defi-journal/\<id\>

### 2\. LP Fee Claims

Track individual fee claim events separately from the running `fees_collected_usd` total. This gives full fee P\&L history rather than just a cumulative number.

**New DB table**:

CREATE TABLE IF NOT EXISTS lp\_fee\_claims (

    id INTEGER PRIMARY KEY AUTOINCREMENT,

    position\_id INTEGER NOT NULL,  \-- references lp\_positions.id

    claimed\_at DATE NOT NULL,

    token0\_amount REAL DEFAULT 0,

    token1\_amount REAL DEFAULT 0,

    token0\_price\_usd REAL DEFAULT 0,

    token1\_price\_usd REAL DEFAULT 0,

    value\_usd REAL NOT NULL,

    notes TEXT,

    created\_at TIMESTAMP DEFAULT CURRENT\_TIMESTAMP

);

**Routes**:

POST /api/lp/fee-claim  {position\_id, claimed\_at, token0\_amount, token1\_amount, token0\_price\_usd?, token1\_price\_usd?, value\_usd, notes?}

GET  /api/lp/fee-claims/\<position\_id\>

DELETE /api/lp/fee-claims/\<id\>

When a fee claim is recorded, also increment `fees_collected_usd` on the `lp_positions` row.

### 3\. LP P\&L Calculation

The `/api/manual-positions` response should include a `pnl` object per position:

{

  "pnl": {

    "entry\_value": 10000,

    "current\_value": 10800,

    "fees\_uncollected": 120,

    "fees\_collected": 340,

    "total\_fees": 460,

    "unrealized\_pnl": 800,

    "total\_pnl": 1260,

    "total\_pnl\_pct": 12.6,

    "days\_held": 45

  }

}

Calculate from `entry_value_usd`, current `value_usd`, `fees_uncollected_usd`, and sum of `lp_fee_claims.value_usd` for that position.

### 4\. Custom DeFi Staking Positions

For tracking positions in apps not supported by Zerion (staking, restaking, reward claiming protocols).

**New DB table**:

CREATE TABLE IF NOT EXISTS defi\_staking (

    id INTEGER PRIMARY KEY AUTOINCREMENT,

    app\_name TEXT NOT NULL,

    chain TEXT NOT NULL,

    position\_label TEXT,          \-- e.g. "ETH Stake", "HYPE Restake"

    token\_symbol TEXT NOT NULL,

    staked\_amount REAL NOT NULL,

    staked\_value\_usd REAL,

    reward\_token TEXT,

    reward\_amount REAL DEFAULT 0,

    reward\_value\_usd REAL DEFAULT 0,

    entry\_date DATE,

    lock\_end\_date DATE,           \-- NULL if not locked

    notes TEXT,

    wallet\_address TEXT,

    is\_active INTEGER DEFAULT 1,

    created\_at TIMESTAMP DEFAULT CURRENT\_TIMESTAMP,

    updated\_at TIMESTAMP DEFAULT CURRENT\_TIMESTAMP

);

**Routes**:

GET    /api/defi-staking           \-- active positions

POST   /api/defi-staking           {app\_name, chain, position\_label, token\_symbol, staked\_amount, staked\_value\_usd?, reward\_token?, reward\_amount?, entry\_date?, lock\_end\_date?, notes?, wallet\_address?}

PUT    /api/defi-staking/\<id\>      \-- update any field; action='close' sets is\_active=0

DELETE /api/defi-staking/\<id\>

---

## Feature Inventory (complete list of what must exist in the rebuilt frontend)

### Global

- [x] Login page (existing Flask session auth — just style it)  
- [x] Hide Values toggle — masks all financial figures site-wide; persisted to localStorage AND synced to `/api/settings/display`  
- [x] Wallet filter — multi-select, persisted in sessionStorage per tab  
- [x] Refresh button in nav — calls `/api/portfolio` with force\_refresh  
- [x] Responsive to desktop viewport (no mobile requirement)

### Dashboard (net new screen)

- [ ] Total portfolio value hero (sum of spot \+ DeFi \+ stablecoins)  
- [ ] 24h change (use portfolio chart data)  
- [ ] Breakdown pills: Spot · DeFi LP · Lending · Stablecoins  
- [ ] Equity sparkline (30-day, from `/api/history/portfolio-chart`)  
- [ ] BTC Macro Zone card (from `/api/market/macro`)  
- [ ] LP Health summary (positions in range count)  
- [ ] Lending Health Factor summary (lowest HF across positions)  
- [ ] AI Brief strip (latest digest from `/api/ai/digest/latest`)  
- [ ] Open positions summary (top 3 LP \+ lending positions by value)  
- [ ] Spot P\&L summary (unrealized \+ realized 30D from `/api/spot/pnl`)

### Portfolio → Token Holdings

- [x] Summary strip: Total Value | 24h Change | Token Count | DeFi Value  
- [x] Multi-wallet filter (toggle per wallet, all selected by default)  
- [x] Chain filter row  
- [x] Group by: Type | Wallet toggle  
- [x] Token table: icon \+ symbol \+ chain badge | balance | USD value | wallet label  
- [x] Dust filter (hide tokens below dust threshold from config)  
- [x] Dust filter notice ("N tokens hidden")

### Portfolio → DeFi Positions

#### LP Position Cards (Zerion \+ manual)

- [x] Gold border on all cards  
- [x] Header: Protocol · Chain · pair chips · In Range / Out of Range chip · age · wallet label  
- [x] Metric row: Position Value | Token Amounts | Uncollected Fees | APR | Price Range bar  
- [x] Stats row: Pool TVL | 24h Volume | Vol/TVL | 24h Fees  
- [x] LP P\&L summary (entry value, current value, total fees, total P\&L %)  
- [x] Claimed fees history (list from `/api/lp/fee-claims/<id>` \+ "Record Claim" button)  
- [x] Journal entries section (from `/api/defi-journal/lp/<id>` \+ Add Entry form)  
- [x] Edit / Rebalance / Archive / ✕ action buttons  
- [x] Edit modal: all position fields editable  
- [x] Archive confirm dialog

#### Lending/Borrowing Cards (Zerion AAVE/HyperLend/HypurrFi)

- [x] Gold border  
- [x] Header: Protocol · Chain · wallet \+ Edit | History (n) | Archive | ✕ buttons  
- [x] 5-metric row: Health Factor | Current LTV | Net Equity | Borrow Remaining | Net APY  
- [x] Health Factor gauge (color-zoned full-width bar)  
- [x] Liquidation price strip per collateral token  
- [x] Lending table → Borrowing table  
- [x] Journal entries section (from `/api/defi-journal/lending/<position_key>` \+ Add Entry)  
- [x] Edit Position modal  
- [x] History modal (timeline \+ Add Entry)  
- [x] Archive confirm dialog

#### Custom DeFi Staking Positions (net new)

- [ ] Staking position cards (separate section below LP/Lending)  
- [ ] Card: App name · Chain · token · staked amount \+ value · reward token \+ amount  
- [ ] Lock end date badge if applicable  
- [ ] Add/Edit/Close/Delete actions  
- [ ] Journal entries per staking position  
- [ ] "Add Staking Position" button → inline form

#### Summary Cards

- [x] LP Summary: Total LP Value | Fees 24h/7d/30d | Positions in range count  
- [x] Lending Summary: Net Equity | Avg Health Factor | Total Lent | Total Borrowed  
- [ ] Staking Summary: Total Staked Value | Total Rewards Claimable

### Portfolio → LP Tools

- [x] Sub-tool switcher: LP Optimizer | IL Calculator | Hedge Calculator  
- [x] LP Optimizer: chain/pair/TVL/portfolio filters → pool table  
- [x] IL Calculator: pair/range/entry/notional/fee APR → position value chart \+ IL chart \+ summary \+ fee income \+ break-even  
- [x] Hedge Calculator: leverage buttons \+ hedge % slider \+ entry/funding → P\&L table \+ crossing-curves chart \+ parameters panels

### Spot P\&L → Live Holdings

- [x] Dry Powder card (stablecoin total from `/api/spot/stablecoins`)  
- [x] Holdings table: Token | Units | Avg Cost | Current Price | Cost Basis | Market Value | Unrealized P\&L | Portfolio %  
- [x] Hide Values toggle (local to this tab, also respects global hide)  
- [x] "FIFO cost basis" label

### Spot P\&L → Trade History

- [x] Table: Token | Buy Date | Sell Date | Units | Avg Buy | Avg Sell | Realized P\&L | Holding Period  
- [x] Data from `/api/spot/history`

### Spot P\&L → Transactions

- [x] "+ Add Transaction" gold primary button → reveals inline form above table  
- [x] "⬆ Import CSV" button → file picker → POST to `/api/spot/import-csv`  
- [x] Hide Values toggle  
- [x] Add form: Date / Symbol / Side (Buy|Sell) / Units / Price USD / Platform / Notes \+ Save/Cancel  
- [x] Transaction table: Date | Type chip | Token | Units | Price | Total | Platform | Notes | Edit | Delete  
- [x] Inline edit (same form, pre-populated)  
- [x] Delete with confirm

### Performance

- [ ] Date range picker: 7D | 30D | 90D | 1Y | All  
- [ ] Portfolio equity curve (full width, from `/api/history/portfolio-chart`)  
- [ ] 4 KPI cards: Net P\&L | Win Rate | Profit Factor | Expectancy (from `/api/spot/history` \+ `/api/history/closed-positions`)  
- [ ] Trade distribution chart (win/loss bar chart)  
- [ ] Drawdown chart  
- [ ] Per-symbol breakdown table

### Market Data

- [x] Price strip: BTC / ETH / key assets (from `/api/market-data`)  
- [x] Fear & Greed gauge (from `/api/market-data`)  
- [x] BTC Macro Cycle Dashboard: multi-indicator table with composite score (from `/api/market/macro`)  
- [x] LP Pool Stats table (from `/api/market/lending-rates` \+ DeFiLlama if available)  
- [x] Lend/Borrow Stats table (from `/api/market/lending-rates`)  
- [x] Stablecoin supply chart (from `/api/market/stablecoin-supply`)  
- [x] Refresh button → POST `/api/market-data/refresh`

### AI Brief

- [x] Date header \+ Regenerate button (POST `/api/ai/digest`)  
- [x] Top Recommendation card (large, prominent)  
- [x] Alerts section (colored chips per alert type)  
- [x] Portfolio analysis narrative  
- [x] Macro context section  
- [x] Recommendations list (colored by action: buy/hold/reduce/avoid)  
- [x] Data sources footer  
- [x] Saved reports list (from `/api/ai/reports`) with ability to view past reports

### Trading Tools — Scanner

- [ ] Watchlist grid: ticker cards with price, % change, signal label, sparkline  
- [ ] Status filter: All | Active | Forming | Watching | Quiet  
- [ ] Rescan button \+ last scan timestamp

### Trading Tools — Validator

- [ ] Multi-step trade setup flow (HTF context → Market structure → Entry trigger → Risk → Confirmation)  
- [ ] Left sidebar: step progress rail  
- [ ] Step adapts based on prior answers  
- [ ] Summary rail (right): answers so far  
- [ ] Pre-trade reasoning record output (saveable to Journal)

### Trading Tools — Journal

- [ ] Timeline of trade reasoning records  
- [ ] Each entry: date / ticker / direction chip / outcome chip / R-multiple / narrative  
- [ ] Filter: All | Long | Short | Win | Loss | Pending  
- [ ] Entry detail view: full narrative \+ validator answers \+ outcome \+ notes \+ edit

### Trading Tools — Reports

- [ ] KPI strip (Net P\&L | Win Rate | Profit Factor | Expectancy)  
- [ ] Equity curve (90D SVG line chart)  
- [ ] Calendar heatmap (daily P\&L)  
- [ ] Win/Loss distribution bar chart  
- [ ] Progression chart (rolling win rate \+ expectancy)

### Trading Tools — Concepts

- [ ] Card grid of trading concepts  
- [ ] Each card: concept name \+ mastery % \+ colored progress bar \+ last tested date  
- [ ] Detail panel on click: definition, rules, examples

### Trading Tools — Quiz

- [ ] Question progress dots (left rail)  
- [ ] Question metadata chips \+ chart area \+ question text  
- [ ] 4-option grid (keyboard shortcuts ⌘+1-4 to select, ⌘↵ to submit)  
- [ ] Selected \= gold, correct \= green, wrong \= red  
- [ ] Concepts mastery update on completion

### Trading Tools — Trading Settings

- [ ] Sidebar sections: Schedule | Watchlist | Validator Rules | Quiz Settings | Concepts | Transcripts | Account | Data

### Settings (full sidebar layout)

- [x] Sidebar: 220px, `var(--panel)`, active item \= `border-left: 3px solid var(--accent)`, `background: var(--panel3)`

#### Display Preferences

- [x] Hide all portfolio values toggle (prominent gold-bordered card) — saves to `/api/settings/display` AND localStorage  
- [x] Dust Threshold input → POST `/api/settings/display`  
- [x] Lending Threshold input → POST `/api/settings/display`

#### Wallets

- [x] Wallet rows: colored dot \+ label \+ masked address \+ portfolio value \+ Visible/Hidden toggle \+ Remove  
- [x] Add wallet: address input \+ label \+ "Add wallet" button

#### Integrations

- [x] RPC Endpoints: Ethereum / Arbitrum / Base — chain label \+ provider dropdown \+ API key/URL \+ Save  
- [x] AI Provider Keys: OpenAI / Anthropic — masked key fields \+ Save  
- [x] Other APIs: Zerion \[REQUIRED\] / Etherscan \[RECOMMENDED\] / FRED \[OPTIONAL\] — badge chips \+ masked keys \+ Save

#### AI Config

- [x] Provider segmented control: Anthropic | OpenAI  
- [x] Model dropdown (fetch from `/api/ai/models/<provider>`)  
- [x] Save → POST `/api/ai/config`

#### Document Uploads

- [x] DeFi Strategy: drag-drop zone \+ doc table (Filename / Uploaded / Regime tag) \+ delete  
- [x] Trading Strategy: drag-drop zone \+ doc table (Filename / Uploaded / Topic tag) \+ delete  
- [x] Upload → POST `/api/strategies/upload` (multipart: file \+ regime \+ doc\_type)  
- [x] Delete → DELETE `/api/strategies/<id>`

#### Spot P\&L Config

- [x] Token table: Token \+ chain badge | Contract Override | Price Source dropdown | Test button  
- [x] Test → GET `/api/spot/price-test/<symbol>`  
- [x] Save → POST `/api/spot/token-config`

#### Backup & Security

- [x] Export DB → GET `/api/backup/db`  
- [x] Import DB → POST `/api/backup/db`  
- [x] Export Settings → GET `/api/backup/config`  
- [x] Import Settings → POST `/api/backup/config`  
- [x] Change password: Current / New / Confirm \+ POST `/api/change-password`

#### Messaging

- [x] Telegram: Bot Token \+ Chat ID \+ Schedule (UTC Hour) \+ Enabled toggle  
- [x] Notification Content: Daily Digest | Market Regime Assessment checkboxes  
- [x] Save → POST `/api/settings/telegram`  
- [x] Send Test → POST `/api/settings/telegram/test`

---

## File Structure (new frontend)

templates/

  index.html          ← Single page app shell, design tokens CSS, React \+ Babel CDN loads,

                         mounts \<div id="root"\>, imports all static JS modules

static/

  app.js              ← React root, routing/tab state, global state (hideValues, activeTab)

  nav.js              ← TVNav component (top nav \+ sub-nav for Trading Tools)

  dashboard.js        ← Dashboard screen

  portfolio.js        ← Portfolio screen (token holdings \+ DeFi positions \+ LP Tools)

  spotpnl.js          ← Spot P\&L screen (live holdings \+ trade history \+ transactions)

  performance.js      ← Performance screen

  marketdata.js       ← Market Data screen

  aibrief.js          ← AI Brief screen

  scanner.js          ← Trading Tools: Scanner

  validator.js        ← Trading Tools: Validator

  journal.js          ← Trading Tools: Journal

  reports.js          ← Trading Tools: Reports

  concepts.js         ← Trading Tools: Concepts

  quiz.js             ← Trading Tools: Quiz

  trading-settings.js ← Trading Tools: Settings

  settings.js         ← Main Settings screen

  utils.js            ← Shared utilities: mask(), fmt(), api(), formatDate(), etc.

  charts.js           ← Shared chart components (sparklines, equity curves, gauges, etc.)

  style.css           ← Global CSS (TV design tokens, shared classes) — replaces existing

## Utility Functions (utils.js)

// Format currency

function fmt(value, decimals \= 2\) { ... }

// Mask financial values when hide mode on

function mask(value, hidden, formatted \= true) {

  if (hidden) return '••••';

  return formatted ? fmt(value) : value;

}

// Fetch wrapper with error handling

async function api(path, options \= {}) {

  const res \= await fetch(path, { ...options, headers: { 'Content-Type': 'application/json', ...options.headers }});

  if (\!res.ok) throw new Error(await res.text());

  return res.json();

}

// Format date

function formatDate(iso) { ... }

// Format percentage with sign

function fmtPct(value) { ... }

// Color class for P\&L (ok/fail)

function pnlClass(value) { return value \>= 0 ? 'ok' : 'fail'; }

---

## Phase Breakdown

### Phase 0 — Backend additions (web\_portfolio.py \+ portfolio\_db.py)

Add the 4 new DB tables and 8 new API routes described above. **Does not touch any existing routes or tables.** Verify: `flask shell` → check tables exist; test each new endpoint with curl. Commit: `git add -A && git commit -m "feat: add defi journal, lp fee claims, staking positions tables and routes" && git push`

### Phase 1 — Shell \+ design system

Create new `templates/index.html`, `static/utils.js`, `static/charts.js`, `static/nav.js`, `static/app.js`, `static/style.css`. Implement: TV design tokens, all shared CSS classes, top nav with 8 tabs, sub-tab routing, global hide-values state. The app renders the nav and a placeholder content area for each tab. Login still works. **Delete old static JS files only after new ones are confirmed working.** Verify: open the app, click every nav item, no console errors. Commit: `git add -A && git commit -m "feat: playbook phase 1 — shell and design system" && git push`

### Phase 2 — Portfolio \+ Spot P\&L

Implement: `portfolio.js` (Token Holdings \+ DeFi Positions \+ LP Tools), `spotpnl.js`. This covers all existing dashboard functionality in the new design. Includes: LP cards with P\&L \+ fee claims \+ journal, Lending cards with journal, manual position CRUD, staking positions section, LP Tools (optimizer/IL/hedge). Verify: add a transaction, add a manual LP position, record a fee claim, add a journal entry. Check hide-values masks everything. Commit: `git add -A && git commit -m "feat: playbook phase 2 — portfolio and spot pnl screens" && git push`

### Phase 3 — Market Data \+ AI Brief \+ Settings

Implement: `marketdata.js`, `aibrief.js`, `settings.js`. Settings replaces the current modal-based approach with the full sidebar layout. Verify: market data loads, AI brief generates, settings save and reload correctly, backup/restore works. Commit: `git add -A && git commit -m "feat: playbook phase 3 — market data, ai brief, settings" && git push`

### Phase 4 — Dashboard \+ Performance

Implement: `dashboard.js`, `performance.js`. These are net-new screens. Dashboard aggregates data from multiple existing endpoints. Verify: portfolio value hero reflects actual data, equity curve renders, KPIs calculate correctly. Commit: `git add -A && git commit -m "feat: playbook phase 4 — dashboard and performance screens" && git push`

### Phase 5 — Trading Tools

Implement: `scanner.js`, `validator.js`, `journal.js`, `reports.js`, `concepts.js`, `quiz.js`, `trading-settings.js`. These are fully net-new features. Implement backend stubs as needed (quiz data, concepts data, validator logic). Commit per screen or as a group: `git add -A && git commit -m "feat: playbook phase 5 — trading tools" && git push`

---

## Important Implementation Notes

1. **React via CDN** — use React 18 \+ ReactDOM \+ Babel standalone. All JSX files use `type="text/babel"`.  
     
   \<script src="https://unpkg.com/react@18/umd/react.development.js"\>\</script\>  
     
   \<script src="https://unpkg.com/react-dom@18/umd/react-dom.development.js"\>\</script\>  
     
   \<script src="https://unpkg.com/@babel/standalone/babel.min.js"\>\</script\>  
     
2. **Module loading order** — because Babel standalone processes scripts in order, load: utils.js → charts.js → nav.js → \[all screen files\] → app.js (last, mounts root)  
     
3. **No localStorage for sensitive data** — hideValues preference goes in localStorage (it's a UI pref, not financial data). All actual config/keys stay server-side.  
     
4. **Auth** — the existing Flask session auth is unchanged. The `/login` route renders `login.html` (keep existing or style it). All API calls return 401 if not logged in; handle globally in the `api()` utility by redirecting to `/login`.  
     
5. **Charts** — use inline SVG for sparklines and simple bars. For the equity curve and more complex charts, use Recharts via CDN (it's compatible with React CDN setup):  
     
   \<script src="https://unpkg.com/recharts/umd/Recharts.js"\>\</script\>  
     
6. **Fira Code font** — load from Google Fonts, apply to `.tv-num` class. All prices, balances, percentages, contract addresses use this class.  
     
7. **LP P\&L calculation** — the frontend should compute total P\&L from the data returned: `total_pnl = (current_value - entry_value) + fees_collected + fees_uncollected` `total_pnl_pct = total_pnl / entry_value * 100`  
     
8. **DeFi Positions from Zerion** — the `/api/portfolio` response contains `aave_positions` (lending) and `lp_positions` (from on-chain data). Manual positions come from `/api/manual-positions`. The frontend merges and renders both. Zerion positions will not have a numeric `id` matching the DB — use `position_id` string as the journal key for Zerion positions.  
     
9. **Wallet filter** — applies to token holdings and DeFi positions. Does NOT apply to Spot P\&L (that's a separate tracking system). Store active wallet filter in React state, not URL.  
     
10. **Dust threshold** — tokens with value below the threshold (from config) are hidden from token holdings by default. Show a notice: "N tokens hidden (below $X dust threshold). \[Show all\]"

