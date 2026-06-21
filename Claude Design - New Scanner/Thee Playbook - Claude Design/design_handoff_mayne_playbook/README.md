# Handoff: The Mayne Playbook

## Overview
The Mayne Playbook is a personal trading and DeFi portfolio management dashboard. It combines:
- A multi-wallet crypto portfolio tracker (tokens, LP positions, lending/borrowing)
- A spot P&L tracker with FIFO cost basis
- A trading education system (daily quiz, concept library, trade validator, journal)
- An AI-powered daily brief with portfolio recommendations
- Market data and BTC macro cycle tracking
- LP tooling (optimizer, IL calculator, hedge calculator)

The app is a single-page application with a persistent top navigation bar and full-screen content areas per tab.

---

## About the Design Files
The files in this bundle are **high-fidelity HTML/JSX prototypes** — design references showing intended look, layout, and interactive behavior. They are **not production code to ship directly**. Your task is to **recreate these designs in the target codebase** using its established framework, component library, and patterns.

Open `index.html` in a browser to view the full interactive design canvas with all screens side-by-side. Each screen is a labelled artboard you can inspect, pan, and zoom.

---

## Fidelity
**High-fidelity.** All screens have final colors, typography, spacing, and representative data. Recreate pixel-accurately using the codebase's existing libraries and patterns. Where exact pixel values are given below, honor them.

---

## Navigation Architecture

```
Top Nav (8 items, persistent):
├── Dashboard
├── Portfolio
│   └── Sub-tabs: Token Holdings | DeFi Positions | LP Tools
├── Spot P&L
│   └── Sub-tabs: Live Holdings | Trade History | Transactions
├── Performance
├── Market Data
├── AI Brief
├── Trading Tools  ← dropdown group
│   └── Sub-nav: Scanner | Validator | Journal | Reports | Concepts | Quiz | Trading Settings
└── Settings
    └── Sidebar sections: Display | Wallets | Integrations | AI Config | Document Uploads | Spot P&L Config | Backup & Security | Messaging
```

The top nav is a horizontal strip, 48px tall, background `#103f63`, with 1px bottom border `#266594`. Active tab has a 2px bottom accent `#ffb52e` and `font-weight: 600`. All Trading Tools child screens highlight "Trading Tools" in the main nav AND show a secondary sub-nav strip below.

---

## Design Tokens

All screens share this palette (defined as `TV` in `validator.jsx`):

### Colors
| Token | Value | Usage |
|---|---|---|
| `bg` | `#0a2a47` | Page/frame background |
| `panel` | `#103f63` | Card surface (primary) |
| `panel2` | `#154a72` | Card surface (elevated / input bg) |
| `panel3` | `#1c5a85` | Active nav item bg, selected states |
| `line` | `#266594` | Card borders, dividers |
| `lineSoft` | `rgba(255,255,255,0.12)` | Subtle row separators |
| `text` | `#ffffff` | Primary text |
| `text2` | `#eef4fd` | Secondary text |
| `text3` | `#d7e5f6` | Tertiary / labels |
| `text4` | `#b6cbe8` | Muted / placeholder |
| `accent` | `#ffb52e` | Gold — section titles, active states, highlights |
| `accentSoft` | `rgba(255,181,46,0.18)` | Accent backgrounds |
| `accentLine` | `rgba(255,181,46,0.5)` | Accent borders |
| `ok` | `#4fdd8e` | Positive values, safe states, green |
| `okSoft` | `rgba(79,221,142,0.18)` | Positive backgrounds |
| `warn` | `#ffd23f` | Warning / amber |
| `warnSoft` | `rgba(255,210,63,0.16)` | Warning backgrounds |
| `fail` | `#ff8a8a` | Negative values, danger |
| `failSoft` | `rgba(255,138,138,0.18)` | Danger backgrounds |
| `adapt` | `#2fb4e8` | Cyan — info, chain badges, AI cues |
| `adaptSoft` | `rgba(47,180,232,0.2)` | Cyan backgrounds |

### Typography
- **Font family**: `'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif`
- **Monospace** (prices, numbers, addresses): `'Fira Code', monospace` — class `tv-num`
- **Uppercase labels**: `font-size: 11px; font-weight: 600; letter-spacing: 0.06em; text-transform: uppercase` — class `tv-uppercase`

### Spacing & Radius
- Card border-radius: `12–14px`
- Card padding: `16–24px`
- Card border: `1px solid #266594`
- Card background: `#103f63` (primary) or `#154a72` (elevated)
- Section gaps: `16–22px`
- Inner row gaps: `8–14px`

### Shared UI Classes (defined in `index.html` `<style>`)
- `.tv-frame` — full screen container, `background: #0a2a47`
- `.tv-btn` — ghost button: `border: 1px solid #266594`, `border-radius: 8px`, `padding: 8px 14px`, `font-size: 13px`, `color: #d7e5f6`, hover: `background: #154a72`
- `.tv-btn.primary` — filled gold button: `background: #ffb52e`, `color: #0a2a47`, `font-weight: 700`
- `.tv-btn.ghost` — transparent, border only
- `.tv-chip` — inline badge: `border-radius: 6px`, `padding: 2px 8px`, `font-size: 11px`, `border: 1px solid`
- `.tv-chip.accent` — gold chip
- `.tv-chip.ok` — green chip
- `.tv-dot` — 6px colored dot inside chips

---

## Screens

### 1. Dashboard (`hifi.jsx` → `DashHF`)
**File**: `hifi.jsx`  
**Purpose**: Hub overview — portfolio health, screener, open trades, AI brief, performance.

**Layout** (flex column, `padding: 20px 28px`):

#### Hero Row (2-column grid, `gridTemplateColumns: 2fr 1fr`, `gap: 16px`)
**Left — Portfolio Value card**:
- Label: "Total Portfolio Value" — 13px, uppercase, `#d7e5f6`
- Value: `$456,230` — 52px, `font-weight: 800`, white, `letter-spacing: -2px`
- 24h change: `+$8,340 / +1.86%` — 18px bold green `#4fdd8e`
- Equity sparkline: 540×52px SVG line chart (30-day data, green line, transparent fill)
- Breakdown pills (flex row): Spot · DeFi LP · Lending · Cash — each `padding: 5px 12px`, `border-radius: 8px`, `background: #154a72`, colored dot + label + value

**Right — Macro + Health (flex column, `gap: 14px`)**:
- BTC Macro Zone card: gradient bar (red→amber→green→cyan) with a position marker at current zone. Label "Value Window" in green. Sub-labels: Bear / Accum. / Value Window / Bull / Euphoria
- LP Health + Lending (2-col): "3 positions / All in range" green · "HF 2.41 / Safe zone" green

#### AI Brief Strip
- Full-width, `padding: 11px 18px`, `border-radius: 12px`, `border: 1px solid rgba(255,181,46,0.5)`, `background: rgba(255,181,46,0.18)`
- ⚡ icon + "AI Brief · Today" gold label + "3 alerts" red chip + recommendation text + "View full brief →" button

#### Main 2-Column Grid (`gridTemplateColumns: 1.55fr 1fr`, `gap: 16px`)
**Left — Screener card**:
- 2×3 grid of ticker cards (`gap: 12px`)
- Each card: ticker name (14px bold) + status dot + price + % change (green/red) + sparkline (100% × 26px) + signal label + TF pair tags
- Active cards: gold border + `rgba(255,181,46,0.18)` background
- Forming cards: `#154a72` background, standard border

**Right — flex column, `gap: 14px`**:
- Open Trades card: 3 trade rows, each with ticker + direction chip (▲ long / ▼ short) + TF tags + unrealized R + entry/now prices + stop→entry→target progress bar (8px track, colored zones, 9px circular marker)
- Spot P&L Summary card: Unrealized `+$2,340` / Realized 30D `+$12,450` in 2-col grid + top movers table (3 rows)

#### Performance Footer (4-column grid)
Cards: Net P&L 90D (with mini sparkline) · Win Rate · Profit Factor · Open Risk
Each: 11px uppercase gold label + 24px bold value + 12px sub-text

---

### 2. Portfolio (`portfolio.jsx` → `PortfolioHF`)
**Sub-tabs**: Token Holdings | DeFi Positions | LP Tools

#### Token Holdings
- Summary strip: 4 cards (Total Value / 24h Change / Token Holdings / DeFi Value)
- Multi-wallet filter buttons (toggleable, `border-radius: 20px`, active = gold bg)
- Chain filter row
- Group toggle: "By Type" | "By Wallet"
- Table: token icon + symbol + chain badge | balance | USD value | wallet label
- Dust filter notice

#### DeFi Positions
**LP Position Cards** — each card:
- `border: 1.5px solid #ffb52e` (gold, all sides equal weight)
- Header: Protocol · Chain · pair chips · "In Range" / "Out of Range" chip · age · wallet
- Metric row (5 cols): Position Value | Token Amounts | Uncollected Fees | APR (daily/weekly/monthly/yearly) | Price Range (progress bar with current price marker)
- Stats row: Pool TVL | 24h Volume | 24h Vol/TVL ratio | 24h Fees
- Edit/Rebalance/Archive/✕ action buttons

**Lending/Borrowing Cards** — each card:
- `border: 1.5px solid #ffb52e`
- Header: Protocol · Chain · LONG/SHORT chip · "Opened date · wallet" + Edit | History (n) | Archive | ✕ buttons
- 5-metric row: Health Factor | Current LTV | Net Equity | Borrow Remaining | Net APY
- Health Factor Gauge (full-width, color-zoned: red→amber→green, 8px track with position marker)
- **Liquidation price strip**: "LIQUIDATES IF PRICE FALLS BELOW" red uppercase label + per-collateral pill (token / liq price / % below current)
- Lending table (Asset | Qty | Price | Value | LiqThr | APY) → arrow → Borrowing table (Asset | Qty | Price | Value | APR)

**Lend/Borrow Modals**:
- **Edit Position**: 2-col fields (Protocol, Chain, Date, Max LTV%) + Lending Assets rows (Token/Qty/LiqThr/APY/Price/✕ + Add Lent Asset) + Borrowing Assets rows + Notes textarea + Cancel/Save
- **History**: Timeline dots + Add Entry form (Action dropdown / Date / Details / Add Entry)
- **Archive**: Simple confirm dialog + red Archive button

**Summary cards** (below main 4 KPI cards):
- LP Summary: Total LP Value | Fees (24h/7d/30d) | Positions in range
- Lending Summary: Net Equity | Avg Health Factor | Total Lent | Total Borrowed

#### LP Tools (3 sub-tools)
**LP Optimizer**: Search form (Chain / Pair / Min TVL / Portfolio Position) → pool table (Symbol / Chain / TVL / 24h Vol / Fee APR / Fee Tier)

**IL Calculator**: 6 inputs (Pair / Range Low / Range High / Entry / Notional / Fee APR) → LP value chart (vs 50/50 HODL) + IL vs HODL chart + Position Summary panel + Fee Income panel + Break-even days

**Hedge Calculator**: Leverage buttons (1x/2x/3x/5x/10x) + Hedge % slider + Entry/Funding inputs → P&L table (price points vs LP/Hedge/Net P&L) + crossing-curves chart + Hedge Parameters / Liquidation / Stop Loss / Costs panels

---

### 3. Spot P&L (`spotpnl.jsx` → `SpotPnlHF`)
**Sub-tabs**: Live Holdings | Trade History | Transactions

#### Live Holdings
- Dry Powder card (total stablecoins)
- Table: Token | Units | Avg Cost | Current Price | Cost Basis | Market Value | Unrealized P&L | Portfolio % (w/ and w/o stables)
- Hide Values toggle (masks all amounts)

#### Trade History
- Table: Token | Buy Date | Sell Date | Units | Avg Buy | Avg Sell | Realized P&L | Holding Period
- FIFO cost basis method note

#### Transactions
- Header: "+ Add transaction" (gold primary button) + "⬆ Import CSV" button + Hide Values toggle
- Inline add form (when open): Date / Symbol / Side (Buy/Sell dropdown) / Units / Price USD / Platform / Notes + Save / Cancel
- Table: Date | Type (Buy/Sell chip) | Token | Units | Price | Total | Platform | Notes | Actions (edit pencil / delete ✕)

---

### 4. Performance (`performance.jsx` → `PerformanceHF`)
- Date range picker (7D / 30D / 90D / 1Y / All)
- Portfolio value chart (equity curve, full width)
- 4 KPI cards: Net P&L | Win Rate | Profit Factor | Expectancy
- Trade distribution chart + Drawdown chart side by side
- Per-symbol breakdown table

---

### 5. Market Data (`marketdata.jsx` → `MarketDataHF`)
Vertically stacked sections (single scrollable artboard):
- **Price strip**: BTC / ETH / key assets with 24h change
- **Fear & Greed**: gauge + value + classification
- **BTC Macro Cycle Dashboard**: multi-indicator table (PI Cycle / MVRV Z / NUPL / Puell / Rainbow / Stock-to-Flow) with zone classification per indicator + composite score
- **LP Pool Stats**: table (Protocol / Pair / Chain / TVL / 24h Volume / Vol/TVL / APR / Fee Tier)
- **Lend/Borrow Stats**: table (Protocol / Chain / Asset / Supply APY / Borrow APR / Total Supply / Total Borrowed / Utilization)

---

### 6. AI Brief (`aibrief.jsx` → `AIBriefHF`)
- Date header + "Regenerate" button
- **Top Recommendation** card (large, prominent): Action chip + asset + rationale
- Alerts section: colored chips per alert type
- Portfolio analysis narrative
- Macro context section
- Recommendations list (bulleted, colored by action type: buy/hold/reduce/avoid)
- Data sources footer

---

### 7. Trading Tools (sub-nav on every screen)

Sub-nav strip: `background: #154a72`, `border-bottom: 1px solid #266594`, `padding: 0 22px`  
Each item: `padding: 7px 13px`, active has `border-bottom: 2px solid #ffb52e`, `font-weight: 600`

#### Scanner (`hifi.jsx` → `ScannerHF`)
- Watchlist grid: 3×3 ticker cards (same as Dashboard screener cards)
- Status filter: All | Active | Forming | Watching | Quiet
- Rescan button + "last scan" timestamp

#### Validator (`validator.jsx` → `ValidatorC`)
Multi-step trade setup validator:
- Left sidebar: step progress rail (numbered circles, `#4fdd8e` done, `#ffb52e` current)
- Main area: step content (HTF context → Market structure → Entry trigger → Risk → Confirmation)
- Summary rail (right): answers so far
- Step adapts based on prior answers (e.g. entry trigger choice changes subsequent steps)

#### Journal (`journal.jsx` → `JournalHF`)
- Timeline of trade reasoning records
- Each entry: date / ticker / direction chip / outcome chip / R-multiple / narrative
- Filter: All | Long | Short | Win | Loss | Pending

#### Journal Entry Detail (`journal-entry.jsx`)
- Full entry: setup narrative + chart annotation ref + validator answers + outcome + notes + edit button

#### Reports (`reports.jsx` → `ReportsHF`)
- KPI strip (same as Performance)
- Equity curve (SVG line chart, 90D)
- Calendar heatmap (daily P&L)
- Win/Loss distribution bar chart
- Progression chart (rolling win rate + expectancy)

#### Concepts (`concepts.jsx` → `ConceptsHF`)
- Card grid of trading concepts (Order Blocks, FVGs, Liquidity Sweeps, BOS/CHoCH, Killzones, etc.)
- Each card: concept name + mastery score (%) + colored progress bar + last tested date
- Detail panel on click: definition, rules, examples, source episodes

#### Quiz (`quiz-complete.jsx` → `QuizHF`)
- Left rail: Q n/8 progress dots
- Main: question metadata chips + chart (HFChart, annotated) + question text + 4-option grid
- Option cards: `padding: 14px 18px`, `border-radius: 10px`, selected = gold border + background, correct = green, wrong = red
- Keyboard shortcuts (⌘+1-4 to select, ⌘↵ to submit)

#### Trading Settings (`settings.jsx` → `SettingsHF`)
- Sidebar: Configuration sections
- Sections: Schedule (quiz cron config) | Watchlist | Validator Rules | Quiz Settings | Concepts | Transcripts | Account | Data

---

### 8. Settings (`settings2.jsx` → `SettingsNewHF`)
Left sidebar (`width: 220px`, `background: #103f63`) + right content panel.

Active sidebar item: `border-left: 3px solid #ffb52e`, `background: #1c5a85`, `font-weight: 600`

#### Display Preferences
- **Hide all portfolio values toggle** (prominent gold-bordered card at top): Off/On pill switch. Masks all personal balances, P&L, and position values site-wide. Quiz, market data unaffected.
- Dust Threshold ($) input
- Lending Threshold ($) input

#### Wallets
- Wallet rows: colored dot + label + masked address + portfolio value + Visible/Hidden toggle + Remove button
- Add wallet: address input + "+ Add wallet" button

#### Integrations
Three sub-cards:
- **RPC Endpoints** (⚡): Ethereum / Arbitrum / Base — each row: chain label + provider dropdown + API key/URL input + Save
- **AI Provider Keys** (🤖): OpenAI / Anthropic / AWS Bedrock — masked key fields + Save
- **Other APIs** (🔗): Zerion [REQUIRED] / Etherscan [RECOMMENDED] / FRED [OPTIONAL] — badge chips + masked keys + Save + helper text

#### AI Config
- Provider segmented control: Anthropic | OpenAI
- Model dropdown (shows available models for selected provider)
- Model chips showing all options

#### Document Uploads
Two upload areas:
- **DeFi Strategy**: drag-drop zone + doc table (Filename / Uploaded / Regime tag: Bear/Bull/Stablecoin/Cashflow) → used by AI for portfolio advice
- **Trading Strategy**: drag-drop zone + doc table (Filename / Uploaded / Topic tag: Setups/Concepts/Validation) → used for quizzes, validation, chart scanning

#### Spot P&L Config
Token table (4 cols): Token + chain badge | Contract Override (monospace address or "auto-detected") | Price Source dropdown | Test ↗ button

#### Backup & Security
- Backup & Restore: Export DB / Import DB / Export Settings / Import Settings buttons
- Warning notice
- Password change: Current / New / Confirm fields + Update Password button

#### Messaging
- Telegram Notifications card: Bot Token (masked) / Chat ID / Schedule (UTC Hour) / Enabled dropdown
- Notification Content checkboxes: Daily Digest | Market Regime Assessment
- Save + Send Test Message buttons

---

## Interactions & Behavior

### Global
- **Hide Values**: When enabled in Settings → Display, all portfolio amounts (balances, P&L, values) show as `••••` across Dashboard, Portfolio, Spot P&L, Performance. Market data and quiz scores remain visible.
- **Quiz Status Pill**: In the Dashboard header — "Quiz Ready" (green dot) / "Quiz Pending" (red dot) / "Quiz Cooking" (amber dot). Positioned between Refresh and Reports buttons.

### Portfolio — Lend/Borrow Cards
- **Edit button**: Opens Edit Position modal (full form overlay with dimmed background)
- **History (n) button**: Opens History modal (timeline + Add Entry form). `n` = count of history entries.
- **Archive button** and **✕**: Opens Archive confirm dialog
- **Modal close**: Click backdrop or ✕ button

### LP Cards
- Edit / Rebalance / Archive / ✕ buttons in card header
- "In Range" chip is green, "Out of Range" is red

### Transactions — Add Transaction
- "+ Add transaction" button reveals inline form above the table
- Form: Date / Symbol / Side dropdown / Units / Price USD / Platform / Notes
- Save writes row to table; Cancel collapses form

### Trading Tools Sub-nav
- Each screen in Trading Tools (Scanner, Validator, Journal, Reports, Concepts, Quiz, Trading Settings) shows:
  1. Main nav with "Trading Tools" highlighted
  2. A secondary sub-nav strip below the main nav with all 7 items, correct one active

---

## State Management

### Key state per screen
| Screen | State |
|---|---|
| Portfolio | `subTab: 'tokens' \| 'defi' \| 'lptools'`, `walletFilter: string[]`, `chainFilter: string[]`, `groupBy: 'type' \| 'wallet'`, `showDust: boolean` |
| Spot P&L | `view: 'live' \| 'history' \| 'tx'`, `hidden: boolean`, `showAddForm: boolean` |
| LP Tools | `tool: 'optimizer' \| 'ilcalc' \| 'hedge'` |
| LendCard | `modal: 'edit' \| 'history' \| 'archive' \| null` |
| Settings | `section: string` (sidebar active section) |
| Display | `hideAllValues: boolean` (global, persist to localStorage) |

---

## Data Sources (runtime)
| Data | Source |
|---|---|
| Token balances & DeFi positions | Zerion API |
| LP pool TVL / Volume / APR | DeFiLlama |
| Price data | CoinGecko (primary), DexScreener (fallback per token config) |
| On-chain LP analytics, health factors | Custom RPC (Alchemy/Infura) |
| BTC macro indicators | FRED API + on-chain data |
| AI recommendations | Anthropic / OpenAI API (configured in Settings → Integrations) |
| Historical transactions | Manual import (CSV) + manual entry |

---

## Files in This Bundle

| File | Contents |
|---|---|
| `index.html` | Entry point — loads all JSX files via Babel, mounts design canvas |
| `validator.jsx` | **Design tokens (TV object)**, shared components (TVNav, TTSubNav, HFSparkline, TfPair, ChainBadge, TokenIcon, ToggleSwitch, QuizStatusPill, HFChart), Validator screen |
| `hifi.jsx` | Dashboard, Scanner, Quiz screens |
| `portfolio.jsx` | Portfolio screen (Token Holdings, DeFi Positions), LP/Lending card components, modals |
| `lp-tools.jsx` | LP Tools screen (Optimizer, IL Calculator, Hedge Calculator) |
| `spotpnl.jsx` | Spot P&L screen (Live Holdings, Trade History, Transactions) |
| `performance.jsx` | Performance screen |
| `marketdata.jsx` | Market Data screen |
| `aibrief.jsx` | AI Brief screen |
| `journal.jsx` | Journal list screen |
| `journal-entry.jsx` | Journal entry detail screen |
| `reports.jsx` | Reports / analytics screen |
| `concepts.jsx` | Concepts library screen |
| `quiz-complete.jsx` | Quiz screen (in-progress state) |
| `settings.jsx` | Trading Settings screen (Trading Tools sub-nav) |
| `settings2.jsx` | Main Settings screen (Display, Wallets, Integrations, AI Config, Document Uploads, Spot P&L Config, Backup, Messaging) |
| `app.jsx` | Design canvas layout — all artboards and sections |
| `concept-charts.jsx` | Chart components used in Concepts screen |
| `ingest.jsx` | Data ingestion / transcript processing screen |

---

## Notes for Developer

1. **Start with design tokens** — implement the `TV` color/typography object as your theme/CSS variables first. Every screen derives from it.
2. **Shared components first** — `TVNav`, `TTSubNav`, `ChainBadge`, `TokenIcon`, `ToggleSwitch`, `tv-btn`, `tv-chip` are used everywhere. Build these once.
3. **The `hideAllValues` global toggle** should be stored in localStorage and read at app startup. Wrap all personal financial figures in a utility like `mask(value, hidden)` that returns `"••••"` when enabled.
4. **LP and Lend card modals** use a fixed-position overlay with `background: rgba(5,18,35,0.82)`. They should trap focus and close on backdrop click or Escape key.
5. **Chart components** (sparklines, equity curves, health bar, LP range bar, IL charts, hedge P&L chart) are all custom SVG — no chart library is used in the prototype. In production, use your preferred charting library (Recharts, Chart.js, Victory, D3, etc.) and match the visual style.
6. **Monospace numbers** — all prices, balances, percentages, and addresses use `font-family: 'Fira Code', monospace` in the design. Use a monospace font for these in production too.
7. **Sub-nav on Trading Tools** — implement as a layout wrapper that renders around any Trading Tools route.
