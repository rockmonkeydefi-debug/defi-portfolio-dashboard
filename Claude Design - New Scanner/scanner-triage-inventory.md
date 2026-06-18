# Scanner Triage v3 — Field & Component Inventory
# Engineering handoff spec. Every data field, prop, and derived value listed per view.

---

## Shared primitives

### TFBadge
| Prop | Type | Notes |
|------|------|-------|
| tf | string | '1W' \| '1D' \| '12H' \| '4H' \| '1H' \| '15M' \| '5M' |
| sm | boolean | Small variant (9px vs 11px) |

Color map (bg / fg):
- 1W → #8b7ad6 / #fff
- 1D → #e8853a / #fff
- 12H → #2180c8 / #fff
- 4H → #2fb4e8 / #0a2a47
- 1H → #4fdd8e / #0a2a47
- 15M → #3dc87a / #0a2a47
- 5M → #b8f5d0 / #0a2a47

### TFPairBadge
| Prop | Type |
|------|------|
| htf | string (TF) |
| ltf | string (TF) |
| sm | boolean |

Renders: `<TFBadge htf> → <TFBadge ltf>`

### DirBadge
| Prop | Type | Values |
|------|------|--------|
| dir | string | 'LONG' \| 'SHORT' |

Green (▲ LONG) / Red (▼ SHORT).

### GradeChip
| Prop | Type | Notes |
|------|------|-------|
| grade | string | 'A' \| 'B' \| 'C' \| 'D' |
| lg | boolean | Large variant |

Color map:
- A → green (#4fdd8e)
- B → gold (#ffb52e)
- C → yellow (#ffd23f)
- D → red (#ff8a8a)

### FreshnessPill
| Prop | Type | Notes |
|------|------|-------|
| mins | number | Minutes since triggered |

Color: <30m green · 30–120m amber · >120m red. Displays "Xm ago" or "Xh Ym ago".

### TradeTrack
Visual stop→entry→target price track.
| Prop | Type |
|------|------|
| stop | number |
| entry | number (zone mid) |
| targets | {price: number, rr: number}[] |

---

## Data shape — Setup object

Every ACT TODAY card and the Risk modal consumes a `Setup`:

```ts
type Setup = {
  id:           string          // unique key
  ticker:       string          // e.g. 'BTC'
  direction:    'LONG' | 'SHORT'
  htf:          string          // higher timeframe, e.g. '1D'
  ltf:          string          // lower timeframe, e.g. '4H'
  tier:         'swing' | 'intra' | 'scalp'
  grade:        'A' | 'B' | 'C' | 'D'  // from Validator
  entryLow:     number          // entry zone bottom
  entryHigh:    number          // entry zone top
  stop:         number          // structural stop price
  targets:      { price: number; rr: number }[]  // 1–2 targets
  triggeredMins: number         // minutes since setup triggered
  rationale:    string          // one line, ~100 chars max
}
```

---

## Data shape — Watch item

```ts
type WatchItem = {
  ticker:     string
  state:      'forming' | 'tapped' | 'watching' | 'cooling'
  htf:        string
  ltf:        string
  waitingFor: string   // one-line description of what's missing
  eta:        string   // display string e.g. 'possibly today' | 'next week' | '—'
}
```

State dot colors:
- forming  → #ffb52e (amber)
- tapped   → #2fb4e8 (cyan)
- watching → #7b9cc4 (muted blue)
- cooling  → #ff8a8a (red)

---

## 5A · ACT TODAY card — ActTodayCard

### Props
| Prop | Type | Notes |
|------|------|-------|
| setup | Setup | Full setup object |
| rank | 0 \| 1 \| 2 | 0=gold, 1=silver, 2=bronze left border |
| onSizeThis | (setup: Setup) => void | Opens Risk modal |

### Fields displayed
| Field | Source | Display |
|-------|--------|---------|
| Rank badge | rank prop | #1 / #2 / #3, colored |
| Ticker | setup.ticker | Large bold |
| Direction | setup.direction | DirBadge |
| TF pair | setup.htf + setup.ltf | TFPairBadge |
| Grade | setup.grade | GradeChip |
| Freshness | setup.triggeredMins | FreshnessPill |
| Rationale | setup.rationale | Italicized one-liner |
| Entry zone | setup.entryLow – setup.entryHigh | Gold, tabular nums |
| Stop | setup.stop | Red, tabular nums |
| Target 1 | setup.targets[0].price | Green + R:R |
| Target 2 | setup.targets[1]?.price | Green + R:R (if present) |
| Trade track | stop / entry mid / targets | Visual price bar |

### Actions
- "Open chart ↗" — ghost button (link to charting tool)
- "Validate setup →" — ghost button (opens Validator for this ticker)
- "Size this trade →" — primary CTA, calls onSizeThis(setup)

---

## 5A · ON WATCH row — WatchRow

### Props
| Prop | Type |
|------|------|
| item | WatchItem |
| last | boolean (no bottom border on last row) |

### Columns
| Column | Source | Width |
|--------|--------|-------|
| Ticker | item.ticker | 76px |
| State | item.state (dot + label) | 90px |
| Pair | item.htf + item.ltf | 116px |
| Waiting for | item.waitingFor | 1fr |
| ETA | item.eta | 100px |

---

## 5A · Tier toggle — TriageBar

### State
| State | Type | Default |
|-------|------|---------|
| screenTime | boolean | false |

### Behavior
- Off → shows swing setups only (1D/4H, 1W/1D)
- On → also shows intra/scalp setups (4H/15M, 1H/5M). ACT TODAY still caps at 3.
- When a ticker moves from ON WATCH to ACT TODAY (intra tier triggers), it is removed from the watch list.

---

## 5B · Empty state — ActTodayEmpty

No props. Displayed when `actToday.length === 0`.

Fields:
- Headline: "Nothing to act on today"
- Body: affirming copy (no trade = valid position)
- Next scan window: string (from scan schedule config)

---

## 5C · Risk / Position-Size modal — RiskModal

### Props
| Prop | Type |
|------|------|
| setup | Setup |
| onClose | () => void |

### User inputs
| Field | Type | Notes |
|-------|------|-------|
| accountSize | number | $ value, user-editable |
| stop (forward mode) | number | Pre-filled from setup.stop, adjustable |
| desiredRR (reverse mode) | number | Step 0.5, drives stop calculation |

### Derived / read-only
| Field | Formula | Display |
|-------|---------|---------|
| riskPct | GRADE_PCT[setup.grade] | Grade A=1.0%, B=0.75%, C=0.5%, D=0.25% |
| dollarRisk | accountSize × riskPct / 100 | $ |
| entry (mid) | (setup.entryLow + setup.entryHigh) / 2 | $ |
| effectiveStop (reverse) | entry − (T1 − entry) / desiredRR | $ |
| stopDist | abs(entry − effectiveStop) | internal |
| positionSize | dollarRisk / stopDist | units of ticker |
| R:R to T1 | (T1 − entry) / stopDist | × multiplier |
| R:R to T2 | (T2 − entry) / stopDist | × multiplier (if T2 exists) |
| P&L to T1 | positionSize × (T1 − entry) | $ |

### Modes
- **Forward**: user sets stop → position size calculated
- **Reverse**: user sets desired R:R → stop placement calculated

### Actions
- "Cancel" → onClose()
- "Validate first →" → opens Validator for this setup
- "Log this trade →" → saves to Journal with pre-filled fields

---

## 5D · Telegram Alerts settings — TradingSettingsTelegram

### State
| Field | Type | Default |
|-------|------|---------|
| enabled | boolean | true |
| botToken | string | user input |
| chatId | string | user input |
| schedule.morning | boolean | true |
| schedule.morningTime | string (HH:MM) | '07:00' |
| schedule.lunch | boolean | true |
| schedule.lunchTime | string (HH:MM) | '12:30' |
| schedule.evening | boolean | true |
| schedule.eveningTime | string (HH:MM) | '20:00' |

### Digest message format (plain text)
```
📊 {Window} · {DD Mon YYYY}

⚡ ACT TODAY ({n})

{rank}. {TICKER} · {DIR} · {HTF}→{LTF} · {Grade}
   Entry: {entryLow}–{entryHigh}
   Stop: {stop}
   T1: {t1.price} ({t1.rr}R)[ · T2: {t2.price} ({t2.rr}R)]
   "{rationale}"

👁 ON WATCH ({n})
• {TICKER}  — {waitingFor}
...

{totalScanned} scanned · nothing else actionable.
```

Rules:
- Plain text only — no markdown, no images, no links
- One message per scheduled window
- Sent only if enabled = true AND the window toggle is on
- If ACT TODAY is empty, sends the empty-state message instead

---

## Grade → Risk % map (shared across Validator + Risk modal + Settings)

| Grade | Risk % |
|-------|--------|
| A | 1.0% |
| B | 0.75% |
| C | 0.5% |
| D | 0.25% |

This is configured in Trading Settings → Validator section and must be the single source of truth.

---

## API / data requirements

- `GET /scan/results` → `{ setups: Setup[], watchItems: WatchItem[], scannedAt: ISO8601, totalScanned: number }`
- `POST /scan/run` → triggers rescan, returns same shape
- `GET /settings/telegram` → returns Telegram config
- `PUT /settings/telegram` → saves Telegram config
- `POST /telegram/test` → sends a test message using current config
- `GET /settings/validator/grades` → returns grade→riskPct map
