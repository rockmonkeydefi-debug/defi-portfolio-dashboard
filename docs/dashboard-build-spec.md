# The Playbook: Dashboard redesign build spec

Target: `static/dashboard.js` (plain React + Recharts, dark only). Mockups: `Dashboard Redesign.dc.html` (assembled page, all states, 390 view) and `Dashboard Decisions.dc.html` (options by id).

**Status:** all seven picks confirmed by Glenn (27 Sep 2026). Two points are still open, with defaults: hidden mode masks health factor and market prices too (§3 S5), and the BTC/ETH strip cells are dropped if there's no price-history source (§4).

> Token note: the mockups use the token **names** from `static/style.css`, with placeholder values (only `--text4 #b6cbe8` is known). The build must use `var(--token)` only, with no raw hex. `color-mix(in oklch, var(--x) N%, var(--panel))` is used for tints. If the "Dashboard Design" system has a `--ds-*` tint primitive, use that instead (see Deviations).

---

## 1. Decisions

| # | Decision | Glenn's pick | Alternatives |
|---|---|---|---|
| 1 | Hero | **1b**: total + status line (dot, "Live · as of HH:MM:SS · oldest part HH:MM:SS (Part)"), warnings badge, Refresh. **24h change moves to the equity strip** until snapshot history carries every part, then may return under the hero. | 1a current, 1c 24h beside total with basis chip |
| 2 | Breakdown | **2c**: parts table inside the hero card (Part / Value / Share / As of / Source). "Spot positions" = info-only row, "Staked/locked" = not-counted row, both in a `--panel2` band below the counted rows. | 2a pills, 2b stacked bar |
| 3 | Equity chart | **3b**: single total line now. Stacked areas of the headline parts once history has them (flag `historyHasParts`). Default range **1M**. Strip = range change $, %, 24h change, BTC and ETH % over the same range, and the range's high/low. | 3a current dashed series, 3c toggle overlays |
| 4 | Right column | **4a**: MaxFi advisor card (replaces LP HEALTH), BTC Macro Zone (kept, gains ETH/SOL), Lending mini. | 4b drop BTC, 4c ticker strip |
| 5 | Row 3 | **5a**: Spot P&L 55% + Hyperliquid 45%. | 5b Spot + MaxFi, 5c Spot full width |
| 6 | Warnings/freshness | **6b**: count badge in hero header (click scrolls to first warned row) + inline warning line under the affected part row. As-of is a table column, and stale times turn `--warn`. The As-of tooltip is removed. | 6a popover, 6c banner |
| 7 | Narrow | **7a**: ≥1280 two-column; 768–1279 hero full width, right column becomes a 3-up row, Row 3 stays 2-up; <768 single column, compact parts table. | 7b single break at 1024 |

---

## 2. Layout (≥1280, drawn at 1440)

Page: `background: var(--bg)`, content padding `20px 24px 32px`, vertical gap `16px`. Existing app bar unchanged (52px, `--panel`, bottom `1px solid var(--line)`). Add or keep the global **Hide values** button there.

Shared card chrome (className, e.g. `.card`): `background: var(--panel)`, `border: 1px solid var(--line)`, `border-radius: 10px`.
Card label: 11px / 600 / letter-spacing .09em / uppercase / `--text4`. Card timestamp (right of label): 12px mono, `--text4`, format `HH:MM:SS · source`.
Numbers: mono, `font-variant-numeric: tabular-nums`.

### Row 1: grid `minmax(0,3fr) minmax(0,2fr)`, gap 16, stretch

**Hero card (left)**
- Header block padding `18px 20px 16px`, gap 8.
  - Row: label `TOTAL PORTFOLIO VALUE` · spacer · warnings badge (only if warnings) · Refresh button.
    - Badge: h28, radius 6, 12px/500, text `--warn`, bg `color-mix(--warn 14%, --panel)`, border `color-mix(--warn 45%, --panel)`. Text "⚠ N warnings".
    - Refresh: h28, radius 6, 12px/500, `--text2` on `--panel2`, border `--line`, hover `--panel3`. Label "Loading…" while fetching.
  - Total: 44px / 500 mono / line-height 1.05 / `--text`, always 2 decimals.
  - Status line: 12px `--text4`. 8px dot: `--ok` live, `--warn` fallback or warnings, `--accent` HL loading, `--text4` first load.
  - Notes (conditional): 12px `--text` on a tint box (radius 6, padding 8/12). `--warn` tint for fallback, `--accent` tint for HL loading.
- Parts table (flush to card edges):
  - Columns `minmax(0,1.5fr) 118px 108px 72px minmax(0,1fr)`, gap 12, padding-x 20.
  - Header h32, `--panel2`, borders top/bottom `--line`, 11px/600 `--text4`.
  - Row min-h 36, padding-y 8, bottom border `--line`.
    - Part: 13px `--text2`, optional sub-line 11px mono `--text4` (HL perp/spot split, lending gross/debt).
    - Value: 13px mono right-aligned `--text` (`--text4` when pending or excluded).
    - Share: 48×6 bar (track `--panel3`, fill `--accent`, width = share × 2.5 capped at 100%) + 12px mono `--text3`.
    - As of: 12px mono `--text3` (`--warn` when stale).
    - Source: 12px `--text4`, ellipsis.
  - Warning line (full row span): 12px `--warn`, "⚠ message". The part name gets a "⚠ " prefix.
  - Row order: Wallet tokens, Stablecoins, MaxFi LP, Other LP, LP fees, MaxFi fees, Hyperliquid, Lending net, GMX. Hide a row when value = 0 and no warning, except MaxFi LP.
  - Extras band: `--panel2`, padding `4px 0 8px`. Group label 11px/600 `--text4`, then row (13px `--text3`, value `--text3`, tag 11px `--text4`).
    - `INFO ONLY: ALREADY INSIDE WALLET TOKENS` → "↳ Spot positions", tag "not added".
    - `NOT COUNTED` → "Staked / locked", tag "excluded".

**Right column** (flex column, gap 16)
1. **MaxFi · Advisor** (padding 16/20, gap 12)
   - Stamp "HH:MM:SS · maxfi_positions".
   - "5 of 7" 26px mono + "in range" 13px `--text3`.
   - Row of 14×14 squares (radius 3): `--ok` in range, `--warn` out.
   - Right side: `FEES RUN RATE` label + 18px mono "$38.20" + 12px `--text3` "/ day".
   - Verdict chips (12px `--text2`, `--panel2`, border `--line`, pill, 7px dot): Hold `--ok`, Rebalance `--warn`, Exit `--fail`.
   - Action list: up to 2 non-Hold positions, rows on `--panel2`, 12px. Left pair · chain `--text2`, right verdict text in `--warn` or `--fail`.
   - Link "Open MaxFi →" 12px `--accent`.
2. **BTC Macro Zone** (padding 16/20)
   - BTC price 22px mono + "±x.x% above/below 200D MA" 12px `--ok`/`--fail`.
   - Bar h8 `--panel3`, scale −30%…+30%, MA tick 2×16 `--text3` at 50%, fill `--ok`/`--fail` from 50% to price, 12px knob `--text` with 2px `--panel` ring.
   - Scale labels 11px mono `--text4`.
   - Footer grid of 3 (top border `--line`): Fear & Greed value + class, ETH price + 24h, SOL price + 24h. Labels 11px `--text4`, values 14px mono.
3. **Lending · Lowest health factor** (padding 14/20)
   - HF 22px mono: `--ok` ≥1.30, `--warn` 1.10–1.29, `--fail` <1.10.
   - Protocol · chain · collateral 12px `--text3`.
   - Right: "net $X · debt $Y" 12px mono.
   - Footnote 11px `--text4`.

### Row 2: Equity (full width card)
- Header padding `16px 20px 12px`: label `EQUITY · SNAPSHOT HISTORY` + basis chip + range segmented control (right).
  - Basis chip: `--warn` tint "Snapshot basis: leaves out Hyperliquid & MaxFi fees". After the workstream: `--ok` tint "Same parts as the headline".
  - Range control: `--panel2` container with border `--line`, radius 6, padding 2. Buttons h26, min-w 44, 12px mono. Active `--panel3` + `--text`, idle `--text3`.
- Comparison strip: 5 equal cells, `--panel2`, borders top/bottom `--line`, cell dividers `--line`, padding 10/20. Label 11px `--text4`, value 14px mono (`--ok`/`--fail` by sign), suffix 12px `--text3`.
- Chart: height 280, margins `16px 20px 0 72px`.
  - Recharts `AreaChart`, 4 horizontal gridlines `--line` with 11px mono `--text4` $k labels.
  - Total line: stroke `--accent` 2px, fill `color-mix(--accent 16%, transparent)`, no dots.
  - Stacked mode: 4 areas. Tokens+stables `--accent`, LP+fees `color-mix(--accent 62%, --panel)`, Hyperliquid 38%, Lending 22%, with 1px `--panel` separators.
  - X labels: 5, 11px mono `--text4`.
  - Tooltip: `--panel3`, border `--line`, 12px. Shows date-time and value, plus the per-part list in stacked mode.
- Footer (padding 12/20/16): legend 12px `--text3` with 10px swatches. Right side "Latest snapshot HH:MM:SS" `--text4`.

### Row 3: grid `minmax(0,55fr) minmax(0,45fr)`, gap 16
- **Spot P&L**
  - Header: label + stamp + "Open Spot →".
  - Stats grid of 3: Unrealized ($ + %), Realized 30D, Current value. Labels 11px `--text4`, values 18px mono, signed values `--ok`/`--fail`.
  - Table header h30 `--panel2` (TOP MOVERS / VALUE / 24H / UNREALIZED), cols `1fr 110 80 110`. Rows h36, 12px mono, asset 13px `--text2`. Money right-aligned.
  - 5 rows, sorted by |24h %|.
- **Hyperliquid**
  - Header: label + stamp "HH:MM:SS · N wallets" + "Open Perps →".
  - Stats: Account value, Open perps.
  - Table WALLET / PERP / SPOT / OPEN, cols `1fr 90 80 56`, rows h36, total row on `--panel2` at weight 500.

### Brightness steps
`--bg` → `--panel` (cards) → `--panel2` (table headers, extras band, strip, action rows) → `--panel3` (bar tracks, active range, tooltips). Each step must be 5–8% apart; check against real values.

---

## 3. States

| State | Trigger | Hero | Elsewhere |
|---|---|---|---|
| S1 First load | `/api/portfolio/total` not yet answered | Total "…", dot `--text4`, status "Waiting for the live total…". Rows keep their names; values "…", as-of "—", no sub-lines. Refresh shows "Loading…" | Cards show their own "…" until their fetch answers. The chart may render from snapshots immediately |
| S2 Hyperliquid loading | HL part `pending` | Total excludes HL. Dot `--accent`. `--accent` note "Hyperliquid loading — not in the total yet." HL row value "Loading…" in `--text4`, share "—", as-of "waiting" | HL card shows "…" values |
| S3 Live total unavailable | total endpoint error or timeout | Total = last snapshot total. Dot `--warn`, status "Snapshot HH:MM:SS · live total unavailable since HH:MM". `--warn` note explains the snapshot basis. Every row: as-of = snapshot time, source "snapshot #id". Parts outside the snapshot (HL, MaxFi fees) show "not in snapshot" in `--text4` | Other cards unaffected |
| S4 Warnings | any part `warnings[]` non-empty, or MaxFi drift | Badge "⚠ N warnings" (click scrolls to the first warned row). Warned rows get the name prefix and a warning line. Stale as-of in `--warn`. Status line shows the oldest part | none |
| S5 Hidden values | global hide toggle | Every money figure → `$••••••` (total `$•••,•••.••`). Share → `••%`, bars at 0 width. Sub-line $ amounts → `$••••` | **Every** figure on the page and **every tooltip** (chart, strip, cards, chart Y labels) masks the same way. Mask **all** figures, including HF, market prices, % changes and counts (`••`). Timestamps stay visible |
| S6 Empty | per source | Zero-value parts drop out (MaxFi LP stays) | MaxFi: "No MaxFi positions. The advisor has nothing to review." + link. Lending: card collapses to one line "No lending positions". Spot: "No spot positions. Add them on the Spot Positions page to track P&L." + link. Hyperliquid: "No Hyperliquid wallets connected, or all accounts at $0." |
| S7 Narrow | viewport | See §5 | none |

---

## 4. Data sources

| Figure | Endpoint · field (confirm names against code) |
|---|---|
| Total | `/api/portfolio/total` → sum of parts where `counted` (or `total` field) |
| Status "as of" | `/api/portfolio/total` → response `as_of`. "Oldest part" = min of `parts[].as_of` among counted parts |
| Part rows | `/api/portfolio/total` → `parts[]`: `value`, `counted`, `as_of`, `source`, `warnings[]`. Keys: wallet_tokens, stablecoins, maxfi_lp, other_lp, lp_fees, maxfi_fees, hyperliquid, lending_net, gmx, staking |
| HL sub-line | `parts.hyperliquid` per-wallet perp + spot, summed |
| Lending sub-line | `parts.lending_net` gross, debt |
| Drift warnings | per-wallet/chain MaxFi drift warnings → attached to the MaxFi LP row |
| Spot positions (info) | Spot Positions page Current Value (same source the current `↳ Spot positions` pill uses) |
| Staked/locked | `parts.staking` (counted = false) |
| Snapshot fallback | latest snapshot row: total, time, id |
| Chart / range change / high-low | snapshot history `total`; after the workstream, per-part series |
| 24h change | snapshot history: latest vs 24h earlier (snapshot basis) |
| BTC/ETH range % | market data price history over the same window. If there's no history endpoint, use the snapshot-time prices stored with snapshots, or drop these two cells |
| BTC zone | market data: BTC price, 200D MA, Fear & Greed; ETH, SOL price + 24h |
| MaxFi card | MaxFi advisor: per-position `verdict`, `in_range`, fees run rate; `maxfi_positions` timestamp |
| Lending mini | lending: lowest health factor position (protocol, chain, collateral), net/debt |
| Spot P&L | spot P&L: positions, unrealized, realized 30D |
| Hyperliquid card | Hyperliquid: account value, open perps count, per-wallet perp/spot |

---

## 5. Narrow widths

- **768–1279**: hero full width. Right column → `grid-template-columns: repeat(3, minmax(0,1fr))`. MaxFi drops the action list; BTC keeps the bar. Equity unchanged, strip wraps to 3 + 2. Row 3 is `1fr 1fr`. The parts table drops the Source column below 1024.
- **<768** (see 390 mock):
  - Page padding 12, gap 12.
  - Hero keeps its header. The table becomes compact: grid `1fr auto`, padding 9/16. Line 1 = part + value (13px); line 2 = "as of · source" 11px `--text4` + share 11px mono. Warning line full width.
  - Equity: basis chip under the label, strip reduced to 24h + range change, chart 160px, range buttons full-width `flex:1` at h44 (touch).
  - MaxFi condensed to 3 lines. Lending + BTC become two half-width minis (HF; BTC vs 200D % + F&G). Spot movers show Asset / Value / Unrealized, rows h40. HL collapses to one line.
  - All tap targets ≥44px.

---

## 6. Visibility rules (checked)
- No text dimmer than `--text4`. Muted/excluded values use `--text4`, never opacity.
- Labels ≥11px, values ≥12px, table cells ≥12px (part names 13px). The old 10px labels are gone.
- Separators use `--line`, which must be ≥0.25 alpha. The mock uses `rgba(text4, .28)`.
- Status text on tints is `--text` at full opacity. Tint only the background and border.

## 7. Deviations from the design system
1. **Tints via `color-mix`** (warn/accent/ok at 14% bg, 45% border on `--panel`). Swap for `--ds-*` tint primitives if they exist. Reason: honest status notes that stay readable.
2. **Chart part fills are steps of `--accent`, not categorical colors.** Reason: `--ok/--warn/--fail` are status colors, and using them for series would read as good/bad.
3. **Mono numerals** everywhere a figure appears (the DS may use proportional). Reason: tabular alignment and stable width, so numbers don't shift as they refresh.
4. **Parts table instead of pills**, per decision 2. The DS pill component is no longer used on this page.

## 8. Removed from the current page
LP HEALTH mini card; As-of tooltip (replaced by the table column); breakdown pills; dashed LP/tokens/lending series; 24h change and 60px sparkline under the hero (the sparkline duplicated the equity chart); empty Row 3 column.
