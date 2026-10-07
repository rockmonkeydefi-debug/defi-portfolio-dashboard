/* ===== PERPS PAGE — Landings 3a and 3b (HANDOFF_spot_perps_rebuild.md 3.2, 3.4, 11) =====
   The Perps menu item (activeTab 'perps', static/app.js). Tabs: Open
   positions · History · Transactions (synced-fills status and manual perp
   trades, which moved here from the retired Trade Log in Landing 3b).

   One read feeds the page: GET /api/trading/trades. Perp trades are built
   from the stored Hyperliquid and TxFlow fills plus manual perp trades from
   the trade log. An open synced trade carries "live" (the venue's view of
   its position: current size, mark, leverage, liquidation, venue stop and
   every take-profit); "untracked_positions" are live venue positions with no
   trade yet (fills not synced, or opened before the sync window); "sync" is
   the fill-sync status per venue. Every number arrives as a string and is
   parsed only for display.

   Writes:
     synced trades: PUT /api/trading/trades/<trade_id>/annotation
     manual trades: POST /api/spot/trade-log (perp only, with leverage; a
                    finished trade in one step), PUT / DELETE /api/spot/trade-log/<id>

   Rulings (section 11): Open risk at stops = entry to the effective stop x
   current size, a stop at or past entry counting 0. Target = the nearest
   take-profit with R = |tp - entry| / |entry - stop|, "+N more" with all of
   them on hover; a take-profit on the losing side of entry, or a stop at or
   past entry, shows the price without an R chip. Hide values masks size,
   money and funding; prices, leverage and R stay visible.

   Landing 4 (section 14): a synced trade's "open_snapshot" holds the noodle
   at its open (price vs the noodle on 15m to 1W, from candles that closed
   before the first fill) and its leverage the first time it was seen open.
   Expanded rows show it as "At open"; a closed trade's Lev comes from it.

   Landing 5 (section 16): "planned_target" is the first take-profit set for
   a trade (stored venue orders, else the take-profit first seen on the open
   position, else a manual trade's logged target). History shows "plan NR"
   under R and a "Planned target" fact; Open details show it only once the
   live target has moved away from it.

   Landing 6 (section 18): a synced trade's stop is the stop in force 10
   minutes after entry (a stop corrected right after opening is the plan);
   "stop_correction" shows the stop placed at entry and the correction.

   Landing 7 (sections 18 and 19): a closed synced trade's "after_exit"
   holds the noodle at the close ("At exit"), the best and worst prices
   while it was open (R by price, against the stop R uses) and "had you
   held the plan" (that stop and the first planned take-profit, followed
   from the open to 14 days after the exit). History details show all
   three; a tally line above the History table counts the verdicts.

   Landing 8c-1 (HANDOFF_advisor_v1.md section 25): the advisor rules. Two
   more reads feed the page, kept apart from the trades read so a failure
   there never blanks the page: GET /api/trading/advisor/perps (verdicts and
   evidence per perp trade) and GET /api/trading/trade-tags. Expanded Open
   and History rows show a "Rule check" block and the setup / POI tag
   controls (PUT /api/trading/trades/<trade_id>/tags); History gets a tally
   block above the table. The components live in static/perpsrules.js. The
   rules refetch after any save on a row and on Reload, not on the cold-cache
   retries; a tag save refetches them too, since E2 and E3 read the tags.

   Landing 8c-2 (Rules v2): History details on a revised exit get "Why did
   you exit early?" (PerpsExitReason in static/perpsrules.js), saved with
   the row's annotation saver; X1 reads it instead of the trade notes.

   Landing 8c-3 (HANDOFF_advisor_v1.md section 31): a fourth tab, Rules
   (PerpsRulesTab in static/perpsrules.js), changes a rule between enforced
   and tracking and enters dated capital for R2. It reads its own settings
   (GET /api/trading/advisor/perps/settings); after a save the page re-reads
   the rule check (loadRules), so Rule check blocks and the tally follow.

   Rows use the shared stacked-card grid (.spot-grid-row and friends in
   static/style.css), so the page never scrolls sideways: a table at 1250px
   and wider, stacked cards below. Every top-level name here starts with prp /
   PRP / Perps: Babel turns top-level declarations into shared globals. */
const { useState: usePRPState, useEffect: usePRPEffect, useRef: usePRPRef } = React;

const PRP_COLD_RETRY_MS = 15000;     // re-read while open synced trades still lack live data (cold caches)
const PRP_COLD_RETRY_MAX = 4;        // at most this many such re-reads per mount
const PRP_SAVED_MS = 3000;           // how long "Saved" stays
const PRP_NOTE_MAX = 2000;           // TRADE_NOTE_MAX on the server
const PRP_LINE = '2px solid rgba(255,255,255,0.25)';
const PRP_HEAD_LINE = '2px solid rgba(255,255,255,0.35)';
const PRP_MONO = "'Fira Code', monospace";
const PRP_SMALL_BTN = { fontSize: 13, padding: '4px 12px', minHeight: 32 };
// tv-btn has no disabled style of its own: a disabled button is dimmed so it doesn't look clickable.
function prpBtn(disabled, base) {
  return Object.assign({}, base || {}, disabled ? { opacity: 0.5, cursor: 'default' } : {});
}
const PRP_OPEN_GRID = 'minmax(150px,1.3fr) minmax(52px,0.5fr) minmax(48px,0.45fr) minmax(92px,0.8fr) '
  + 'repeat(4,minmax(80px,0.9fr)) minmax(120px,1.2fr) minmax(90px,1fr) minmax(76px,0.8fr) minmax(100px,1fr)';
const PRP_HIST_GRID = 'minmax(150px,1.3fr) minmax(52px,0.5fr) minmax(48px,0.45fr) minmax(120px,1.1fr) '
  + 'minmax(170px,1.5fr) minmax(84px,0.8fr) minmax(90px,0.9fr) minmax(70px,0.7fr) minmax(100px,1fr) minmax(100px,1fr)';
const PRP_TABS = [{ id: 'open', label: 'Open positions' }, { id: 'history', label: 'History' }, { id: 'transactions', label: 'Transactions' },
                  { id: 'rules', label: 'Rules' }];

const PRP_STOP_SOURCE = {
  manual: 'Entered here',
  hl_order: 'Hyperliquid stop order',
  txflow_order: 'TxFlow stop order',
  txflow_tpsl: 'TxFlow position stop',
  manual_log: 'Logged with the trade',
};

const PRP_GATE_SHORT = {
  open: 'Open', before_rule: 'Before the rule', not_trading_book: 'Tagged holding', needs_review: 'Needs review',
  deviated: 'Deviated', no_stop: 'No stop', stop_after_close: 'Stop set after close', spot: 'Not gated', no_r: 'No R',
  before_gate_count: 'Before restart',
};

const PRP_GATE_LONG = {
  open: 'Still open — only closed trades count.',
  before_rule: 'Opened before the gate start, so it does not count.',
  not_trading_book: 'Tagged as a long-term or bot holding.',
  needs_review: 'Mark it followed or deviated to decide whether it counts.',
  deviated: 'Deviated trades are tracked separately and never count.',
  no_stop: 'No stop was recorded for this trade.',
  stop_after_close: 'The stop was recorded after the trade closed.',
  spot: "Spot trades don't count toward the perp risk gate.",
  no_r: 'R could not be calculated (entry equals stop, or a price is missing).',
  before_gate_count: 'Opened before the gate count restarted, so it does not count.',
};

// Landing 15: the gate counts perp trades opened since summary.gate.count_from;
// before_gate_count names that day when the page has it.
function prpGateLong(reason, countFrom) {
  if (reason === 'before_gate_count' && countFrom)
    return 'Opened before ' + prpDate(countFrom) + ' (UTC), when the gate count restarted, so it does not count.';
  return PRP_GATE_LONG[reason] || reason || '—';
}

const PRP_FLAGS = {
  funding_approx: 'Funding approximate', funding_missing: 'Funding not recorded', stop_missing: 'No stop order found',
  liquidated: 'Liquidated', flip_split: 'Flipped direction', chain_gap: 'Fill history gap',
};

/* ── display helpers ─────────────────────────────────────────────────── */

function prpNum(v) {
  if (v === null || v === undefined || v === '') return null;
  const n = Number(v);
  return isFinite(n) ? n : null;
}

function prpUsd(v, hide, signed) {
  if (hide) return '••••';
  const n = prpNum(v);
  if (n === null) return '—';
  const abs = Math.abs(n).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  if (abs === '0.00') return '$0.00';
  if (n < 0) return '-$' + abs;
  return (signed ? '+$' : '$') + abs;
}

// A price: sub-cent via fmtPrice; else up to 6 significant digits, and at
// least 2 decimals below $1,000 ("$1.30", not "$1.3").
function prpPx(v) {
  const n = prpNum(v);
  if (n === null) return '—';
  if (n > 0 && n < 0.01) return fmtPrice(n);
  let s = n.toLocaleString('en-US', { maximumSignificantDigits: 6 });
  if (Math.abs(n) < 1000 && (s.split('.')[1] || '').length < 2) {
    s = n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }
  return '$' + s;
}

function prpSize(v, hide) {
  if (hide) return '••••';
  const n = prpNum(v);
  if (n === null) return '—';
  return n.toLocaleString('en-US', { maximumSignificantDigits: 6 });
}

function prpR(v) {
  const n = prpNum(v);
  if (n === null) return '—';
  return (n > 0 ? '+' : '') + n.toFixed(2) + 'R';
}

function prpDate(v, withTime) {
  if (!v) return '—';
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(v));
  const d = m ? new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3])) : new Date(v);
  if (isNaN(d.getTime())) return String(v);
  const opts = { month: 'short', day: 'numeric' };
  if (d.getFullYear() !== new Date().getFullYear()) opts.year = 'numeric';
  let s = d.toLocaleDateString('en-US', opts);
  if (withTime && !m) s += ', ' + String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0');
  return s;
}

function prpAgo(iso) {
  const ms = Date.parse(iso || '');
  if (isNaN(ms)) return null;
  const min = Math.max(0, Math.round((Date.now() - ms) / 60000));
  if (min < 1) return 'just now';
  if (min < 60) return min + ' min ago';
  const h = Math.round(min / 60);
  if (h < 48) return h + ' h ago';
  return Math.round(h / 24) + ' days ago';
}

function prpColor(v) {
  const n = prpNum(v);
  if (n === null || n === 0) return 'var(--text2)';
  return n > 0 ? 'var(--ok)' : 'var(--fail)';
}

function prpMoneyColor(v, hide) {
  // Hidden amounts stay neutral so the color does not give away gain or loss.
  return hide ? 'var(--text2)' : prpColor(v);
}

function prpErr(e) {
  const text = (e && e.message) || String(e || 'Request failed');
  let out = text;
  try {
    const parsed = JSON.parse(text);
    if (parsed && typeof parsed.error === 'string') out = parsed.error;
  } catch (err) { /* not JSON: keep the text */ }
  return out.length > 200 ? out.slice(0, 200) : out;
}

function prpPositive(s) {
  const t = String(s || '').trim();
  if (t === '') return false;
  const n = Number(t);
  return isFinite(n) && n > 0;
}

function prpTextOrNull(s) {
  return String(s || '').trim() === '' ? null : s;
}

function prpNowLocal() {
  const d = new Date();
  d.setMinutes(d.getMinutes() - d.getTimezoneOffset());
  return d.toISOString().slice(0, 16);
}

function prpLocalToIso(value) {
  if (!value) return null;
  const d = new Date(value);
  return isNaN(d.getTime()) ? null : d.toISOString();
}

function prpReadLocal(key, fallback) {
  try { const v = localStorage.getItem(key); return v === null ? fallback : v; } catch (_e) { return fallback; }
}

function prpWriteLocal(key, v) {
  try { localStorage.setItem(key, v); } catch (_e) { /* the choice still applies until reload */ }
}

function prpVenueLine(t) {
  if (t.source === 'manual') return (!t.venue || t.venue === 'Manual') ? 'Manual entry' : 'Manual · ' + t.venue;
  return (!t.wallet_label || t.wallet_label === t.venue) ? t.venue : t.venue + ' · ' + t.wallet_label;
}

function prpSide(direction) {
  const long = direction === 'long';
  const text = direction ? direction.charAt(0).toUpperCase() + direction.slice(1) : '—';
  return <span style={{ color: long ? 'var(--ok)' : direction === 'short' ? 'var(--fail)' : 'var(--text2)' }}>{text}</span>;
}

// "10x" and its hover text; '—' when unknown (a trade that closed before it was ever seen open).
function prpLev(lev, type) {
  const n = prpNum(lev);
  if (n === null) return { text: '—', tip: "Leverage is read from the venue while a position is open; none was recorded for this trade." };
  const text = (Number.isInteger(n) ? String(n) : String(+n.toFixed(2))) + 'x';
  return { text, tip: text + (type ? ' ' + type : '') };
}

// The current size of an open trade: the venue's live size, else the peak (manual trades, cold caches).
function prpOpenSize(t) {
  return t.live && prpNum(t.live.size) !== null ? prpNum(t.live.size) : prpNum(t.size_peak);
}

// 1R = |avg entry - stop| x peak size, the same basis as R at the close; null when it can't be computed.
function prpOneR(t) {
  const entry = prpNum(t.avg_entry);
  const stop = t.stop ? prpNum(t.stop.px) : null;
  const size = prpNum(t.size_peak);
  if (entry === null || stop === null || size === null) return null;
  const r = Math.abs(entry - stop) * size;
  return r > 0 ? r : null;
}

// Planned risk of one open trade (ruling 2): (entry - stop) x current size in
// the losing direction; 0 when the stop is at or past entry; null without a stop or a price.
function prpOpenRisk(t) {
  const entry = prpNum(t.avg_entry);
  const stop = t.stop ? prpNum(t.stop.px) : null;
  const size = prpOpenSize(t);
  if (entry === null || stop === null || size === null) return null;
  const perUnit = (entry - stop) * (t.direction === 'short' ? -1 : 1);
  return Math.max(0, perUnit) * Math.abs(size);
}

// The Target cell's model. tps: take-profit prices nearest first (strings),
// or null when unknown. Returns {nearest, more, r, why}.
function prpTarget(direction, entryV, stopV, tps) {
  if (!Array.isArray(tps)) return null;
  if (!tps.length) return { nearest: null, more: [], r: null, why: 'No take-profit order found' };
  const nearest = tps[0];
  const entry = prpNum(entryV);
  const stop = prpNum(stopV);
  const tp = prpNum(nearest);
  const sign = direction === 'short' ? -1 : 1;
  let r = null, why = null;
  if (stop === null) why = 'R needs a stop';
  else if (entry === null || tp === null) why = 'A price is missing';
  else if ((entry - stop) * sign <= 0) why = 'The stop is at or past entry, so the target has no R';
  else if ((tp - entry) * sign <= 0) why = 'This take-profit is on the losing side of entry, so it has no R';
  else r = Math.abs(tp - entry) / Math.abs(entry - stop);
  return { nearest, more: tps.slice(1), r, why };
}

function PerpsTargetCell({ model, unknownTip }) {
  if (!model) return <span title={unknownTip || "Take-profit orders couldn't be read"} style={{ color: 'var(--text3)' }}>—</span>;
  if (!model.nearest) return <span title={model.why} style={{ color: 'var(--text3)' }}>—</span>;
  const all = [model.nearest].concat(model.more).map(prpPx).join(', ');
  const tip = (model.more.length ? 'Take-profits, nearest first: ' + all : 'Take-profit ' + all)
    + (model.r !== null ? ' · ' + model.r.toFixed(2) + 'R from entry' : model.why ? ' · ' + model.why : '');
  return <div title={tip}>
    <div>
      <span style={{ fontFamily: PRP_MONO }}>{prpPx(model.nearest)}</span>
      {model.r !== null
        ? <span style={{ marginLeft: 6, fontSize: 12, fontWeight: 600, padding: '1px 6px', borderRadius: 999, border: '1px solid rgba(255,255,255,0.45)', color: 'var(--text)', whiteSpace: 'nowrap' }}>{model.r.toFixed(1) + 'R'}</span>
        : model.why === 'R needs a stop' && <div style={{ fontSize: 12, color: 'var(--warn)' }}>R needs a stop</div>}
    </div>
    {model.more.length > 0 && <div style={{ fontSize: 12, color: 'var(--text3)', marginTop: 2 }}>{'+' + model.more.length + ' more'}</div>}
  </div>;
}

function PerpsKpi({ label, value, color, sub, title, children }) {
  return <div className="tv-card" title={title} style={{ flex: '1 1 240px', minWidth: 0, padding: '14px 18px' }}>
    <div className="tv-label" style={{ fontSize: 12 }}>{label}</div>
    {value !== undefined && <div className="tv-num" style={{ fontSize: 20, fontWeight: 700, marginTop: 6, color: color || 'var(--text)', overflowWrap: 'anywhere' }}>{value}</div>}
    {sub}
    {children}
  </div>;
}

function PerpsFact({ label, children, mono, color }) {
  return <React.Fragment>
    <span style={{ fontSize: 13, color: 'var(--text3)' }}>{label}</span>
    <span style={{ fontSize: 13, color: color || 'var(--text2)', fontFamily: mono ? PRP_MONO : 'inherit', overflowWrap: 'anywhere' }}>{children}</span>
  </React.Fragment>;
}

function PerpsStatus({ saving, status }) {
  if (saving) return <span role="status" style={{ fontSize: 13, color: 'var(--text3)' }}>Saving…</span>;
  if (status === 'saved') return <span role="status" style={{ fontSize: 13, color: 'var(--ok)' }}>Saved</span>;
  if (status && status.error) return <span role="alert" style={{ fontSize: 13, color: 'var(--fail)' }}>{status.error}</span>;
  return null;
}

const PRP_SECTION = { fontSize: 12, lineHeight: '16px', fontWeight: 600, letterSpacing: '0.08em', textTransform: 'uppercase', color: 'var(--text3)' };
const PRP_FACTS = { display: 'grid', gridTemplateColumns: 'minmax(110px,150px) minmax(0,1fr)', rowGap: 8, columnGap: 12, alignContent: 'start' };

/* ── at open (Landing 4) ─────────────────────────────────────────────── */

// open_snapshot.trend: price vs the noodle at the open on each timeframe, from
// candles that closed before the first fill (the scanner's engine and settings).
// Captured in the background after each fill sync, a few trades at a time.
const PRP_OPEN_TFS = [['15m', '15m'], ['30m', '30m'], ['1h', '1H'], ['4h', '4H'], ['12h', '12H'], ['1d', '1D'], ['1w', '1W']];
const PRP_POS_WORD = { above: 'above the noodle', touch: 'touching the noodle', below: 'below the noodle' };
const PRP_POS_COLOR = { above: 'var(--ok)', touch: 'var(--warn)', below: 'var(--fail)' };
const PRP_TREND_WORD = { BULLISH: 'Bullish', BEARISH: 'Bearish', WARMUP: 'Neutral' };
const PRP_OPEN_REASON = {
  not_on_hyperliquid: "Not listed on Hyperliquid, so there's no noodle reading.",
  no_open_time: "The open time is unknown, so there's no noodle reading.",
  price_mismatch: "Hyperliquid's price for this symbol was far from the entry (likely a different token), so there's no noodle reading.",
};
const PRP_OPEN_PENDING = 'Not captured yet';
const PRP_OPEN_PENDING_TIP = 'Captured in the background after each fill sync, a few trades at a time.';

// One timeframe's reading: {label, pos, text}; no position = too few candles before the open.
function prpOpenReading(label, x) {
  if (!x || !PRP_POS_WORD[x.position]) {
    return { label, pos: null, text: label + ': ' + (x && prpNum(x.bars) === 0 ? 'no candles that far back' : 'too few candles before the open') };
  }
  const trend = PRP_TREND_WORD[x.state];
  return { label, pos: x.position, text: label + ': ' + PRP_POS_WORD[x.position] + (trend ? ', trend ' + trend : '') };
}

function PerpsDot({ pos }) {
  const color = PRP_POS_COLOR[pos];
  return <span style={{ width: 10, height: 10, borderRadius: 999, display: 'inline-block', flex: 'none',
    background: color || 'transparent', border: color ? 'none' : '1.5px solid rgba(255,255,255,0.6)' }} />;
}

// The "At open" fact of an expanded synced trade; nothing for manual trades.
function PerpsAtOpen({ trade: t }) {
  const snap = t.open_snapshot;
  if (!snap) return null;
  const tr = snap.trend;
  if (!tr) return <PerpsFact label="At open"><span title={PRP_OPEN_PENDING_TIP}>{PRP_OPEN_PENDING}</span></PerpsFact>;
  if (tr.reason) return <PerpsFact label="At open">{PRP_OPEN_REASON[tr.reason] || "No noodle reading."}</PerpsFact>;
  const tfs = tr.timeframes || {};
  const parts = PRP_OPEN_TFS.map(([tf, label]) => prpOpenReading(label, tfs[tf]));
  const weekly = PRP_TREND_WORD[tr.weekly_state];
  const market = tr.market && String(tr.market).toUpperCase() !== String(t.symbol || '').toUpperCase() ? ' · Hyperliquid market ' + tr.market : '';
  const when = 'from candles closed before ' + prpDate(tr.as_of, true);
  const text = 'At open, price vs the noodle: ' + parts.map(p => p.text).join('; ') + '. ' + when + market + '.';
  return <PerpsFact label="At open">
    <span role="img" aria-label={text} style={{ display: 'inline-flex', flexWrap: 'wrap', gap: '6px 12px' }}>
      {parts.map(p => <span key={p.label} title={p.text} style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}>
        <span style={{ fontSize: 12, color: 'var(--text3)' }}>{p.label}</span><PerpsDot pos={p.pos} />
      </span>)}
    </span>
    <span style={{ display: 'block', fontSize: 12, color: 'var(--text3)', marginTop: 4 }} title={when + market}>
      {(weekly ? '1W trend ' + weekly + ' · ' : '') + 'candles closed before the open' + market}</span>
  </PerpsFact>;
}

/* ── planned target (Landing 5) ──────────────────────────────────────── */

const PRP_PLAN_SOURCE = {
  hl_order: 'Hyperliquid take-profit order',
  txflow_order: 'TxFlow take-profit',
  seen_live: 'take-profit seen on the open position',
  manual_log: 'target logged with the trade',
};

// How long after the open a time is: "at open", "12 min after open", "3 h after open", "2 days after open".
function prpAfterOpen(atIso, openIso) {
  const at = Date.parse(atIso || ''), open = Date.parse(openIso || '');
  if (isNaN(at) || isNaN(open)) return null;
  const min = Math.round((at - open) / 60000);
  if (min <= 1) return 'at open';
  if (min < 60) return min + ' min after open';
  const h = Math.round(min / 60);
  if (h < 48) return h + ' h after open';
  return Math.round(h / 24) + ' days after open';
}

// The plan model: prpTarget's {nearest, more, r, why} on the planned prices
// (R from entry to the trade's stop, by price), plus {plan, moved, when}; null without a plan.
function prpPlan(t) {
  const p = t.planned_target;
  if (!p || !Array.isArray(p.prices) || !p.prices.length) return null;
  const stop = t.stop ? t.stop.px : null;
  const model = prpTarget(t.direction, t.avg_entry, stop, p.prices);
  const moved = p.moved_to ? prpTarget(t.direction, t.avg_entry, stop, [p.moved_to]) : null;
  return Object.assign({}, model, { plan: p, moved, when: p.set_at ? prpAfterOpen(p.set_at, t.opened_at) : null });
}

// "set 1 min after open" for an order, "first seen 3 h after open" for a take-profit seen live; null without a time.
function prpPlanWhen(m) {
  if (!m || !m.when) return null;
  return (m.plan.source === 'seen_live' ? 'first seen ' : 'set ') + m.when;
}

function prpCap(text) {
  return text ? text.charAt(0).toUpperCase() + text.slice(1) : text;
}

function prpPlanR(m) {
  return m && m.r !== null ? m.r.toFixed(1) + 'R' : null;
}

// One line of text for hovers: "$98.00 (1.5R), Hyperliquid take-profit order, set 1 min after open · moved later to $105 (2.4R)".
function prpPlanText(m) {
  if (!m) return null;
  const r = prpPlanR(m);
  let s = prpPx(m.nearest) + (r ? ' (' + r + ')' : '') + ', ' + (PRP_PLAN_SOURCE[m.plan.source] || 'take-profit');
  if (prpPlanWhen(m)) s += ', ' + prpPlanWhen(m);
  if (m.more.length) s += ' · +' + m.more.length + ' more: ' + m.more.map(prpPx).join(', ');
  if (m.moved) s += ' · moved later to ' + prpPx(m.moved.nearest) + (prpPlanR(m.moved) ? ' (' + prpPlanR(m.moved) + ')' : '');
  if (!r && m.why) s += ' · ' + m.why;
  return s;
}

// The "Planned target" fact of an expanded row. emptyText: shown without a plan (null hides the fact).
function PerpsPlanFact({ trade: t, model, emptyText }) {
  if (!model) return emptyText ? <PerpsFact label="Planned target">{emptyText}</PerpsFact> : null;
  const r = prpPlanR(model);
  return <PerpsFact label="Planned target">
    <span style={{ fontFamily: PRP_MONO }}>{prpPx(model.nearest)}</span>
    {r ? <span style={{ marginLeft: 6, fontSize: 12, fontWeight: 600, padding: '1px 6px', borderRadius: 999,
                         border: '1px solid rgba(255,255,255,0.45)', color: 'var(--text)', whiteSpace: 'nowrap' }}>{r}</span>
       : model.why && <span style={{ marginLeft: 6, fontSize: 12, color: 'var(--text3)' }}>{model.why}</span>}
    <span style={{ display: 'block', fontSize: 12, color: 'var(--text3)', marginTop: 3 }}>
      {prpCap(PRP_PLAN_SOURCE[model.plan.source] || 'take-profit')
        + (prpPlanWhen(model) ? ', ' + prpPlanWhen(model) + ' (' + prpDate(model.plan.set_at, true) + ')' : '')}</span>
    {model.more.length > 0 && <span style={{ display: 'block', fontSize: 12, color: 'var(--text3)', marginTop: 2 }}>
      {'+' + model.more.length + ' more: ' + model.more.map(p => {
        const x = prpTarget(t.direction, t.avg_entry, t.stop ? t.stop.px : null, [p]);
        return prpPx(p) + (prpPlanR(x) ? ' (' + prpPlanR(x) + ')' : '');
      }).join(', ')}</span>}
    {model.moved && <span style={{ display: 'block', fontSize: 12, color: 'var(--text3)', marginTop: 2 }}>
      {'Moved later to ' + prpPx(model.moved.nearest) + (prpPlanR(model.moved) ? ' (' + prpPlanR(model.moved) + ')' : '')
        + (model.plan.moved_at ? ', ' + prpDate(model.plan.moved_at, true) : '')}</span>}
  </PerpsFact>;
}

/* ── settled stop (Landing 6) ────────────────────────────────────────── */

// "under a minute after entry" / "5 min after entry".
function prpCorrectedWhen(c) {
  const m = prpNum(c && c.minutes_after_open);
  if (m === null) return 'after entry';
  return m < 1 ? 'under a minute after entry' : Math.round(m) + ' min after entry';
}

// One line: "$4,360 → $4,300, 5 min after entry".
function prpCorrectionText(c) {
  return c ? prpPx(c.from_px) + ' → ' + prpPx(c.to_px) + ', ' + prpCorrectedWhen(c) : null;
}

const PRP_CORRECTION_TIP = 'R, 1R and the gate use the stop in force 10 minutes after entry, so a stop corrected right after opening counts as the plan.';

function PerpsCorrectionFact({ trade: t }) {
  if (!t.stop_correction) return null;
  return <PerpsFact label="Stop corrected">
    <span title={PRP_CORRECTION_TIP}><span style={{ fontFamily: PRP_MONO }}>{prpPx(t.stop_correction.from_px) + ' → ' + prpPx(t.stop_correction.to_px)}</span>
      {', ' + prpCorrectedWhen(t.stop_correction)}</span>
    <span style={{ display: 'block', fontSize: 12, color: 'var(--text3)', marginTop: 3 }}>R uses the corrected stop.</span>
  </PerpsFact>;
}

/* ── after exit (Landing 7) ──────────────────────────────────────────── */

// after_exit: the noodle at the close ("trend"), the best and worst prices while
// the trade was open ("excursion") and had you held the plan ("held"). Worked
// out in the background after each fill sync, a few closed trades at a time.
const PRP_EXIT_PENDING_TIP = 'Worked out in the background after each fill sync, a few closed trades at a time.';
const PRP_INTERVAL_WORD = { '1m': '1-minute', '5m': '5-minute', '15m': '15-minute' };
const PRP_EXIT_REASON = {
  not_on_hyperliquid: "Not listed on Hyperliquid, so there are no candles to read.",
  no_open_time: "The open time is unknown, so there are no candles to read.",
  price_mismatch: "Hyperliquid's price for this symbol was far from the entry (likely a different token), so there's no reading.",
  no_candles: "Hyperliquid has no candles back to this trade's open.",
};
const PRP_HELD_REASON = {
  no_target: 'No planned target, so there is no plan to test.',
  no_stop: 'No stop, so there is no plan to test.',
  no_entry: 'The entry price is missing, so there is no plan to test.',
  stop_not_past_entry: 'The stop was at or past entry, so the plan has no risk to test.',
  target_not_past_entry: 'The planned target is on the losing side of entry, so there is no plan to test.',
};
const PRP_HELD_TIP = 'The plan: the stop R uses and your first take-profit, followed from the open to 14 days after the exit; '
  + 'whichever was hit first decides. Plan R is by price, before fees; yours is net of fees and funding.';

// One timeframe's reading at the close: {label, pos, text}.
function prpExitReading(label, x) {
  if (!x || !PRP_POS_WORD[x.position]) {
    return { label, pos: null, text: label + ': ' + (x && prpNum(x.bars) === 0 ? 'no candles that far back' : 'too few candles before the close') };
  }
  const trend = PRP_TREND_WORD[x.state];
  return { label, pos: x.position, text: label + ': ' + PRP_POS_WORD[x.position] + (trend ? ', trend ' + trend : '') };
}

// "40 min", "3 h", "2 days" after the exit. The first after-exit candle is the 15-minute one
// containing the close, so a touch there started before the close: "within 15 minutes of your exit".
function prpAfterExit(atIso, closedIso) {
  const at = Date.parse(atIso || ''), closed = Date.parse(closedIso || '');
  if (isNaN(at) || isNaN(closed)) return null;
  const min = Math.round((at - closed) / 60000);
  if (min <= 0) return 'within 15 minutes of your exit';
  if (min < 60) return min + ' min after your exit';
  const h = Math.round(min / 60);
  if (h < 48) return h + ' h after your exit';
  return Math.round(h / 24) + ' days after your exit';
}

// The "At exit" fact of an expanded closed synced trade; nothing for other trades.
function PerpsAtExit({ trade: t }) {
  const ae = t.after_exit;
  if (!ae) return null;
  const tr = ae.trend;
  if (!tr) return <PerpsFact label="At exit"><span title={PRP_EXIT_PENDING_TIP}>{PRP_OPEN_PENDING}</span></PerpsFact>;
  if (tr.reason) return <PerpsFact label="At exit">{PRP_OPEN_REASON[tr.reason] || "No noodle reading."}</PerpsFact>;
  const tfs = tr.timeframes || {};
  const parts = PRP_OPEN_TFS.map(([tf, label]) => prpExitReading(label, tfs[tf]));
  const weekly = PRP_TREND_WORD[tr.weekly_state];
  const market = tr.market && String(tr.market).toUpperCase() !== String(t.symbol || '').toUpperCase() ? ' · Hyperliquid market ' + tr.market : '';
  const when = 'from candles closed before ' + prpDate(tr.as_of, true);
  const text = 'At exit, the average exit price vs the noodle: ' + parts.map(p => p.text).join('; ') + '. ' + when + market + '.';
  return <PerpsFact label="At exit">
    <span role="img" aria-label={text} style={{ display: 'inline-flex', flexWrap: 'wrap', gap: '6px 12px' }}>
      {parts.map(p => <span key={p.label} title={p.text} style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}>
        <span style={{ fontSize: 12, color: 'var(--text3)' }}>{p.label}</span><PerpsDot pos={p.pos} />
      </span>)}
    </span>
    <span style={{ display: 'block', fontSize: 12, color: 'var(--text3)', marginTop: 4 }} title={when + market}>
      {(weekly ? '1W trend ' + weekly + ' · ' : '') + 'candles closed before the close' + market}</span>
  </PerpsFact>;
}

// One price line: "$104.00  +0.80R, Sep 27, 15:05".
function PerpsExcursionLine({ px, r, at }) {
  return <React.Fragment>
    <span style={{ fontFamily: PRP_MONO }}>{prpPx(px)}</span>
    {prpNum(r) !== null && <span style={{ marginLeft: 6, fontFamily: PRP_MONO, fontWeight: 600, color: prpColor(r) }}>{prpR(r)}</span>}
    {at && <span style={{ color: 'var(--text3)' }}>{', ' + prpDate(at, true)}</span>}
  </React.Fragment>;
}

// "Best during the trade" and "Worst during the trade"; nothing for other trades.
function PerpsExcursionFacts({ trade: t }) {
  const ae = t.after_exit;
  if (!ae) return null;
  const x = ae.excursion;
  if (!x) return <PerpsFact label="Best during the trade"><span title={PRP_EXIT_PENDING_TIP}>{PRP_OPEN_PENDING}</span></PerpsFact>;
  if (x.reason) return <PerpsFact label="Best during the trade">{PRP_EXIT_REASON[x.reason] || 'No candles to read.'}</PerpsFact>;
  const src = 'From ' + (PRP_INTERVAL_WORD[x.interval] || x.interval || '') + ' candles, open to close';
  const tip = src + ' (a time is the start of its candle). R is by price, against the stop R uses.';
  return <React.Fragment>
    <PerpsFact label="Best during the trade"><span title={tip}><PerpsExcursionLine px={x.best_px} r={x.best_r} at={x.best_at} /></span></PerpsFact>
    <PerpsFact label="Worst during the trade">
      <span title={tip}><PerpsExcursionLine px={x.worst_px} r={x.worst_r} at={x.worst_at} /></span>
      <span style={{ display: 'block', fontSize: 12, color: 'var(--text3)', marginTop: 3 }}>
        {src + (prpNum(x.best_r) === null ? ' · R needs a stop' : '')}</span>
    </PerpsFact>
  </React.Fragment>;
}

// The had-you-held verdict as {main, sub}; null for a trade without after_exit.
function prpHeldText(t) {
  const ae = t.after_exit;
  if (!ae) return null;
  const h = ae.held;
  if (!h) return { main: PRP_OPEN_PENDING, sub: null, pending: true };
  if (h.stale) return { main: 'Being re-checked: the stop or target changed since it was tested.', sub: null, pending: true };
  if (h.reason) return { main: PRP_HELD_REASON[h.reason] || PRP_EXIT_REASON[h.reason] || 'Not tested.', sub: null };
  const tpx = prpPx(h.target_px), spx = prpPx(h.stop_px);
  const planR = prpNum(h.plan_r);
  const yours = prpNum(t.r_multiple);
  const yoursText = yours === null ? null : 'your ' + prpR(yours);
  const date = prpDate(h.at, true);
  const after = prpAfterExit(h.at, t.closed_at);
  if (h.outcome === 'target') {
    const sub = planR !== null && yoursText ? 'Holding the plan: ' + prpR(planR) + ' vs ' + yoursText : null;
    if (h.phase === 'during') return { main: 'Target ' + tpx + (planR !== null ? ' (' + prpR(planR) + ')' : '') + ' reached during the trade, ' + date + '.', sub };
    return { main: 'Target first: ' + tpx + ' reached ' + date + (after ? ', ' + after : '') + '.', sub };
  }
  if (h.outcome === 'stop') {
    let sub = yoursText ? 'Plan ' + prpR(-1) + ' vs ' + yoursText : null;
    if (h.phase === 'after' && yours !== null && yours > -1) sub = 'Your exit saved ' + (yours + 1).toFixed(2) + 'R (plan ' + prpR(-1) + ' vs ' + yoursText + ')';
    if (h.phase === 'during') return { main: 'Stop ' + spx + ' hit during the trade, ' + date + '.', sub };
    return { main: 'Stop first: ' + spx + ' hit ' + date + (after ? ', ' + after : '') + '.', sub };
  }
  if (h.outcome === 'both') {
    return { main: 'Unclear: one ' + (PRP_INTERVAL_WORD[h.interval] || '') + ' candle (' + date + ') touched both the target ' + tpx + ' and the stop ' + spx + '.', sub: null };
  }
  if (h.outcome === 'neither') return { main: 'No verdict: neither the target ' + tpx + ' nor the stop ' + spx + ' was hit within 14 days of your exit.', sub: null };
  if (h.outcome === 'watching') return { main: 'Watching until ' + prpDate(h.horizon_end) + ': neither the target ' + tpx + ' nor the stop ' + spx + ' has been hit yet.', sub: null };
  return { main: 'Not tested.', sub: null };
}

function PerpsHeldFact({ trade: t }) {
  const v = prpHeldText(t);
  if (!v) return null;
  const h = t.after_exit.held;
  const tip = v.pending ? PRP_EXIT_PENDING_TIP
    : PRP_HELD_TIP + (h && h.checked_at ? ' Checked ' + prpDate(h.checked_at, true) + '.' : '');
  return <PerpsFact label="Had you held the plan">
    <span title={tip}>{v.main}</span>
    {v.sub && <span style={{ display: 'block', fontSize: 12, color: 'var(--text3)', marginTop: 3 }}>{v.sub}</span>}
  </PerpsFact>;
}

// The History tally: verdict counts over the trades in view; null when none has after_exit.
function prpHeldTally(rows) {
  const withExit = rows.filter(t => t.after_exit);
  if (!withExit.length) return null;
  const c = { target: 0, stop: 0, both: 0, neither: 0, watching: 0, untested: 0 };
  withExit.forEach(t => {
    const h = t.after_exit.held;
    if (h && !h.stale && !h.reason && ['target', 'stop', 'both', 'neither', 'watching'].indexOf(h.outcome) >= 0) c[h.outcome] += 1;
    else c.untested += 1;
  });
  const parts = ['target first ' + c.target, 'stop first ' + c.stop];
  if (c.both) parts.push('unclear ' + c.both);
  if (c.neither) parts.push('no verdict ' + c.neither);
  if (c.watching) parts.push('watching ' + c.watching);
  if (c.untested) parts.push('not tested ' + c.untested);
  return 'Had you held the plan: ' + parts.join(' · ');
}

/* ── saving ──────────────────────────────────────────────────────────── */

// A text draft starts from the stored value and follows it when the stored
// value changes, unless the user has an unsaved edit.
function prpUseFollowingDraft(stored) {
  const [draft, setDraft] = usePRPState(stored);
  const prevRef = usePRPRef(stored);
  usePRPEffect(() => {
    const prev = prevRef.current;
    if (stored !== prev) {
      setDraft(d => (d === prev || d === stored) ? stored : d);
      prevRef.current = stored;
    }
  }, [stored]);
  return [draft, setDraft];
}

// One trade's writes: the annotation route for synced trades, the trade-log
// route for manual ones. onSaved re-reads the page.
function prpUseSaver(trade, onSaved) {
  const [saving, setSaving] = usePRPState(false);
  const [status, setStatus] = usePRPState(null);
  const aliveRef = usePRPRef(true);
  const timerRef = usePRPRef(null);
  usePRPEffect(() => () => { aliveRef.current = false; clearTimeout(timerRef.current); }, []);

  function send(path, options) {
    setSaving(true);
    setStatus(null);
    clearTimeout(timerRef.current);
    return api(path, options).then(() => {
      if (!aliveRef.current) return true;
      setSaving(false);
      setStatus('saved');
      timerRef.current = setTimeout(() => { if (aliveRef.current) setStatus(null); }, PRP_SAVED_MS);
      onSaved();
      return true;
    }).catch(e => {
      if (aliveRef.current) { setSaving(false); setStatus({ error: prpErr(e) }); }
      return false;
    });
  }
  const isManual = trade.source === 'manual';
  return {
    saving, status, aliveRef, isManual,
    annotate: body => send('/api/trading/trades/' + encodeURIComponent(trade.trade_id) + '/annotation',
                           { method: 'PUT', body: JSON.stringify(body) }),
    manual: body => send('/api/spot/trade-log/' + trade.manual_id, { method: 'PUT', body: JSON.stringify(body) }),
    remove: () => send('/api/spot/trade-log/' + trade.manual_id, { method: 'DELETE' }),
  };
}

/* ── shared pieces of an expanded row ────────────────────────────────── */

function PerpsStopEditor({ trade, saver, closed }) {
  const [draft, setDraft] = usePRPState('');
  const valid = prpPositive(draft);
  const id = 'prp-stop-' + trade.trade_id;
  function save() {
    if (saver.saving || !valid) return;
    saver.annotate({ stop_px: draft.trim() }).then(ok => { if (ok && saver.aliveRef.current) setDraft(''); });
  }
  const s = trade.stop;
  const hint = closed ? "A stop entered now, after the close, gives this trade an R but won't count toward the gate."
    : s ? (s.source === 'manual' ? 'Entered here. It is not an order on the venue; a venue stop order would be used once you clear this.'
           : 'From the ' + (PRP_STOP_SOURCE[s.source] || s.source).toLowerCase() + '. A stop entered here replaces it for R and the gate.')
    : 'No stop order found on ' + trade.venue + '. A stop entered here counts for R and the gate.';
  return <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
    <label htmlFor={id} style={PRP_SECTION}>Stop</label>
    <div style={{ fontSize: 13, color: 'var(--text2)' }}>
      {s ? <span><span style={{ fontFamily: PRP_MONO }}>{prpPx(s.px)}</span>
             {' · ' + (PRP_STOP_SOURCE[s.source] || s.source) + (s.set_at ? ' · set ' + prpDate(s.set_at, true) : '')}</span>
        : 'No stop recorded.'}
    </div>
    <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
      <input id={id} className="tv-input" style={{ width: 170, fontFamily: PRP_MONO }} inputMode="decimal"
        placeholder="Stop price" value={draft} disabled={saver.saving}
        onChange={e => setDraft(e.target.value)} onKeyDown={e => { if (e.key === 'Enter') save(); }} />
      <button type="button" className="tv-btn primary" style={prpBtn(!valid || saver.saving, PRP_SMALL_BTN)} disabled={!valid || saver.saving} onClick={save}>Save stop</button>
      {s && s.source === 'manual' && <button type="button" className="tv-btn" style={prpBtn(saver.saving, PRP_SMALL_BTN)} disabled={saver.saving}
        onClick={() => saver.annotate({ stop_px: null })}>Clear</button>}
    </div>
    <div style={{ fontSize: 12, color: 'var(--text3)' }}>{hint}</div>
  </div>;
}

// Trade notes (and, on a closed trade, the deviation note): saved together.
function PerpsNotesEditor({ trade, saver, withDeviation }) {
  const ann = trade.annotation || {};
  const storedNotes = ann.notes || '';
  const storedDev = ann.deviation_note || '';
  const [notes, setNotes] = prpUseFollowingDraft(storedNotes);
  const [dev, setDev] = prpUseFollowingDraft(storedDev);
  const dirty = notes !== storedNotes || (withDeviation && dev !== storedDev);
  const idN = 'prp-notes-' + trade.trade_id;
  const idD = 'prp-dev-' + trade.trade_id;
  function save() {
    if (saver.saving || !dirty) return;
    const body = withDeviation ? { deviation_note: prpTextOrNull(dev), notes: prpTextOrNull(notes) } : { notes: prpTextOrNull(notes) };
    (saver.isManual ? saver.manual(body) : saver.annotate(body)).then(ok => {
      if (ok && saver.aliveRef.current) {
        setNotes(body.notes || '');
        if (withDeviation) setDev(body.deviation_note || '');
      }
    });
  }
  return <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
    {withDeviation && <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      <label htmlFor={idD} style={PRP_SECTION}>Deviation note</label>
      <input id={idD} className="tv-input" maxLength={PRP_NOTE_MAX} placeholder="What was different from the plan (optional)"
        value={dev} disabled={saver.saving} onChange={e => setDev(e.target.value)} />
    </div>}
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      <label htmlFor={idN} style={PRP_SECTION}>Trade notes</label>
      <textarea id={idN} className="tv-input" rows={4} maxLength={PRP_NOTE_MAX}
        style={{ resize: 'vertical', fontFamily: 'inherit', fontSize: 14, lineHeight: '21px' }}
        placeholder={withDeviation ? "What went right, what you'd change" : 'Why you took it and the plan'}
        value={notes} disabled={saver.saving} onChange={e => setNotes(e.target.value)} />
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        <button type="button" className="tv-btn primary" style={prpBtn(!dirty || saver.saving, PRP_SMALL_BTN)} disabled={!dirty || saver.saving} onClick={save}>
          Save notes</button>
        {dirty && <span style={{ fontSize: 12, color: 'var(--warn)' }}>Unsaved changes</span>}
        <span style={{ marginLeft: 'auto', fontSize: 12, color: 'var(--text3)', fontFamily: PRP_MONO }}>{notes.length} / {PRP_NOTE_MAX}</span>
      </div>
    </div>
  </div>;
}

function PerpsReviewButtons({ trade, saver }) {
  const followed = (trade.annotation || {}).followed_rules;
  function pick(value) {
    if (saver.saving) return;
    if (saver.isManual) saver.manual({ followed_rules: value ? 1 : 0 });
    else saver.annotate({ followed_rules: value });
  }
  const btn = (value, label, color) => {
    const active = followed === value;
    return <button key={label} type="button" className="tv-btn" aria-pressed={active} disabled={saver.saving}
      onClick={() => pick(value)}
      style={prpBtn(saver.saving, { ...PRP_SMALL_BTN, borderRadius: 999, background: active ? 'var(--panel3)' : 'transparent',
               borderColor: active ? color : 'var(--line)', color: active ? color : 'var(--text3)', fontWeight: active ? 600 : 400 })}>{label}</button>;
  };
  return <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
    <span style={PRP_SECTION}>Did you follow your rules?</span>
    <div role="group" aria-label={'Review for the ' + trade.symbol + ' ' + trade.direction} style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
      {btn(true, 'Followed', 'var(--ok)')}
      {btn(false, 'Deviated', 'var(--fail)')}
      {!saver.isManual && btn(null, 'Not reviewed', 'var(--text3)')}
    </div>
  </div>;
}

function PerpsManualClose({ trade, saver }) {
  const [exit, setExit] = usePRPState('');
  const [at, setAt] = usePRPState(prpNowLocal());
  const [followed, setFollowed] = usePRPState('');
  const valid = prpPositive(exit) && followed !== '';
  function close() {
    if (saver.saving || !valid) return;
    saver.manual({ exit_price: Number(exit.trim()), exited_at: prpLocalToIso(at), followed_rules: Number(followed) });
  }
  const id = 'prp-exit-' + trade.trade_id;
  return <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
    <label htmlFor={id} style={PRP_SECTION}>Close this trade</label>
    <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
      <input id={id} className="tv-input" style={{ width: 140, fontFamily: PRP_MONO }} inputMode="decimal" placeholder="Exit price"
        value={exit} disabled={saver.saving} onChange={e => setExit(e.target.value)} />
      <input className="tv-input" type="datetime-local" aria-label="Closed at" style={{ width: 210 }} value={at}
        disabled={saver.saving} onChange={e => setAt(e.target.value)} />
      <select className="tv-select" aria-label="Followed the rules?" value={followed} disabled={saver.saving}
        onChange={e => setFollowed(e.target.value)}>
        <option value="">Followed the rules?</option>
        <option value="1">Followed</option>
        <option value="0">Deviated</option>
      </select>
      <button type="button" className="tv-btn primary" style={prpBtn(!valid || saver.saving, PRP_SMALL_BTN)} disabled={!valid || saver.saving} onClick={close}>Close trade</button>
    </div>
  </div>;
}

function PerpsManualDelete({ trade, saver }) {
  function del() {
    if (saver.saving) return;
    const ok = window.confirm('Delete the manual ' + trade.symbol + ' trade logged ' + prpDate(trade.opened_at) + "? This can't be undone.");
    if (ok) saver.remove();
  }
  return <div><button type="button" className="tv-btn danger" style={prpBtn(saver.saving, PRP_SMALL_BTN)} disabled={saver.saving} onClick={del}>Delete manual trade</button></div>;
}

/* ── Open positions ──────────────────────────────────────────────────── */

const PRP_TP_SOURCE = { hyperliquid: 'Hyperliquid take-profit orders', txflow: 'TxFlow position take-profits' };

function PerpsOpenRow({ trade: t, open, onToggle, hide, onSaved, advisor, tag, onTagSaved }) {
  const saver = prpUseSaver(t, onSaved);
  const isManual = t.source === 'manual';
  const live = t.live;
  const lev = prpLev(t.leverage, t.leverage_type);
  const levSeen = !isManual && t.open_snapshot && t.open_snapshot.leverage ? prpLev(t.open_snapshot.leverage.value, t.open_snapshot.leverage.type) : null;
  const plan = prpPlan(t);
  const size = prpOpenSize(t);
  const tps = isManual ? (t.target_px ? [t.target_px] : []) : live ? live.take_profits : null;
  const target = prpTarget(t.direction, t.avg_entry, t.stop ? t.stop.px : null, tps);
  const unknownTip = isManual ? undefined : live ? "This venue's take-profit orders couldn't be read" : 'No live data for this position yet';
  const unr = prpNum(t.unrealized_pnl);
  const oneR = prpOneR(t);
  const fundingApprox = (t.flags || []).indexOf('funding_approx') >= 0;
  const fundingMissing = (t.flags || []).indexOf('funding_missing') >= 0;
  const fundingText = isManual || t.funding == null ? '—' : fundingMissing ? 'Not recorded'
    : (fundingApprox ? '≈ ' : '') + prpUsd(t.funding, hide, true);
  const sym = String(t.symbol || '');
  const num = (label, content, style, title) => <div className="spot-cell tv-num" data-label={label} title={title}
    style={{ textAlign: 'right', fontFamily: PRP_MONO, ...style }}>{content}</div>;

  let status;
  if (t.attention === 'needs_stop') status = <span className="tv-chip warn" style={{ fontSize: 12, fontWeight: 600 }}>Needs a stop</span>;
  else if (!t.stop) status = <span style={{ color: 'var(--text3)' }} title="Opened before the gate start, so it isn't flagged">No stop</span>;
  else status = <span style={{ color: 'var(--text3)' }}>Stop set</span>;
  let statusNote = null;
  if (isManual) statusNote = 'Manual · no price feed';
  else if (!live) statusNote = 'No live data';
  else if (live.stale) statusNote = 'Price may be stale';
  const statusTip = isManual ? 'Manual trades have no price feed, so Mark and Unrealized stay empty.'
    : !live ? 'The venue cache has no open position for this trade: it is still loading, or the position closed on the venue and the next fill sync (every 10 minutes) will close this trade.'
    : live.stale ? 'The last venue read for this wallet failed; these are the previous figures.' : undefined;

  const row = <div id={'prp-row-' + t.trade_id} className="spot-grid-row" style={{ gridTemplateColumns: PRP_OPEN_GRID, padding: '10px 16px', borderBottom: PRP_LINE,
                                                      fontSize: 13, color: 'var(--text2)', background: open ? 'var(--panel2)' : undefined }}>
    <div className="spot-span" style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0 }}>
      <button type="button" className="tv-btn" aria-expanded={open}
        aria-label={(open ? 'Hide' : 'Show') + ' details for the ' + sym + ' ' + t.direction}
        onClick={() => onToggle(t.trade_id)}
        style={{ width: 32, height: 32, padding: 0, flex: 'none', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 13, color: 'var(--text)' }}>
        {open ? '▾' : '▸'}</button>
      <div style={{ display: 'flex', flexDirection: 'column', minWidth: 0 }}>
        <span style={{ fontWeight: 700, color: 'var(--text)', fontSize: 14 }}>
          {sym}{(t.annotation || {}).notes && String(t.annotation.notes).trim()
            ? <span title="Has trade notes" aria-label="Has trade notes" style={{ marginLeft: 6, color: 'var(--text3)', fontWeight: 400 }}>✎</span> : null}
        </span>
        <span style={{ fontSize: 12, color: 'var(--text3)', overflowWrap: 'anywhere' }}>{prpVenueLine(t)}</span>
      </div>
    </div>
    <div className="spot-cell" data-label="Side">{prpSide(t.direction)}</div>
    {num('Leverage', lev.text, null, lev.tip)}
    <div className="spot-cell spot-pad-left" data-label="Opened" style={{ color: 'var(--text3)', whiteSpace: 'nowrap' }}>{prpDate(t.opened_at, true)}</div>
    {num('Size', prpSize(size, hide), null, live ? undefined : isManual ? 'Logged size' : 'Peak size (no live data)')}
    {num('Entry', prpPx(t.avg_entry))}
    {num('Mark', isManual ? '—' : live ? prpPx(live.mark_px) : '—', null, isManual ? 'Manual trades have no price feed' : undefined)}
    {num('Stop', t.stop ? prpPx(t.stop.px) : '—', null,
         t.stop ? (PRP_STOP_SOURCE[t.stop.source] || t.stop.source) + (t.stop.set_at ? ' · set ' + prpDate(t.stop.set_at, true) : '')
           + (t.stop_correction ? ' · corrected ' + prpCorrectedWhen(t.stop_correction) + ' from ' + prpPx(t.stop_correction.from_px) : '')
           : 'No stop recorded')}
    <div className="spot-cell" data-label="Target" style={{ textAlign: 'right' }}><PerpsTargetCell model={target} unknownTip={unknownTip} /></div>
    <div className="spot-cell tv-num" data-label="Unrealized" style={{ textAlign: 'right', fontFamily: PRP_MONO }}>
      <div style={{ fontWeight: 600, color: isManual ? 'var(--text3)' : prpMoneyColor(unr, hide) }}>{isManual ? '—' : prpUsd(unr, hide, true)}</div>
      {!isManual && unr !== null && oneR !== null && <div style={{ fontSize: 11, color: 'var(--text3)' }}>{'≈ ' + prpR(unr / oneR)}</div>}
    </div>
    {num('Funding', fundingText, { color: fundingMissing ? 'var(--text3)' : prpMoneyColor(t.funding, hide) },
         fundingApprox ? 'TxFlow funding is approximate (from position readings)' : fundingMissing ? 'TxFlow funding was not recorded for this trade' : 'Funding so far (negative = paid)')}
    <div className="spot-cell spot-pad-left" data-label="Status" title={statusTip} style={{ display: 'flex', flexDirection: 'column', gap: 3, alignItems: 'flex-start' }}>
      {status}
      {statusNote && <span style={{ fontSize: 11, color: live && live.stale ? 'var(--warn)' : 'var(--text3)' }}>{statusNote}</span>}
    </div>
  </div>;
  if (!open) return row;

  const tpList = Array.isArray(tps) && tps.length ? tps.map(prpPx).join(', ') : null;
  return <React.Fragment>
    {row}
    <div className="spot-detail" style={{ padding: '16px 16px 20px 56px', borderBottom: PRP_LINE, background: 'var(--bg)',
                                          display: 'flex', flexWrap: 'wrap', gap: 28 }}>
      <div style={{ ...PRP_FACTS, flex: '1 1 280px' }}>
        <PerpsFact label="Venue">{prpVenueLine(t)}</PerpsFact>
        <PerpsFact label="Opened">{prpDate(t.opened_at, true)}</PerpsFact>
        <PerpsAtOpen trade={t} />
        <PerpsFact label="Leverage" mono>{(lev.text === '—' ? '—' : lev.tip)
          + (levSeen && levSeen.text !== '—' && levSeen.tip !== lev.tip ? ' · first seen ' + levSeen.tip : '')}</PerpsFact>
        <PerpsFact label="Peak size" mono>{prpSize(t.size_peak, hide)}</PerpsFact>
        {!isManual && <PerpsFact label="Fees so far" mono color={prpMoneyColor(t.fees == null ? null : -prpNum(t.fees), hide)}>
          {t.fees == null ? '—' : prpUsd(-prpNum(t.fees), hide, true)}</PerpsFact>}
        {!isManual && <PerpsFact label="Funding so far" mono>{fundingText}</PerpsFact>}
        <PerpsFact label="1R at the stop" mono>{oneR === null ? '—' : prpUsd(oneR, hide)}</PerpsFact>
        <PerpsCorrectionFact trade={t} />
        {!isManual && <PerpsFact label="Liquidation" mono>{live && live.liquidation_px ? prpPx(live.liquidation_px) : '—'}</PerpsFact>}
        <PerpsFact label="Take-profit">
          {tpList ? (isManual ? 'Target logged with the trade: ' : (PRP_TP_SOURCE[t.source] || 'Take-profits') + ': ') + tpList
            : Array.isArray(tps) ? 'No take-profit order found' : unknownTip}
        </PerpsFact>
        {plan && Array.isArray(tps) && (!tps.length || prpNum(tps[0]) !== prpNum(plan.nearest) || plan.moved)
          && <PerpsPlanFact trade={t} model={plan} />}
        {!isManual && live && live.as_of && <PerpsFact label="Live data">{'As of ' + prpDate(live.as_of, true)}</PerpsFact>}
      </div>
      <div style={{ flex: '2 1 420px', display: 'flex', flexDirection: 'column', gap: 16, minWidth: 0 }}>
        <PerpsTagEditor trade={t} tag={tag} onSaved={onTagSaved} />
        {isManual ? <PerpsManualClose trade={t} saver={saver} /> : <PerpsStopEditor trade={t} saver={saver} closed={false} />}
        <PerpsNotesEditor trade={t} saver={saver} withDeviation={false} />
        <span style={{ fontSize: 13, color: 'var(--text3)' }}>Followed or deviated is set once the trade closes, in History.</span>
        {isManual && <PerpsManualDelete trade={t} saver={saver} />}
        <PerpsStatus saving={saver.saving} status={saver.status} />
      </div>
      <div style={{ flex: '1 1 100%', minWidth: 0 }}><PerpsRuleCheck trade={t} advisor={advisor} hide={hide} /></div>
    </div>
  </React.Fragment>;
}

// A live venue position with no trade yet: live fields only, nothing to save.
function PerpsUntrackedRow({ row: u, hide }) {
  const live = u.live || {};
  const lev = prpLev(live.leverage, live.leverage_type);
  const target = prpTarget(u.direction, live.entry_px, live.stop_px, live.take_profits);
  const num = (label, content, style, title) => <div className="spot-cell tv-num" data-label={label} title={title}
    style={{ textAlign: 'right', fontFamily: PRP_MONO, ...style }}>{content}</div>;
  const unr = prpNum(live.unrealized_pnl);
  return <div className="spot-grid-row" style={{ gridTemplateColumns: PRP_OPEN_GRID, padding: '10px 16px', borderBottom: PRP_LINE,
                                                 fontSize: 13, color: 'var(--text2)' }}>
    <div className="spot-span" style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0 }}>
      <span aria-hidden="true" style={{ width: 32, flex: 'none' }} />
      <div style={{ display: 'flex', flexDirection: 'column', minWidth: 0 }}>
        <span style={{ fontWeight: 700, color: 'var(--text)', fontSize: 14 }}>{u.symbol}</span>
        <span style={{ fontSize: 12, color: 'var(--text3)', overflowWrap: 'anywhere' }}>
          {(!u.wallet_label || u.wallet_label === u.venue) ? u.venue : u.venue + ' · ' + u.wallet_label}</span>
      </div>
    </div>
    <div className="spot-cell" data-label="Side">{prpSide(u.direction)}</div>
    {num('Leverage', lev.text, null, lev.tip)}
    <div className="spot-cell spot-pad-left" data-label="Opened" style={{ color: 'var(--text3)' }}>—</div>
    {num('Size', prpSize(live.size, hide))}
    {num('Entry', prpPx(live.entry_px), null, "The venue's average entry")}
    {num('Mark', prpPx(live.mark_px))}
    {num('Stop', live.stop_px ? prpPx(live.stop_px) : '—', null, live.stop_px ? 'Venue stop order' : 'No stop order found')}
    <div className="spot-cell" data-label="Target" style={{ textAlign: 'right' }}><PerpsTargetCell model={target} /></div>
    {num('Unrealized', prpUsd(unr, hide, true), { fontWeight: 600, color: prpMoneyColor(unr, hide) })}
    {num('Funding', '—')}
    <div className="spot-cell spot-pad-left" data-label="Status"
      title="This position is open on the venue but not in your trade history yet: its fills haven't synced, or it opened before the sync window. Stops, notes and reviews attach once it becomes a trade.">
      <span className="tv-chip adapt" style={{ fontSize: 12, fontWeight: 600 }}>Not in trade history yet</span>
    </div>
  </div>;
}

function PerpsOpenTab({ trades, untracked, expanded, onToggle, hide, onSaved, advisor, tags, onTagSaved }) {
  const head = { fontSize: 12, lineHeight: '16px', fontWeight: 600, letterSpacing: '0.06em', textTransform: 'uppercase', color: 'var(--text3)' };
  const right = { textAlign: 'right' };
  if (!trades.length && !untracked.length) {
    return <div className="tv-card" style={{ color: 'var(--text3)', padding: 20, textAlign: 'center', fontSize: 14 }}>No open perp positions.</div>;
  }
  return <div>
    <div className="tv-card" style={{ padding: 0, overflow: 'hidden' }}>
      <div className="spot-grid-row spot-grid-head" style={{ ...head, gridTemplateColumns: PRP_OPEN_GRID, alignItems: 'end',
                                                             padding: '12px 16px', borderBottom: PRP_HEAD_LINE }}>
        <span>Symbol</span><span>Side</span><span style={right}>Lev</span><span className="spot-pad-left">Opened</span>
        <span style={right}>Size</span><span style={right}>Entry</span><span style={right}>Mark</span><span style={right}>Stop</span>
        <span style={right}>Target</span><span style={right}>Unrealized</span><span style={right}>Funding</span>
        <span className="spot-pad-left">Status</span>
      </div>
      {trades.map(t => <PerpsOpenRow key={t.trade_id} trade={t} open={!!expanded[t.trade_id]} onToggle={onToggle} hide={hide} onSaved={onSaved}
        advisor={advisor} tag={tags[t.trade_id]} onTagSaved={onTagSaved} />)}
      {untracked.map(u => <PerpsUntrackedRow key={u.venue + '|' + u.wallet_label + '|' + u.symbol} row={u} hide={hide} />)}
    </div>
    <div style={{ fontSize: 13, color: 'var(--text3)', marginTop: 10 }}>
      Target shows the nearest take-profit and its distance from entry in R (1R = entry to stop). Size is the venue's current size; 1R uses the peak size, like R at the close.
    </div>
  </div>;
}

/* ── History ─────────────────────────────────────────────────────────── */

function PerpsHistoryRow({ trade: t, open, onToggle, hide, onSaved, gateStart, gateCountFrom, advisor, tag, onTagSaved }) {
  const saver = prpUseSaver(t, onSaved);
  const isManual = t.source === 'manual';
  const lev = prpLev(t.leverage, t.leverage_type);
  const levSeen = !isManual && t.open_snapshot && t.open_snapshot.leverage;
  const levTip = lev.text !== '—' && levSeen ? lev.tip + ' · seen while the position was open, ' + prpDate(levSeen.seen_at, true) : lev.tip;
  const plan = prpPlan(t);
  const rTip = [t.r_basis === 'price' ? 'R from prices (manual trades have no fee data)' : null,
                plan ? 'Plan: ' + prpPlanText(plan) : null].filter(Boolean).join(' · ') || undefined;
  const followed = (t.annotation || {}).followed_rules;
  const g = t.gate || {};
  const sym = String(t.symbol || '');
  const flags = t.flags || [];
  const num = (label, content, style, title) => <div className="spot-cell tv-num" data-label={label} title={title}
    style={{ textAlign: 'right', fontFamily: PRP_MONO, ...style }}>{content}</div>;
  let review;
  if (followed === true) review = <span style={{ color: 'var(--ok)' }}>Followed</span>;
  else if (followed === false) review = <span style={{ color: 'var(--fail)' }}>Deviated</span>;
  else if (t.attention === 'needs_review') review = <span className="tv-chip warn" style={{ fontSize: 12, fontWeight: 600 }}>Needs review</span>;
  else review = <span style={{ color: 'var(--text3)' }}>Not reviewed</span>;
  const fundingMissing = flags.indexOf('funding_missing') >= 0;
  const fundingText = isManual || t.funding == null ? '—' : fundingMissing ? 'Not recorded'
    : (flags.indexOf('funding_approx') >= 0 ? '≈ ' : '') + prpUsd(t.funding, hide, true);
  const oneR = prpOneR(t);

  const row = <div id={'prp-row-' + t.trade_id} className="spot-grid-row" style={{ gridTemplateColumns: PRP_HIST_GRID, padding: '10px 16px', borderBottom: PRP_LINE,
                                                      fontSize: 13, color: 'var(--text2)', background: open ? 'var(--panel2)' : undefined }}>
    <div className="spot-span" style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0 }}>
      <button type="button" className="tv-btn" aria-expanded={open}
        aria-label={(open ? 'Hide' : 'Show') + ' details for the ' + sym + ' ' + t.direction + ' closed ' + prpDate(t.closed_at)}
        onClick={() => onToggle(t.trade_id)}
        style={{ width: 32, height: 32, padding: 0, flex: 'none', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 13, color: 'var(--text)' }}>
        {open ? '▾' : '▸'}</button>
      <div style={{ display: 'flex', flexDirection: 'column', minWidth: 0 }}>
        <span style={{ fontWeight: 700, color: 'var(--text)', fontSize: 14 }}>
          {sym}{(t.annotation || {}).notes && String(t.annotation.notes).trim()
            ? <span title="Has trade notes" aria-label="Has trade notes" style={{ marginLeft: 6, color: 'var(--text3)', fontWeight: 400 }}>✎</span> : null}
        </span>
        <span style={{ fontSize: 12, color: 'var(--text3)', overflowWrap: 'anywhere' }}>{prpVenueLine(t)}</span>
      </div>
    </div>
    <div className="spot-cell" data-label="Side">{prpSide(t.direction)}</div>
    {num('Leverage', lev.text, null, levTip)}
    <div className="spot-cell spot-pad-left" data-label="Opened → closed" style={{ color: 'var(--text3)' }}>{prpDate(t.opened_at) + ' → ' + prpDate(t.closed_at)}</div>
    {num('Entry → exit', prpPx(t.avg_entry) + ' → ' + prpPx(t.avg_exit))}
    {num('Stop', t.stop ? prpPx(t.stop.px) : '—', null, t.stop ? (PRP_STOP_SOURCE[t.stop.source] || t.stop.source)
         + (t.stop_correction ? ' · corrected ' + prpCorrectedWhen(t.stop_correction) + ' from ' + prpPx(t.stop_correction.from_px) : '')
         : 'No stop recorded')}
    {num('Net P&L', prpUsd(t.net_pnl, hide, true), { fontWeight: 600, color: prpMoneyColor(t.net_pnl, hide) })}
    <div className="spot-cell tv-num" data-label="R" title={rTip} style={{ textAlign: 'right', fontFamily: PRP_MONO }}>
      <div style={{ color: prpColor(t.r_multiple) }}>{prpR(t.r_multiple) + (t.r_multiple != null && t.r_basis === 'price' ? '*' : '')}</div>
      {plan && <div style={{ fontSize: 11, color: 'var(--text3)' }}>{'plan ' + (prpPlanR(plan) || prpPx(plan.nearest))}</div>}
    </div>
    <div className="spot-cell spot-pad-left" data-label="Review">{review}</div>
    <div className="spot-cell" data-label="Gate" title={g.eligible ? 'Counts toward the gate' : prpGateLong(g.reason, gateCountFrom)}>
      {g.eligible ? <span className="tv-chip ok" style={{ fontSize: 12, fontWeight: 600 }}>Counts</span>
        : <span style={{ color: 'var(--text3)' }}>{PRP_GATE_SHORT[g.reason] || g.reason || '—'}</span>}
    </div>
  </div>;
  if (!open) return row;

  const gateText = g.eligible ? 'Counts toward the gate' : prpGateLong(g.reason, gateCountFrom);
  return <React.Fragment>
    {row}
    <div className="spot-detail" style={{ padding: '16px 16px 20px 56px', borderBottom: PRP_LINE, background: 'var(--bg)',
                                          display: 'flex', flexWrap: 'wrap', gap: 28 }}>
      <div style={{ flex: '1 1 280px', display: 'flex', flexDirection: 'column', gap: 12 }}>
        <div style={PRP_FACTS}>
          <PerpsFact label="Venue">{prpVenueLine(t)}</PerpsFact>
          <PerpsFact label="Opened">{prpDate(t.opened_at, true)}</PerpsFact>
          <PerpsFact label="Closed">{prpDate(t.closed_at, true)}</PerpsFact>
          <PerpsAtOpen trade={t} />
          <PerpsAtExit trade={t} />
          <PerpsFact label="Peak size" mono>{prpSize(t.size_peak, hide)}</PerpsFact>
          {!isManual && <PerpsFact label="Fees" mono color={prpMoneyColor(t.fees == null ? null : -prpNum(t.fees), hide)}>
            {t.fees == null ? '—' : prpUsd(-prpNum(t.fees), hide, true)}</PerpsFact>}
          {!isManual && <PerpsFact label="Funding" mono>{fundingText}</PerpsFact>}
          <PerpsFact label="1R (peak size to stop)" mono>{oneR === null ? '—' : prpUsd(oneR, hide)}</PerpsFact>
          <PerpsFact label="Stop source">{t.stop ? (PRP_STOP_SOURCE[t.stop.source] || t.stop.source) : 'No stop recorded'}</PerpsFact>
          <PerpsCorrectionFact trade={t} />
          <PerpsPlanFact trade={t} model={plan} emptyText={isManual ? 'No target logged' : 'No take-profit order found'} />
          <PerpsExcursionFacts trade={t} />
          <PerpsHeldFact trade={t} />
          <PerpsFact label="Gate" color={g.eligible ? 'var(--ok)' : undefined}>{gateText}</PerpsFact>
        </div>
        {flags.filter(f => PRP_FLAGS[f]).length > 0 && <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
          {flags.filter(f => PRP_FLAGS[f]).map(f => <span key={f} className="tv-chip warn">{PRP_FLAGS[f]}</span>)}
        </div>}
        {t.before_rule && <div style={{ fontSize: 12, color: 'var(--text3)' }}>{'Opened before ' + (gateStart ? prpDate(gateStart) : 'the gate start') + ', so it does not count toward the gate.'}</div>}
      </div>
      <div style={{ flex: '2 1 420px', display: 'flex', flexDirection: 'column', gap: 16, minWidth: 0 }}>
        <PerpsReviewButtons trade={t} saver={saver} />
        <PerpsExitReason trade={t} advisor={advisor} saver={saver} />
        <PerpsTagEditor trade={t} tag={tag} onSaved={onTagSaved} />
        <PerpsNotesEditor trade={t} saver={saver} withDeviation={true} />
        {!isManual && <PerpsStopEditor trade={t} saver={saver} closed={true} />}
        {isManual && <PerpsManualDelete trade={t} saver={saver} />}
        <PerpsStatus saving={saver.saving} status={saver.status} />
      </div>
      <div style={{ flex: '1 1 100%', minWidth: 0 }}><PerpsRuleCheck trade={t} advisor={advisor} hide={hide} /></div>
    </div>
  </React.Fragment>;
}

function PerpsUnattached({ items }) {
  return <div className="tv-card" style={{ marginTop: 16 }}>
    <div className="tv-label" style={{ fontSize: 12 }}>{'Notes no longer attached to a trade (' + items.length + ')'}</div>
    <div style={{ fontSize: 13, color: 'var(--text2)', margin: '8px 0' }}>
      Their trade changed shape (for example, its first fill was corrected). Nothing was deleted.
    </div>
    {items.map(a => <div key={a.trade_id} style={{ fontSize: 13, color: 'var(--text2)', padding: '6px 0', borderTop: PRP_LINE }}>
      {(a.market === 'perp' ? 'Perp' : 'Spot') + ' · last edited ' + prpDate(a.updated_at, true) + ' · '
        + (a.has_notes ? 'has notes' : 'stop or review only')}
    </div>)}
  </div>;
}

function PerpsHistoryTab({ trades, expanded, onToggle, hide, onSaved, gateStart, gateCountFrom, unattached, advisor, tags, onTagSaved }) {
  const [earlier, setEarlierState] = usePRPState(() => prpReadLocal('perpsHistoryEarlier', '0') === '1');
  function setEarlier(v) { setEarlierState(v); prpWriteLocal('perpsHistoryEarlier', v ? '1' : '0'); }
  const earlierCount = trades.filter(t => t.before_rule).length;
  const when = v => { const ms = Date.parse(v || ''); return isNaN(ms) ? -Infinity : ms; };
  // Newest close first, then newest open (like Spot History by trade).
  const rows = trades.filter(t => earlier || !t.before_rule)
    .sort((a, b) => when(b.closed_at) - when(a.closed_at) || when(b.opened_at) - when(a.opened_at));
  const head = { fontSize: 12, lineHeight: '16px', fontWeight: 600, letterSpacing: '0.06em', textTransform: 'uppercase', color: 'var(--text3)' };
  const right = { textAlign: 'right' };
  const sinceText = gateStart ? prpDate(gateStart) : 'Sep 13';
  const toReview = rows.filter(t => t.attention === 'needs_review').length;
  const tally = prpHeldTally(rows);
  return <div>
    <div style={{ display: 'flex', alignItems: 'center', gap: 16, flexWrap: 'wrap', marginBottom: 12, fontSize: 13, color: 'var(--text3)' }}>
      <span>{rows.length + ' closed' + (toReview ? ' · ' + toReview + ' to review' : '')}</span>
      <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6, cursor: 'pointer' }}>
        <input type="checkbox" checked={earlier} onChange={e => setEarlier(e.target.checked)} />
        {'Show trades opened before ' + sinceText + ' (' + earlierCount + ')'}
      </label>
    </div>
    {tally && <div title={'Counts the closed trades in this view. ' + PRP_HELD_TIP + ' Not tested: no planned target or stop, not worked out yet, or being re-checked.'}
      style={{ fontSize: 13, color: 'var(--text2)', marginBottom: 12 }}>{tally}</div>}
    <PerpsRulesTally rows={rows} advisor={advisor} tags={tags} />
    {trades.length === 0 ? <div className="tv-card" style={{ color: 'var(--text3)', padding: 20, textAlign: 'center', fontSize: 14 }}>No closed perp trades yet.</div>
    : rows.length === 0 ? <div className="tv-card" style={{ color: 'var(--text3)', padding: 20, textAlign: 'center', fontSize: 14 }}>No closed trades in this view.</div>
    : <div className="tv-card" style={{ padding: 0, overflow: 'hidden' }}>
        <div className="spot-grid-row spot-grid-head" style={{ ...head, gridTemplateColumns: PRP_HIST_GRID, alignItems: 'end',
                                                               padding: '12px 16px', borderBottom: PRP_HEAD_LINE }}>
          <span>Symbol</span><span>Side</span><span style={right}>Lev</span><span className="spot-pad-left">Opened → closed</span>
          <span style={right}>Entry → exit</span><span style={right}>Stop</span><span style={right}>Net P&L</span>
          <span style={right}>R</span><span className="spot-pad-left">Review</span><span>Gate</span>
        </div>
        {rows.map(t => <PerpsHistoryRow key={t.trade_id} trade={t} open={!!expanded[t.trade_id]} onToggle={onToggle}
          hide={hide} onSaved={onSaved} gateStart={gateStart} gateCountFrom={gateCountFrom}
          advisor={advisor} tag={tags[t.trade_id]} onTagSaved={onTagSaved} />)}
      </div>}
    <div style={{ fontSize: 13, color: 'var(--text3)', marginTop: 10 }}>
      * R from prices (manual trades have no fee data). R uses the stop in force 10 minutes after entry, so a stop corrected right after opening counts as the plan. "plan" under R is the first take-profit you set, in R from entry to the stop (by price, before fees). Lev on closed synced trades comes from the trade-open snapshot; trades closed before it existed show "—". After exit: best and worst during the trade are in R by price against that stop; "had you held the plan" follows your first take-profit and that stop from the open to 14 days after the exit, and one candle touching both counts as unclear.
    </div>
    {unattached.length > 0 && <PerpsUnattached items={unattached} />}
  </div>;
}

/* ── the top cards ───────────────────────────────────────────────────── */

function PerpsCards({ summary, openTrades, hide }) {
  const perp = summary.perp || {};
  const all = perp.all_time || {};
  const gate = summary.gate || {};
  const sinceText = gate.start ? prpDate(gate.start) : 'Sep 13';
  // Landing 15: the gate counts from its own day; the Closed card keeps the rules-era start.
  const countText = gate.count_from ? prpDate(gate.count_from) : sinceText;

  const net = prpNum(perp.net_pnl);
  const closedSub = (perp.closed_count || 0) + ' closed · ' + (perp.win_count || 0) + 'W / ' + (perp.loss_count || 0) + 'L'
    + (perp.avg_r != null ? ' · avg ' + prpR(perp.avg_r) : '');

  const synced = openTrades.filter(t => t.source !== 'manual');
  const manualOpen = openTrades.length - synced.length;
  const unrKnown = synced.filter(t => prpNum(t.unrealized_pnl) !== null);
  const unr = unrKnown.reduce((s, t) => s + prpNum(t.unrealized_pnl), 0);
  const funding = synced.reduce((s, t) => s + (prpNum(t.funding) || 0), 0);
  const unrSubParts = [openTrades.length + ' open'];
  if (synced.length) unrSubParts.push('funding ' + prpUsd(funding, hide, true));
  if (manualOpen) unrSubParts.push(manualOpen + ' manual, no price feed');
  if (unrKnown.length < synced.length) unrSubParts.push((synced.length - unrKnown.length) + ' waiting for prices');

  let risk = 0, noStop = 0, unpriced = 0, freeRide = 0;
  openTrades.forEach(t => {
    if (!t.stop) { noStop += 1; return; }
    const r = prpOpenRisk(t);
    if (r === null) { unpriced += 1; return; }
    if (r === 0) freeRide += 1;
    risk += r;
  });
  const riskNotes = [];
  if (noStop) riskNotes.push(noStop === 1 ? '1 open trade has no stop' : noStop + ' open trades have no stop');
  if (freeRide) riskNotes.push(freeRide === 1 ? '1 stop at or past entry (no risk)' : freeRide + ' stops at or past entry (no risk)');
  if (unpriced) riskNotes.push(unpriced + ' without a price');

  const target = Number(gate.target) || 0;
  const count = Number(gate.eligible_count) || 0;
  const exp = prpNum(gate.expectancy_r);
  const unlocked = !!gate.unlocked;
  const check = (ok, text, need) => <span>
    <span aria-hidden="true" style={{ color: ok ? 'var(--ok)' : 'var(--fail)', fontWeight: 700, marginRight: 6 }}>{ok ? '✓' : '✗'}</span>
    <span style={{ color: 'var(--text)' }}>{text}</span>{' '}
    <span style={{ color: 'var(--text3)', whiteSpace: 'nowrap' }}>{'(' + need + ')'}</span>
    <span className="sr-only" style={{ position: 'absolute', width: 1, height: 1, overflow: 'hidden', clip: 'rect(0 0 0 0)' }}>{ok ? ' passed' : ' not passed'}</span>
  </span>;

  return <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12, marginBottom: 16 }}>
    <PerpsKpi label={'Closed since ' + sinceText} value={net === null ? '—' : prpUsd(net, hide, true)} color={prpMoneyColor(net, hide)}
      title={'All time: ' + (all.closed_count || 0) + ' closed · ' + prpUsd(all.net_pnl, hide, true)}
      sub={<div style={{ fontSize: 13, color: 'var(--text3)', marginTop: 4 }}>{closedSub}</div>} />
    <PerpsKpi label="Open unrealized" value={synced.length ? prpUsd(unr, hide, true) : '—'} color={synced.length ? prpMoneyColor(unr, hide) : undefined}
      sub={<div style={{ fontSize: 13, color: 'var(--text3)', marginTop: 4 }}>{unrSubParts.join(' · ')}</div>} />
    <PerpsKpi label="Open risk at stops" value={prpUsd(risk, hide)}
      title="What every open perp trade would lose from entry to its stop, at its current size. A stop at or past entry counts as no risk. Stops entered here count, even though they aren't orders on the venue."
      sub={<div style={{ fontSize: 13, marginTop: 4, color: noStop ? 'var(--warn)' : 'var(--text3)' }}>
        {riskNotes.length ? riskNotes.join(' · ') : 'entry to stop · current size'}</div>} />
    <PerpsKpi label="Risk gate · 1% → 2%"
      title={'Counts closed perp trades opened since ' + countText + ' (UTC) that you marked Followed, with a stop placed before they closed. Both checks must pass to move to 2%.'}>
      <div style={{ fontSize: 20, lineHeight: '26px', fontWeight: 700, marginTop: 6, color: unlocked ? 'var(--ok)' : 'var(--warn)' }}>
        {unlocked ? '2% allowed' : 'Stay at 1%'}</div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 2, marginTop: 4, fontSize: 13, color: 'var(--text2)' }}>
        {check(count >= target, count + ' rule-following since ' + countText.split(' ').join(' '), target + '+ needed')}
        {check(exp !== null && exp > 0, 'Average R ' + (exp === null ? '—' : (exp > 0 ? '+' : '') + exp.toFixed(2)), 'above 0 needed')}
      </div>
    </PerpsKpi>
  </div>;
}

/* ── Transactions (Landing 3b) ───────────────────────────────────────── */

const PRP_TX_GRID = 'minmax(130px,1fr) minmax(56px,0.5fr) minmax(52px,0.45fr) minmax(170px,1.4fr) '
  + 'repeat(4,minmax(80px,0.8fr)) minmax(96px,0.8fr)';
const PRP_LEV_MAX = 1000;            // TRADE_LOG_LEVERAGE_MAX on the server

function prpEmptyForm() {
  return { ticker: '', direction: 'long', leverage: '', qty: '', entry_price: '', stop_price: '', target_price: '',
           venue: '', entered_at: prpNowLocal(), exit_price: '', exited_at: '', followed: '', deviation_note: '', notes: '' };
}

// The synced-fills card: one line per venue (wallet labels only).
function PerpsSyncCard({ sync }) {
  const venues = Array.isArray(sync) ? sync : [];
  return <div className="tv-card" style={{ display: 'flex', flexDirection: 'column', gap: 8, padding: '16px 20px' }}>
    <span style={PRP_SECTION}>Synced fills</span>
    {venues.length === 0 && <span style={{ fontSize: 14, color: 'var(--text3)' }}>No perp wallets are synced yet.</span>}
    {venues.map(v => <div key={v.venue} style={{ fontSize: 14, color: 'var(--text2)', display: 'flex', flexWrap: 'wrap', gap: '4px 10px' }}>
      <span style={{ fontWeight: 600, color: 'var(--text)' }}>{v.venue}</span>
      <span style={{ color: 'var(--text3)' }}>{v.wallets === 1 ? '1 wallet' : v.wallets + ' wallets'}</span>
      <span style={{ color: 'var(--text3)' }}>{v.in_flight ? 'syncing now'
        : v.last_ok_at ? 'last good sync ' + prpAgo(v.last_ok_at) + ' (' + prpDate(v.last_ok_at, true) + ')' : 'not synced yet'}</span>
      {v.failing && v.failing.length > 0 && <span role="status" style={{ color: 'var(--warn)' }}>{'last attempt failed for ' + v.failing.join(', ')}</span>}
    </div>)}
    <span style={{ fontSize: 13, color: 'var(--text3)' }}>Every 10 minutes while the app is open, every 2 hours otherwise. Trades are built from these fills automatically.</span>
  </div>;
}

// The manual perp trade form (moved from Trade Log; perp only, ruling 3):
// Leverage, and a finished trade can be logged in one step (ruling 5):
// Exit price with Followed / Deviated required, Closed and the deviation note optional.
function PerpsManualForm({ onSaved, onClose }) {
  const [form, setForm] = usePRPState(prpEmptyForm);
  const [tickers, setTickers] = usePRPState(null);
  const [saving, setSaving] = usePRPState(false);
  const [error, setError] = usePRPState(null);
  const aliveRef = usePRPRef(true);
  usePRPEffect(() => () => { aliveRef.current = false; }, []);
  usePRPEffect(() => {
    api('/api/trading/scanner/noodle-state').then(d => {
      if (!aliveRef.current) return;
      setTickers((d && Array.isArray(d.symbols) ? d.symbols : []).map(x => x && x.symbol).filter(Boolean));
    }).catch(() => { if (aliveRef.current) setTickers([]); });
  }, []);
  function set(k, v) { setForm(f => Object.assign({}, f, { [k]: v })); }

  const blank = v => String(v).trim() === '';
  const closing = !blank(form.exit_price);
  const problems = [];
  if (blank(form.ticker)) problems.push('a symbol');
  if (!prpPositive(form.qty)) problems.push('a size above 0');
  if (!prpPositive(form.entry_price)) problems.push('an entry price above 0');
  if (!prpPositive(form.stop_price)) problems.push('a stop price above 0');
  const sameEntryStop = prpPositive(form.entry_price) && prpPositive(form.stop_price) && Number(form.entry_price) === Number(form.stop_price);
  const levBad = !blank(form.leverage) && !(prpPositive(form.leverage) && Number(form.leverage) <= PRP_LEV_MAX);
  const targetBad = !blank(form.target_price) && !prpPositive(form.target_price);
  const exitBad = closing && !prpPositive(form.exit_price);
  const followedMissing = closing && form.followed === '';
  const openedMs = Date.parse(form.entered_at || '');
  const closedMs = Date.parse(form.exited_at || '');
  const closedEarly = closing && !isNaN(openedMs) && !isNaN(closedMs) && closedMs < openedMs;
  const closedWithoutExit = !closing && !blank(form.exited_at);
  const valid = !problems.length && !sameEntryStop && !levBad && !targetBad && !exitBad && !followedMissing && !closedEarly && !closedWithoutExit;
  const messages = [];
  if (sameEntryStop) messages.push("Entry and stop can't be equal (zero risk).");
  if (levBad) messages.push('Leverage must be above 0 and at most ' + PRP_LEV_MAX + '.');
  if (targetBad) messages.push('Target must be above 0, or blank.');
  if (exitBad) messages.push('Exit price must be above 0, or blank while the trade is open.');
  if (followedMissing) messages.push('A closed trade needs Followed or Deviated.');
  if (closedEarly) messages.push("Closed can't be before Opened.");
  if (closedWithoutExit) messages.push('Closed needs an exit price.');

  function submit() {
    if (!valid || saving) return;
    setSaving(true);
    setError(null);
    const body = {
      ticker: form.ticker.trim(), direction: form.direction, market: 'perp', source: 'manual',
      venue: form.venue.trim() || null,
      entry_price: Number(form.entry_price), stop_price: Number(form.stop_price), qty: Number(form.qty),
      target_price: blank(form.target_price) ? null : Number(form.target_price),
      leverage: blank(form.leverage) ? null : Number(form.leverage),
      entered_at: prpLocalToIso(form.entered_at),
      notes: prpTextOrNull(form.notes),
    };
    if (closing) {
      body.exit_price = Number(form.exit_price);
      body.followed_rules = Number(form.followed);
      if (!blank(form.exited_at)) body.exited_at = prpLocalToIso(form.exited_at);
      if (!blank(form.deviation_note)) body.deviation_note = form.deviation_note;
    }
    api('/api/spot/trade-log', { method: 'POST', body: JSON.stringify(body) }).then(() => {
      if (!aliveRef.current) return;
      setSaving(false);
      setForm(prpEmptyForm());
      onSaved();
      onClose();
    }).catch(e => {
      if (!aliveRef.current) return;
      setSaving(false);
      setError(prpErr(e));
    });
  }

  const field = { display: 'flex', flexDirection: 'column', gap: 6, fontSize: 13, fontWeight: 500, color: 'var(--text3)' };
  const input = (k, label, extra) => <label style={field}>{label}
    <input className="tv-input" value={form[k]} onChange={e => set(k, e.target.value)} {...(extra || {})} />
  </label>;
  return <div className="tv-card" style={{ padding: 20, display: 'flex', flexDirection: 'column', gap: 14 }}>
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
      <span style={PRP_SECTION}>Add a manual perp trade · venues without a feed</span>
    </div>
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(160px, 1fr))', gap: 12 }}>
      <label style={field}>Symbol
        <input className="tv-input" list="prp-ticker-options" value={form.ticker} placeholder="e.g. BTC"
          onChange={e => set('ticker', e.target.value)} />
        <datalist id="prp-ticker-options">{(tickers || []).map(x => <option key={x} value={x} />)}</datalist>
      </label>
      <label style={field}>Side
        <select className="tv-select" value={form.direction} onChange={e => set('direction', e.target.value)}>
          <option value="long">Long</option>
          <option value="short">Short</option>
        </select>
      </label>
      {input('leverage', 'Leverage', { inputMode: 'decimal', placeholder: 'e.g. 5' })}
      {input('qty', 'Size', { inputMode: 'decimal', placeholder: 'Units' })}
      {input('entry_price', 'Entry price', { inputMode: 'decimal', placeholder: '0.00' })}
      {input('stop_price', 'Stop price', { inputMode: 'decimal', placeholder: '0.00' })}
      {input('target_price', 'Target (optional)', { inputMode: 'decimal', placeholder: '0.00' })}
      {input('venue', 'Venue', { placeholder: 'e.g. Kraken' })}
      {input('entered_at', 'Opened', { type: 'datetime-local' })}
      {input('exit_price', 'Exit price', { inputMode: 'decimal', placeholder: 'Blank if still open' })}
      {input('exited_at', 'Closed', { type: 'datetime-local', disabled: !closing, title: closing ? 'Blank = now' : 'Fill the exit price first' })}
      <label style={field}>Followed the rules?
        <select className="tv-select" value={form.followed} disabled={!closing} onChange={e => set('followed', e.target.value)}>
          <option value="">{closing ? 'Choose…' : 'Once closed'}</option>
          <option value="1">Followed</option>
          <option value="0">Deviated</option>
        </select>
      </label>
    </div>
    {closing && <label style={field}>Deviation note (optional)
      <input className="tv-input" maxLength={PRP_NOTE_MAX} value={form.deviation_note} placeholder="What was different from the plan"
        onChange={e => set('deviation_note', e.target.value)} />
    </label>}
    <label style={field}>Trade notes
      <textarea className="tv-input" rows={3} maxLength={PRP_NOTE_MAX} style={{ resize: 'vertical', fontFamily: 'inherit', fontSize: 14 }}
        value={form.notes} placeholder="Why you took it and the plan" onChange={e => set('notes', e.target.value)} />
    </label>
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
      <button type="button" className="tv-btn primary" style={prpBtn(!valid || saving)} disabled={!valid || saving} onClick={submit}>{saving ? 'Saving…' : 'Save trade'}</button>
      <button type="button" className="tv-btn" style={prpBtn(saving)} disabled={saving} onClick={onClose}>Cancel</button>
      {!valid && problems.length > 0 && <span style={{ fontSize: 13, color: 'var(--text3)' }}>{'Needs ' + problems.join(', ') + '.'}</span>}
      {messages.map(m => <span key={m} style={{ fontSize: 13, color: 'var(--fail)' }}>{m}</span>)}
      {error && <span role="alert" style={{ fontSize: 13, color: 'var(--fail)' }}>{error}</span>}
    </div>
  </div>;
}

function PerpsTransactionsTab({ trades, sync, hide, onSaved, onJump }) {
  const [adding, setAdding] = usePRPState(false);
  const manual = trades.filter(t => t.source === 'manual');
  const head = { fontSize: 12, lineHeight: '16px', fontWeight: 600, letterSpacing: '0.06em', textTransform: 'uppercase', color: 'var(--text3)' };
  const right = { textAlign: 'right' };
  const num = (label, content) => <div className="spot-cell tv-num" data-label={label} style={{ textAlign: 'right', fontFamily: PRP_MONO }}>{content}</div>;
  return <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
    <PerpsSyncCard sync={sync} />
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
      <span style={PRP_SECTION}>{'Manual trades · ' + (manual.length === 1 ? '1 trade' : manual.length + ' trades')}</span>
      {!adding && <button type="button" className="tv-btn" onClick={() => setAdding(true)}>+ Add manual trade</button>}
    </div>
    {adding && <PerpsManualForm onSaved={onSaved} onClose={() => setAdding(false)} />}
    {manual.length === 0
      ? <div className="tv-card" style={{ color: 'var(--text3)', padding: 20, textAlign: 'center', fontSize: 14 }}>
          No manual perp trades. Use them for venues without a fill feed.</div>
      : <div className="tv-card" style={{ padding: 0, overflow: 'hidden' }}>
          <div className="spot-grid-row spot-grid-head" style={{ ...head, gridTemplateColumns: PRP_TX_GRID, alignItems: 'end',
                                                                 padding: '12px 16px', borderBottom: PRP_HEAD_LINE }}>
            <span>Symbol</span><span>Side</span><span style={right}>Lev</span><span className="spot-pad-left">Opened → closed</span>
            <span style={right}>Size</span><span style={right}>Entry</span><span style={right}>Stop</span><span style={right}>Exit</span>
            <span className="spot-pad-left"></span>
          </div>
          {manual.map(t => {
            const lev = prpLev(t.leverage, t.leverage_type);
            const closed = t.status === 'closed';
            return <div key={t.trade_id} className="spot-grid-row" style={{ gridTemplateColumns: PRP_TX_GRID, padding: '10px 16px',
                                                                            borderBottom: PRP_LINE, fontSize: 13, color: 'var(--text2)' }}>
              <div className="spot-span" style={{ display: 'flex', flexDirection: 'column', minWidth: 0 }}>
                <span style={{ fontWeight: 700, color: 'var(--text)', fontSize: 14 }}>{t.symbol}</span>
                <span style={{ fontSize: 12, color: 'var(--text3)' }}>{prpVenueLine(t)}</span>
              </div>
              <div className="spot-cell" data-label="Side">{prpSide(t.direction)}</div>
              {num('Leverage', lev.text)}
              <div className="spot-cell spot-pad-left" data-label="Opened → closed" style={{ color: 'var(--text3)' }}>
                {prpDate(t.opened_at) + ' → ' + (closed ? prpDate(t.closed_at) : 'open')}</div>
              {num('Size', prpSize(t.size_peak, hide))}
              {num('Entry', prpPx(t.avg_entry))}
              {num('Stop', t.stop ? prpPx(t.stop.px) : '—')}
              {num('Exit', closed ? prpPx(t.avg_exit) : '—')}
              <div className="spot-cell spot-pad-left">
                <button type="button" className="tv-btn" style={PRP_SMALL_BTN} onClick={() => onJump(t)}
                  aria-label={'Open the ' + t.symbol + ' ' + t.direction + ' trade in ' + (closed ? 'History' : 'Open positions')}>
                  {closed ? 'In History' : 'In Open positions'}</button>
              </div>
            </div>;
          })}
        </div>}
    <div style={{ fontSize: 13, color: 'var(--text3)' }}>
      Close, review, add notes to or delete a manual trade from its row in Open positions or History. Manual trades have no price feed, so they show no mark or unrealized P&L.
    </div>
  </div>;
}

/* ── the screen ──────────────────────────────────────────────────────── */

function prpSyncLine(sync) {
  const venues = Array.isArray(sync) ? sync : [];
  if (!venues.length) return { text: '', tip: '', warn: false };
  const oks = venues.map(v => v.last_ok_at);
  const oldest = oks.some(x => !x) ? null : oks.slice().sort((a, b) => Date.parse(a) - Date.parse(b))[0];
  const failing = venues.filter(v => v.failing && v.failing.length);
  const busy = venues.some(v => v.in_flight);
  const tip = venues.map(v => v.venue + ': ' + (v.last_ok_at ? 'last good sync ' + prpDate(v.last_ok_at, true) : 'not synced yet')
    + (v.failing && v.failing.length ? ' · last attempt failed for ' + v.failing.join(', ') : '')).join('\n');
  const text = busy ? 'Syncing fills…' : oldest ? 'Fills synced ' + prpAgo(oldest) : 'Fills not synced yet';
  return { text: text + (failing.length ? ' · a sync failed' : ''), tip, warn: failing.length > 0 };
}

function PerpsScreen({ hideValues, refreshTrigger }) {
  const [data, setData] = usePRPState(null);
  const [loading, setLoading] = usePRPState(false);
  const [loadError, setLoadError] = usePRPState(null);
  const [updateError, setUpdateError] = usePRPState(null);
  const [updatedAt, setUpdatedAt] = usePRPState(null);
  const [expanded, setExpanded] = usePRPState({});
  const [tab, setTabState] = usePRPState(() => {
    const v = prpReadLocal('perpsSubTab', 'open');
    return PRP_TABS.some(t => t.id === v) ? v : 'open';
  });
  const [rulesData, setRulesData] = usePRPState(null);
  const [rulesLoading, setRulesLoading] = usePRPState(false);
  const [rulesError, setRulesError] = usePRPState(null);
  const [tags, setTags] = usePRPState({});
  const reqRef = usePRPRef(0);
  const rulesReqRef = usePRPRef(0);
  const tagsReqRef = usePRPRef(0);
  const tagsEpochRef = usePRPRef(0);      // bumped by every tag save: a GET started before it is ignored
  const hasDataRef = usePRPRef(false);
  const coldTimerRef = usePRPRef(null);
  const coldCountRef = usePRPRef(0);
  const firstRef = usePRPRef(true);

  function setTab(v) { setTabState(v); prpWriteLocal('perpsSubTab', v); }

  function load() {
    const mine = ++reqRef.current;
    setLoading(true);
    api('/api/trading/trades').then(d => {
      if (mine !== reqRef.current) return;
      if (!d || !Array.isArray(d.trades) || !d.summary) throw new Error('Unexpected response');
      hasDataRef.current = true;
      setData(d);
      setLoadError(null);
      setUpdateError(null);
      setUpdatedAt(new Date());
      setLoading(false);
      const counts = tradesNavCounts(d);    // the nav's Spot and Perps badges (utils.js)
      if (counts) window.dispatchEvent(new CustomEvent('trades-attention', { detail: counts }));
      const cold = d.trades.some(t => t.market === 'perp' && t.source !== 'manual' && t.status !== 'closed'
                                      && (t.live === null || t.unrealized_pnl === null));
      if (cold && coldCountRef.current < PRP_COLD_RETRY_MAX) {
        coldCountRef.current += 1;
        clearTimeout(coldTimerRef.current);
        coldTimerRef.current = setTimeout(load, PRP_COLD_RETRY_MS);
      }
    }).catch(e => {
      if (mine !== reqRef.current) return;
      setLoading(false);
      if (hasDataRef.current) setUpdateError(prpErr(e));
      else setLoadError(prpErr(e));
    });
  }

  // The advisor read: its own request counter, its own error, never blanks
  // the page. The last good answer stays while a newer one is on its way.
  function loadRules() {
    const mine = ++rulesReqRef.current;
    setRulesLoading(true);
    api('/api/trading/advisor/perps').then(d => {
      if (mine !== rulesReqRef.current) return;
      if (!d || typeof d.trades !== 'object' || !Array.isArray(d.rules)) throw new Error('Unexpected response');
      setRulesData(d);
      setRulesError(null);
      setRulesLoading(false);
    }).catch(e => {
      if (mine !== rulesReqRef.current) return;
      setRulesLoading(false);
      setRulesError(prpErr(e));
    });
  }

  function loadTags() {
    const mine = ++tagsReqRef.current;
    const epoch = tagsEpochRef.current;
    api('/api/trading/trade-tags').then(d => {
      if (mine !== tagsReqRef.current || epoch !== tagsEpochRef.current) return;
      if (d && d.tags && typeof d.tags === 'object') setTags(d.tags);
    }).catch(() => { /* the editors keep what they have; a failed read is not shown */ });
  }

  // A tag was saved: show it now, and re-read the verdicts (E2 and E3 use it).
  function onTagSaved(tradeId, resp) {
    tagsEpochRef.current += 1;
    tagsReqRef.current += 1;
    setTags(prev => {
      const next = Object.assign({}, prev);
      if (resp && (resp.setup || resp.poi)) next[tradeId] = resp; else delete next[tradeId];
      return next;
    });
    loadRules();
  }

  function loadAll() { load(); loadRules(); loadTags(); }
  // A save on a row re-reads the trades and the verdicts, not the tags. The
  // cold-cache retries call load() alone.
  function onSavedAll() { load(); loadRules(); }

  usePRPEffect(() => {
    loadAll();
    return () => {
      reqRef.current += 1;              // late answers are ignored after unmount
      rulesReqRef.current += 1;
      tagsReqRef.current += 1;
      clearTimeout(coldTimerRef.current);
    };
  }, []);

  usePRPEffect(() => {
    if (firstRef.current) { firstRef.current = false; return; }
    loadAll();
  }, [refreshTrigger]);

  function toggle(id) { setExpanded(x => Object.assign({}, x, { [id]: !x[id] })); }
  // From the Transactions list: open the trade's row where it lives (an older
  // closed trade turns on History's Show earlier first) and scroll to it.
  function jump(t) {
    const closed = t.status === 'closed';
    if (closed && t.before_rule) prpWriteLocal('perpsHistoryEarlier', '1');
    setExpanded(x => Object.assign({}, x, { [t.trade_id]: true }));
    setTab(closed ? 'history' : 'open');
    setTimeout(() => {
      const el = document.getElementById('prp-row-' + t.trade_id);
      if (el && el.scrollIntoView) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }, 60);
  }

  const title = <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
    <h1 style={{ margin: 0, fontSize: 20, lineHeight: '26px', fontWeight: 700, color: 'var(--text)' }}>Perps</h1>
    <div style={{ fontSize: 13, lineHeight: '18px', color: 'var(--text3)' }}>Hyperliquid and TxFlow trades, built from your fills, plus trades you enter by hand.</div>
  </div>;

  if (!data && loadError) {
    return <div>
      <div style={{ marginBottom: 16 }}>{title}</div>
      <div className="tv-card" style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
        <span role="alert" style={{ color: 'var(--fail)', fontSize: 14 }}>{"Couldn't load trades: " + loadError}</span>
        <button type="button" className="tv-btn" style={prpBtn(loading)} disabled={loading} onClick={load}>Retry</button>
      </div>
    </div>;
  }
  if (!data) {
    return <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: 240, gap: 10, color: 'var(--text3)', fontSize: 14 }}>
      <span style={{ display: 'inline-block', animation: 'spin 0.8s linear infinite', fontSize: 18 }}>↻</span>
      Loading trades…
    </div>;
  }

  const perps = data.trades.filter(t => t.market === 'perp');
  const openTrades = perps.filter(t => t.status !== 'closed');
  const closedTrades = perps.filter(t => t.status === 'closed');
  const untracked = Array.isArray(data.untracked_positions) ? data.untracked_positions : [];
  const unattached = Array.isArray(data.unattached_annotations) ? data.unattached_annotations : [];
  const gateStart = (data.summary.gate && data.summary.gate.start) || null;
  const gateCountFrom = (data.summary.gate && data.summary.gate.count_from) || null;
  const sync = prpSyncLine(data.sync);
  const updatedText = updatedAt ? 'Updated ' + String(updatedAt.getHours()).padStart(2, '0') + ':' + String(updatedAt.getMinutes()).padStart(2, '0') : '';
  const advisor = { data: rulesData, loading: rulesLoading, error: rulesError, reload: loadRules };
  const attention = { open: openTrades.filter(t => t.attention === 'needs_stop').length,
                      history: closedTrades.filter(t => t.attention === 'needs_review').length };

  return <div>
    <div style={{ display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap', marginBottom: 16 }}>
      {title}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap', fontSize: 13 }}>
        {updateError && <span role="alert" style={{ color: 'var(--fail)' }}>{'Update failed: ' + updateError}</span>}
        {sync.text && <span title={sync.tip} style={{ color: sync.warn ? 'var(--warn)' : 'var(--text3)' }}>{sync.text}</span>}
        <span style={{ color: 'var(--text3)' }}>{loading ? 'Updating…' : updatedText}</span>
        <button type="button" className="tv-btn" style={prpBtn(loading, { fontSize: 13 })} disabled={loading} onClick={loadAll}>Reload</button>
      </div>
    </div>

    <PerpsCards summary={data.summary} openTrades={openTrades} hide={hideValues} />

    <div role="group" aria-label="Perps sections" style={{ display: 'flex', gap: 4, marginBottom: 16, flexWrap: 'wrap', alignItems: 'center' }}>
      {PRP_TABS.map(t => <button key={t.id} type="button" className="tv-btn" aria-pressed={tab === t.id}
        style={{ background: tab === t.id ? 'var(--panel3)' : 'transparent', borderColor: tab === t.id ? 'var(--accent-line)' : 'var(--line)',
                 color: tab === t.id ? 'var(--text)' : 'var(--text3)', fontWeight: tab === t.id ? 600 : 400 }}
        onClick={() => setTab(t.id)}>
        {t.label}
        {attention[t.id] > 0 && <span className="tv-chip warn" style={{ marginLeft: 6, fontSize: 11, padding: '0 6px' }}
          aria-label={attention[t.id] + (t.id === 'open' ? ' need a stop' : ' need review')}
          title={t.id === 'open' ? 'Needs a stop' : 'Needs review'}>{attention[t.id]}</span>}
      </button>)}
    </div>

    {tab === 'open' && <PerpsOpenTab trades={openTrades} untracked={untracked} expanded={expanded} onToggle={toggle}
      hide={hideValues} onSaved={onSavedAll} advisor={advisor} tags={tags} onTagSaved={onTagSaved} />}
    {tab === 'history' && <PerpsHistoryTab trades={closedTrades} expanded={expanded} onToggle={toggle} hide={hideValues}
      onSaved={onSavedAll} gateStart={gateStart} gateCountFrom={gateCountFrom} unattached={unattached} advisor={advisor} tags={tags} onTagSaved={onTagSaved} />}
    {tab === 'transactions' && <PerpsTransactionsTab trades={perps} sync={data.sync} hide={hideValues} onSaved={onSavedAll} onJump={jump} />}
    {tab === 'rules' && <PerpsRulesTab advisor={advisor} hide={hideValues} onChanged={loadRules} />}

    {(tab === 'open' || tab === 'history') && <div style={{ fontSize: 12, color: 'var(--text3)', marginTop: 12 }}>
      Perp fills sync every 10 minutes while the app is open, and every 2 hours otherwise. Trades on venues without a feed are added by hand on the Transactions tab.
    </div>}
  </div>;
}

window.PerpsScreen = PerpsScreen;
