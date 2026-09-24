# Design Audit — MaxFi Position Ledger (Position Ledger dashboard)

Documentation only. Not imported, required, or linked from any template,
route, or script — verify with `grep -rn "design-audit" templates/ static/
web_portfolio.py` (no hits expected).

Scope: this audit targets `static/maxfi.js`'s `MX_C` color object and
everything it styles (the MaxFi / Position Ledger tab), per the task that
produced it. It also documents where MX_C sits relative to the rest of the
app's styling, since that turned out to be load-bearing for understanding
what "the styling system" even means here.

## 1. Styling approach found

**There is no single source of truth.** This app runs at least three
independent, non-overlapping color systems simultaneously:

1. **`static/style.css`** — one hand-authored global stylesheet, linked from
   `templates/index.html` (`<link rel="stylesheet" href="/static/style.css">`).
   Defines a `:root` custom-property palette (see §2) used by most of the
   app's other tabs (Dashboard, Archive, Action Plan, etc.) via `className`
   on JSX elements — e.g. `static/dashboard.js:151` and
   `static/archive.js:93` both use `className="tv-num"`.
2. **`static/maxfi.js`'s `MX_C` object** (line 16-47) — a second, entirely
   separate palette, used **only** by the MaxFi tab. Every MaxFi element is
   built with `React.createElement(...)` and an inline `style` object —
   **no JSX, no `className`, no reference to `style.css`'s `:root`
   variables anywhere in this file.** This is the file this audit's fixes
   target.
3. **`static/ai.js`** — a third, ad-hoc palette of its own inline hex
   values (`#8892b0`, `#64ffda`, `#0a0a1a`, `#1e3050`, etc., lines
   103-197), used only by the AI Brief tab. Not touched by this audit;
   flagged in §9 as a separate issue.

So: **MX_C is not the site's single source of truth — it is one of (at
least) three parallel, non-communicating systems.** Within its own scope
(the MaxFi tab), MX_C *is* authoritative: no MaxFi element reads
`style.css`'s CSS variables, and `style.css` defines nothing MaxFi-specific.

**No CSS custom properties (`:root` variables) exist inside `MX_C` or
anywhere in `maxfi.js`** — it's a plain JS object of string literals,
referenced directly (`MX_C.primary`, etc.) at every call site. `style.css`
*does* use `:root` custom properties (see §2), but MaxFi never reads them.

## 2. Every MX_C key, its value, and what it styles

(`static/maxfi.js` lines 16-47; occurrence counts from `grep -c` against
the current file after this commit's edits.)

| Key | Value | Styles | Occurrences |
|---|---|---|---|
| `primary` | `#e6edf3` | Primary text — table cell values, headings, input text, most numeric figures | 60+ |
| `secondary` | `#b3bdcb` *(was `#c9d1d9` — see §8)* | Muted/secondary text — labels, captions, status lines, "unresolved"/dash placeholders | 60+ |
| `border` | `rgba(255,255,255,0.25)` | Card/table/panel/button perimeters (translucent white over whatever's behind it) | 30+ |
| `sep` | `rgba(255,255,255,0.32)` | Functional separators — summary grid's row/header borders (`borderBottom: '2px solid ' + MX_C.sep`) | 4 |
| `summaryEdge` | `rgba(255,255,255,0.65)` | Summary grid's own outer frame only (deliberately heavier than `sep`, which is heavier than `border` — see the object's own comment, line 19-22) | 1 |
| `bg` | `#12161c` | Page/panel background; also input/select/textarea background | 10+ |
| `panel` | `#0d1117` | Secondary panel background (expanded-panel labeled blocks, popovers) | 4 |
| `head` | `#1b2129` | Table `<thead>` background | 2 |
| `zebra` | `#262a30` | **Defined but unused** — see the object's own comment (line 23-27): retired in favor of uniform `card` rows, kept only because nothing reads it | 0 (definition only) |
| `hover` | `#4e5258` | Hovered table row background (JS-driven, via `onMouseEnter`/`onMouseLeave` — see §6) | 2 |
| `accent` | `#7ee2a8` | Interactive/success affordances — "edit"/"set" link, "Copied" indicator, "Saved." text, legend action text, pool-yield "History" expand link | 8 |
| `warn` | `#f0a0a0` | Error/negative text — every error message, negative P/L, "unavailable" states, destructive-action confirm text | 40+ |
| `rangeRed` | `#ef4444` | Range bar's "out of range" fill only | 1 |
| `accentBright` | `#3ddc84` *(was `#4ade80` — see §8)* | Positive/gain — positive P/L, positive Run 7d, HOLD verdict badge, active-filter count badge | 8 |
| `card` | `#1a1f26` | Uniform table row background (replaces retired zebra banding) | 2 |
| `edgeNeutral` | `#8b949e` | Row's left accent edge when no value-health color applies | 3 |
| `expandedBg` | `#2b2415` | Expanded-row background and its right-column panel background | 6 |
| `expandedEdge` | `#d29922` | Expanded-row left edge accent; "auto · last observed" closing-value badge | 6 |

**Colors used outside MX_C, still MaxFi-scoped (`static/maxfi.js`):**

| Value | Where | Line(s) |
|---|---|---|
| `#1a1a3a` | Button background (every small/toolbar button — History, Refresh, Scan, Filters, Clear, asset-class select, wallet select) | 413, 743, 806, 1571→now 646a74 border kept bg, 2963, 2988, 3001, 3709 |
| `#1c4260` | Summary grid's header row / totals-row background | 3453, 3456, 3465 (post-edit line numbers) |
| `#facc15` (`MX_CRASH_BADGE_COLOR`) | Crash badge (amber), range bar's "near edge" state | 138, 305, 864 |
| `#c084fc` (`MX_PATH_DAMAGE_BADGE_COLOR`) | Path-damage badge (violet) | 313 |
| `#2b0d0d` / `#6b1a1a` / `#f87171` | `MaxFiErrorBoundary`'s error box (background / border / heading text) | 389-391 |

## 3. Type scale as it exists (post-fix — see §8 for what changed)

All sizes below are from `static/maxfi.js` unless marked `[style.css]`.
`fontVariantNumeric: 'tabular-nums'` (via the shared `mxTabularNums`/
`mxNumCell` objects, line ~3022) is MaxFi's numeric-alignment mechanism —
there is no separate monospace font switch for numbers (see §4).

| Size | Weight | Letter-spacing | Applies to |
|---|---|---|---|
| 11px | 600-700 | none | **Glyph-only spans exempted from the floor sweep** — single directional/marker characters (▾/▸ collapse chevrons, ●/○ note-dot, `*` footnote marker). Lines 1131, 2948, 3233, 3557, 3679. Not text content in the sentence/label/numeric/caption sense the floor rules define. |
| 12px | 700 | `0.08em` (added this commit) | All-caps captions: `mxVerdictBadge` badges (CLOSE/HOLD — line 283), "WHAT THE BADGES MEAN" legend header (3556), "CLOSED POSITIONS (N)" header, both states (3672, 3678). See §8's note on `mxVerdictBadge`'s imperfect fit (it also renders lowercase content). |
| 13px | 400-700 | none (0.04-0.06em on a few Title-Case headings) | Everything else — sentence text, error messages, field labels, button labels, numeric/tabular cell values, form inputs. This is now the effective floor for all non-caption, non-glyph text (raised from 11px/12px this commit — full list in §8). |
| 14px | 400-700 | none | Table `<th>`/`<td>` content (main open/closed tables), filter-toolbar inputs/selects |
| 15px | 700 | `0.04em` | Summary grid header cells (`summaryHeadCell`/`summaryHeadNumCell`, line ~3459) |
| 20px | 700 | none | `[style.css]` `.tv-page-title` |
| — | — | 0.06em | `[style.css]` `.tv-label` (11px, all-caps utility class — not used anywhere in maxfi.js; site-wide only) |

## 4. Font families

`templates/index.html`: `<link href="https://fonts.googleapis.com/css2?family=Fira+Code:wght@400;500&family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">`

- **Loaded:** Fira Code 400/500; Inter 400/500/600/700.
- **Actually used (`fontWeight` values found in code):** 400, 600, 700 only,
  in both `static/maxfi.js` (2× 400, 21× 600, 27× 700) and `static/style.css`
  (5× 600, 3× 700). **Weight 500 is loaded for both families but never
  referenced anywhere** — dead weight in the Google Fonts request, not a
  missing-weight bug (the reverse of what the task asked me to check for,
  worth noting since it's the same class of drift).
- **No weight used in code is missing from the load** — no defect there.
- **Fira Code vs Inter split:** `body` (`style.css` line 30) sets
  `font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI',
  system-ui, sans-serif` as the page default. `style.css`'s own `.tv-num`
  (line 101-103) and `.tv-table .num` (line 232) switch to
  `'Fira Code', monospace` — used by the *other* tabs (dashboard.js,
  archive.js, etc. via `className="tv-num"`).
  **`static/maxfi.js` never applies Fira Code at all.** It has no
  `fontFamily` declaration anywhere except one `fontFamily: 'inherit'`
  (the notes textarea, line ~1259, inheriting Inter from `body`).
  Its numeric columns get alignment from `fontVariantNumeric: 'tabular-nums'`
  (a number-spacing OpenType feature) rather than a monospace font switch.
  **This is a real, verifiable split, not assumed:** every other tab's
  numbers are Fira Code; every MaxFi number is Inter with tabular-nums.

## 5. Spacing, gap, border-radius

MaxFi has no shared spacing/radius token constants (no `MX_SPACE`/`MX_RADIUS`
equivalent to `MX_C`) — every `padding`/`gap`/`margin`/`borderRadius` is a
literal at its call site. Values actually seen, by frequency:

- **`borderRadius`:** `4px` (inputs, small buttons, badges — most common),
  `5px` (toolbar buttons, dropdowns), `6px` (panels, cards, popovers,
  table containers), `50%` — not used in maxfi.js (that's `style.css`'s
  `.tv-dot` only), `3px` (range bar).
- **`padding`:** most common are `'3px 6px'` (compact inputs),
  `'4px 8px'`/`'4px 10px'`/`'4px 12px'` (buttons/badges), `'5px 9px'`/
  `'6px 9px'` (table cells), `'8px 9px'`/`'10px 12px'` (panels/popovers),
  `'1px 6px'` (small pill badges).
- **`gap`:** `4px`, `6px`, `8px`, `10px`, `12px`, `16px` — no single
  dominant value; chosen per-layout.
- No 2px/8px consistent base grid — values are picked ad hoc per
  component, not derived from a shared scale.

## 6. Interaction/empty/error states, quoted verbatim

MaxFi has **no CSS `:hover`/`:focus`/`:active`/`:disabled` rules** — every
element is an inline-styled `React.createElement` call with no `className`,
so pseudo-classes can't apply. States are expressed in JS instead:

- **Hover** (table rows only): `const rowBg = hoveredRowKey === rowKey ? MX_C.hover : MX_C.card;`
  (line ~3199, mirrored for the closed table at ~3642), driven by
  `onMouseEnter: () => setHoveredRowKey(rowKey), onMouseLeave: () => setHoveredRowKey(null)`.
  The file's own comment (line 1958-1960, unchanged by this commit):
  *"React inline styles can't express :hover and this file has no
  className mechanism for a real :hover rule."*
- **Focus:** none existed before this commit (verified — zero `:focus`
  occurrences in `maxfi.js`, and every input/select/textarea in it is
  unstyled-by-class). Added this commit via `static/style.css` (see §8.4).
- **Disabled:** `cursor: disabled ? 'default' : 'pointer', opacity: disabled ? 0.6 : 1`
  (`mxSmallBtnStyle`, line ~403-409) plus ad-hoc identical treatment on the
  header's Refresh/Scan buttons (line ~2983, ~2996):
  `opacity: (anyBusy || scanning || !selectedWallet) ? 0.6 : 1`.
- **Loading:** text substitution, not a spinner in most places — e.g.
  `anyBusy ? 'Loading…' : 'Refresh'`, `scanning ? 'Scanning…' : 'Scan'`,
  `'Loading wallets…'`, `'Loading valuation…'`. `.spin` (`style.css` line
  242-243, `@keyframes spin` + `animation: spin 1s linear infinite`) exists
  site-wide but is not invoked anywhere in `maxfi.js` — MaxFi's own busy
  states are text-only, never the spin animation.
- **Empty-state**, quoted verbatim:
  - `'No open MaxFi positions found.'` (line ~3803, rows.length === 0 branch)
  - `'No claims recorded'` (MaxFiClaimsPanel, claims.length === 0)
  - `'No wallets are flagged for MaxFi. Go to Settings → Wallets and enable the MaxFi toggle on a wallet.'`
- **Error-state**, quoted verbatim:
  - `MaxFiErrorBoundary`'s dedicated box (line ~389-394):
    `style: { background: '#2b0d0d', border: '1px solid #6b1a1a', ... }`,
    heading `'MaxFi view failed'` in `color: '#f87171'`, body:
    `'This panel hit an error and was contained — the rest of the page keeps working. ' + msg`
  - Every per-field error path renders its message in `MX_C.warn`
    (`#f0a0a0`) — e.g. `'session expired'`, `'Enter a number greater than 0.'`,
    `'Enter a valid number for the basis.'`.
- **`[style.css]`** interaction states (site-wide, not MaxFi — quoted for
  completeness since style.css is in scope):
  - `.tv-btn:hover { background: var(--panel2); }`
  - `.tv-btn.primary:hover { opacity: 0.9; }`
  - `.tv-btn.danger:hover { background: var(--fail-soft); }`
  - `.tv-nav-item:hover { background: var(--panel2); }`
  - `.tv-subnav-item:hover { background: var(--panel3); }`
  - `.tv-table tbody tr:hover { background: var(--panel2); }`
  - `.tv-input:focus { border-color: var(--accent); }`
  - `.tv-select:focus { border-color: var(--accent); }`
  - `.login-input:focus { border-color: var(--accent); outline: none; }`
  - `.login-btn:hover { opacity: 0.9; }`
  - `.login-error { background: var(--fail-soft); border: 1px solid var(--fail); color: var(--fail); ... }` (error-state block, not a pseudo-class)
  - No `:active`, `:disabled`, `:focus-visible`, `aria-busy`, or other
    empty/error pseudo-state rules exist in `style.css`.

## 7. Responsive breakpoints

**None.** Zero `@media` queries anywhere in `style.css` (confirmed — full
file read) or `maxfi.js`. The file's own comment (line ~1761-1762,
unchanged): *"there are no media queries anywhere in this file and none
are added here - flexWrap is the only responsive mechanism available."*
`MaxFiExpandedPanel` (line ~1777) uses `flexWrap: 'wrap'` so its two
columns stack on a narrow viewport — that is the entire responsive
strategy for this tab.

## 8. Changes applied this commit

### 8.1 Color — contrast table (computed via script, WCAG 2.1; 4.5:1 text / 3:1 non-text)

Every `MX_C` text color against every real background it's rendered on
(`bg #12161c`, `panel #0d1117`, `card #1a1f26`, `hover #4e5258`,
`head #1b2129`, `expandedBg #2b2415`, plus the two non-MX_C backgrounds
`#1a1a3a` and `#1c4260`), computed with a Python script (not by hand —
`luminance()`/`contrast()` per the WCAG 2.1 relative-luminance formula):

| Token | Value | Worst-case background | Worst ratio | AA (4.5:1) |
|---|---|---|---|---|
| `primary` | `#e6edf3` | `summary_1c4260` | 8.90:1 | PASS |
| `secondary` (pre-fix `#c9d1d9`) | `#c9d1d9` | `summary_1c4260` | 6.81:1 | **PASS everywhere already** |
| `warn` | `#f0a0a0` | `hover #4e5258` | 3.83:1 | **FAIL** (not one of the 3 authorized target roles — see §9) |
| `accent` | `#7ee2a8` | `hover #4e5258` | 4.99:1 | PASS |
| `accentBright` (pre-fix `#4ade80`) | `#4ade80` | `hover #4e5258` | 4.51:1 | PASS (barely) |
| `expandedEdge` | `#d29922` | `hover #4e5258` | 3.11:1 | **FAIL** (not a target role — §9) |
| `edgeNeutral` (as text) | `#8b949e` | `hover #4e5258` | 2.56:1 | **FAIL** (not a target role — §9) |
| `#facc15` (crash badge) | — | `hover #4e5258` | 5.13:1 | PASS |
| `#c084fc` (path-damage badge) | — | `hover #4e5258` | 2.97:1 | **FAIL** (not a target role — §9) |
| `#f87171` (error heading) | — | `hover #4e5258` | 2.84:1 | **FAIL** (not a target role — §9; also never actually rendered on `hover` bg in practice — it's fixed to the error box's own `#2b0d0d`) |

Border tokens (translucent white composited over each background, WCAG
1.4.11 non-text 3:1 minimum):

| Token | Composited (on `bg #12161c`) | Ratio | 3:1 |
|---|---|---|---|
| `border` `rgba(255,255,255,0.25)` | `#4d5055` | 2.24:1 | **FAIL everywhere** (every background checked) |
| `sep` `rgba(255,255,255,0.32)` | `#5e6165` | 2.92:1 | **FAIL everywhere** |
| `summaryEdge` `rgba(255,255,255,0.65)` | `#acadb0` | 8.09:1 | PASS everywhere |

Task's three target colors, computed independently (not the task's own
stated numbers — my own script):

| Target | Value | on `bg #12161c` | on `card #1a1f26` |
|---|---|---|---|
| Secondary/muted text | `#b3bdcb` | 9.56:1 | 8.72:1 |
| Positive/gain | `#3ddc84` | 10.17:1 | 9.28:1 |
| Control edges | `#646a74` | 3.33:1 | 3.04:1 |

**`accent` vs `accentBright` separation check** (task's own trigger: "if
within 1 point of each other, too close"): pre-fix, `accent` (#7ee2a8) vs
`accentBright` (#4ade80) differed by **1.11 points on `bg`, 1.01 points on
`card`** (`card` is the actual table-row background used almost
everywhere). Both are right at the boundary of "within 1 point" — 1.01 is
technically 0.01 over the literal threshold, which I read as effectively a
pass of the "too close" test given the two are also perceptually similar
(both light greens). Flagging as-is rather than rounding it away.

### 8.2 Color — what was applied and why

- `MX_C.secondary`: `#c9d1d9` → `#b3bdcb` (`static/maxfi.js` line 20).
  **Not a contrast failure** — the old value passed AA everywhere
  (6.81-12.26:1). Applied anyway because it plays the secondary/muted-text
  role the task named, per the task's own "or whichever keys play these
  roles" instruction (not conditioned on failing).
- `MX_C.accentBright`: `#4ade80` → `#3ddc84` (`static/maxfi.js` line 40).
  Same basis — plays the positive/gain role; not conditioned on the
  accent/accentBright separation check landing exactly over the 1-point
  line.
- Control-edge borders: **not an `MX_C` key change** (the task says "do
  not rename MX_C keys," and `MX_C.border`/`MX_C.sep` are each shared by
  many non-control uses — card perimeters, buttons, table cell borders,
  summary separators — that this task does not authorize touching).
  Instead, `#646a74` was applied as a literal border color at the 7
  distinct style definitions that actually back a real `<input>`,
  `<select>`, or `<textarea>` DOM element:
  1. `static/maxfi.js` ~557 — `MaxFiBasisCell`'s basis-entry `<input>`
  2. ~1266 — `MaxFiNotesEditor`'s `<textarea>`
  3. ~1480 — `MaxFiClaimsPanel`'s shared `inputStyle` (date + proceeds inputs)
  4. ~1571 — `MaxFiAssetClassEditor`'s `<select>`
  5. ~1758 — `MaxFiClosingValueEditor`'s `<input>`
  6. ~2963 — the header's wallet `<select>`
  7. ~3705 — `mxFilterInputStyle` (Pool text input, 10 numeric min/max
     inputs, Range `<select>`, Value-vs-basis `<select>` — all share this
     one style object)

  Buttons (which also use `MX_C.border` for their outline) were left
  untouched — the revised task's own step 3 lists only "control edges" and
  no longer explicitly names "outlined buttons" the way the original draft
  did; treating buttons as out of scope avoids restyling something not
  clearly named.

### 8.3 Type size floor — every raise, old → new, selector/content

76 line-level edits (`static/maxfi.js`), applied via a line-indexed script
(verified against the file's own line numbers, not blind global
find/replace, given how many identical `fontSize: 11`/`fontSize: 12`
fragments recur for different content):

**`11px → 13px`** (31 sites — labels, sentences, error messages, button
labels, numeric annotations; none of these are exclusively all-caps
caption content, so the stricter 13px floor applies): lines 267 (`mxBadge`
— shared by "NO BASIS"/"STALE"/"UNTRACKED" *and* lowercase
"inherited"/"auto-split"/"needs review"; raised to the stricter floor
rather than split, see the caveat below), 406 (`mxSmallBtnStyle` — every
button label), 464, 531, 557, 559, 609, 616, 626, 628, 777, 1123, 1134,
1269, 1271, 1466, 1498, 1502, 1575, 1577, 1578, 1636, 1739, 1755, 3213,
3225, 3356, 3420, 3545, 3629, 3649.

**`12px → 13px`** (39 sites — sentence text, form inputs, table cells,
numeric/tabular values): lines 548, 689, 704, 717, 719, 736, 746, 749,
769, 772, 803, 806, 845, 1257, 1440, 1442, 1444, 1452, 1471, 1564, 1690,
1692, 1733, 1741, 1749, 1876, 2956, 2981, 2994, 3011, 3014, 3017, 3341,
3352, 3369, 3397, 3402, 3436, 3691.

**`11px → 12px` + `letterSpacing: '0.08em'` added** (2 sites — genuine
all-caps-only captions): line 1475 (`'CLAIMS'` heading) and line 1773
(`MaxFiExpandedPanel`'s `labeledBlock` label — renders `'CLOSING VALUE'`,
`'ASSET CLASS'`, `'NOTES'`, `'OPEN DATE'`, all-caps, every call site).

**`12px` unchanged, `letterSpacing: '0.08em'` added** (4 sites — already
at the caption floor, just missing the required letter-spacing): line 283
(`mxVerdictBadge` — see caveat below), 3556 (`'WHAT THE BADGES MEAN'`),
3672 and 3678 (`'CLOSED POSITIONS (N)'`, both the zero-state and toggle
variants).

**Exempted — reviewed, deliberately not raised** (5 sites): single
decorative/directional glyphs, not text content under any of the task's
three floor categories (sentence/label, numeric/tabular, all-caps
caption): lines 1131 (●/○ note-dot), 2948/3557/3679 (▾/▸ collapse
chevrons), 3233 (`*` footnote marker — the actual explanatory text lives
in that span's `title` tooltip, not its visible content).

**Two caveats, stated plainly:**
- `mxBadge` (line 267→13px) and `mxVerdictBadge` (line 283→12px+letter-spacing)
  are each a single shared component rendering both all-caps and
  non-caption text through one hardcoded style. Splitting them by content
  type would be a structural change this task doesn't authorize ("do not
  refactor component structure"), so each got the floor that's safe for
  its *worst-fitting* content: `mxBadge` raised to the stricter 13px floor
  (satisfies both sub-rules since 13 ≥ 12); `mxVerdictBadge` kept at
  12px+letter-spacing because its dominant, most-frequent use (CLOSE/HOLD)
  is a genuine all-caps caption, even though it also renders lowercase
  content (`'path -N%'`) and arbitrary-case wallet labels that don't
  perfectly fit the caption category. Flagged, not silently resolved.

### 8.4 Fee-basis toggle — skipped per instruction

No Claimed/Locked control exists anywhere in this repository. Nothing was
recolored to compensate. Per the revised task's step 5: the real filter
toolbar's **active-filter indicator uses `MX_C.accentBright`**
(`static/maxfi.js` ~3735 — the `(N)` count badge shown next to the
"Filters" button once any filter is applied; also `~3777`, the
value-health facet count). After this commit, `accentBright` is `#3ddc84`
(was `#4ade80`). There is no separate "selected" visual state on the
Range/Value-vs-basis `<select>` elements themselves — they're plain native
dropdowns with no custom active styling; the count badge and the
conditionally-rendered "Clear" button are the toolbar's only "something is
active" signals.

### 8.5 Focus rings

Added to `static/style.css` (new rule, ~17 lines, after the SPIN ANIMATION
section, before LOGIN PAGE):

```css
.tv-content--wide button:focus-visible,
.tv-content--wide input:focus-visible,
.tv-content--wide select:focus-visible,
.tv-content--wide textarea:focus-visible {
  outline: 2px solid #4bb5a8;
  outline-offset: 2px;
}
```

`maxfi.js` has no `className` on any element (see §1) — `:focus-visible`
cannot be expressed inline, and adding classNames to every focusable
element would be a structural change this task doesn't authorize. Instead
this targets `.tv-content--wide`, a class `static/app.js` (~line 182)
already applies to the content wrapper **only when the MaxFi tab is
active** (confirmed by reading `app.js`, not assumed) — so the rule reaches
every MaxFi button/input/select/textarea without becoming a site-wide
change and without touching any component's structure. Nothing existing
was removed (there was nothing to remove — zero pre-existing `:focus`
rules on any MaxFi element), and no `outline: none` was added anywhere.

## 9. Design smells and other issues found — NOT fixed (out of scope)

- **Three independent, non-communicating color systems** in one app
  (`style.css`'s `:root` tokens, `maxfi.js`'s `MX_C`, `ai.js`'s own inline
  hexes) — see §1. A change to "the palette" has to be made in up to three
  places today.
- **`style.css`'s `.tv-input`, `.tv-select`, and `.login-input` set
  `outline: none` unconditionally** (site-wide, not MaxFi — lines ~201,
  213, 273), suppressing the native focus ring on every input styled with
  those classes anywhere else in the app. Not touched — out of this
  commit's MaxFi-only scope, and removing it would be a real behavior
  change on tabs this task never asked me to look at. This is the one
  `outline: none`/`outline: 0` hit the quality-check grep will still show;
  see §10.
- **Several MX_C colors fail WCAG contrast against `MX_C.hover`
  (`#4e5258`)** specifically — `warn` (3.83:1), `expandedEdge` (3.11:1),
  `edgeNeutral` (2.56:1), `#c084fc` path-damage badge (2.97:1), `#f87171`
  error heading (2.84:1) — none of these are one of the task's three
  authorized target roles (secondary text / positive-gain / control
  edges), so none were changed. `MX_C.hover` itself (`#4e5258`) is
  arguably too light relative to the text colors it's meant to sit
  behind — worth a dedicated pass.
- **`mxBadge` and `mxVerdictBadge` each serve visually and semantically
  different content (all-caps status words vs. lowercase phrases vs.
  numeric-badge annotations) through one shared style** — see §8.3's
  caveat. A real fix would split these by content type, which is a
  structural change outside this task.
- **`MX_C.zebra` (`#262a30`) is defined but never read anywhere** (the
  object's own comment admits this, line 23-27) — dead code in the design
  token object.
- **Google Fonts weight 500 (both families) is loaded but never used**
  anywhere in the codebase (§4) — free to drop from the `<link>` if
  confirmed unused elsewhere too.
- **Two authoring styles for React components coexist**: `maxfi.js` (and
  a few others) use raw `React.createElement` with no JSX and no
  className; `dashboard.js`/`archive.js`/`actionplan.js` use JSX with
  `className`. Not a bug, but a real inconsistency for anyone maintaining
  both.

## 10. Quality check output

See the task summary in chat for the full output of all four checks
(JS parse, CSS brace balance, `outline: none`/`outline: 0` grep, app-boot
HTTP check).

## Addendum — Community Position Ledger reference audit (Sep 22)

Source: community-built "Position Ledger" site (Robinhood Chain), reviewed as a
model for MaxFi position views. Positions sampled: WETH/BONER #963655,
USDG/RBLX #1261881. Catalog only — no dashboard changes until the ledger
initiative ends.

### Do NOT copy
- "Principal" = Value − Deposit (unrealized mark-to-market), shown green and
  summed into "Total claimed — fees plus principal." Verified exactly on both
  positions ($377.60 − $301.37 = $76.23; $387.91 − $379.55 = $8.36), with zero
  sells/withdrawals. Realized and unrealized must never share a "claimed" label.
- The "% of deposit" headline mixes realized fees with unrealized value.
- No HODL benchmark: value-over-deposit doesn't show whether LPing beat holding.

### Defects observed (avoid in our build)
- Price precision: 2-dp prices on microcaps ("$0.07" BONER; 1,201 × $0.07 =
  $84.07 but row shows $84.57). Use significant-figure formatting.
- Claim count unit mismatch: header counts claim events (5 / 3), tab counts
  token rows (10 / 6). Pick one unit and label it.
- Trading Result "$0.00 — sold above claim value" in green with 0 sells
  (template branch bug); the other position correctly says "nothing sold yet".
- Fees Claimed and Fees Locked render as two identical cards when nothing is
  sold. Collapse when equal, or use a single Fee Basis toggle (Claimed/Locked).
- "Pending, gross" wraps alone onto a second row (grid width, not grouping).
- Range bar has no proximity/out-of-range state (RBLX at 49.954 vs 50.009 upper).
- Inconsistent decimals on amounts; text column (TOKEN) right-aligned.
- [Inference, from pixels] Secondary text, column headers, footnotes and
  inactive nav are ~11px muted gray; separators look below 0.25 opacity / 2px.
  All fail our visibility standards.

### Borrow
- Harvested split: to wallet / compounded / total / value at claim
  (maps to ledger compounded0/1 exposure).
- Per-claim table: date, token, net amount, price at claim, value, destination
  (front end for maxfi_ledger_claims).
- "Pending, gross — not counted as profit" as an explicit accounting stance.
- Semantics footnotes: net of 15% performance fee; price at claim, not today's.
- Position lineage across rebalances ("opened 09-02 · 3 rebalances" on a
  tokenId the ledger first saw Sep 21). Our per-tokenId key sees only the
  current segment; a position view must chain segments via SnuggleRebalanced.

### Our design decision of record
- Unrealized value change gets its own clearly labeled line, separate from
  realized fees; HODL comparison is a later addition on that line.

### QA oracle
- The site's claim values are net-of-fee at claim price, the same semantics as
  maxfi_ledger_claims.claimed_usd. It holds all of Glenn's positions, so any
  can be used to cross-check ledger rows once Robinhood converges (tolerance
  max($1, 1%)). Cover all rebalance segments, not just the current tokenId.
  Runs after the owed checks on ids 112, 114 and 113.

## Status of record (Sep 24)

- Deferral lifted: ledger work is parked (emissions complete at 7a935bc), so the
  addendum's "no dashboard changes until the ledger initiative ends" is superseded.
  The UI redesign is the active workstream: MaxFi first, then the Trends scanner
  (static/trends.js) and other pages.
- Secondary text stays #c9d1d9 (10.83:1). Any #b3bdcb target earlier in this file
  is superseded.
- The recovered Sep 19 WIP landed on main at 99943c0 (cherry-pick of a2ebb32:
  13px text floor, contrast fixes, MaxFi-only focus rings). Branch
  design-audit/maxfi-0919 is dead; never reuse it.
- The Sep 22 addendum above was written in a separate design chat and first
  entered this file on Sep 24.
- Design System of record: the "Dashboard Design" artifact (Claude Design,
  Sep 19). Its tokens.json is the token contract.

## Redesign rulings (Sep 24)

1. Tokens: two-tier CSS custom properties in static/style.css. --ds-* primitives
   come from the Design System's tokens.json; page role tokens (--mx-* for MaxFi,
   later --trends-*) point at them. MX_C becomes an alias map of var(--mx-*)
   strings, so call sites don't change. No JS token accessor until a canvas or
   chart consumer migrates. The existing navy :root tokens stay untouched until
   a page is deliberately moved.
2. Landing split: a plumbing commit first (--mx-* set to current values, zero
   visual change), then a style.css-only retune pointing --mx-* at --ds-*.
   Both are review-gated.
3. This file is the redesign's doc of record. All additions are append-only.
4. Workflow: Claude Design handles visuals and token edits. The Project chat
   reads the approved artifact by link and writes specs into instruction blocks
   using token names and px values, never screenshots. Claude Code only
   implements. Every retune gate includes a tokens.json-vs-style.css value diff
   and a WCAG contrast table checked against the visibility standards.
5. House rules win where they conflict with the Design System: money columns are
   never right-aligned, and Pool-cell badge colors (crash amber, path-damage
   violet, range red, verdict styles) stay distinct as role tokens despite the
   Design System's single warning hue.
6. MaxFi gets both a sortable table and a card view, built on one shared row
   model: the same filtered and sorted rows, the same badge helpers, mxSortValue
   for card sorting, and MaxFiExpandedPanel for detail. Default view,
   persistence, closed-position cards and expand behavior are decided in the
   card view's own design pass.
7. Sequence: L3 step-1 read-only, L4a plumbing, L4b retune, L5 card view,
   L6 trends.js (the Trends caching root cause is owed there), then other pages.
8. One venue: the Project chat runs this workstream; the earlier Claude Design
   chat stands down.
