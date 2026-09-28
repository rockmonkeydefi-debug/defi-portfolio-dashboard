/* ===== DASHBOARD SCREEN ===== */

const { useState: useDashState, useEffect: useDashEffect, useMemo: useDashMemo, useCallback: useDashCallback, useRef: useDashRef } = React;

/* ── live total (/api/portfolio/total) helpers ── */
// A timestamp with a Z / ±HH:MM suffix parses as-is; a naive ISO string is
// server time, which is UTC, so it is read as UTC by appending 'Z'.
function _dashParseUtc(s) {
  if (!s || typeof s !== 'string') return null;
  const aware = /(Z|[+-]\d{2}:?\d{2})$/.test(s);
  const d = new Date(aware ? s : s + 'Z');
  return isNaN(d.getTime()) ? null : d;
}

function _dashComp(total, key) {
  const list = total && Array.isArray(total.components) ? total.components : [];
  return list.find(c => c && c.key === key) || null;
}

function _dashNonZero(v) {
  return Math.round(Math.abs(v) * 100) !== 0;
}

// Clock label: HH:MM:SS today, "Mon D, HH:MM" on another day, '—' for none.
function _dashClock(d) {
  if (!d) return '—';
  const now = new Date();
  if (d.toDateString() === now.toDateString()) {
    return d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  }
  return d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

function _dashHHMM(d) {
  return d ? d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' }) : '—';
}

function _dashDateTime(d) { return d ? d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : '—'; }

// Hidden-values masks (design-audit.md "Dashboard redesign rulings (Sep 27)", ruling 6).
const DASH_MASK_MONEY = '$••••••';
const DASH_MASK_TOTAL = '$•••,•••.••';
const DASH_MASK_SUB   = '$••••';
const DASH_MASK_PCT   = '••%';
const DASH_MASK_COUNT = '••';
const DASH_MASK_WARNING = '⚠ Details hidden while values are hidden';

// Parts table rows, in order (compose_total component keys).
const DASH_PART_ROWS = [
  ['wallet_tokens', 'Wallet tokens'], ['stablecoins', 'Stablecoins'], ['maxfi_lp', 'MaxFi LP'],
  ['other_lp', 'Other LP'], ['lp_uncollected', 'LP fees'], ['maxfi_uncollected', 'MaxFi fees'],
  ['hyperliquid', 'Hyperliquid'], ['lending_net', 'Lending (net)'], ['gmx', 'GMX collateral'],
];
const DASH_IDLE_KEYS = ['wallet_tokens', 'stablecoins', 'maxfi_lp', 'maxfi_uncollected', 'hyperliquid'];
// A part's as-of turns --dash-warn when older than this.
const DASH_STALE_MS = { hyperliquid: 30 * 60000, maxfi_uncollected: 24 * 3600000 };
const DASH_STALE_DEFAULT_MS = 135 * 60000;

function _dashNum(v) {
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

// Hyperliquid sub-line: "spot $S · + perp $P · perp $P inside spot · perp $P not counted".
function _dashHlSub(comp, money) {
  const wallets = (comp && comp.detail && Array.isArray(comp.detail.wallets)) ? comp.detail.wallets : [];
  if (!wallets.length) return null;
  let spot = 0;
  const perp = { counted: 0, inside_spot: 0, not_counted_unknown_mode: 0 };
  const seen = { counted: false, inside_spot: false, not_counted_unknown_mode: false };
  for (const w of wallets) {
    for (const x of (w.spot || [])) { if (x && x.value != null) spot += Number(x.value) || 0; }
    if (w.perp_treatment in perp) {
      perp[w.perp_treatment] += Number(w.perp_account_value) || 0;
      seen[w.perp_treatment] = true;
    }
  }
  const parts = ['spot ' + money(spot)];
  if (seen.counted) parts.push('+ perp ' + money(perp.counted));
  if (seen.inside_spot) parts.push('perp ' + money(perp.inside_spot) + ' inside spot');
  if (seen.not_counted_unknown_mode) parts.push('perp ' + money(perp.not_counted_unknown_mode) + ' not counted');
  return parts.join(' · ');
}

// /api/portfolio/total re-check: a cold cache or a still-loading Hyperliquid
// part is retried every 10 s, at most 4 requests per fetch.
const DASH_TOTAL_RETRY_MS = 10000;
const DASH_TOTAL_MAX_ATTEMPTS = 4;
// A request that has not answered after 30 s is aborted (-> 'unavailable').
const DASH_TOTAL_TIMEOUT_MS = 30000;

/* ── BTC Zone Bar ── */
const BTC_ZONES = [
  { key: 'bear',   label: 'Bear',         color: 'var(--fail)',    chip: 'Risk',      chipCls: 'fail' },
  { key: 'accum',  label: 'Accum.',       color: '#f97316',        chip: 'Caution',   chipCls: 'warn' },
  { key: 'value',  label: 'Value Window', color: 'var(--warn)',    chip: 'Favorable', chipCls: 'ok' },
  { key: 'bull',   label: 'Bull',         color: 'var(--ok-soft)', chip: 'Favorable', chipCls: 'ok' },
  { key: 'euphoria', label: 'Euphoria',   color: 'var(--ok)',      chip: 'Caution',   chipCls: 'warn' },
];

function _deriveZone(btcPrice, ma200, fg) {
  if (!btcPrice || !ma200) return null;
  if (btcPrice < ma200 * 0.85) return 'bear';
  if (btcPrice < ma200)        return 'accum';
  if (btcPrice < ma200 * 1.2 && fg < 50) return 'value';
  if (btcPrice < ma200 * 1.5)  return 'bull';
  return 'euphoria';
}

function BtcZoneBar({ btcPrice, ma200, fg }) {
  const zoneKey = _deriveZone(btcPrice, ma200, fg);
  const zoneIdx = BTC_ZONES.findIndex(z => z.key === zoneKey);
  const zone = zoneIdx >= 0 ? BTC_ZONES[zoneIdx] : null;
  // dot center = (zoneIdx + 0.5) * 20% of bar
  const dotPct = zoneIdx >= 0 ? (zoneIdx + 0.5) * 20 : null;

  return (
    <div>
      {/* Segment bar */}
      <div style={{ display: 'flex', borderRadius: 6, overflow: 'hidden', height: 10, marginBottom: 6, position: 'relative' }}>
        {BTC_ZONES.map(z => (
          <div key={z.key} style={{ flex: 1, background: z.color, opacity: z.key === zoneKey ? 1 : 0.4 }} />
        ))}
        {/* Indicator dot */}
        {dotPct != null && (
          <div style={{
            position: 'absolute',
            left: `${dotPct}%`,
            top: '50%',
            transform: 'translate(-50%, -50%)',
            width: 12,
            height: 12,
            borderRadius: '50%',
            background: '#fff',
            boxShadow: '0 0 0 2px rgba(0,0,0,0.4)',
            border: '2px solid var(--bg)',
          }} />
        )}
      </div>
      {/* Segment labels */}
      <div style={{ display: 'flex', marginBottom: 10 }}>
        {BTC_ZONES.map(z => (
          <div key={z.key} style={{ flex: 1, fontSize: 9, color: z.key === zoneKey ? 'var(--text)' : 'var(--text4)', textAlign: 'center', fontWeight: z.key === zoneKey ? 600 : 400 }}>
            {z.label}
          </div>
        ))}
      </div>
      {/* Zone name + chip */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
        <span style={{ fontSize: 18, fontWeight: 700, color: 'var(--accent)' }}>
          {zone ? zone.label : '—'}
        </span>
        {zone && <span className={`tv-chip ${zone.chipCls}`}>{zone.chip}</span>}
      </div>
      <div style={{ fontSize: 11, color: 'var(--text4)' }}>Pi Cycle · MVRV Z · NUPL · Puell Multiple</div>
    </div>
  );
}

/* ── ROW 1 Right: MaxFi advisor card (GET /api/maxfi/advisor?kick=0 + /api/maxfi/range/<chain>/<wallet>) ── */
const DASH_MAXFI_CHAINS = [['robinhood', 'RH'], ['base', 'Base']];
// A range request that has not answered after 20 s is aborted (-> not checked).
const DASH_RANGE_TIMEOUT_MS = 20000;

function _dashChainLabel(chain) {
  const c = DASH_MAXFI_CHAINS.find(x => x[0] === chain);
  return c ? c[1] : String(chain || '');
}

// MaxFi page rule: any flag means No verdict.
function _dashVerdict(p) {
  const flags = Array.isArray(p.flags) ? p.flags : [];
  const v = String(p.verdict || '').toUpperCase();
  if (!flags.length && v === 'HOLD') return 'hold';
  if (!flags.length && v === 'CLOSE') return 'close';
  return 'none';
}

function _dashPair(p) {
  const s = p.symbols || {};
  return s.token0 && s.token1 ? s.token0 + '/' + s.token1 : '#' + p.token_id;
}

// A number, or null for null / blank / non-finite (_dashNum reads null as 0).
function _dashFinite(v) {
  return v == null || v === '' ? null : _dashNum(v);
}

function _dashMaxfiModel({ advisor, wallets, range, hideValues, nowMs }) {
  if (advisor.status !== 'ok') return { status: advisor.status };
  const data = advisor.data;
  const all = data.positions.filter(p => p && typeof p === 'object');
  const lower = (p) => String(p.wallet || '').toLowerCase();
  let positions = all, rangeNote = null;
  if (wallets.status === 'error') rangeNote = 'Range not checked: wallet list unavailable.';
  else if (wallets.status === 'ok') {
    const inList = new Set(wallets.list.map(w => w.address));
    positions = all.filter(p => inList.has(lower(p)));
  }

  const rows = positions.map(p => {
    const r = range[p.chain + '|' + lower(p)];
    let state;
    if (wallets.status === 'error' || !DASH_MAXFI_CHAINS.some(c => c[0] === p.chain)) state = 'unknown';
    else if (wallets.status === 'loading' || !r) state = 'pending';
    else if (r.status === 'ok') {
      const e = (r.positions || []).find(x => x && String(x.token_id) === String(p.token_id));
      state = e && e.status === 'ok' && e.in_range === true ? 'in' : e && e.status === 'ok' && e.in_range === false ? 'out' : 'unknown';
    } else if (r.loading) state = 'pending';
    else state = 'unknown';
    return { p, verdict: _dashVerdict(p), state, pair: _dashPair(p), chain: _dashChainLabel(p.chain), value: _dashFinite(p.current_value_usd) };
  });
  const count = (k, v) => rows.filter(x => x[k] === v).length;

  let fees = 0, rated = 0;
  for (const x of rows) {
    const rate = _dashFinite(x.p.run_rate_7d_pct_day);
    if (rate != null && x.value != null && x.value > 0) { fees += rate / 100 * x.value; rated++; }
  }
  if (rows.length && !rated) fees = null;

  const rank = { close: 0, none: 1 };
  const actions = rows.filter(x => x.verdict !== 'hold')
    .sort((x, y) => rank[x.verdict] - rank[y.verdict] || (y.value || 0) - (x.value || 0)).slice(0, 2);

  let stamp = null;
  for (const x of rows) {
    const d = _dashParseUtc(x.p.current_value_at);
    if (d && (!stamp || d < stamp)) stamp = d;
  }

  const failed = [];
  if (wallets.status === 'ok') {
    for (const w of wallets.list) {
      for (const [chain, label] of DASH_MAXFI_CHAINS) {
        const r = range[chain + '|' + w.address];
        if (r && r.status === 'error' && !r.loading) {
          failed.push(label + (wallets.list.length > 1 && w.label ? ' (' + w.label + ')' : ''));
        }
      }
    }
  }

  const order = { in: 0, out: 1, unknown: 2, pending: 3 };
  return {
    status: 'ok', rows: rows.slice().sort((x, y) => order[x.state] - order[y.state]),
    M: rows.length, inN: count('state', 'in'), outN: count('state', 'out'),
    unknownN: count('state', 'unknown'), pendingN: count('state', 'pending'),
    holdN: count('verdict', 'hold'), closeN: count('verdict', 'close'), noneN: count('verdict', 'none'),
    fees, noRate: rows.length - rated, actions, stamp,
    stale: !!stamp && nowMs - stamp.getTime() > DASH_STALE_MS.maxfi_uncollected,
    failed: [...new Set(failed)], rangeNote, claimsUnavailable: !!data.claims_unavailable,
  };
}

const DASH_RANGE_WORD = { in: 'in range', out: 'out of range', unknown: 'not checked', pending: 'not checked' };
const DASH_VERDICT_CHIPS = [['hold', 'Hold', 'var(--dash-pos)'], ['close', 'Close', 'var(--dash-warn)'], ['none', 'No verdict', 'var(--dash-text4)']];

function DashMaxfiCard({ model, hideValues, onOpen }) {
  const link = <button type="button" className="dash-link" onClick={onOpen}>Open MaxFi →</button>;
  const loading = model.status === 'loading';
  const ok = model.status === 'ok';
  const header = (
    <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, flexWrap: 'wrap' }}>
      <div className="dash-label">MAXFI · ADVISOR</div>
      <div style={{ flex: 1 }} />
      <div className="dash-num" style={{ fontSize: 12, color: ok && model.stale ? 'var(--dash-warn)' : 'var(--dash-text4)' }}>
        {_dashClock(ok ? model.stamp : null) + ' · maxfi_positions'}
      </div>
    </div>
  );
  const shell = (children) => (
    <div className="dash-card" style={{ padding: '16px 20px', display: 'flex', flexDirection: 'column', gap: 12 }}>
      {header}{children}
    </div>
  );
  const msg = (t) => <div style={{ fontSize: 13, color: 'var(--dash-text3)' }}>{t}</div>;
  if (model.status === 'error') return shell(<>{msg('MaxFi advisor unavailable.')}{link}</>);
  if (ok && model.M === 0) return shell(<>{msg('No MaxFi positions. The advisor has nothing to review.')}{link}</>);

  const n = (v) => (loading ? '…' : hideValues ? DASH_MASK_COUNT : v);
  let sub = null;
  if (ok) {
    if (model.pendingN === model.M) sub = 'Checking range…';
    else {
      const parts = [];
      if (model.unknownN > 0) parts.push(n(model.unknownN) + ' not checked');
      if (model.pendingN > 0) parts.push(n(model.pendingN) + ' checking');
      sub = parts.join(' · ') || null;
    }
  }
  const feesText = loading ? '…' : hideValues ? DASH_MASK_MONEY : model.fees == null ? '—' : fmt(model.fees, 2);
  const squareStyle = (state) => ({
    width: 14, height: 14, borderRadius: 3, boxSizing: 'border-box',
    background: state === 'in' ? 'var(--dash-pos)' : state === 'out' ? 'var(--dash-warn)' : 'var(--dash-raised)',
    border: state === 'in' || state === 'out' ? 'none' : '1px solid var(--dash-text4)',
  });

  return shell(<>
    <div style={{ display: 'flex', justifyContent: 'space-between', flexWrap: 'wrap', gap: 16 }}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6, minWidth: 0 }}>
        <div>
          <span className="dash-num" style={{ fontSize: 26, color: 'var(--dash-text)' }}>
            {loading ? '…' : hideValues ? '•• of ••' : model.inN + ' of ' + model.M}
          </span>
          <span style={{ fontSize: 13, color: 'var(--dash-text3)' }}> in range</span>
        </div>
        {sub && <div style={{ fontSize: 12, color: 'var(--dash-text3)' }}>{sub}</div>}
        {ok && (hideValues
          ? <div className="dash-maxfi-squares" role="img" aria-label="Range hidden while values are hidden" />
          : (
            <div className="dash-maxfi-squares" role="img" aria-label={model.inN + ' of ' + model.M + ' in range'}>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                {model.rows.map(x => (
                  <span key={x.p.id != null ? x.p.id : x.p.chain + x.p.token_id} title={x.pair + ' · ' + x.chain + ' · ' + DASH_RANGE_WORD[x.state]} style={squareStyle(x.state)} />
                ))}
              </div>
            </div>
          ))}
      </div>
      <div title="Advisor 7-day run rate × current value, summed" style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
        <div className="dash-label">FEES RUN RATE</div>
        <div>
          <span className="dash-num" style={{ fontSize: 18, color: 'var(--dash-text)' }}>{feesText}</span>
          <span style={{ fontSize: 12, color: 'var(--dash-text3)' }}> / day</span>
        </div>
        {ok && model.noRate > 0 && (
          <div style={{ fontSize: 11, color: 'var(--dash-text4)' }}>{(hideValues ? DASH_MASK_COUNT : model.noRate) + ' without a rate'}</div>
        )}
      </div>
    </div>
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
      {DASH_VERDICT_CHIPS.map(([key, label, dot]) => (
        <span key={key} style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 12, color: 'var(--dash-text2)',
          background: 'var(--dash-band)', border: '1px solid var(--dash-line)', borderRadius: 999, padding: '2px 10px' }}>
          <span aria-hidden="true" style={{ width: 7, height: 7, borderRadius: '50%', background: dot }} />
          {label} <span className="dash-num">{n(ok ? model[key + 'N'] : 0)}</span>
        </span>
      ))}
    </div>
    {ok && model.actions.length > 0 && (
      <div className="dash-maxfi-actions">
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          {model.actions.map(x => (
            <div key={x.p.id != null ? x.p.id : x.p.chain + x.p.token_id} style={{ display: 'flex', justifyContent: 'space-between', gap: 8,
              background: 'var(--dash-band)', borderRadius: 6, padding: '6px 10px', fontSize: 12 }}>
              <span style={{ color: 'var(--dash-text2)', minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{x.pair + ' · ' + x.chain}</span>
              <span style={{ color: x.verdict === 'close' ? 'var(--dash-warn)' : 'var(--dash-text3)', whiteSpace: 'nowrap' }}>{x.verdict === 'close' ? 'Close' : 'No verdict'}</span>
            </div>
          ))}
        </div>
      </div>
    )}
    {ok && model.claimsUnavailable && <div style={{ fontSize: 12, color: 'var(--dash-warn)' }}>Ledger unavailable: verdicts withheld</div>}
    {ok && model.failed.length > 0 && (
      <div style={{ fontSize: 12, color: 'var(--dash-warn)' }}>{'Range check failed: ' + model.failed.join(' · ') + ' — Refresh to retry.'}</div>
    )}
    {ok && model.rangeNote && <div style={{ fontSize: 12, color: 'var(--dash-text3)' }}>{model.rangeNote}</div>}
    {link}
  </>);
}

/* ── ROW 1 Right: mini cards ── */
function LendingMiniCard({ aavePositions }) {
  const hfs = (aavePositions || []).map(p => p.health_factor).filter(h => h != null && h > 0 && isFinite(h));
  const lowestHF = hfs.length ? Math.min(...hfs) : null;
  const cls = lowestHF == null ? 'text4' : lowestHF > 2 ? 'ok' : lowestHF > 1.5 ? 'warn' : 'fail';
  const label = lowestHF == null ? 'No positions' : lowestHF > 2 ? 'Safe zone' : lowestHF > 1.5 ? 'Caution' : 'Danger';

  return (
    <div style={{ flex: 1, background: 'var(--panel3)', borderRadius: 8, padding: '10px 12px' }}>
      <div className="tv-label" style={{ color: 'var(--accent)', marginBottom: 6, fontSize: 10 }}>LENDING</div>
      <div className="tv-num" style={{ fontSize: 24, color: `var(--${cls})` }}>
        {lowestHF != null ? lowestHF.toFixed(2) : '—'}
      </div>
      <div style={{ fontSize: 11, marginTop: 3, color: `var(--${cls})` }}>{label}</div>
    </div>
  );
}

/* ── ROW 3 Right: Spot P&L card ── */
function SpotPnlCard({ spotPnl, spotHistory, hideValues }) {
  const unrealized = (spotPnl || []).reduce((s, h) => s + (h.unrealized_pnl_usd || 0), 0);
  const costBasis  = (spotPnl || []).reduce((s, h) => s + (h.total_cost_basis    || 0), 0);
  const unrealPct  = costBasis > 0 ? (unrealized / costBasis * 100) : null;

  // Realized last 30 days: filter by last_sell_date
  const cutoff30d = Date.now() - 30 * 86_400_000;
  const realized30d = (spotHistory || [])
    .filter(p => p.last_sell_date && new Date(p.last_sell_date).getTime() >= cutoff30d)
    .reduce((s, p) => s + (p.realized_pnl || 0), 0);

  // Top movers by abs(unrealized_pct)
  const movers = [...(spotPnl || [])]
    .filter(h => h.unrealized_pct != null)
    .sort((a, b) => Math.abs(b.unrealized_pct) - Math.abs(a.unrealized_pct))
    .slice(0, 3);

  return (
    <div className="tv-card" style={{ marginTop: 12 }}>
      <div className="tv-label" style={{ color: 'var(--accent)', marginBottom: 12 }}>Spot P&amp;L</div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginBottom: 14 }}>
        <div style={{ background: 'var(--panel2)', borderRadius: 8, padding: '10px 12px' }}>
          <div className="tv-label" style={{ fontSize: 10, marginBottom: 4 }}>UNREALIZED</div>
          <div className="tv-num" style={{ fontSize: 20, color: unrealized >= 0 ? 'var(--ok)' : 'var(--fail)' }}>
            {hideValues ? '••••' : (unrealized >= 0 ? '+' : '') + fmt(unrealized)}
          </div>
          {unrealPct != null && (
            <div style={{ fontSize: 11, color: 'var(--text4)', marginTop: 3 }}>
              {unrealPct >= 0 ? '+' : ''}{unrealPct.toFixed(1)}% of cost basis
            </div>
          )}
        </div>
        <div style={{ background: 'var(--panel2)', borderRadius: 8, padding: '10px 12px' }}>
          <div className="tv-label" style={{ fontSize: 10, marginBottom: 4 }}>REALIZED · 30D</div>
          <div className="tv-num" style={{ fontSize: 20, color: realized30d >= 0 ? 'var(--ok)' : 'var(--fail)' }}>
            {hideValues ? '••••' : (realized30d >= 0 ? '+' : '') + fmt(realized30d)}
          </div>
          <div style={{ fontSize: 11, color: 'var(--text4)', marginTop: 3 }}>Closed positions</div>
        </div>
      </div>
      {movers.length > 0 && (
        <>
          <div className="tv-label" style={{ fontSize: 10, marginBottom: 8 }}>TOP MOVERS · 24H</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {movers.map((h, i) => (
              <div key={i} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <span className="tv-chip" style={{ fontSize: 11 }}>{h.symbol}</span>
                <span style={{ fontSize: 13, fontWeight: 500, color: (h.unrealized_pct || 0) >= 0 ? 'var(--ok)' : 'var(--fail)' }}>
                  {hideValues ? '••••' : fmtPct(h.unrealized_pct || 0)}
                </span>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

/* ── ROW 1 Left: hero card (live total + parts table) ── */
const DASH_DOT = { text4: 'var(--dash-text4)', pos: 'var(--dash-pos)', warn: 'var(--dash-warn)', loading: 'var(--dash-loading)' };

// Everything the hero shows, from the live total (ok), the latest complete
// snapshot run (unavailable) or nothing yet (idle). Values stay raw here; the
// card applies hidden-value masking.
function _dashHeroModel({ totalState, totalData, fallback, unavailableSince, spotPnl, hideValues, nowMs }) {
  const subMoney = (v) => hideValues ? DASH_MASK_SUB : fmt(v, 2);
  const shareOf = (v, total) => (v != null && Number.isFinite(total) && total !== 0) ? v / total * 100 : null;
  const staleFor = (key, d) => !!d && nowMs - d.getTime() > (DASH_STALE_MS[key] || DASH_STALE_DEFAULT_MS);
  const rows = [];
  const extras = [];
  const notes = [];
  let total = null, totalEmpty = '…', dot = 'text4', status = 'Waiting for the live total…';

  const spotRows = (spotPnl || []).filter(r => r && r.current_value_usd != null);
  const addExtras = (stakingValue) => {
    if (spotRows.length) {
      extras.push({ key: 'spot', group: 'INFO ONLY: ALREADY INSIDE WALLET TOKENS', part: '↳ Spot positions',
        value: spotRows.reduce((acc, r) => acc + (Number(r.current_value_usd) || 0), 0), tag: 'not added' });
    }
    if (stakingValue != null && _dashNonZero(stakingValue)) {
      extras.push({ key: 'staking', group: 'NOT COUNTED', part: 'Staked / locked', value: stakingValue, tag: 'excluded' });
    }
  };

  if (totalState === 'ok' && totalData && Number.isFinite(totalData.total_usd)) {
    const t = totalData;
    total = t.total_usd;
    const hlComp = _dashComp(t, 'hyperliquid');
    const hlLoading = !!hlComp && !hlComp.counted;
    const drift = (Array.isArray(t.warnings) ? t.warnings : [])
      .filter(w => w && w.component === 'maxfi_drift').map(w => w.warning);
    for (const [key, label] of DASH_PART_ROWS) {
      const c = _dashComp(t, key);
      if (!c) continue;
      const value = _dashNum(c.value_usd) ?? 0;
      const pending = key === 'hyperliquid' && hlLoading;
      let warnings = (Array.isArray(c.warnings) ? c.warnings : []).filter(w => !(pending && w === 'Hyperliquid loading'));
      if (key === 'maxfi_lp') warnings = warnings.concat(drift);
      if (!(key === 'maxfi_lp' || warnings.length || pending || _dashNonZero(value))) continue;
      const asOf = _dashParseUtc(c.as_of);
      const d = c.detail || {};
      let sub = null;
      if (!pending) {
        if (key === 'hyperliquid') sub = _dashHlSub(c, subMoney);
        else if (key === 'lending_net') sub = 'collateral ' + subMoney(Number(d.gross_collateral_usd) || 0) + ' · debt ' + subMoney(Number(d.debt_usd) || 0);
        else if (key === 'maxfi_uncollected') sub = '85% of ' + subMoney(Number(d.gross_uncollected_usd) || 0) + ' gross';
      }
      rows.push({
        key, label, value: pending ? null : value, pendingText: pending ? 'Loading…' : null,
        share: (c.counted && !pending) ? shareOf(value, total) : null,
        asOf: pending ? null : asOf, asOfText: pending ? 'waiting' : _dashClock(asOf),
        stale: !pending && staleFor(key, asOf), source: c.source || '', sub, warnings,
        counted: !!c.counted && !pending,
      });
    }
    addExtras(_dashNum((_dashComp(t, 'zerion_staking') || {}).value_usd));
    const warnCount = rows.reduce((acc, r) => acc + r.warnings.length, 0);
    dot = hlLoading ? 'loading' : warnCount > 0 ? 'warn' : 'pos';
    const asOfP = _dashParseUtc(t.as_of && t.as_of.portfolio);
    status = 'Live · as of ' + _dashClock(asOfP);
    const oldest = rows.filter(r => r.counted && r.asOf && _dashNonZero(r.value || 0))
      .reduce((o, r) => (!o || r.asOf < o.asOf) ? r : o, null);
    if (asOfP && oldest && asOfP.getTime() - oldest.asOf.getTime() > 60000) {
      status += ' · oldest part ' + _dashClock(oldest.asOf) + ' (' + oldest.label + ')';
    }
    if (hlLoading) notes.push({ tone: 'loading', text: 'Hyperliquid loading — not in the total yet.' });
  } else if (totalState === 'unavailable') {
    dot = 'warn';
    const since = _dashHHMM(unavailableSince);
    const row = fallback && fallback.status === 'ok' ? fallback.row : null;
    if (row) {
      total = _dashNum(row.total_usd);
      const rowTime = _dashParseUtc(row.timestamp);
      status = 'Snapshot ' + _dashClock(rowTime) + ' · live total unavailable since ' + since;
      notes.push({ tone: 'warn', text: 'Live total unavailable — showing the last snapshot run. Its parts use the same definition as the live total.' });
      for (const [key, label] of DASH_PART_ROWS) {
        const value = _dashNum(row[key + '_usd']);
        if (!(key === 'maxfi_lp' || _dashNonZero(value || 0))) continue;
        rows.push({
          key, label, value, pendingText: null, share: shareOf(value, total), asOf: rowTime,
          asOfText: _dashClock(rowTime), stale: staleFor(key, rowTime), source: 'snapshot #' + row.id,
          sub: null, warnings: [], counted: true,
        });
      }
      addExtras(_dashNum(row.zerion_staking_usd));
    } else if (fallback && fallback.status === 'none') {
      totalEmpty = '—';
      status = 'Live total unavailable since ' + since;
      notes.push({ tone: 'warn', text: 'Live total unavailable and no recent snapshot run.' });
    } else {
      status = 'Live total unavailable since ' + since + ' · loading the last snapshot run…';
    }
  } else {
    for (const key of DASH_IDLE_KEYS) {
      const label = DASH_PART_ROWS.find(r => r[0] === key)[1];
      rows.push({ key, label, value: null, pendingText: '…', share: null, asOf: null, asOfText: '—',
        stale: false, source: '', sub: null, warnings: [], counted: false });
    }
  }
  return { total, totalEmpty, dot, status, notes, rows, extras,
           warnCount: rows.reduce((acc, r) => acc + r.warnings.length, 0) };
}

function DashPartsTable({ rows, extras, hideValues }) {
  const cellHead = { fontSize: 11, fontWeight: 600, letterSpacing: '.09em', textTransform: 'uppercase', color: 'var(--dash-text4)' };
  return (
    <div>
      <div className="dash-parts-row dash-parts-head"
        style={{ minHeight: 32, background: 'var(--dash-band)', borderTop: '1px solid var(--dash-line)', borderBottom: '1px solid var(--dash-line)' }}>
        <div style={cellHead}>Part</div>
        <div style={{ ...cellHead, textAlign: 'right' }}>Value</div>
        <div style={cellHead}>Share</div>
        <div style={cellHead}>As of</div>
        <div className="dash-c-source" style={cellHead}>Source</div>
      </div>
      {rows.map(r => {
        const muted = r.value == null;
        const valueText = r.value == null ? (r.pendingText || '—') : hideValues ? DASH_MASK_MONEY : fmt(r.value, 2);
        const shareText = r.share == null ? '—' : hideValues ? DASH_MASK_PCT : r.share.toFixed(2) + '%';
        const barWidth = (r.share == null || hideValues) ? 0 : Math.min(100, Math.max(0, r.share * 2.5));
        const warned = r.warnings.length > 0;
        const warningLines = !warned ? [] : hideValues ? [DASH_MASK_WARNING] : r.warnings.map(w => '⚠ ' + w);
        return (
          <div key={r.key} id={'dash-part-' + r.key} tabIndex={-1} className="dash-parts-row"
            style={{ minHeight: 36, paddingTop: 8, paddingBottom: 8, borderBottom: '1px solid var(--dash-line)' }}>
            <div className="dash-c-part" style={{ fontSize: 13, color: 'var(--dash-text2)', minWidth: 0 }}>
              <div>{warned ? '⚠ ' : ''}{r.label}</div>
              {r.sub && <div className="dash-num" style={{ fontSize: 11, color: 'var(--dash-text4)' }}>{r.sub}</div>}
            </div>
            <div className="dash-c-value dash-num" style={{ textAlign: 'right', fontSize: 13, color: muted ? 'var(--dash-text4)' : 'var(--dash-text)' }}>
              {valueText}
            </div>
            <div className="dash-c-share">
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <div style={{ width: 48, height: 6, borderRadius: 3, background: 'var(--dash-raised)', flex: '0 0 auto', overflow: 'hidden' }}>
                  <div style={{ width: barWidth + '%', height: '100%', background: 'var(--dash-accent)' }} />
                </div>
                <span className="dash-num" style={{ fontSize: 12, color: 'var(--dash-text3)' }}>{shareText}</span>
              </div>
            </div>
            <div className="dash-c-asof dash-num" style={{ fontSize: 12, color: r.stale ? 'var(--dash-warn)' : 'var(--dash-text3)' }}>
              {r.asOfText}
            </div>
            <div className="dash-c-source" title={r.source || undefined}
              style={{ fontSize: 12, color: 'var(--dash-text4)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
              {r.source || '—'}
            </div>
            <div className="dash-c-meta" title={(r.asOfText || '') + (r.source ? ' · ' + r.source : '')}>{r.asOfText}{r.source ? ' · ' + r.source : ''}</div>
            <div className="dash-c-meta-share dash-num">{shareText}</div>
            {warningLines.map((w, i) => (
              <div key={i} style={{ gridColumn: '1 / -1', fontSize: 12, color: 'var(--dash-warn)' }}>{w}</div>
            ))}
          </div>
        );
      })}
      {extras.length > 0 && (
        <div style={{ background: 'var(--dash-band)', padding: '4px 0 8px' }}>
          {extras.map(x => (
            <React.Fragment key={x.key}>
              <div className="dash-label" style={{ padding: '0 20px', marginTop: 4 }}>{x.group}</div>
              <div className="dash-parts-row" style={{ minHeight: 32, paddingTop: 4, paddingBottom: 4 }}>
                <div style={{ fontSize: 13, color: 'var(--dash-text3)', minWidth: 0 }}>{x.part}</div>
                <div className="dash-num" style={{ textAlign: 'right', fontSize: 13, color: 'var(--dash-text3)' }}>
                  {hideValues ? DASH_MASK_MONEY : fmt(x.value, 2)}
                </div>
                <div className="dash-c-share" style={{ gridColumn: '3 / -1', fontSize: 11, color: 'var(--dash-text4)' }}>{x.tag}</div>
                <div className="dash-c-meta">{x.tag}</div>
              </div>
            </React.Fragment>
          ))}
        </div>
      )}
    </div>
  );
}

function DashHeroCard({ model, hideValues, refreshing, totalIdle, onRefresh }) {
  const busy = refreshing || totalIdle;
  const n = model.warnCount;
  const countText = hideValues ? DASH_MASK_COUNT : String(n);
  const warnWord = (!hideValues && n === 1) ? 'warning' : 'warnings';
  const firstWarned = model.rows.find(r => r.warnings.length > 0);
  const goFirst = () => {
    const el = firstWarned && document.getElementById('dash-part-' + firstWarned.key);
    if (!el) return;
    el.scrollIntoView({ block: 'center', behavior: 'smooth' });
    el.focus({ preventScroll: true });
  };
  const totalText = model.total == null ? model.totalEmpty : hideValues ? DASH_MASK_TOTAL : fmt(model.total, 2);
  return (
    <div className="dash-card" style={{ overflow: 'hidden' }}>
      <div style={{ padding: '18px 20px 16px', display: 'flex', flexDirection: 'column', gap: 8 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          <div className="dash-label">TOTAL PORTFOLIO VALUE</div>
          <div style={{ flex: 1 }} />
          {n > 0 && (
            <button type="button" className="dash-badge" onClick={goFirst}
              aria-label={countText + ' ' + warnWord + ' — go to the first'}>
              ⚠ {countText} {warnWord}
            </button>
          )}
          <button type="button" className="dash-btn" onClick={onRefresh} disabled={refreshing}
            aria-busy={busy ? 'true' : undefined}>
            {busy ? 'Loading…' : 'Refresh'}
          </button>
        </div>
        <div className="dash-num" style={{ fontSize: 44, fontWeight: 500, lineHeight: 1.05, color: 'var(--dash-text)' }}>
          {totalText}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, color: 'var(--dash-text4)' }}>
          <span aria-hidden="true" style={{ width: 8, height: 8, borderRadius: '50%', background: DASH_DOT[model.dot], flex: '0 0 auto' }} />
          <span>{model.status}</span>
        </div>
        {model.notes.map((note, i) => (
          <div key={i} role="status" style={{
            fontSize: 12, color: 'var(--dash-text)', borderRadius: 6, padding: '8px 12px',
            background: 'var(--dash-' + note.tone + '-tint)', border: '1px solid var(--dash-' + note.tone + '-edge)',
          }}>{note.text}</div>
        ))}
      </div>
      <DashPartsTable rows={model.rows} extras={model.extras} hideValues={hideValues} />
    </div>
  );
}

/* ── ROW 2: equity card (complete-total history, GET /api/history/portfolio-total-chart) ── */
const DASH_DAY_MS = 86400000;
const DASH_RANGES = [['24H', 1], ['1W', 7], ['1M', 30], ['1Y', 365], ['ALL', null]];
const DASH_CROSSED_TITLE = ' · Across the Sep 27 definition change, both ends are compared without MaxFi fees (old basis + Hyperliquid)';

// Change between two chart points. Ends on different definitions are compared
// on the old basis (basis0 = snapshot total + Hyperliquid) at both ends.
function _dashChange(a, b) {
  if (!a || !b) return null;
  const crossed = a.v !== b.v;
  const from = crossed ? a.basis0 : a.total;
  const to = crossed ? b.basis0 : b.total;
  if (from == null || to == null || from === 0) return null;
  return { usd: to - from, pct: (to - from) / from * 100, crossed, from: a };
}

// BTC/ETH % over the range: from the last price at or before the range start
// (else the first after it) to the last price.
function _dashBenchPct(benchmarks, coin, startMs) {
  const priced = benchmarks.filter(b => b[coin] != null);
  if (!priced.length) return null;
  let start = null;
  for (const b of priced) { if (b.ms <= startMs) start = b; else break; }
  if (!start) start = priced.find(b => b.ms > startMs) || null;
  const end = priced[priced.length - 1];
  if (!start || start === end || !start[coin]) return null;
  return (end[coin] - start[coin]) / start[coin] * 100;
}

// Evenly spaced round Y ticks (at most 6) covering [min, max]; step = c × 10^k
// with c in 1, 2, 2.5, 5. Recharts' own tickCount can drop a tick.
function _dashNiceTicks(min, max) {
  if (!(max > min)) {
    const w = Math.max(Math.abs(max) * 0.01, 1);
    min -= w; max += w;
  }
  const mag = 10 ** Math.floor(Math.log10((max - min) / 6));
  let s = null;
  for (const m of [mag, 10 * mag, 100 * mag]) {
    for (const c of [1, 2, 2.5, 5]) {
      if (Math.ceil(max / (c * m)) - Math.floor(min / (c * m)) + 1 <= 6) { s = c * m; break; }
    }
    if (s != null) break;
  }
  if (s == null) s = 500 * mag;
  const lo = Math.floor(min / s) * s, hi = Math.ceil(max / s) * s;
  const ticks = [];
  for (let i = 0; lo + i * s <= hi + s / 2; i++) ticks.push(Number((lo + i * s).toPrecision(12)));
  return { ticks, domain: [ticks[0], ticks[ticks.length - 1]], step: s };
}

// Smallest d in 0..3 that shows u exactly.
function _dashDecimals(u) {
  for (let d = 0; d <= 3; d++) {
    const x = u * 10 ** d;
    if (Math.abs(Math.round(x) - x) < 1e-9) return d;
  }
  return 3;
}

function useDashNarrow() {
  const query = '(max-width: 767px)';
  const [narrow, setNarrow] = useDashState(() => typeof window.matchMedia === 'function' && window.matchMedia(query).matches);
  useDashEffect(() => {
    if (typeof window.matchMedia !== 'function') return undefined;
    const mql = window.matchMedia(query);
    const onChange = () => setNarrow(mql.matches);
    onChange();
    if (mql.addEventListener) mql.addEventListener('change', onChange); else mql.addListener(onChange);
    return () => { if (mql.removeEventListener) mql.removeEventListener('change', onChange); else mql.removeListener(onChange); };
  }, []);
  return narrow;
}

function DashChartTooltip({ active, payload, hideValues }) {
  if (!active || !payload || !payload.length) return null;
  const p = payload[0].payload;
  const when = new Date(p.ms).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
  return (
    <div style={{ background: 'var(--dash-raised)', border: '1px solid var(--dash-line)', borderRadius: 6, padding: '8px 10px', fontSize: 12 }}>
      <div style={{ color: 'var(--dash-text)' }}>{when}</div>
      <div className="dash-num" style={{ color: 'var(--dash-text)' }}>{hideValues ? DASH_MASK_MONEY : fmt(p.total, 2)}</div>
      {p.v === 0 && <div style={{ color: 'var(--dash-text3)' }}>Hyperliquid reconstructed · MaxFi fees not included</div>}
    </div>
  );
}

// The definition seam: a dashed vertical line at x, drawn from the chart's own
// x-scale. (Recharts' ReferenceLine logs a defaultProps warning under the
// React development build this app loads.)
function DashSeamLine({ x, xAxisMap, offset }) {
  const axis = xAxisMap && Object.values(xAxisMap)[0];
  if (!axis || !axis.scale || !offset) return null;
  const px = axis.scale(x);
  if (!Number.isFinite(px) || px < offset.left || px > offset.left + offset.width) return null;
  return (
    <line className="dash-seam-line" x1={px} x2={px} y1={offset.top} y2={offset.top + offset.height}
      stroke="var(--dash-text3)" strokeDasharray="4 4" strokeWidth={1} />
  );
}

function DashStripCell({ label, value, suffix, color, title, extra }) {
  return (
    <div className={extra ? 'dash-strip-extra' : undefined} title={title}>
      <div style={{ fontSize: 11, color: 'var(--dash-text4)' }}>{label}</div>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 6, flexWrap: 'wrap' }}>
        <span className="dash-num" style={{ fontSize: 14, color }}>{value}</span>
        {suffix && <span className="dash-num" style={{ fontSize: 12, color: 'var(--dash-text3)' }}>{suffix}</span>}
      </div>
    </div>
  );
}

function DashEquityCard({ chart, hideValues }) {
  const R = window.Recharts || {};
  const narrow = useDashNarrow();
  const [range, setRange] = useDashState('1M');
  const points = chart.points;
  const seam = chart.seams.length ? chart.seams[chart.seams.length - 1] : null;
  const seamMs = seam ? Date.parse(seam.t) : null;
  const seamDate = seam ? new Date(seamMs) : null;

  const days = DASH_RANGES.find(r => r[0] === range)[1];
  const cutoff = days == null ? -Infinity : Date.now() - days * DASH_DAY_MS;
  let inRange = points.filter(p => p.ms >= cutoff);
  let showingAll = false;
  if (inRange.length < 2 && points.length >= 2) { inRange = points; showingAll = true; }
  const first = inRange[0] || null;
  const last = inRange.length ? inRange[inRange.length - 1] : null;

  const rangeChange = inRange.length >= 2 ? _dashChange(first, last) : null;
  const end = points.length ? points[points.length - 1] : null;
  let start24 = null;
  if (end) { for (const p of points) { if (p.ms <= end.ms - DASH_DAY_MS) start24 = p; else break; } }
  const change24 = start24 ? _dashChange(start24, end) : null;

  let hiP = null, loP = null;
  for (const p of inRange) {
    if (!hiP || p.total > hiP.total) hiP = p;
    if (!loP || p.total < loP.total) loP = p;
  }
  const hi = hiP ? hiP.total : 0, lo = loP ? loP.total : 0;
  const pad = Math.max((hi - lo) * 0.08, hi * 0.002);
  const nice = _dashNiceTicks(lo - pad, hi + pad);

  const firstMs = first ? first.ms : null, lastMs = last ? last.ms : null;
  const seamVisible = seamMs != null && firstMs != null && seamMs >= firstMs && seamMs <= lastMs;

  let chip = null;
  if (points.length) {
    if (seam) {
      chip = (first && first.ms < seamMs)
        ? { tone: 'neutral', text: 'Before ' + _dashDateTime(seamDate) + ': Hyperliquid reconstructed, MaxFi fees not included' }
        : { tone: 'pos', text: 'Same parts as the headline' };
    } else if (points.every(p => p.v === 0)) {
      chip = { tone: 'neutral', text: 'Hyperliquid reconstructed, MaxFi fees not included' };
    } else {
      chip = { tone: 'pos', text: 'Same parts as the headline' };
    }
  }
  const chipStyle = chip && chip.tone === 'pos'
    ? { color: 'var(--dash-text)', background: 'var(--dash-pos-tint)', border: '1px solid var(--dash-pos-edge)' }
    : { color: 'var(--dash-text3)', background: 'var(--dash-band)', border: '1px solid var(--dash-line)' };

  const signedCell = (ch) => {
    if (!ch) return { value: '—', suffix: null, color: 'var(--dash-text3)' };
    if (hideValues) return { value: DASH_MASK_SUB, suffix: DASH_MASK_PCT, color: 'var(--dash-text)' };
    return {
      value: (ch.usd >= 0 ? '+' : '') + fmt(ch.usd, 0),
      suffix: (ch.pct >= 0 ? '+' : '') + ch.pct.toFixed(2) + '%',
      color: ch.usd >= 0 ? 'var(--dash-pos)' : 'var(--dash-neg)',
    };
  };
  const pctCell = (pct) => pct == null
    ? { value: '—', color: 'var(--dash-text3)' }
    : { value: (pct >= 0 ? '+' : '') + pct.toFixed(2) + '%', color: pct >= 0 ? 'var(--dash-pos)' : 'var(--dash-neg)' };
  const rc = signedCell(rangeChange), dc = signedCell(change24);
  const benchStart = firstMs != null ? firstMs : -Infinity;
  const btc = pctCell(_dashBenchPct(chart.benchmarks, 'btc', benchStart));
  const eth = pctCell(_dashBenchPct(chart.benchmarks, 'eth', benchStart));
  const hiLoText = !hiP ? '—' : hideValues ? DASH_MASK_SUB + ' / ' + DASH_MASK_SUB : fmt(hi, 0) + ' / ' + fmt(lo, 0);
  const hiLoTitle = hiP ? 'High ' + _dashClock(new Date(hiP.ms)) + ' · low ' + _dashClock(new Date(loP.ms)) : undefined;

  const height = narrow ? 160 : 280;
  const tick = { fontSize: 11, fontFamily: "'Fira Code', monospace", fill: 'var(--dash-text4)' };
  const xFmt = (ms) => range === '24H'
    ? new Date(ms).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })
    : new Date(ms).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
  const dK = _dashDecimals(nice.step / 1000), dM = _dashDecimals(nice.step / 1000000);
  const yFmt = (v) => {
    if (hideValues) return '••';
    if (Math.abs(v) >= 1000000) return '$' + (v / 1000000).toFixed(dM) + 'M';
    return '$' + (v / 1000).toFixed(dK) + 'k';
  };
  const data = inRange.map(p => ({ ms: p.ms, total: p.total, v: p.v }));
  // Five evenly spaced x ticks (Recharts ignores tickCount on a time scale).
  const xTicks = data.length >= 2 ? [0, 1, 2, 3, 4].map(i => firstMs + (lastMs - firstMs) * i / 4) : undefined;
  const emptyStyle = { height, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 13, color: 'var(--dash-text4)', textAlign: 'center' };
  let body;
  if (chart.status === 'loading') body = <div style={emptyStyle}>…</div>;
  else if (chart.status === 'error') body = <div style={emptyStyle}>Chart unavailable (history request failed)</div>;
  else if (!R.AreaChart) body = <div style={emptyStyle}>Chart library not loaded</div>;
  else if (data.length < 2) body = <div style={emptyStyle}>No portfolio history yet</div>;
  else {
    const { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Customized } = R;
    body = (
      <ResponsiveContainer width="100%" height={height}>
        <AreaChart data={data} margin={{ top: 16, right: 20, bottom: 0, left: 8 }}>
          <CartesianGrid vertical={false} stroke="var(--dash-line)" />
          <XAxis dataKey="ms" type="number" scale="time" domain={['dataMin', 'dataMax']} tickCount={5} ticks={xTicks}
            tickLine={false} axisLine={false} tick={tick} tickFormatter={xFmt} />
          <YAxis orientation="left" width={64} domain={nice.domain} ticks={nice.ticks} interval={0}
            tickLine={false} axisLine={false} tick={tick} tickFormatter={yFmt} />
          <Tooltip content={<DashChartTooltip hideValues={hideValues} />} isAnimationActive={false} />
          {seamVisible && Customized && <Customized component={<DashSeamLine x={seamMs} />} />}
          <Area dataKey="total" type="linear" stroke="var(--dash-accent)" strokeWidth={2} fill="var(--dash-accent)"
            fillOpacity={0.16} dot={false} activeDot={{ r: 4, fill: 'var(--dash-accent)', stroke: 'var(--dash-card)' }}
            isAnimationActive={false} />
        </AreaChart>
      </ResponsiveContainer>
    );
  }
  const n = chart.excluded.incomplete || 0;

  return (
    <div className="dash-card" style={{ overflow: 'hidden' }}>
      <div style={{ padding: '16px 20px 12px', display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 8 }}>
        <div className="dash-label">EQUITY · SNAPSHOT HISTORY</div>
        {chip && <span style={{ fontSize: 12, borderRadius: 6, padding: '4px 8px', ...chipStyle }}>{chip.text}</span>}
        <div style={{ flex: 1 }} />
        <div className="dash-range" role="group" aria-label="Chart range">
          {DASH_RANGES.map(([label]) => (
            <button key={label} type="button" aria-pressed={range === label ? 'true' : 'false'} onClick={() => setRange(label)}>{label}</button>
          ))}
        </div>
      </div>
      {showingAll && (
        <div style={{ padding: '0 20px 8px', fontSize: 12, color: 'var(--dash-text4)' }}>Showing all available data</div>
      )}
      <div className="dash-strip">
        <DashStripCell label={'Change · ' + range} value={rc.value} suffix={rc.suffix} color={rc.color}
          title={'Change in total value, including deposits and withdrawals' + (rangeChange && rangeChange.crossed ? DASH_CROSSED_TITLE : '')} />
        <DashStripCell label="24h change" value={dc.value} suffix={dc.suffix} color={dc.color}
          title={(start24 ? 'vs ' + _dashClock(new Date(start24.ms)) : 'No point 24 h before the latest') + (change24 && change24.crossed ? DASH_CROSSED_TITLE : '')} />
        <DashStripCell extra label={'BTC · ' + range} value={btc.value} color={btc.color} />
        <DashStripCell extra label={'ETH · ' + range} value={eth.value} color={eth.color} />
        <DashStripCell extra label={'High / low · ' + range} value={hiLoText} color="var(--dash-text)" title={hiLoTitle} />
      </div>
      <div>{body}</div>
      <div style={{ padding: '12px 20px 16px', display: 'flex', justifyContent: 'space-between', flexWrap: 'wrap', gap: 8, fontSize: 12 }}>
        <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 16, color: 'var(--dash-text3)' }}>
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
            <span aria-hidden="true" style={{ width: 10, height: 10, borderRadius: 2, background: 'var(--dash-accent)' }} />
            Total portfolio value
          </span>
          {seamVisible && (
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
              <span aria-hidden="true" style={{ width: 12, borderTop: '2px dashed var(--dash-text3)' }} />
              Definition change · {_dashDateTime(seamDate)}
            </span>
          )}
          {n > 0 && (
            <span style={{ color: 'var(--dash-text4)' }}>
              {(hideValues ? DASH_MASK_COUNT : n) + (n === 1 && !hideValues ? ' run' : ' runs') + ' left out: a wallet failed'}
            </span>
          )}
        </div>
        <div style={{ color: 'var(--dash-text4)' }}>Latest snapshot {end ? _dashClock(new Date(end.ms)) : '—'}</div>
      </div>
    </div>
  );
}

/* ── MAIN SCREEN ── */
function DashboardScreen({ hideValues, refreshTrigger, setActiveTab }) {
  const [portfolio,   setPortfolio]   = useDashState(null);
  // Equity chart (GET /api/history/portfolio-total-chart); status 'loading' | 'ok' | 'error'.
  const [chart,       setChart]       = useDashState({ status: 'loading', points: [], seams: [], excluded: {}, benchmarks: [] });
  const [marketData,  setMarketData]  = useDashState(null);
  const [spotPnl,     setSpotPnl]     = useDashState([]);
  const [spotHistory, setSpotHistory] = useDashState([]);
  const [refreshing,  setRefreshing]  = useDashState(false);
  // Live total (/api/portfolio/total): 'idle' | 'ok' | 'unavailable'.
  const [totalData,   setTotalData]   = useDashState(null);
  const [totalState,  setTotalState]  = useDashState('idle');
  // Fallback while the live total is unavailable: the latest complete live
  // portfolio_total_snapshots row. status 'idle' | 'loading' | 'ok' | 'none'.
  const [fallback,    setFallback]    = useDashState({ status: 'idle', row: null });
  const [unavailableSince, setUnavailableSince] = useDashState(null);
  const [loadCount,   setLoadCount]   = useDashState(0);
  // MaxFi card: advisor (?kick=0), the MaxFi wallets from /api/wallets, and the
  // on-chain range checks keyed chain + '|' + wallet (lowercase).
  const [advisor,     setAdvisor]     = useDashState({ status: 'loading', data: null });
  const [mxWallets,   setMxWallets]   = useDashState({ status: 'loading', list: [] });
  const [mxRange,     setMxRange]     = useDashState({});
  // 'loading' | 'ok' | 'error' for /api/portfolio and /api/market-data.
  const [portfolioStatus, setPortfolioStatus] = useDashState('loading');
  const [marketStatus,    setMarketStatus]    = useDashState('loading');
  const totalGenRef = useDashRef(0);
  const allGenRef = useDashRef(0);
  const fallbackGenRef = useDashRef(0);
  const firstTriggerRef = useDashRef(true);

  // Reads the live total from the in-memory portfolio cache. Each call starts a
  // new generation; an older loop exits without touching state. A cold cache,
  // or a total whose Hyperliquid part is still loading, is re-checked every
  // DASH_TOTAL_RETRY_MS (the last good response stays displayed meanwhile).
  const fetchTotal = useDashCallback(async () => {
    const gen = ++totalGenRef.current;
    for (let attempt = 1; attempt <= DASH_TOTAL_MAX_ATTEMPTS; attempt++) {
      let t;
      const ctrl = new AbortController();
      const timer = setTimeout(() => ctrl.abort(), DASH_TOTAL_TIMEOUT_MS);
      try {
        const r = await fetch('/api/portfolio/total', { signal: ctrl.signal });
        if (gen !== totalGenRef.current) return;
        if (!r.ok) { setTotalState('unavailable'); return; }
        t = await r.json();
      } catch (_) {
        if (gen === totalGenRef.current) setTotalState('unavailable');
        return;
      } finally {
        clearTimeout(timer);
      }
      if (gen !== totalGenRef.current) return;
      const cold = !!(t && t.status === 'cache_cold');
      if (t && t.status === 'ok') {
        setTotalData(t);
        setTotalState('ok');
        const hl = _dashComp(t, 'hyperliquid');
        if (!hl || hl.counted) return;
      } else if (!cold) {
        setTotalState('unavailable');
        return;
      }
      if (attempt === DASH_TOTAL_MAX_ATTEMPTS) {
        if (cold) setTotalState('unavailable');
        return;
      }
      await new Promise(res => setTimeout(res, DASH_TOTAL_RETRY_MS));
      if (gen !== totalGenRef.current) return;
    }
  }, []);

  // Unmount: retire any total loop still waiting to retry, and any fetchAll /
  // fallback response still in flight.
  useDashEffect(() => () => {
    totalGenRef.current += 1;
    allGenRef.current += 1;
    fallbackGenRef.current += 1;
  }, []);

  // Range checks (an RPC call per wallet and chain): one wallet at a time, both
  // chains in parallel. A newer fetchAll or unmount stops the loop before its
  // next wallet; answers from a retired generation are dropped.
  const runRange = useDashCallback(async (gen, list) => {
    const live = () => gen === allGenRef.current;
    for (const w of list) {
      if (!live()) return;
      await Promise.all(DASH_MAXFI_CHAINS.map(async ([chain]) => {
        const key = chain + '|' + w.address;
        setMxRange(m => ({ ...m, [key]: { ...(m[key] || {}), loading: true } }));
        const ctrl = new AbortController();
        const timer = setTimeout(() => ctrl.abort(), DASH_RANGE_TIMEOUT_MS);
        let result;
        try {
          const r = await fetch('/api/maxfi/range/' + chain + '/' + w.address, { signal: ctrl.signal });
          let body = null;
          try { body = await r.json(); } catch (e) { if (e && e.name === 'AbortError') throw e; }
          if (!r.ok || !body || typeof body !== 'object' || !Array.isArray(body.positions) || body.error) {
            result = { status: 'error', positions: [], error: (body && body.error) || 'HTTP ' + r.status };
          } else {
            result = { status: 'ok', positions: body.positions, error: null };
          }
        } catch (e) {
          result = { status: 'error', positions: [], error: e && e.name === 'AbortError' ? 'timeout' : 'network' };
        } finally {
          clearTimeout(timer);
        }
        if (live()) setMxRange(m => ({ ...m, [key]: { ...result, loading: false } }));
      }));
    }
  }, []);

  // Each source sets its own state as it answers; a response from an older
  // call is discarded. The live total starts once /api/portfolio settles
  // (its cache is then warm).
  const fetchAll = useDashCallback(() => {
    const gen = ++allGenRef.current;
    const live = () => gen === allGenRef.current;
    setLoadCount(c => c + 1);
    const load = (url, apply, fallbackValue) => fetch(url).then(r => r.json()).then(
      d => { if (live()) apply(d); },
      () => { if (live()) apply(fallbackValue); });
    return Promise.all([
      load('/api/portfolio', d => {
        setPortfolio(d);
        setPortfolioStatus(d && typeof d === 'object' && !d.error ? 'ok' : 'error');
      }, null).then(() => { if (live()) fetchTotal(); }),
      load('/api/history/portfolio-total-chart', d => {
        if (!d || !Array.isArray(d.points)) { setChart(c => ({ ...c, status: 'error' })); return; }
        const withMs = (list) => (Array.isArray(list) ? list : []).map(x => ({ ...x, ms: Date.parse(x.t) })).filter(x => Number.isFinite(x.ms));
        setChart({ status: 'ok', points: withMs(d.points), seams: Array.isArray(d.seams) ? d.seams : [],
                   excluded: d.excluded || {}, benchmarks: withMs(d.benchmarks) });
      }, null),
      load('/api/market-data', d => {
        setMarketData(d);
        setMarketStatus(d && typeof d === 'object' && d.snapshot ? 'ok' : 'error');
      }, null),
      load('/api/spot/pnl', d => setSpotPnl(Array.isArray(d) ? d : []), []),
      load('/api/spot/history', d => setSpotHistory(Array.isArray(d) ? d : []), []),
      load('/api/maxfi/advisor?kick=0', d => setAdvisor(d && Array.isArray(d.positions) ? { status: 'ok', data: d } : { status: 'error', data: null }), null),
      // The range loop is started, not returned: Refresh does not wait for it.
      load('/api/wallets', d => {
        const ok = !!(d && Array.isArray(d.wallets));
        const list = ok ? d.wallets.filter(w => w && w.maxfi === true)
          .map(w => ({ address: String(w.address).toLowerCase(), label: w.label || '' })) : [];
        setMxWallets({ status: ok ? 'ok' : 'error', list });
        if (live() && list.length) runRange(gen, list);
      }, null),
    ]);
  }, [fetchTotal, runRange]);

  useDashEffect(() => { fetchAll(); }, []);

  // Top-bar Refresh: app.js has already forced the portfolio refresh.
  useDashEffect(() => {
    if (firstTriggerRef.current) { firstTriggerRef.current = false; return; }
    fetchAll();
  }, [refreshTrigger]);

  // Live total unavailable: remember since when, and read the latest complete
  // live row of portfolio_total_snapshots (again on every reload).
  useDashEffect(() => {
    if (totalState === 'ok') {
      setUnavailableSince(null);
      setFallback({ status: 'idle', row: null });
      return;
    }
    if (totalState !== 'unavailable') return;
    setUnavailableSince(prev => prev || new Date());
    const gen = ++fallbackGenRef.current;
    setFallback(f => (f.status === 'ok' ? f : { status: 'loading', row: null }));
    fetch('/api/history/portfolio-total?days=2')
      .then(r => (r.ok ? r.json() : Promise.reject(new Error('HTTP ' + r.status))))
      .then(rows => {
        if (gen !== fallbackGenRef.current) return;
        const usable = (Array.isArray(rows) ? rows : [])
          .filter(r => r && r.usable === true && Number(r.definition_version) >= 1 && r.total_usd != null);
        const row = usable.length ? usable[usable.length - 1] : null;
        setFallback(row ? { status: 'ok', row } : { status: 'none', row: null });
      })
      .catch(() => { if (gen === fallbackGenRef.current) setFallback({ status: 'none', row: null }); });
  }, [totalState, loadCount]);

  async function handleRefresh() {
    if (refreshing) return;
    setRefreshing(true);
    try {
      await fetch('/api/portfolio?refresh=true');
      await fetchAll();
    } catch (_) {}
    setRefreshing(false);
  }

  /* ── derived values ── */
  const heroModel = _dashHeroModel({
    totalState, totalData, fallback, unavailableSince, spotPnl, hideValues, nowMs: Date.now(),
  });
  const maxfiModel = _dashMaxfiModel({ advisor, wallets: mxWallets, range: mxRange, hideValues, nowMs: Date.now() });
  const snapshot = marketData?.snapshot || {};
  const fgIndex  = snapshot.fear_greed_index ?? 50;

  return (
    <div className="dash-page">

      {/* ── ROW 1 — Hero + right column ── */}
      <div className="dash-row1">
        <DashHeroCard model={heroModel} hideValues={hideValues} refreshing={refreshing}
          totalIdle={totalState === 'idle'} onRefresh={handleRefresh} />

        <div className="dash-right">
          <DashMaxfiCard model={maxfiModel} hideValues={hideValues} onOpen={() => setActiveTab && setActiveTab('maxfi')} />

          {/* BTC Zone card */}
          <div className="dash-card" style={{ padding: '16px 20px' }}>
            <div className="tv-label" style={{ color: 'var(--accent)', marginBottom: 12, fontSize: 11 }}>BTC MACRO ZONE</div>
            <BtcZoneBar btcPrice={snapshot.btc_price} ma200={snapshot.btc_200d_ma} fg={fgIndex} />
            {snapshot.btc_price && (
              <div style={{ marginTop: 10, fontSize: 12, color: 'var(--text3)', display: 'flex', gap: 12 }}>
                <span>BTC <span className="tv-num" style={{ fontSize: 13 }}>{fmt(snapshot.btc_price, 0)}</span></span>
                {snapshot.btc_200d_ma && (
                  <span>200D MA <span className="tv-num" style={{ fontSize: 13 }}>{fmt(snapshot.btc_200d_ma, 0)}</span></span>
                )}
                {snapshot.fear_greed_index != null && (
                  <span>F&amp;G <span className="tv-num" style={{ fontSize: 13, color: fgIndex < 25 ? 'var(--fail)' : fgIndex < 50 ? 'var(--warn)' : 'var(--ok)' }}>{fgIndex}</span></span>
                )}
              </div>
            )}
          </div>

          {/* Lending mini card */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
            <LendingMiniCard aavePositions={portfolio?.aave_positions} />
          </div>
        </div>
      </div>

      {/* ── ROW 2 — Equity chart ── */}
      <DashEquityCard chart={chart} hideValues={hideValues} />

      {/* ── ROW 3 — Two columns ── */}
      <div style={{ display: 'grid', gridTemplateColumns: '55% 45%', gap: 16, alignItems: 'start' }}>

        {/* RIGHT — Spot P&L */}
        <div>
          <SpotPnlCard spotPnl={spotPnl} spotHistory={spotHistory} hideValues={hideValues} />
        </div>

      </div>

    </div>
  );
}

window.DashboardScreen = DashboardScreen;
