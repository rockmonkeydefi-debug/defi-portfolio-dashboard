# MaxFi: Cards view build spec

Product: The Playbook · MaxFi tab · single user (Glenn)
Scope: the MaxFi content area only. The table view is unchanged. Cards is a second view over the same rows.
Sources: `MaxFi Cards.dc.html` (annotated canvas, artboards A–F), `MaxFi Prototype.dc.html` (working prototype), `MaxFiCard.dc.html` (the card).

## 0. Conventions

- **Colors:** only the `--mx-*` role tokens. No other color values.
- **Type:** written as `size / weight / line-height`, all in px.
- **Numbers:** every figure uses `font-variant-numeric: tabular-nums`.
- **Money format:**
  - `$` + thousands separators + 2 decimals, e.g. `$1,234.50`.
  - Negatives use U+2212: `−$78.38`.
  - Only P/L is always signed (`+$30.39`, `−$78.38`). Other money is unsigned.
  - An empty value is `—`.
- **Rates:**
  - Run 7d is 2 decimals + `%/day`, with `+` only when > 0: `+0.17%/day`, `0.00%/day`, `−0.41%/day`.
  - Decay is 2 decimals + `%/day`, no sign, never below `0.00%/day`, and `—` when there is no advisor data.
- **Font family:** `IBM Plex Sans` (text) and `IBM Plex Mono` (class letter, pins) are stand-ins. Use the design-system families (see Deviations).
- **Pills:** "pill" means `display: inline-flex; align-items: center; box-sizing: border-box`.

Token values, for reference only (use the names):
`--mx-primary #e6eaf0 · --mx-secondary #c9d1d9 · --mx-accent #4bb5a8 · --mx-bg #12161d · --mx-card/--mx-head/--mx-panel #191e27 · --mx-hover #29303c · --mx-warn #fd8a8a · --mx-accent-bright #3ddc84 · --mx-health-caution/--mx-range-near-edge #d08a52 · --mx-range-red #ef4444 · --mx-crash #facc15 · --mx-path-damage #cd9dfd · tints = own color @14% · --mx-expanded-bg #2b2415 · --mx-expanded-edge #d29922 · --mx-border white 25% · --mx-sep white 32% · --mx-control-bg #12161d · --mx-control-border #646a74 · --mx-focus-ring #4bb5a8`

---

## 1. Decisions

| # | Decision | Glenn's pick |
|---|---|---|
| 1 | Card anatomy | **1a · P/L headline.** P/L 22px leads, with P/L % in parentheses. Value sits beside it at 15px. Below come the money rows (Basis, Claimed fees, Uncollected fees), then the range block (state, Width, Delay, bar, Run 7d vs Decay). Asset class, open-date editor, claims list, closing value and notes go to the drawer. |
| 2 | Money alignment in cards | **2a · Label left, value right-aligned, tabular numerals.** This matches the table's right-aligned money, so decimals line up down each card. |
| 3 | Grid | **3a · `repeat(auto-fill, minmax(320px, 1fr))`, gap 16px, card max-width 460px.** 1440 → 4 per row; 1920 → 5 per row. |
| 4 | View toggle + default + persistence | **4a · A "Table \| Cards" segmented control at the far right of the MaxFi toolbar.** The first visit opens Table. The last choice is saved per browser in `localStorage["mx.maxfi.view"]` (`"table"` \| `"cards"`). |
| 5 | Card sorting | **5a · A native `<select>` with all 15 keys in 4 optgroups, plus a Desc/Asc button.** It is one sort state shared with the table headers. |
| 6 | Expanded detail | **6a · Side drawer, 480px, non-modal, in-flow.** The grid narrows beside it, and the selected card gets an `--mx-expanded-edge` border. |
| 7 | Closed positions | **7a · Keep the existing table,** in a collapsible "Closed positions" section below the open cards. |

No decision is OPEN.

Added by Glenn after pass 1 (specified in §9): P/L % on the card, a summary strip, and filters.

---

## 2. Card anatomy (top to bottom)

### 2.0 Container
- Element: `div role="button" tabindex="0"`, `aria-label="{chain} {pool} {fee}, P/L {pnl}, {range state}, verdict {verdict}. Open details"`, `aria-expanded="true|false"`. Enter or Space opens the drawer; click opens the drawer.
- Background `--mx-card` · border `1px solid --mx-border` · radius `8px` · padding `16px`.
- Layout: flex column, gap `12px` between blocks 2.1–2.7.
- Width: min `320px` (from the grid track), `max-width: 460px`.
- Default text color `--mx-primary` · cursor pointer · tabular-nums.

### 2.1 Header row
Flex row, `align-items: center`, gap `6px`, min-width 0. Height 20px.

| Element | Data field · example | Color | Type | Box |
|---|---|---|---|---|
| Chain chip | chain · `RH` \| `Base` | text `--mx-secondary`, border `--mx-border` | 11 / 600 / 16, uppercase, letter-spacing 0.04em | pill, height 20, padding `0 6px`, radius 4, border 1px solid, flex none |
| Class letter | class · `S` \| `C` | text `--mx-primary`, border `--mx-border` | Mono 12 / 600 / 16 | 20×20 box, centered, radius 4, border 1px solid, flex none |
| Pool + fee tier | pool + fee · `WETH/AI` `1%` | pair `--mx-primary`; fee `--mx-secondary` | pair 15 / 600 / 20; fee 13 / 400 / 20 | flex 1, min-width 0, baseline aligned, gap 6. One line: the pair truncates with ellipsis; the fee does not shrink. Full text in the `title` attribute. |
| Verdict badge | advisor verdict · `CLOSE` \| `HOLD` \| `NEUTRAL` | see §3 | 11 / 700 / 16, letter-spacing 0.04em | pill, height 20, padding `0 8px`, radius 4, border 1px solid, flex none, right end of row |

### 2.2 Meta row
Flex row, align center, gap `8px`, `margin-top: -4px` (so it sits 8px below the header).

| Element | Data field · example | Color | Type | Box |
|---|---|---|---|---|
| Opened · age | opened date + age · `Aug 31 · 24d` | `--mx-secondary` | 12 / 400 / 16 | — |
| Wallet badge | wallet label · `Degen` · **rendered only when the wallet scope is All** | text `--mx-secondary`, bg `--mx-secondary-tint` | 11 / 500 / 16 | pill, height 20, padding `0 6px`, radius 4, no border |

### 2.3 Badge row (advisor + status)
- Omitted entirely when there are no badges.
- Flex-wrap, gap `6px`.
- Order: crash, then path damage, then status badges in data order.
- Every badge: pill, height 20, padding `0 6px`, radius 4, border 1px solid, 11 / 600 / 16, nowrap. Text as written in the data (uppercase or lowercase).
- Colors per badge type: see §3.

### 2.4 Headline
Flex row, `justify-content: space-between`, `align-items: flex-end`, gap `12px`.

| Element | Data field · example | Color | Type | Box |
|---|---|---|---|---|
| Label "P/L" | — | `--mx-secondary` | 11 / 600 / 16, uppercase, 0.04em | — |
| P/L figure | P/L · `+$30.39` | > 0 `--mx-accent-bright`; < 0 `--mx-warn`; = 0 `--mx-primary`; unavailable `--mx-secondary` | 22 / 600 / 28 | margin-top 2; wrapper flex, baseline, gap 6, nowrap |
| P/L % | P/L ÷ Basis × 100, 1 decimal, always signed · `(+24.7%)` | same token as the P/L figure | 15 / 600 / 20 | follows the figure on its baseline, gap 6; omitted when P/L is unavailable |
| Label "Value" | — | `--mx-secondary` | 11 / 600 / 16, uppercase, 0.04em | block right-aligned |
| Value figure | Value · `$98.10` | `--mx-primary` (loading: `--mx-secondary`) | 15 / 600 / 20 | margin-top 2, `aria-busy` while loading |

P/L is the table's existing P/L. The prototype computes it as value + claimed + uncollected − basis for sample data only.

### 2.5 Money rows
- Block: `border-top: 1px solid --mx-border` · padding-top `12px`.
- Grid: `grid-template-columns: minmax(0,1fr) auto` · row-gap `6px` · column-gap `12px` · `align-items: center` · 13 / 20.

| Row | Label (13 / 400 / 20, `--mx-secondary`) | Value (13 / 500 / 20, `--mx-primary`, right-aligned) |
|---|---|---|
| 1 | `Basis` | `$123.00`, followed by the edit button (gap 6). |
| 2 | `Claimed fees · realized` | `$52.24` or `—` |
| 3 | `Uncollected fees · unrealized` | `$3.05` or `—` |

**Basis edit button:**
- 20×20, no border, bg transparent, radius 4, glyph `✎` 13px `--mx-accent`.
- `:hover` bg `--mx-hover` · `:focus-visible` outline `2px solid --mx-focus-ring`.
- `aria-label="Edit basis"`. Click must not open the drawer (stop propagation).

**Basis inline editor** (replaces the value cell while editing):
- Input: 96×28, padding `0 8px 0 18px`, prefix `$` 13px `--mx-secondary` at left 8, bg `--mx-control-bg`, border `1px solid --mx-control-border`, radius 6, text 13 / 500 `--mx-primary`, right-aligned, `inputmode="decimal"`, `aria-label="Basis in USD"`.
- Save button: height 28, padding `0 10px`, bg `--mx-accent`, text `--mx-bg` 13 / 600, radius 6.
- Cancel button: `✕` 28×28, bg none, `--mx-secondary`, hover bg `--mx-hover`, `aria-label="Cancel"`.
- Gap 6 between controls. Enter saves; Esc cancels (Esc must not close the drawer).
- Validation: the value must be > 0. On failure the input border becomes `--mx-warn` and `aria-invalid="true"`.
- On save, focus returns to the card.

The rule "never call unrealized value change *claimed*" holds: realized fees and uncollected fees are separate, labeled rows, and no row shows value change.

### 2.6 Range block
- `border-top: 1px solid --mx-border` · padding-top `12px` · flex column, gap `8px`.

**a. Range header row:** flex, space-between, align center, gap 8.

| Element | Data field · example | Color | Type | Box |
|---|---|---|---|---|
| Range state badge | range state · `In range` \| `Near edge` \| `Out of range` | see §3 | 11 / 600 / 16 | pill, height 20, padding `0 6px`, radius 4, border 1px solid, bg none, gap 6 (for the out-of-range square) |
| Width | width % · `Width 101.4%` | label `--mx-secondary`, value `--mx-primary` | 13 / 400 label, 13 / 500 value, lh 20 | right group: flex, gap 12 |
| Delay | rebalance delay · `Delay 10h` | label `--mx-secondary`, value `--mx-primary` | as Width | follows Width |

**b. Range bar:**
- `role="img"`, `aria-label` such as "Price inside range", "Price near upper edge", or "Price outside lower edge".
- Container height `16px`, position relative.
- Band: absolute, `left: 8%; right: 8%; top: 4px; height: 8px`, bg `--mx-hover`, border `1px solid --mx-border`, radius 4. The band is the LP range; the 8% on each side is the outside-range gutter.
- Price marker: absolute, `3×16px`, radius 2, `left = 8% + position × 84%` (clamped 3%–97%), `margin-left: -1px`. Color: see §3.

**c. Run 7d vs Decay comparison pair:**
- The verdict is CLOSE when Run 7d < 2 × Decay, so the two are shown as a pair.
- Box: `role="group"` with an `aria-label` read as a sentence, e.g. "Run 7d +0.89%/day is at least 2 times Decay 0.18%/day". Border `1px solid --mx-border`, radius 6, padding `8px 10px`.
- Grid `minmax(0,1fr) auto minmax(0,1fr)`, gap 8, `align-items: end`.

| Cell | Data · example | Color | Type |
|---|---|---|---|
| Left: label `Run 7d` + value | Run 7d · `+0.89%/day` | label `--mx-secondary`; value `--mx-accent-bright` when ≥ 0, `--mx-warn` when < 0 | label 11 / 600 / 16 uppercase 0.04em; value 13 / 500 / 20, margin-top 2 |
| Center: operator | derived · `≥ 2×` \| `< 2×` \| `vs` | `< 2×` → `--mx-warn`; `≥ 2×` → `--mx-secondary`; `vs` (no Decay) → `--mx-secondary` | 13 / 600 / 20, nowrap |
| Right (right-aligned): label `Decay` + value | Decay · `0.18%/day` \| `0.00%/day` \| `—` | label `--mx-secondary`; value `--mx-primary` | as the left cell |

### 2.7 Footer
- `border-top: 1px solid --mx-border` · padding-top `10px` · flex, justify end.
- Text `Details ›` · `--mx-accent` · 13 / 500 / 20.
- It is a visual cue only; the whole card is the click target.

---

## 3. Card states

Every state keeps the §2 layout. Only the listed properties change.

| State | Trigger | Changes (tokens / px) |
|---|---|---|
| Default | — | bg `--mx-card`, border `1px solid --mx-border`, no outline |
| Hover | pointer over the card | bg `--mx-hover`; border-color `--mx-sep`; text unchanged (lowest pair: `--mx-range-near-edge` on `--mx-hover` = 4.7:1) |
| Keyboard focus | `:focus-visible` on the card | `outline: 2px solid --mx-focus-ring; outline-offset: 2px`; bg and border unchanged; mouse focus shows no outline |
| Expanded (drawer open for this card) | card selected | border-color `--mx-expanded-edge` (1px); `aria-expanded="true"`; bg `--mx-card` (hover still applies) |
| In range | range = in | badge text + border `--mx-accent-bright`, bg none, label `In range`; marker `--mx-accent-bright`, inside the band |
| Near edge | range = near | badge text + border `--mx-range-near-edge`, bg none, label `Near edge`; marker `--mx-range-near-edge`, inside the band near the edge |
| Out of range | range = out | badge text `--mx-primary`, border `--mx-range-red`, bg none, label `Out of range`, preceded by an 8×8 square `--mx-range-red` (radius 2, gap 6); marker `--mx-range-red`, in the outside gutter. Red is never text (4.44:1 on `--mx-card`). |
| Crash badge | advisor crash present | badge row: `⚠ -23% · range`, bg `--mx-crash-tint`, text + border `--mx-crash`, 11 / 600, height 20, padding `0 6px`, radius 4 |
| Path-damage badge | advisor path damage present | badge row: `path -12%`, bg `--mx-path-damage-tint`, text + border `--mx-path-damage`, same box as crash |
| CLOSE | advisor verdict CLOSE | verdict badge `CLOSE`: bg `--mx-warn-tint`, text + border `--mx-warn`; comparison operator `< 2×` in `--mx-warn` |
| HOLD | advisor verdict HOLD | verdict badge `HOLD`: bg `--mx-gain-tint`, text + border `--mx-accent-bright`; operator `≥ 2×` in `--mx-secondary` |
| Neutral | no verdict / no advisor data | verdict badge `NEUTRAL`: bg none, text `--mx-secondary`, border `--mx-border`; Decay `—`, operator `vs` |
| NO BASIS | basis missing | status badge `NO BASIS` (bg none, text `--mx-secondary`, border `--mx-border`, 11 / 600, height 20, padding `0 6px`, radius 4). The Basis value cell becomes a `Set basis` button (no border or bg, `--mx-accent`, 13 / 500 / 20), which opens the §2.5 inline editor. P/L shows `—` in `--mx-secondary`; P/L % is omitted. |
| STALE | data stale | status badge `STALE` (same style as NO BASIS). Values show as delivered, with no dimming. |
| UNTRACKED | untracked | status badge `UNTRACKED` (same style). |
| inherited · auto-split · needs review | flags | status badges `inherited`, `auto-split`, `needs review` (same style, lowercase as written) |
| Value loading | valuation not yet returned | Value figure `…` in `--mx-secondary` with `aria-busy="true"`; P/L `…` in `--mx-secondary`; P/L % omitted. Any other money field whose data hasn't loaded also shows `…` in `--mx-secondary`. |

Advisor badge hues stay distinct and are never merged: crash yellow, path-damage violet, out-of-range red, near-edge/caution orange, CLOSE `--mx-warn`, HOLD `--mx-accent-bright`. Status badges are neutral outline badges.

---

## 4. Grid

- Content area padding `24px`.
- Grid: `display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 16px; align-items: start`.
- Card: min 320px (from the track), `max-width: 460px`.
- Column counts, measured on content width minus 48px of padding:

| Viewport content width | Drawer | Grid width | Columns | Card width |
|---|---|---|---|---|
| 1440 | closed | 1392 | 4 | 336px |
| 1920 | closed | 1872 | 5 | ≈362px |
| 1440 | open (480 + 24 gap) | 888 | 2 | 436px |
| 1920 | open | 1368 | 4 | 330px |

- 16 open cards = 4 rows at 1440 and 4 rows at 1920 (the last row holds 1 card).

---

## 5. View toggle and sort control

### Content-area order, top to bottom
1. Summary strip (§9.2)
2. Toolbar (below)
3. Filter row (§9.3)
4. Result line (§9.3)
5. Cards grid or table
6. Closed positions (§7)

### Toolbar
- min-height `48px` · flex, `align-items: center`, `justify-content: space-between`, `flex-wrap: wrap`, gap `12px` · margin-bottom `16px` · no background.
- **Left:** title `Open positions` (15 / 600 / 20, `--mx-primary`) and a count pill (12 / 600 / 16, text `--mx-secondary`, bg `--mx-secondary-tint`, radius 10, padding `1px 8px`), gap 8. The count is the number of rows shown after filters.
- **Right:** flex, wrap, gap `16px`. It holds the sort group (Cards view only), then the view toggle.

### Sort group (rendered in Cards view only; the table keeps header sorting)
- Flex, align center, gap `8px`.
- **Label:** a visible `<label for>` reading `Sort`, 13 / 400 / 20, `--mx-secondary`.
- **Select:** native `<select>`.
  - Box: `appearance: none`, height `32px`, min-width `148px`, padding `0 28px 0 10px`, bg `--mx-control-bg`, border `1px solid --mx-control-border`, radius 6, text 13 / 500 `--mx-primary`.
  - Chevron: `▾`, 11px `--mx-secondary`, absolute at right 10, top 8, `pointer-events: none`.
  - `:hover` bg `--mx-hover` · `:focus-visible` outline `2px solid --mx-focus-ring`, offset 2.
  - Options:
    - Identity: Chain `chain` · Class `class` · Pool `pool` · Opened `opened`
    - Money: Basis `basis` · Value `value` · Claimed `claimed` · Uncollected `uncollected` · P/L `pnl`
    - Range: Width `width` · Delay `delay` · Range `range` · Run 7d `run7d` · Decay `decay`
    - Advisor: Verdict `verdict`
- **Direction button:**
  - Box: height `32px`, padding `0 10px`, same bg / border / radius / type as the select. `:hover` bg `--mx-hover` · `:focus-visible` as the select.
  - Text `↓ Desc` or `↑ Asc`, with `aria-label="Sort direction: descending|ascending"`. Click toggles.
- **Shared state:** one `{key, dir}` for both views. Picking a table header sets the key (desc first; clicking the same header toggles direction). Cards and table read the same state.
- **Sort semantics:**
  - Nulls (e.g. `—`, loading) always sort last, in either direction.
  - Range order: in → near → out.
  - Verdict order: CLOSE → HOLD → neutral.
  - Text sorts alphabetically; dates sort chronologically.
- **Custom list reference** (if not native): bg `--mx-panel`, border `1px solid --mx-border`, radius 6, padding `4px 0`.
  - Group label: 11 / 600 uppercase `--mx-secondary`, padding `8px 10px 4px`.
  - Option: 13 / 400 `--mx-primary`, height 28, padding `0 10px`.
  - Selected option: bg `--mx-hover` plus `✓` 12px `--mx-accent`.

### View toggle
- `role="radiogroup"`, `aria-label="View"`.
- Container: height `32px`, `box-sizing: border-box`, padding `2px`, gap `2px`, bg `--mx-control-bg`, border `1px solid --mx-control-border`, radius 6.
- Options `Table` and `Cards`: `role="radio"`, height `26px`, padding `0 12px`, radius 4, no border, 13 / 500.
  - Selected: bg `--mx-hover`, text `--mx-primary`, `aria-checked="true"`, `tabindex=0`.
  - Unselected: bg none, text `--mx-secondary`, `tabindex=-1`, `:hover` text `--mx-primary`.
  - `:focus-visible`: outline `2px solid --mx-focus-ring`, offset 0.
- Keyboard: ←/→/↑/↓ switch the view and move focus.
- Default `table`. Persist the choice to `localStorage["mx.maxfi.view"]` on each change and read it on load.

---

## 6. Expanded detail (side drawer)

**Layout**
- In Cards view, when a card is opened, the content row becomes `grid-template-columns: minmax(0,1fr) 480px; gap: 24px; align-items: start`.
- The grid reflows into the left column. There is no overlay and no scrim.
- Switching to Table view hides the drawer.

**Drawer box**
- `<aside role="dialog" aria-modal="false" aria-labelledby="{title id}">`.
- `position: sticky; top: 0; max-height: 100vh; overflow-y: auto; box-sizing: border-box`.
- bg `--mx-expanded-bg` · `border-left: 2px solid --mx-expanded-edge` · padding `20px` · flex column, gap `20px`.

**Behavior**
- On open, focus moves to the close button.
- Esc or `✕` closes, and focus returns to the originating card.
- Esc inside an inline editor cancels that editor first and does not close the drawer.
- Clicking another card swaps the drawer contents.

**Sections, in order**

1. **Header.** Flex, space-between, align start, gap 12.
   - Left column (gap 6):
     - chain chip + class letter (exactly as §2.1), gap 6
     - title: pool 17 / 600 / 24 `--mx-primary` + fee 13 / 400 / 20 `--mx-secondary`, baseline, gap 6
     - `Opened Aug 31 · 24d`, 12 / 400 / 16 `--mx-secondary`
   - Close button: 32×32, no border, bg none, radius 6, `✕` 15px `--mx-secondary`, `:hover` bg `--mx-hover`, `aria-label="Close details"`.

2. **Asset class + Open date.**
   - Section: `border-top: 1px solid --mx-border`, padding-top 16. Grid `minmax(0,1fr) minmax(0,1fr)`, gap 12.
   - Each field: column, gap 8.
   - Label: 11 / 600 / 16 uppercase 0.04em `--mx-secondary`, as a `<label for>`.
   - Asset class: native select, same spec as the §5 sort select, width 100%. Option values come from the existing asset-class list.
   - Open date: `<input type="date">`, max = today, height 32, padding `0 10px`, bg `--mx-control-bg`, border `1px solid --mx-control-border`, radius 6, 13 / 500 `--mx-primary`, `color-scheme: dark`, focus outline `2px --mx-focus-ring`. Changing it updates the card's age.

3. **Claims list + Add claim.**
   - Section: border-top as above, padding-top 16, column, gap 8. Label `Claims`.
   - Rows: flex space-between, height 32, `border-bottom: 1px solid --mx-border`. Date 13 / 400 `--mx-secondary` (`Sep 8`); amount 13 / 500 `--mx-primary`, right-aligned (`$18.40`). Sorted by date, ascending.
   - Empty list: one 32px row reading `No claims yet`, 13 `--mx-secondary`.
   - Total row: height 32, 13 / 600 `--mx-primary`, `Claimed fees (realized)` … `$52.24`. It equals the card's Claimed.
   - `+ Add claim` button: height 32, padding `0 12px`, bg none, border `1px solid --mx-accent`, text `--mx-accent` 13 / 500, radius 6, `:hover` bg `--mx-hover`. It is hidden while the inline row is open.
   - Inline add row (inserted above the total):
     - Layout: padding `8px 0`, border-bottom `--mx-border`; controls in a flex row, gap 8.
     - Controls: date input (flex 1, default today, max today) · amount input (flex 1, `$` prefix at left 10, padding-left 22, right-aligned, `inputmode="decimal"`, placeholder `0.00`) · Save (height 32, padding `0 14px`, bg `--mx-accent`, text `--mx-bg` 13 / 600, radius 6) · cancel `✕` 32×32.
     - Keys: Enter saves; Esc cancels.
     - Validation: amount > 0. On failure the amount border becomes `--mx-warn`, `aria-invalid`, and the message `Enter an amount above $0.00.` appears at 12 / 400 `--mx-warn` with `role="alert"`.
     - On save: the claim is appended and sorted, the total and the card update, and focus returns to Add claim.

4. **Closing-value editor.**
   - Section: border-top, padding-top 16, column, gap 8. Label `Closing value`.
   - Row: flex, gap 8.
     - Input: flex 1, height 32, `$` prefix, padding `0 10px 0 22px`, right-aligned, control tokens as the Open date input, placeholder `0.00`.
     - Save button: as the add-claim Save.
   - Status line below: min-height 16, 12 / 400, `aria-live="polite"`.
     - Success: `Saved: $120.50` in `--mx-secondary`.
     - Empty save: clears the value and shows `Cleared`.
     - Invalid: `Enter a dollar amount, e.g. 120.50.` in `--mx-warn`, with the input border `--mx-warn`.
   - Enter saves.

5. **Notes.**
   - Section: border-top, padding-top 16, column, gap 8. Label `Notes`.
   - `<textarea>`: width 100%, min-height 96, padding `8px 10px`, 13 / 400 / 20 `--mx-primary`, bg `--mx-control-bg`, border `1px solid --mx-control-border`, radius 6, `resize: vertical`, placeholder `Add a note`.
   - Saving uses the existing notes save behavior. The prototype saves on change.

---

## 7. Closed positions

**Decision:** keep the existing table. It is not cards, so there is no card layout.

- **Placement:** below the open grid (Cards view) or the open table (Table view), 32px gap.
- **Disclosure button:**
  - `aria-expanded`, `aria-controls` → the table. Height 40, flex, align center, gap 8, bg none, no border.
  - Contents: chevron `▸` (collapsed) / `▾` (open), 13 / 400 `--mx-secondary`, width 12 · `Closed positions` 15 / 600 / 20 `--mx-primary` · a count pill as in the toolbar (`44`).
  - `:focus-visible` outline `2px --mx-focus-ring`, offset 2.
- **Default:** collapsed. The state is saved to `localStorage["mx.maxfi.closedOpen"]` (`"true"` \| `"false"`).
- **Contents:** the existing MaxFi closed table, unchanged (columns, sort, expanded row).
- **Filters:** filters and the summary strip do not apply to closed positions.

---

## 8. Deviations and inventions

**Tokens and colors**
- No new tokens. No colors outside the listed `--mx-*` tokens. Tints are the brief's own `--mx-*-tint` tokens, each its own color at 14% opacity.
- Several tokens are used outside their literal role name:
  - `--mx-hover` is the fill of the range band, the selected view-toggle option, and the selected sort option (non-hover uses).
  - `--mx-secondary-tint` is the wallet badge and count-pill background.
  - `--mx-expanded-edge` / `--mx-expanded-bg`, defined for the table's expanded row, are reused for the selected card border and the drawer.
  - `--mx-primary` is the hover border of filter chips.
  - `--mx-accent` is the fill of selected filter chips and Save buttons, with `--mx-bg` text (7.4:1).
- No tint exists for `--mx-range-red` or `--mx-range-near-edge`, so the range-state badges are outline-only (bg none).
- `--mx-range-red` fails 4.5:1 as text on `--mx-card` (4.44:1). It is used only for the marker, the badge border and the 8px square; the "Out of range" text uses `--mx-primary`.

**House rules not met or interpreted**
- **Adjacent sections, possibly not met:** `--mx-card` (#191e27) on `--mx-bg` (#12161d) is about 3.4 points apart in HSL lightness, below the ≥5% rule. It applies to cards, the summary strip and the drawer edge area. Separation relies on the 1px `--mx-border`. Unresolved, and it needs a token decision from Glenn.
- **Font-size floor, interpreted:** "body and labels ≥13px". Field labels (`P/L`, `Value`, `Run 7d`, `Decay`, drawer section labels, filter group labels) and all badges are 11px uppercase, treated as *secondary labels* (≥11). The opened/age line, chip counts, summary sub-lines, the drawer "Opened" line and validation messages are 12px, treated as secondary. Money-row labels and all body text are 13px. If these labels must be 13px, raise them to 13 / 600 and remove the uppercase styling.
- **Font family:** the "Dashboard Design" system file was not available. IBM Plex Sans / IBM Plex Mono are stand-ins.

**Fields, features and copy beyond the brief**
- **P/L % field:** added at Glenn's request (`(+24.7%)` = P/L ÷ Basis).
- **Summary strip** (§9.2): a new feature, added at Glenn's request.
- **Filters** (§9.3): a new feature, added at Glenn's request. The wallet scope, assumed to be an existing control, is presented as a chip group in the filter row instead of a dropdown.
- **Invented elements:**
  - `NEUTRAL` verdict badge text
  - `Details ›` footer cue
  - the "Run 7d vs Decay" comparison box and its `≥ 2×` / `< 2×` / `vs` operator (built from Glenn's CLOSE rule)
  - the P/L and Value field labels
- **Label copy:** `Claimed fees · realized` and `Uncollected fees · unrealized`.
- **Invented copy:**
  - validation: `Enter an amount above $0.00.`, `Enter a dollar amount, e.g. 120.50.`
  - status: `Saved: $x`, `Cleared`
  - empty lists: `No claims yet`
  - placeholders: `Add a note`, `Pair or token`
  - the empty-state title and body (§9.3)
- **Invented behavior:**
  - on the card: the basis inline-editor layout; Esc-cancels-editor-before-drawer
  - in the drawer: focus moves on open and close
  - in the toolbar: arrow keys on the view toggle; the sort control is hidden in Table view
  - the drawer is hidden in Table view
  - persisting the closed-section state
- **Sample data only, not for build:** wallet names `Main` / `Degen`, asset-class options (`Stock token`, `Crypto`, `Stablecoin`), eight extra open rows, closed rows, Value and Uncollected amounts, claim dates, the note text, and the prototype's P/L formula and derived verdicts. The table in the prototype is a stand-in with guessed columns.

---

## 9. Appendix: contrast, and the specs added after pass 1

### 9.1 Contrast (WCAG, text on its actual background)
| Pair | Ratio |
|---|---|
| `--mx-primary` on `--mx-card` | 13.9:1 |
| `--mx-secondary` on `--mx-card` | 10.8:1 |
| `--mx-accent` on `--mx-card` | 6.7:1 |
| `--mx-accent-bright` on `--mx-card` | 9.4:1 |
| `--mx-warn` on `--mx-card` | 7.3:1 |
| `--mx-range-near-edge` on `--mx-card` | 5.9:1 |
| `--mx-crash` on `--mx-crash-tint` (over card) | 7.9:1 |
| `--mx-path-damage` on `--mx-path-damage-tint` | 6.0:1 |
| `--mx-warn` on `--mx-warn-tint` | 5.7:1 |
| `--mx-accent-bright` on `--mx-gain-tint` | 7.0:1 |
| `--mx-secondary` on `--mx-secondary-tint` | 7.8:1 |
| `--mx-accent` on `--mx-hover` | 5.3:1 |
| `--mx-range-near-edge` on `--mx-hover` | 4.7:1 |
| `--mx-warn` on `--mx-hover` | 5.8:1 |
| `--mx-accent` on `--mx-expanded-bg` | 6.2:1 |
| `--mx-bg` on `--mx-accent` (Save, selected chip) | 7.4:1 |
| `--mx-range-red` on `--mx-card` | 4.44:1, **not used as text** |

### 9.2 Summary strip
- **Placement:** top of the content area, above the toolbar.
- **Container:**
  - Grid `repeat(auto-fit, minmax(170px, 1fr))`, margin `8px 0 20px`.
  - bg `--mx-card`, border `1px solid --mx-border`, radius 8, overflow hidden.
  - Tiles are separated by `border-left: 1px solid --mx-border`. The first tile has none; use `margin-left: -1px` on each tile, or omit it on the first.
- **Tile:**
  - Padding `16px 20px` · flex column, gap 6, min-width 0.
  - Label: 11 / 600 / 16 uppercase 0.04em `--mx-secondary`.
  - Figure: 22 / 600 / 28, nowrap, tabular.
  - Sub-line: 12 / 400 / 16 `--mx-secondary`.
- **Tiles, in order:**
  1. `Value`: Σ Value · sub `{n} open`, plus ` (filtered)` when a wallet or filter is active · `--mx-primary`
  2. `Basis`: Σ Basis of rows with a basis · sub `what went in`, plus ` · {k} without basis excluded` when k > 0 · `--mx-primary`
  3. `Claimed fees`: Σ claimed · sub `realized` · `--mx-primary`
  4. `Uncollected fees`: Σ uncollected · sub `unrealized, not yet claimed` · `--mx-primary`
  5. `P/L`: Σ P/L of rows with a basis, signed · sub `value + claimed + uncollected − basis` · > 0 `--mx-accent-bright`, < 0 `--mx-warn`, 0 `--mx-primary`
  6. `Return`: Σ P/L ÷ Σ Basis, 1 decimal, signed, e.g. `+12.4%` · sub `P/L ÷ basis` · same colors as P/L
- **Loading:** while any visible row's Value is loading, Value, Uncollected, P/L and Return show `…` in `--mx-secondary` with `aria-busy`.
- **Scope:** the strip follows the wallet and filters and never includes closed positions.

### 9.3 Filters
- **Filter row:**
  - `role="group" aria-label="Filters"`, directly below the toolbar.
  - Flex-wrap, column-gap 16, row-gap 10, align center, margin-bottom 12.
- **Groups, in order:**
  1. Wallet: single-select `All` / each wallet; default `All`
  2. Chain: `RH`, `Base`
  3. Class: `S`, `C`
  4. Range: `In range`, `Near edge`, `Out of range`
  5. Verdict: `CLOSE`, `HOLD`, `Neutral`
  6. Advisor: `Crash`, `Path damage`
  7. Status: `NO BASIS`, `STALE`, `UNTRACKED`, `inherited`, `auto-split`, `needs review`
  8. P/L: `Gain` (P/L > 0), `Loss` (P/L < 0)
  9. Search
- **Divider:** 1×20px, bg `--mx-border`, between groups.
- **Group:** `role="group"` with an `aria-label`, flex-wrap, gap 6. Label: 11 / 600 / 16 uppercase 0.04em `--mx-secondary`, margin-right 2.
- **Chip:**
  - `<button aria-pressed>`, height 28, padding `0 10px`, radius 14, 13 / 500 / 20, gap 6, nowrap.
  - Off: bg none, border `1px solid --mx-control-border`, text `--mx-secondary`.
  - On: bg `--mx-accent`, border `--mx-accent`, text `--mx-bg`.
  - `:hover` border-color `--mx-primary` · `:focus-visible` outline `2px --mx-focus-ring`, offset 2.
- **Chip count:**
  - Trailing number, 12 / 500, same color as the label.
  - Value: the rows that would match if this chip were added to the current filters. A selected chip shows the current result count.
  - Wallet chip counts: the current filters applied within that wallet.
- **Logic:**
  - AND everywhere, including within a group: `RH` + `Base` matches 0 rows. Search ANDs with chips.
  - Filters are not saved; they reset each visit.
  - They apply to Cards and Table, and never to closed positions.
- **Search:**
  - Visible label `Search` (group-label style), then `<input type="search">`.
  - Box: width 180, height 28, padding `0 12px`, radius 14, bg `--mx-control-bg`, border `1px solid --mx-control-border`, 13 / 400 `--mx-primary`.
  - Placeholder `Pair or token`. Case-insensitive substring match on pair + fee tier.
- **Result line:**
  - `aria-live="polite"`, flex, gap 12, min-height 28, margin-bottom 16, 13 / 400 / 20 `--mx-secondary`.
  - Text `{shown} of {in wallet} open`, plus ` · filters combine with AND` when any filter is active.
  - `Clear filters` link-button: 13 / 500 `--mx-accent`, hover underline. Shown only when a chip or search is active. It resets chips and search, but not Wallet.
- **Empty state** (replaces the grid when 0 rows match):
  - Box: border `1px dashed --mx-border`, radius 8, padding 24, flex column, align start, gap 8.
  - Title `No open positions match every selected filter`, 15 / 600 / 20 `--mx-primary`.
  - Body `Filters combine with AND, including values in the same group (RH + Base matches nothing).`, 13 / 400 / 20 `--mx-secondary`.
  - `Clear filters` button: height 32, padding `0 12px`, border `1px solid --mx-accent`, text `--mx-accent` 13 / 500, radius 6, hover bg `--mx-hover`.
