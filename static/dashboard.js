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
// Hyperliquid cumFunding.sinceOpen is positive when the account PAID funding, so the card shows sign x value (negative = paid, positive = received). Confirmed Oct 1 2026 on an open BTC long: sinceOpen +0.00026 vs the stored funding rows for the same position -0.000260 (/api/trading/perps/trades, negative = paid).
const DASH_PERPS_FUNDING_SIGN = -1;
const DASH_PERPS_RETRY_MS = 15000;
const DASH_PERPS_MAX_ATTEMPTS = 8;
const DASH_PERPS_TIMEOUT_MS = 20000;
// Matches HL_ACCOUNTS_TTL_MINUTES in web_portfolio.py: a request that finds the snapshot older than this starts a refresh.
const DASH_PERPS_REFRESH_AGE_MS = 15 * 60000;
const DASH_PERPS_GRID = 'minmax(130px,1fr) minmax(130px,1fr) 104px 92px 92px 112px 112px 96px 88px 88px 88px';
const DASH_PERPS_MIN_WIDTH = 1272;

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

// Wallet tokens sub-line (Bittensor; ruling 9 in portfolio_total.py): the
// counted Bittensor value inside Wallet tokens. "fresh" and "stale"
// wallets are counted; "unavailable" ones are not (their warning line says so).
function _dashBtSub(comp, money) {
  const bt = (comp && comp.detail && comp.detail.bittensor && typeof comp.detail.bittensor === 'object')
    ? comp.detail.bittensor : null;
  if (!bt) return null;
  let value = 0, counted = 0, stale = false;
  for (const s of Object.values(bt)) {
    if (!s || (s.state !== 'fresh' && s.state !== 'stale')) continue;
    counted += 1;
    value += Number(s.value_usd) || 0;
    if (s.state === 'stale') stale = true;
  }
  if (!counted) return null;
  return 'incl. Bittensor ' + money(value) + (stale ? ' (last good read)' : '');
}

// /api/portfolio/total re-check: a cold cache or a still-loading Hyperliquid
// part is retried every 10 s, at most 4 requests per fetch.
const DASH_TOTAL_RETRY_MS = 10000;
const DASH_TOTAL_MAX_ATTEMPTS = 4;
// A request that has not answered after 30 s is aborted (-> 'unavailable').
const DASH_TOTAL_TIMEOUT_MS = 30000;

/* ── BTC Macro Zone ── */
const DASH_ZONES = {
  bear:     { name: 'Bear',         rule: 'Price below 85% of the 200-day MA' },
  accum:    { name: 'Accumulation', rule: 'Price from 85% up to the 200-day MA' },
  value:    { name: 'Value Window', rule: 'Price from the 200-day MA up to 120% of it, with Fear & Greed below 50' },
  bull:     { name: 'Bull',         rule: 'Price below 150% of the 200-day MA (outside the Value Window)' },
  euphoria: { name: 'Euphoria',     rule: 'Price at or above 150% of the 200-day MA' },
};

// Fear & Greed class and color (Market Data page bands).
function _dashFg(v) {
  if (v <= 25) return { name: 'Extreme Fear', color: 'var(--dash-neg)' };
  if (v <= 45) return { name: 'Fear', color: 'var(--dash-neg)' };
  if (v <= 55) return { name: 'Neutral', color: 'var(--dash-warn)' };
  if (v <= 75) return { name: 'Greed', color: 'var(--dash-pos)' };
  return { name: 'Extreme Greed', color: 'var(--dash-pos)' };
}

// Position on the −30% … +30% bar around the 200-day MA, in % of its width.
function _dashBarPos(pct) {
  return Math.min(100, Math.max(0, 50 + pct / 30 * 50));
}

function _deriveZone(btcPrice, ma200, fg) {
  if (!btcPrice || !ma200) return null;
  if (btcPrice < ma200 * 0.85) return 'bear';
  if (btcPrice < ma200)        return 'accum';
  if (btcPrice < ma200 * 1.2 && fg < 50) return 'value';
  if (btcPrice < ma200 * 1.5)  return 'bull';
  return 'euphoria';
}

function DashBtcCard({ snap, status }) {
  const narrow = useDashNarrow();
  const price = (k) => { const v = _dashFinite(snap[k]); return v != null && v > 0 ? v : null; };
  const btc = price('btc_price'), ma200 = price('btc_200d_ma'), ma50 = price('btc_50d_ma');
  const eth = price('eth_price'), sol = price('sol_price');
  const fg = _dashFinite(snap.fear_greed_index);
  const fgc = fg != null ? _dashFg(fg) : null;
  const signed = (v, d) => (v >= 0 ? '+' : '') + v.toFixed(d) + '%';
  const signColor = (v) => (v >= 0 ? 'var(--dash-pos)' : 'var(--dash-neg)');
  const pct200 = btc != null && ma200 != null ? (btc / ma200 - 1) * 100 : null;
  const pct50 = btc != null && ma50 != null ? (btc / ma50 - 1) * 100 : null;
  const ma50vs200 = ma50 != null && ma200 != null ? (ma50 / ma200 - 1) * 100 : null;
  const zoneKey = _deriveZone(btc, ma200, fg != null ? fg : 50);
  const zone = zoneKey ? DASH_ZONES[zoneKey] : null;
  const vsLine = (pct, label) => (
    <div style={{ fontSize: 12, color: pct == null ? 'var(--dash-text3)' : signColor(pct) }}>
      {pct == null ? label + ' —' : signed(pct, 1) + ' ' + label}
    </div>
  );
  const vs200 = ma200 == null
    ? <div style={{ fontSize: 12, color: 'var(--dash-text3)' }}>200-day MA unavailable</div>
    : vsLine(pct200, 'vs 200D MA');
  const msg = (t) => <div style={{ fontSize: 13, color: 'var(--dash-text3)' }}>{t}</div>;

  if (narrow) {
    return (
      <div className="dash-card" style={{ padding: '14px 16px', display: 'flex', flexDirection: 'column', gap: 6 }}>
        <div className="dash-label">BTC</div>
        {status === 'loading' ? <div className="dash-num" style={{ fontSize: 18, color: 'var(--dash-text)' }}>…</div>
          : status === 'error' ? msg('Market data unavailable')
          : <>
            <div className="dash-num" style={{ fontSize: 18, color: 'var(--dash-text)' }}>{btc != null ? fmt(btc, 0) : '—'}</div>
            {vs200}
            {vsLine(pct50, 'vs 50D MA')}
            <div style={{ fontSize: 13, color: 'var(--dash-text2)' }}>
              {'F&G ' + (fg != null ? Math.round(fg) : '—') + ' · '}
              <span style={{ color: fgc ? fgc.color : 'var(--dash-text3)' }}>{fgc ? fgc.name : '—'}</span>
            </div>
          </>}
      </div>
    );
  }

  const header = (
    <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, flexWrap: 'wrap' }}>
      <div className="dash-label">BTC MACRO ZONE</div>
      <div style={{ flex: 1 }} />
      <div className="dash-num" style={{ fontSize: 12, color: 'var(--dash-text4)' }}>
        {_dashClock(_dashParseUtc(snap.timestamp)) + ' · market_snapshots'}
      </div>
    </div>
  );
  const shell = (children) => (
    <div className="dash-card" style={{ padding: '16px 20px', display: 'flex', flexDirection: 'column', gap: 12 }}>
      {header}{children}
    </div>
  );
  if (status === 'loading') return shell(<div className="dash-num" style={{ fontSize: 22, color: 'var(--dash-text)' }}>…</div>);
  if (status === 'error') return shell(msg('Market data unavailable'));

  const pricePos = pct200 != null ? _dashBarPos(pct200) : null;
  const tick50 = ma50vs200 != null ? _dashBarPos(ma50vs200) : null;
  const abs = { position: 'absolute', top: '50%', transform: 'translate(-50%, -50%)' };
  const foot = (label, value) => (
    <div>
      <div style={{ fontSize: 11, color: 'var(--dash-text4)' }}>{label}</div>
      <div>{value}</div>
    </div>
  );
  const coin = (v, d, ch) => (
    <div style={{ display: 'flex', alignItems: 'baseline', gap: 6, flexWrap: 'wrap' }}>
      <span className="dash-num" style={{ fontSize: 14, color: 'var(--dash-text)' }}>{v != null ? fmt(v, d) : '—'}</span>
      {_dashFinite(ch) != null && <span className="dash-num" style={{ fontSize: 12, color: signColor(_dashFinite(ch)) }}>{signed(_dashFinite(ch), 2)}</span>}
    </div>
  );
  const maLine = (label, v) => (
    <div>
      <span style={{ fontSize: 11, color: 'var(--dash-text4)' }}>{label + ' '}</span>
      <span className="dash-num" style={{ fontSize: 13, color: 'var(--dash-text)' }}>{v != null ? fmt(v, 0) : '—'}</span>
    </div>
  );

  return shell(<>
    <div style={{ display: 'flex', justifyContent: 'space-between', flexWrap: 'wrap', gap: 16 }}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 4, minWidth: 0 }}>
        <div className="dash-num" style={{ fontSize: 22, color: 'var(--dash-text)' }}>{btc != null ? fmt(btc, 0) : '—'}</div>
        {vs200}
        {vsLine(pct50, 'vs 50D MA')}
        {zone && ma200 != null && (
          <div title={zone.rule} style={{ fontSize: 12, color: 'var(--dash-text2)' }}>{'Zone: ' + zone.name}</div>
        )}
      </div>
      <div style={{ minWidth: 128, display: 'flex', flexDirection: 'column', gap: 6 }}>
        <div className="dash-label">FEAR &amp; GREED</div>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
          <span className="dash-num" style={{ fontSize: 22, color: 'var(--dash-text)' }}>{fg != null ? Math.round(fg) : '—'}</span>
          <span style={{ fontSize: 13, fontWeight: 600, color: fgc ? fgc.color : 'var(--dash-text3)' }}>{fgc ? fgc.name : '—'}</span>
        </div>
        <div role="img" aria-label={fg != null ? 'Fear and Greed ' + Math.round(fg) + ' of 100, ' + fgc.name : 'Fear and Greed unavailable'}
          style={{ position: 'relative', width: '100%', height: 6, borderRadius: 3, background: 'var(--dash-raised)', margin: '2px 0' }}>
          {[25, 45, 55, 75].map(t => <span key={t} style={{ ...abs, left: t + '%', width: 1, height: 10, background: 'var(--dash-text3)' }} />)}
          {fg != null && (
            <span style={{ ...abs, left: Math.min(100, Math.max(0, fg)) + '%', width: 10, height: 10, borderRadius: '50%',
              background: 'var(--dash-text)', boxShadow: '0 0 0 2px var(--dash-card)' }} />
          )}
        </div>
      </div>
    </div>
    {pricePos != null && (
      <div>
        <div style={{ position: 'relative', paddingTop: tick50 != null ? 16 : 4 }}>
          {tick50 != null && (
            <span className="dash-num" style={{ position: 'absolute', top: 0, left: Math.min(94, Math.max(6, tick50)) + '%', transform: 'translateX(-50%)',
              fontSize: 11, lineHeight: 1, color: 'var(--dash-text4)' }}>50D</span>
          )}
          <div role="img" aria-label={'BTC ' + signed(pct200, 1) + ' vs its 200-day MA' + (ma50vs200 != null ? '; 50-day MA ' + signed(ma50vs200, 1) + ' vs the 200-day' : '')}
            style={{ position: 'relative', height: 8, borderRadius: 4, background: 'var(--dash-raised)' }}>
            <span style={{ position: 'absolute', top: 0, bottom: 0, left: Math.min(50, pricePos) + '%', width: Math.abs(pricePos - 50) + '%',
              background: pct200 >= 0 ? 'var(--dash-pos)' : 'var(--dash-neg)' }} />
            <span style={{ ...abs, left: '50%', width: 2, height: 16, background: 'var(--dash-text3)' }} />
            {tick50 != null && <span style={{ ...abs, left: tick50 + '%', width: 2, height: 16, background: 'var(--dash-accent)' }} />}
            <span style={{ ...abs, left: pricePos + '%', width: 12, height: 12, borderRadius: '50%', background: 'var(--dash-text)', boxShadow: '0 0 0 2px var(--dash-card)' }} />
          </div>
        </div>
        <div className="dash-num" style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: 'var(--dash-text4)', marginTop: 8 }}>
          <span>−30%</span><span>200D</span><span>+30%</span>
        </div>
      </div>
    )}
    <div className="dash-btc-foot" style={{ display: 'grid', gap: 12, borderTop: '1px solid var(--dash-line)', paddingTop: 10 }}>
      {foot('MOVING AVG', <>{maLine('200D', ma200)}{maLine('50D', ma50)}</>)}
      {foot('ETH', coin(eth, 0, snap.eth_24h_change))}
      {foot('SOL', coin(sol, 2, snap.sol_24h_change))}
    </div>
  </>);
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

/* ── ROW 1 Right: Lending card (GET /api/portfolio aave_positions) ── */
// A row counts as a position when collateral or debt is at least $0.01; the
// health factor comes only from rows reporting one above 0 (Zerion rows carry 0).
function _dashLendingModel(rows) {
  const list = Array.isArray(rows) ? rows.filter(r => r && typeof r === 'object') : [];
  const money = (v) => Number(v) || 0;
  const pos = list.filter(r => _dashNonZero(money(r.total_collateral_usd)) || _dashNonZero(money(r.total_debt_usd)));
  const hf = pos.filter(r => r.health_factor != null && Number.isFinite(Number(r.health_factor)) && Number(r.health_factor) > 0);
  let lowest = null;
  for (const r of hf) { if (!lowest || Number(r.health_factor) < Number(lowest.health_factor)) lowest = r; }
  const collateral = pos.reduce((s, r) => s + money(r.total_collateral_usd), 0);
  const debt = pos.reduce((s, r) => s + money(r.total_debt_usd), 0);
  return { pos, hf, lowest, collateral, debt, net: collateral - debt };
}

function DashLendingCard({ portfolio, status, hideValues }) {
  const narrow = useDashNarrow();
  const m = _dashLendingModel(portfolio && portfolio.aave_positions);
  if (status !== 'ok' || m.pos.length === 0) {
    const text = status === 'loading' ? '…' : status === 'error' ? 'Lending unavailable' : 'No lending positions';
    return (
      <div className="dash-card" style={{ padding: '14px 20px', display: 'flex', alignItems: 'baseline', alignContent: 'flex-start', flexWrap: 'wrap', columnGap: 12, rowGap: 4 }}>
        <div className="dash-label">LENDING</div>
        <div style={{ fontSize: 13, color: 'var(--dash-text3)' }}>{text}</div>
      </div>
    );
  }
  const money = (v) => (hideValues ? DASH_MASK_SUB : fmt(v, 0));
  const count = (v) => (hideValues ? DASH_MASK_COUNT : v);
  let hfText, hfColor, word;
  if (hideValues) { hfText = '••'; hfColor = 'var(--dash-text3)'; word = null; }
  else if (!m.lowest) { hfText = '—'; hfColor = 'var(--dash-text3)'; word = 'Health factor not reported (Zerion)'; }
  else {
    const h = Number(m.lowest.health_factor);
    hfText = h.toFixed(2);
    hfColor = h > 2 ? 'var(--dash-pos)' : h > 1.5 ? 'var(--dash-warn)' : 'var(--dash-neg)';
    word = h > 2 ? 'Safe zone' : h > 1.5 ? 'Caution' : 'Danger';
  }
  const hfRow = (
    <div style={{ display: 'flex', alignItems: 'baseline', flexWrap: 'wrap', gap: 8 }}>
      <span className="dash-num" style={{ fontSize: narrow ? 18 : 22, color: hfColor }}>{hfText}</span>
      {word && <span style={{ fontSize: 12, color: m.lowest ? hfColor : 'var(--dash-text3)' }}>{word}</span>}
    </div>
  );
  if (narrow) {
    return (
      <div className="dash-card" style={{ padding: '14px 16px', display: 'flex', flexDirection: 'column', gap: 6 }}>
        <div className="dash-label">LENDING</div>
        {hfRow}
      </div>
    );
  }
  // The protocol line describes the lowest-HF row, else the largest by collateral.
  const row = m.lowest || m.pos.reduce((a, r) => (Number(r.total_collateral_usd) || 0) > (Number(a.total_collateral_usd) || 0) ? r : a);
  const n = m.pos.length, k = m.pos.length - m.hf.length;
  return (
    <div className="dash-card" style={{ padding: '14px 20px', display: 'flex', flexDirection: 'column', gap: 8 }}>
      <div className="dash-label">LENDING · LOWEST HEALTH FACTOR</div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', flexWrap: 'wrap', gap: 8 }}>
        {hfRow}
        <div className="dash-num" style={{ fontSize: 12, color: 'var(--dash-text2)', marginLeft: 'auto', textAlign: 'right' }}>
          {'net ' + money(m.net) + ' · debt ' + money(m.debt)}
        </div>
      </div>
      <div style={{ fontSize: 12, color: 'var(--dash-text3)' }}>
        {[row.protocol_name, row.chain_name || row.chain, money(Number(row.total_collateral_usd) || 0) + ' collateral'].filter(Boolean).join(' · ')}
      </div>
      <div style={{ fontSize: 11, color: 'var(--dash-text4)' }}>
        {count(n) + (n === 1 && !hideValues ? ' position' : ' positions') + (k > 0 ? ' · ' + count(k) + ' without a health factor' : '')}
      </div>
    </div>
  );
}

/* ── ROW 3 Left: Spot P&L card (GET /api/spot/pnl + /api/spot/history) ── */
// Holding books (HANDOFF_trading_performance.md rulings 1-2): the Spot P&L
// card covers the trading book only; long-term / bot-capital positions get
// one line beneath it and an LT / BOT chip on 24h movers and Top holdings.
const DASH_BOOK_CHIP = { long_term: { text: 'LT', title: 'Long-term holding' }, bot_capital: { text: 'BOT', title: 'Bot capital' } };

function _dashBookOf(r) {
  return r && r.book ? r.book : 'trading';
}

function _dashBookChip(book) {
  const entry = DASH_BOOK_CHIP[book];
  if (!entry) return null;
  return (
    <span title={entry.title} style={{ flex: 'none', fontSize: 11, fontWeight: 600, lineHeight: '16px', padding: '0 6px', borderRadius: 4,
      border: '1px solid var(--dash-line)', color: 'var(--dash-text2)' }}>{entry.text}</span>
  );
}

// Open positions tagged long_term / bot_capital: count, priced count, value
// and unrealized (null when no row has one), with _dashSpotModel's null rules.
function _dashOtherBooksModel(rows) {
  const list = (Array.isArray(rows) ? rows : []).filter(r => r && typeof r === 'object' && _dashBookOf(r) !== 'trading');
  const priced = list.filter(r => _dashFinite(r.current_value_usd) != null);
  const u = list.filter(r => _dashFinite(r.unrealized_pnl_usd) != null);
  return {
    n: list.length, pricedN: priced.length,
    value: priced.reduce((s, r) => s + _dashFinite(r.current_value_usd), 0),
    unreal: u.length ? u.reduce((s, r) => s + _dashFinite(r.unrealized_pnl_usd), 0) : null,
  };
}

// A null value / unrealized means unpriced (unknown), not $0 (Spot page parity).
// history realized_pnl is lifetime realized per key; the route has no per-sale split.
function _dashSpotModel(rows, history, historyOk, nowMs) {
  const list = (Array.isArray(rows) ? rows : []).filter(r => r && typeof r === 'object');
  const priced = list.filter(r => _dashFinite(r.current_value_usd) != null);
  const value = priced.reduce((s, r) => s + _dashFinite(r.current_value_usd), 0);
  const u = list.filter(r => _dashFinite(r.unrealized_pnl_usd) != null);
  const unreal = u.reduce((s, r) => s + _dashFinite(r.unrealized_pnl_usd), 0);
  const cost = u.reduce((s, r) => s + (_dashFinite(r.total_cost_basis) || 0), 0);
  let realized30 = null;
  if (historyOk) {
    realized30 = 0;
    for (const h of (Array.isArray(history) ? history : [])) {
      const t = h ? Date.parse(String(h.last_sell_date)) : NaN;
      if (Number.isFinite(t) && t >= nowMs - 30 * DASH_DAY_MS) realized30 += _dashFinite(h.realized_pnl) || 0;
    }
  }
  const movers = list.filter(r => _dashFinite(r.unrealized_pct) != null)
    .sort((a, b) => Math.abs(_dashFinite(b.unrealized_pct)) - Math.abs(_dashFinite(a.unrealized_pct)))
    .slice(0, 5);
  let stamp = null;
  for (const r of priced) {
    const d = _dashParseUtc(r.price_as_of);
    if (d && (!stamp || d < stamp)) stamp = d;
  }
  return {
    n: list.length, pricedN: priced.length, unpricedN: list.length - priced.length, value,
    unreal: u.length ? unreal : null, unrealPct: cost > 0 ? unreal / cost * 100 : null, realized30, movers, stamp,
  };
}

function DashSpotCard({ model, status, hideValues, onOpen, other }) {
  const signed = (v, d) => (v >= 0 ? '+' : '') + fmt(v, d);
  const signColor = (v) => (v >= 0 ? 'var(--dash-pos)' : 'var(--dash-neg)');
  const header = (
    <div style={{ padding: '16px 20px 12px', display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
      <div className="dash-label">SPOT P&amp;L · TRADING</div>
      <div style={{ flex: 1 }} />
      <div className="dash-num" style={{ fontSize: 12, color: 'var(--dash-text4)' }}>{_dashClock(model.stamp) + ' · spot prices'}</div>
      <button type="button" className="dash-link" onClick={onOpen}>Open Spot →</button>
    </div>
  );
  const msg = (t) => <div style={{ padding: '0 20px 16px', fontSize: 13, color: 'var(--dash-text3)' }}>{t}</div>;
  const otherLine = other && other.n > 0 && (
    <div style={{ padding: '0 20px 12px', fontSize: 12, color: 'var(--dash-text3)' }}
      title="Excluded from the trading numbers above. Tag positions on the Spot page.">
      {'Long-term & bot: value ' + (hideValues ? DASH_MASK_SUB : other.pricedN ? fmt(other.value, 2) : '—')
        + ' · unrealized ' + (hideValues ? DASH_MASK_SUB : other.unreal == null ? '—' : signed(other.unreal, 2))}
    </div>
  );
  if (status === 'error') return <div className="dash-card" style={{ overflow: 'hidden' }}>{header}{msg('Spot P&L unavailable.')}</div>;
  if (status === 'ok' && model.n === 0 && other && other.n > 0) {
    return <div className="dash-card" style={{ overflow: 'hidden' }}>{header}{msg('No trading positions. Every open spot position is tagged long-term or bot capital.')}{otherLine}</div>;
  }
  if (status === 'ok' && model.n === 0) {
    return <div className="dash-card" style={{ overflow: 'hidden' }}>{header}{msg('No spot positions. Add them on the Spot Positions page to track P&L.')}</div>;
  }

  const loading = status !== 'ok';
  const cell = (label, value, color, suffix, title) => (
    <div title={title}>
      <div style={{ fontSize: 11, color: 'var(--dash-text4)' }}>{label}</div>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 6, flexWrap: 'wrap' }}>
        <span className="dash-num" style={{ fontSize: 18, color }}>{value}</span>
        {suffix && <span className="dash-num" style={{ fontSize: 12, color: 'var(--dash-text3)' }}>{suffix}</span>}
      </div>
    </div>
  );
  let unrealCell, realCell, valueCell;
  if (loading) {
    unrealCell = ['…', 'var(--dash-text)', null];
    realCell = ['…', 'var(--dash-text)'];
    valueCell = ['…', 'var(--dash-text)'];
  } else if (hideValues) {
    unrealCell = [DASH_MASK_MONEY, 'var(--dash-text)', DASH_MASK_PCT];
    realCell = [model.realized30 == null ? '—' : DASH_MASK_MONEY, model.realized30 == null ? 'var(--dash-text3)' : 'var(--dash-text)'];
    valueCell = [DASH_MASK_MONEY, 'var(--dash-text)'];
  } else {
    unrealCell = model.unreal == null ? ['—', 'var(--dash-text3)', null]
      : [signed(model.unreal, 2), signColor(model.unreal), model.unrealPct == null ? null : (model.unrealPct >= 0 ? '+' : '') + model.unrealPct.toFixed(2) + '%'];
    realCell = model.realized30 == null ? ['—', 'var(--dash-text3)'] : [signed(model.realized30, 2), signColor(model.realized30)];
    valueCell = model.pricedN ? [fmt(model.value, 2), 'var(--dash-text)'] : ['—', 'var(--dash-text3)'];
  }

  const right = { textAlign: 'right' };
  const rowText = (v, fn) => (v == null ? '—' : fn(v));
  return (
    <div className="dash-card" style={{ overflow: 'hidden' }}>
      {header}
      <div className="dash-spot-stats" style={{ gap: 12, padding: '0 20px 14px' }}>
        {cell('UNREALIZED', unrealCell[0], unrealCell[1], unrealCell[2])}
        {cell('REALIZED · SOLD IN 30D', realCell[0], realCell[1], null,
          'Lifetime realized P&L of positions with a sale in the last 30 days (the route has no per-sale split)')}
        {cell('CURRENT VALUE', valueCell[0], valueCell[1])}
      </div>
      {!loading && model.unpricedN > 0 && (
        <div style={{ padding: '0 20px 12px', fontSize: 11, color: 'var(--dash-text4)' }}>
          {hideValues ? DASH_MASK_COUNT + ' positions without a price are left out'
            : model.unpricedN === 1 ? '1 position without a price is left out'
            : model.unpricedN + ' positions without a price are left out'}
        </div>
      )}
      {!loading && otherLine}
      {!loading && (model.movers.length === 0 ? (
        <div style={{ padding: '0 20px 16px', fontSize: 12, color: 'var(--dash-text3)' }}>No priced positions</div>
      ) : (
        <div>
          <div className="dash-spot-row" style={{ minHeight: 30, background: 'var(--dash-band)', borderTop: '1px solid var(--dash-line)',
            borderBottom: '1px solid var(--dash-line)', fontSize: 11, fontWeight: 600, textTransform: 'uppercase', color: 'var(--dash-text4)' }}>
            <div title="Sorted by the size of unrealized %"><span className="dash-spot-sort-long">ASSET · BY UNREALIZED %</span><span className="dash-spot-sort-short">BY UNREAL. %</span></div>
            <div style={right}>VALUE</div>
            <div className="dash-spot-usd" style={right}>UNREALIZED</div>
            <div style={right}>%</div>
          </div>
          {model.movers.map((r, i) => {
            const usd = _dashFinite(r.unrealized_pnl_usd), pct = _dashFinite(r.unrealized_pct), val = _dashFinite(r.current_value_usd);
            const tone = (v) => (hideValues || v == null ? 'var(--dash-text)' : signColor(v));
            return (
              <div key={r.position_key || String(r.symbol) + i} className="dash-spot-row" style={{ borderBottom: '1px solid var(--dash-line)', fontSize: 12 }}>
                <div title={r.symbol} style={{ fontSize: 13, color: 'var(--dash-text2)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{r.symbol}</div>
                <div className="dash-num" style={{ ...right, color: 'var(--dash-text)' }}>{hideValues ? DASH_MASK_SUB : rowText(val, v => fmt(v, 2))}</div>
                <div className="dash-num dash-spot-usd" style={{ ...right, color: tone(usd) }}>{hideValues ? DASH_MASK_SUB : rowText(usd, v => signed(v, 2))}</div>
                <div className="dash-num" style={{ ...right, color: tone(pct) }}>{hideValues ? DASH_MASK_PCT : rowText(pct, v => (v >= 0 ? '+' : '') + v.toFixed(1) + '%')}</div>
              </div>
            );
          })}
        </div>
      ))}
    </div>
  );
}

/* ── ROW 1 Right: spot 24h movers + top holdings (GET /api/spot/pnl + /api/spot/change-24h) ── */
// Rulings (Glenn, Sep 29): spot positions only; the 24h change comes from
// snapshot history; movers ranked by |24h %| with an approximate $ change
// (value x pct / (100 + pct): today's value less the value at the older
// price, units assumed unchanged); % of portfolio = the live total's total_usd.
function _dashSpotCardsModel(spotRows, change, totalUsd) {
  const list = (Array.isArray(spotRows) ? spotRows : []).filter(r => r && typeof r === 'object');
  const positions = (change && change.positions && typeof change.positions === 'object') ? change.positions : {};
  const pctOf = (r) => { const c = positions[r.position_key]; return c ? _dashFinite(c.pct) : null; };
  const movers = list
    .filter(r => pctOf(r) != null && _dashFinite(r.current_value_usd) != null)
    .map(r => {
      const pct = pctOf(r), value = _dashFinite(r.current_value_usd);
      return { symbol: r.symbol, pct, value, usd24: value * pct / (100 + pct), position_key: r.position_key, book: _dashBookOf(r) };
    })
    .sort((a, b) => Math.abs(b.pct) - Math.abs(a.pct))
    .slice(0, 5);
  const holdings = list
    .filter(r => _dashFinite(r.current_value_usd) != null)
    .map(r => {
      const value = _dashFinite(r.current_value_usd);
      return { symbol: r.symbol, value, share: totalUsd > 0 ? value / totalUsd * 100 : null,
               unrealized_pct: _dashFinite(r.unrealized_pct), position_key: r.position_key, book: _dashBookOf(r) };
    })
    .sort((a, b) => b.value - a.value)
    .slice(0, 5);
  return { n: list.length, movers, noChangeN: list.filter(r => pctOf(r) == null).length, holdings,
           asOf: change ? _dashParseUtc(change.as_of) : null };
}

function _dashSpotMiniHeader(label, meta, onOpen) {
  return (
    <div style={{ padding: '16px 20px 12px', display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
      <div className="dash-label">{label}</div>
      <div style={{ flex: 1 }} />
      {meta && <div className="dash-num" style={{ fontSize: 12, color: 'var(--dash-text4)' }}>{meta}</div>}
      <button type="button" className="dash-link" onClick={onOpen}>Open Spot →</button>
    </div>
  );
}

function _dashSpotMiniHead(cols) {
  return (
    <div className="dash-mini-row" style={{ minHeight: 30, background: 'var(--dash-band)', borderTop: '1px solid var(--dash-line)',
      borderBottom: '1px solid var(--dash-line)', fontSize: 11, fontWeight: 600, textTransform: 'uppercase', color: 'var(--dash-text4)' }}>
      {cols.map(([text, cls], i) => (
        <div key={i} className={cls} style={i ? { textAlign: 'right' } : undefined}>{text}</div>
      ))}
    </div>
  );
}

const _dashSignColor = (v) => (v >= 0 ? 'var(--dash-pos)' : 'var(--dash-neg)');
const _dashSignedPct = (v, d) => (v >= 0 ? '+' : '') + v.toFixed(d) + '%';

function DashSpotMoversCard({ model, status, hideValues, onOpen }) {
  const header = _dashSpotMiniHeader('24H MOVERS · SPOT', 'as of ' + _dashClock(model.asOf) + ' · wallet snapshots', onOpen);
  const msg = (t) => <div style={{ padding: '0 20px 16px', fontSize: 13, color: 'var(--dash-text3)' }}>{t}</div>;
  const wrap = (body) => <div className="dash-card" style={{ overflow: 'hidden' }}>{header}{body}</div>;
  if (status === 'error') return wrap(msg('24h change unavailable.'));
  if (status !== 'ok') return wrap(msg('…'));
  if (model.n === 0) return wrap(msg('No spot positions.'));
  const n = model.noChangeN;
  const note = n > 0 && (
    <div style={{ padding: '8px 20px 12px', fontSize: 11, color: 'var(--dash-text4)' }}>
      {hideValues ? DASH_MASK_COUNT + ' positions without 24h data' : n === 1 ? '1 position without 24h data' : n + ' positions without 24h data'}
    </div>
  );
  if (model.movers.length === 0) return wrap(<>{msg('No 24h data yet')}{note}</>);
  const right = { textAlign: 'right' };
  return wrap(
    <div>
      {_dashSpotMiniHead([['ASSET'], ['24H %'], ['≈24H $'], ['VALUE', 'dash-mini-opt']])}
      {model.movers.map((r, i) => (
        <div key={r.position_key || String(r.symbol) + i} className="dash-mini-row" style={{ borderBottom: '1px solid var(--dash-line)', fontSize: 12 }}>
          <div title={r.symbol} style={{ display: 'flex', alignItems: 'center', gap: 6, minWidth: 0 }}>
            <span style={{ fontSize: 13, color: 'var(--dash-text2)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', minWidth: 0 }}>{r.symbol}</span>
            {_dashBookChip(r.book)}
          </div>
          <div className="dash-num" style={{ ...right, color: _dashSignColor(r.pct) }}>{_dashSignedPct(r.pct, 1)}</div>
          <div className="dash-num" style={{ ...right, color: hideValues ? 'var(--dash-text)' : _dashSignColor(r.usd24) }}
            title="Approximate: today's value less its value at the price 24 h ago">
            {hideValues ? DASH_MASK_SUB : (r.usd24 >= 0 ? '+' : '') + fmt(r.usd24, 0)}
          </div>
          <div className="dash-num dash-mini-opt" style={{ ...right, color: 'var(--dash-text)' }}>{hideValues ? DASH_MASK_SUB : fmt(r.value, 0)}</div>
        </div>
      ))}
      {note}
    </div>
  );
}

function DashTopHoldingsCard({ model, status, totalReady, hideValues, onOpen }) {
  const header = _dashSpotMiniHeader('TOP HOLDINGS · SPOT', null, onOpen);
  const msg = (t) => <div style={{ padding: '0 20px 16px', fontSize: 13, color: 'var(--dash-text3)' }}>{t}</div>;
  const wrap = (body) => <div className="dash-card" style={{ overflow: 'hidden' }}>{header}{body}</div>;
  if (status === 'error') return wrap(msg('Spot P&L unavailable.'));
  if (status !== 'ok') return wrap(msg('…'));
  if (model.n === 0) return wrap(msg('No spot positions. Add them on the Spot Positions page to track P&L.'));
  if (model.holdings.length === 0) return wrap(msg('No priced positions'));
  const right = { textAlign: 'right' };
  return wrap(
    <div>
      {_dashSpotMiniHead([['ASSET'], ['VALUE'], ['% OF PORTFOLIO'], ['UNREAL. %', 'dash-mini-opt']])}
      {model.holdings.map((r, i) => {
        const share = hideValues ? DASH_MASK_PCT : !totalReady ? '…' : r.share == null ? '—' : r.share.toFixed(1) + '%';
        const u = r.unrealized_pct;
        return (
          <div key={r.position_key || String(r.symbol) + i} className="dash-mini-row" style={{ borderBottom: '1px solid var(--dash-line)', fontSize: 12 }}>
            <div title={r.symbol} style={{ display: 'flex', alignItems: 'center', gap: 6, minWidth: 0 }}>
              <span style={{ fontSize: 13, color: 'var(--dash-text2)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', minWidth: 0 }}>{r.symbol}</span>
              {_dashBookChip(r.book)}
            </div>
            <div className="dash-num" style={{ ...right, color: 'var(--dash-text)' }}>{hideValues ? DASH_MASK_SUB : fmt(r.value, 0)}</div>
            <div className="dash-num" style={{ ...right, color: 'var(--dash-text)' }}>{share}</div>
            <div className="dash-num dash-mini-opt" style={{ ...right, color: hideValues || u == null ? 'var(--dash-text)' : _dashSignColor(u) }}>
              {hideValues ? DASH_MASK_PCT : u == null ? '—' : _dashSignedPct(u, 1)}
            </div>
          </div>
        );
      })}
    </div>
  );
}

/* ── ROW 3 Right: Hyperliquid card (the live total's Hyperliquid part) ── */
// Per wallet, VALUE is what the total counts: priced spot, plus perp equity only
// for 'counted' (standard-mode) wallets. Unified accounts hold perp inside spot.
function _dashHlModel(totalState, totalData, nowMs) {
  const comp = totalState === 'ok' ? _dashComp(totalData, 'hyperliquid') : null;
  if (!comp) return { comp: null };
  const detail = comp.detail || {};
  const rows = (Array.isArray(detail.wallets) ? detail.wallets : []).filter(w => w && typeof w === 'object').map(w => {
    const spot = (Array.isArray(w.spot) ? w.spot : []).reduce((s, x) => s + ((x && _dashFinite(x.value)) || 0), 0);
    const perp = _dashFinite(w.perp_account_value) || 0;
    return { w, spot, perp, counted: spot + (w.perp_treatment === 'counted' ? perp : 0), open: Number(w.open_perps) || 0 };
  }).filter(x => _dashNonZero(x.counted) || _dashNonZero(x.perp) || x.open > 0);
  const asOf = _dashParseUtc(comp.as_of);
  return {
    comp, counted: !!comp.counted, rows, value: _dashFinite(comp.value_usd), open: rows.reduce((s, x) => s + x.open, 0),
    checked: _dashFinite(detail.wallets_checked), anyInside: rows.some(x => x.w.perp_treatment === 'inside_spot'),
    asOf, stale: !!asOf && nowMs - asOf.getTime() > DASH_STALE_MS.hyperliquid,
  };
}

const DASH_HL_TAG = { inside_spot: 'in spot', not_counted_unknown_mode: 'not counted' };

// Wallet cell title: the full label and the address (a narrow column cuts the label off).
function _dashHlWalletTitle(w) {
  const name = w.label || String(w.wallet || '').slice(0, 10);
  const addr = String(w.wallet || '');
  return name + (addr && addr !== name ? ' · ' + addr : '') + (w.stale ? ' — last refresh failed, showing last good values' : '');
}

function DashHlCard({ model, totalState, hideValues }) {
  const narrow = useDashNarrow();
  const count = (v) => (hideValues ? DASH_MASK_COUNT : v == null ? '—' : v);
  let note = null;
  if (totalState === 'unavailable') note = 'Unavailable while the live total is unavailable.';
  else if (totalState === 'ok' && !model.comp) note = 'Hyperliquid is not part of the live total.';
  const pending = !note && (totalState !== 'ok' || !model.counted);
  const loadingLine = totalState === 'ok' && model.comp && !model.counted ? 'Hyperliquid loading — not in the total yet.' : null;
  const valueText = pending ? '…' : hideValues ? DASH_MASK_MONEY : model.value == null ? '—' : fmt(model.value, 2);
  const openText = pending ? '…' : count(model.open);
  const muted = (t, size) => <div style={{ fontSize: size, color: 'var(--dash-text3)' }}>{t}</div>;

  if (narrow) {
    return (
      <div className="dash-card" style={{ padding: '14px 16px', display: 'flex', flexWrap: 'wrap', alignItems: 'baseline', gap: 8 }}>
        <div className="dash-label">HYPERLIQUID</div>
        {note ? muted(note, 13) : <>
          <span className="dash-num" style={{ fontSize: 13, color: 'var(--dash-text)' }}>{valueText}</span>
          <span style={{ fontSize: 12, color: 'var(--dash-text3)' }}>{openText + ' open perps'}</span>
          {loadingLine && muted(loadingLine, 12)}
        </>}
      </div>
    );
  }

  const header = (
    <div style={{ padding: '16px 20px 12px', display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
      <div className="dash-label">HYPERLIQUID</div>
      <div style={{ flex: 1 }} />
      {model.comp && (
        <div className="dash-num" style={{ fontSize: 12, color: model.stale ? 'var(--dash-warn)' : 'var(--dash-text4)' }}>
          {_dashClock(model.asOf) + ' · ' + count(model.checked) + ' wallets checked'}
        </div>
      )}
    </div>
  );
  if (note) return <div className="dash-card" style={{ overflow: 'hidden' }}>{header}<div style={{ padding: '0 20px 16px' }}>{muted(note, 13)}</div></div>;

  const right = { textAlign: 'right' };
  const money = (v) => (hideValues ? DASH_MASK_SUB : fmt(v, 2));
  const headCell = { fontSize: 11, fontWeight: 600, textTransform: 'uppercase', color: 'var(--dash-text4)' };
  return (
    <div className="dash-card" style={{ overflow: 'hidden' }}>
      {header}
      <div className="dash-hl-stats" style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0,1fr))', gap: 12, padding: '0 20px 14px' }}>
        <div title="Counted in the total: priced spot balances, plus perp equity for standard-mode accounts. Unified accounts hold perp equity inside spot USDC.">
          <div style={{ fontSize: 11, color: 'var(--dash-text4)' }}>ACCOUNT VALUE</div>
          <div className="dash-num" style={{ fontSize: 18, color: 'var(--dash-text)' }}>{valueText}</div>
        </div>
        <div>
          <div style={{ fontSize: 11, color: 'var(--dash-text4)' }}>OPEN PERPS</div>
          <div className="dash-num" style={{ fontSize: 18, color: 'var(--dash-text)' }}>{openText}</div>
        </div>
      </div>
      {loadingLine && <div style={{ padding: '0 20px 16px' }}>{muted(loadingLine, 12)}</div>}
      {!pending && model.rows.length === 0 && <div style={{ padding: '0 20px 16px' }}>{muted('No Hyperliquid wallets connected, or all accounts at $0.', 13)}</div>}
      {!pending && model.rows.length > 0 && (
        <div>
          <div className="dash-hl-row" style={{ minHeight: 30, background: 'var(--dash-band)', borderTop: '1px solid var(--dash-line)', borderBottom: '1px solid var(--dash-line)', ...headCell }}>
            <div>WALLET</div><div style={right}>VALUE</div><div style={right}>PERP</div><div style={right}>OPEN</div>
          </div>
          {model.rows.map((x, i) => (
            <div key={x.w.wallet || i} className="dash-hl-row" style={{ minHeight: 36, borderBottom: '1px solid var(--dash-line)', padding: '6px 20px' }}>
              <div title={_dashHlWalletTitle(x.w)}
                style={{ fontSize: 13, color: 'var(--dash-text2)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {(x.w.stale ? '⚠ ' : '') + (x.w.label || String(x.w.wallet || '').slice(0, 10))}
              </div>
              <div className="dash-num" style={{ ...right, fontSize: 12, color: 'var(--dash-text)' }}>{money(x.counted)}</div>
              <div style={right}>
                <div className="dash-num" style={{ fontSize: 12, color: 'var(--dash-text3)' }}>{money(x.perp)}</div>
                {DASH_HL_TAG[x.w.perp_treatment] && <div style={{ fontSize: 11, color: 'var(--dash-text4)' }}>{DASH_HL_TAG[x.w.perp_treatment]}</div>}
              </div>
              <div className="dash-num" style={{ ...right, fontSize: 12, color: 'var(--dash-text)' }}>{count(x.open)}</div>
            </div>
          ))}
          <div className="dash-hl-row" style={{ minHeight: 36, background: 'var(--dash-band)', fontWeight: 500, fontSize: 12, color: 'var(--dash-text)' }}>
            <div style={{ fontSize: 13 }}>Total</div>
            <div className="dash-num" style={right}>{model.value == null ? '—' : money(model.value)}</div>
            <div />
            <div className="dash-num" style={right}>{count(model.open)}</div>
          </div>
          {model.anyInside && (
            <div style={{ padding: '8px 20px 12px', fontSize: 11, color: 'var(--dash-text4)' }}>Unified accounts hold perp equity inside spot USDC, so it is not added.</div>
          )}
        </div>
      )}
    </div>
  );
}

/* ── ROW 3 Right: Alpha Chasers (a Bittensor bot's result in TAO) ── */
// TAO amount text: masked when values are hidden, '—' for none.
function _dashTaoText(v, hide, signed) {
  if (hide) return '•••• TAO';
  if (v == null) return '—';
  return (signed && v >= 0 ? '+' : '') + v.toFixed(4) + ' TAO';
}

// Sparkline paths in a 0 0 300 56 box: the value-in-TAO line, and the net
// deposited step (the level in force at each moment) across the same window.
// null with fewer than 2 points.
function _dashAcSpark(series, deposits) {
  const pts = (Array.isArray(series) ? series : [])
    .map(p => ({ ms: Date.parse(p.t), v: p.tao_eq }))
    .filter(p => Number.isFinite(p.ms) && Number.isFinite(p.v));
  if (pts.length < 2) return null;
  const t0 = pts[0].ms, t1 = pts[pts.length - 1].ms;
  const deps = (Array.isArray(deposits) ? deposits : [])
    .map(d => ({ ms: Date.parse(d.t), v: d.net_tao }))
    .filter(d => Number.isFinite(d.ms) && Number.isFinite(d.v) && d.ms <= t1);
  const before = deps.filter(d => d.ms <= t0);
  const start = before.length ? before[before.length - 1].v : null;
  const inside = deps.filter(d => d.ms > t0);
  const levels = (start != null ? [start] : []).concat(inside.map(d => d.v));
  const vals = pts.map(p => p.v).concat(levels);
  let lo = Math.min(...vals), hi = Math.max(...vals);
  const pad = hi > lo ? (hi - lo) * 0.05 : (Math.abs(hi) * 0.05 || 1);
  lo -= pad; hi += pad;
  const x = (ms) => (t1 > t0 ? (ms - t0) / (t1 - t0) * 300 : 0).toFixed(1);
  const y = (v) => (56 - (v - lo) / (hi - lo) * 56).toFixed(1);
  const line = pts.map((p, i) => (i ? 'L' : 'M') + x(p.ms) + ' ' + y(p.v)).join(' ');
  let dep = null;
  if (levels.length) {
    dep = start != null ? 'M0 ' + y(start) : 'M' + x(inside[0].ms) + ' ' + y(inside[0].v);
    inside.forEach((d, i) => {
      if (start == null && i === 0) return;
      dep += ' H' + x(d.ms) + ' V' + y(d.v);
    });
    dep += ' H300';
  }
  return { line, dep };
}

// Today's local date as YYYY-MM-DD (the form's default).
function _dashLocalDate() {
  const d = new Date();
  const p = (n) => String(n).padStart(2, '0');
  return d.getFullYear() + '-' + p(d.getMonth() + 1) + '-' + p(d.getDate());
}

// One Bittensor wallet's card: stats, result vs net TAO deposited, trend,
// and the hand-entered deposits / withdrawals (POST/DELETE /api/bittensor/flows).
function DashAcWalletCard({ w, hideValues, onChanged }) {
  const flows = Array.isArray(w.flows) ? w.flows : [];
  const [open, setOpen] = useDashState(flows.length === 0);
  const [kind, setKind] = useDashState('deposit');
  const [amount, setAmount] = useDashState('');
  const [date, setDate] = useDashState(_dashLocalDate);
  const [note, setNote] = useDashState('');
  const [saving, setSaving] = useDashState(false);
  const [err, setErr] = useDashState(null);

  const stale = w.state === 'stale';
  const narrow = useDashNarrow();
  const label = 'ALPHA CHASERS' + (w.label && w.label !== 'Bittensor' ? ' · ' + w.label : '');
  const statLabel = { fontSize: 11, color: 'var(--dash-text4)' };
  const statValue = { fontSize: 18, color: 'var(--dash-text)' };
  const valueText = hideValues ? DASH_MASK_MONEY : w.usd_now == null ? '—' : fmt(w.usd_now, 2);

  // The result is shown against simply holding the TAO deposited: the % as the
  // headline, the TAO and the dollars (at today's TAO price) underneath. With no
  // result the tile shows '—' and one line below the stats says why.
  const counted = w.state === 'fresh' || w.state === 'stale';
  const hasResult = counted && w.net_deposited_tao != null && w.result_tao != null;
  let resultNote = null;
  if (!counted) {
    resultNote = <span style={{ color: 'var(--dash-warn)' }}>{'Not counted — ' + (w.reason || 'no Taostats data')}</span>;
  } else if (w.net_deposited_tao == null) {
    resultNote = <span style={{ color: 'var(--dash-text3)' }}>Record the starting deposit below to see the bot's result.</span>;
  }
  const resultColor = !hasResult || hideValues || w.result_tao === 0 ? 'var(--dash-text)'
    : w.result_tao > 0 ? 'var(--dash-pos)' : 'var(--dash-neg)';
  const taoResult = hasResult ? _dashTaoText(w.result_tao, hideValues, true) : null;
  let headline = '—';
  if (hasResult) {
    headline = hideValues ? DASH_MASK_PCT : w.result_pct != null ? _dashSignedPct(w.result_pct, 2) : taoResult;
  }
  let resultSub = null;
  if (hasResult) {
    const parts = [];
    if (headline !== taoResult) parts.push(taoResult);
    if (w.result_usd != null) parts.push(_dashPerpsSigned(w.result_usd, hideValues, DASH_MASK_SUB).text);
    resultSub = parts.length ? parts.join(' · ') : null;
  }
  const depositedSub = counted && w.net_deposited_tao != null
    ? 'deposited ' + _dashTaoText(w.net_deposited_tao, hideValues) : null;
  const statSub = { fontSize: 11, color: 'var(--dash-text3)', marginTop: 2 };

  const spark = _dashAcSpark(w.series, w.deposits);

  const send = async (url, init) => {
    setSaving(true);
    setErr(null);
    try {
      const r = await fetch(url, init);
      let body = null;
      try { body = await r.json(); } catch (_) {}
      if (!r.ok) { setErr((body && body.error) || 'HTTP ' + r.status); return false; }
      return true;
    } catch (_) {
      setErr('network error');
      return false;
    } finally {
      setSaving(false);
    }
  };
  const save = async () => {
    const ok = await send('/api/bittensor/flows', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ wallet: w.wallet, kind, amount_tao: Number(amount), date, note }),
    });
    if (!ok) return;
    setAmount('');
    setNote('');
    onChanged && onChanged();
  };
  const remove = async (id) => {
    if (!window.confirm('Delete this entry?')) return;
    if (await send('/api/bittensor/flows/' + id, { method: 'DELETE' })) onChanged && onChanged();
  };
  const input = { fontSize: 13, padding: '5px 8px', width: 'auto' };

  return (
    <div className="dash-card" style={{ overflow: 'hidden' }}>
      <div style={{ padding: '16px 20px 12px', display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <div className="dash-label">{label}</div>
        <div style={{ flex: 1 }} />
        <div className="dash-num" style={{ fontSize: 12, color: stale ? 'var(--dash-warn)' : 'var(--dash-text4)' }}>
          {_dashClock(_dashParseUtc(w.as_of))}
        </div>
        {stale && <span className="tv-chip warn" style={{ fontSize: 11, padding: '1px 6px' }}>stale</span>}
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: narrow ? 'repeat(2, minmax(0,1fr))' : 'repeat(3, minmax(0,1fr))',
                    gap: 12, padding: '0 20px 14px' }}>
        <div title="Plain TAO plus subnet alpha, valued at pool prices">
          <div style={statLabel}>VALUE IN TAO</div>
          <div className="dash-num" style={statValue}>{_dashTaoText(w.tao_now, hideValues)}</div>
          {depositedSub && <div className="dash-num" style={statSub}>{depositedSub}</div>}
        </div>
        <div>
          <div style={statLabel}>VALUE</div>
          <div className="dash-num" style={statValue}>{valueText}</div>
        </div>
        <div style={narrow ? { gridColumn: '1 / -1' } : undefined}
          title="The bot's result against simply holding the TAO you deposited: value in TAO now minus net TAO deposited. Dollars at today's TAO price.">
          <div style={statLabel}>VS HOLDING TAO</div>
          <div className="dash-num" style={{ ...statValue, color: resultColor }}>{headline}</div>
          {resultSub && (
            <div className="dash-num" style={{ ...statSub, color: hideValues ? 'var(--dash-text3)' : resultColor }}>{resultSub}</div>
          )}
        </div>
      </div>
      {resultNote && <div style={{ padding: '0 20px 10px', fontSize: 13 }}>{resultNote}</div>}
      <div style={{ padding: '0 20px 12px' }}>
        {spark ? (
          <svg viewBox="0 0 300 56" preserveAspectRatio="none" style={{ width: '100%', height: 56, display: 'block' }}
            role="img" aria-label="Value in TAO trend">
            <path d={spark.line} fill="none" stroke="var(--dash-text2)" strokeWidth="1.5" vectorEffect="non-scaling-stroke" />
            {spark.dep && <path d={spark.dep} fill="none" stroke="var(--dash-text4)" strokeWidth="1" strokeDasharray="4 3"
              vectorEffect="non-scaling-stroke" />}
          </svg>
        ) : (
          <div style={{ fontSize: 12, color: 'var(--dash-text3)' }}>Trend appears after the next snapshots.</div>
        )}
      </div>
      <div style={{ borderTop: '1px solid var(--dash-line)', padding: '10px 20px 14px' }}>
        <button type="button" className="dash-btn" aria-expanded={open} onClick={() => setOpen(o => !o)}>
          {'Deposits & withdrawals (' + (hideValues ? DASH_MASK_COUNT : flows.length) + ')'}
        </button>
        {open && (
          <div style={{ marginTop: 10, display: 'flex', flexDirection: 'column', gap: 8 }}>
            {flows.map(f => (
              <div key={f.id} style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: 13, flexWrap: 'wrap' }}>
                <span className="dash-num" style={{ color: 'var(--dash-text2)' }}>{String(f.flow_at || '').slice(0, 10)}</span>
                <span className="dash-num" style={{ color: 'var(--dash-text)' }}>{_dashTaoText(f.amount_tao, hideValues, true)}</span>
                <span style={{ color: 'var(--dash-text3)', flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {f.note || ''}
                </span>
                <button type="button" className="dash-btn" title="Delete" aria-label="Delete" disabled={saving}
                  onClick={() => remove(f.id)}>×</button>
              </div>
            ))}
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
              <select className="tv-input" style={input} value={kind} onChange={e => setKind(e.target.value)} aria-label="Kind">
                <option value="deposit">Deposit</option>
                <option value="withdrawal">Withdrawal</option>
              </select>
              <input className="tv-input" style={{ ...input, width: 130 }} type="number" step="any" min="0"
                placeholder="Amount (TAO)" aria-label="Amount (TAO)" value={amount} onChange={e => setAmount(e.target.value)} />
              <input className="tv-input" style={input} type="date" aria-label="Date" value={date}
                onChange={e => setDate(e.target.value)} />
              <input className="tv-input" style={{ ...input, flex: 1, minWidth: 120 }} type="text" maxLength={200}
                placeholder="Note (optional)" aria-label="Note" value={note} onChange={e => setNote(e.target.value)} />
              <button type="button" className="dash-btn" disabled={saving || !(Number(amount) > 0)} onClick={save}>Save</button>
            </div>
            {err && <div style={{ fontSize: 12, color: 'var(--dash-warn)' }}>{err}</div>}
          </div>
        )}
      </div>
    </div>
  );
}

// perf: { status: 'ok', as_of, wallets } | { status: 'loading' | 'cache_cold' | 'error' }.
function DashAlphaChasersCard({ perf, hideValues, onChanged }) {
  const status = perf && perf.status;
  if (status === 'ok') {
    const wallets = Array.isArray(perf.wallets) ? perf.wallets : [];
    if (!wallets.length) return null;
    return <>{wallets.map(w => <DashAcWalletCard key={w.wallet} w={w} hideValues={hideValues} onChanged={onChanged} />)}</>;
  }
  const busy = status === 'loading' || status === 'cache_cold';
  return (
    <div className="dash-card" style={{ overflow: 'hidden' }}>
      <div style={{ padding: '16px 20px 12px' }}><div className="dash-label">ALPHA CHASERS</div></div>
      <div style={{ padding: '0 20px 16px', fontSize: 13, color: busy ? 'var(--dash-text3)' : 'var(--dash-warn)' }}>
        {busy ? '…' : 'Alpha Chasers data unavailable.'}
      </div>
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
        else if (key === 'wallet_tokens') sub = _dashBtSub(c, subMoney);
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

function DashHeroCard({ model, hideValues, refreshing, totalIdle, onRefresh, maxfiAttention }) {
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
  // MaxFi positions out of range or with verdict Close (ruling Sep 29).
  const mxN = maxfiAttention || 0;
  const mxCount = hideValues ? DASH_MASK_COUNT : String(mxN);
  const mxWord = (!hideValues && mxN === 1) ? 'needs attention' : 'need attention';
  const goMaxfi = () => {
    const el = document.getElementById('dash-maxfi');
    if (!el) return;
    el.scrollIntoView({ block: 'center', behavior: 'smooth' });
    el.focus({ preventScroll: true });
  };
  return (
    <div className="dash-card" style={{ overflow: 'hidden' }}>
      <div style={{ padding: '18px 20px 16px', display: 'flex', flexDirection: 'column', gap: 8 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          <div className="dash-label">TOTAL PORTFOLIO VALUE</div>
          <div style={{ flex: 1 }} />
          {mxN > 0 && (
            <button type="button" className="dash-badge" onClick={goMaxfi}
              aria-label={'MaxFi: ' + mxCount + ' positions need attention — go to the MaxFi card'}>
              MaxFi: {mxCount} {mxWord}
            </button>
          )}
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

/* ── ROW 1a: trading card (GET /api/trading/trades + the open perps already loaded) ── */
const DASH_TRADING_DAYS = 30;

// A trade time in ms: a bare "YYYY-MM-DD" (spot trades) is that local
// calendar day's midnight; anything else goes through Date.parse. null when
// empty or unreadable.
function _dashTradeMs(v) {
  if (!v) return null;
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(v));
  const ms = m ? new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3])).getTime() : Date.parse(v);
  return Number.isFinite(ms) ? ms : null;
}

// The card's model. trades and perps are { status, data } states. Only
// trading-book trades count (ruling 2).
// - net30: net P&L and count of trades closed since local midnight
//   DASH_TRADING_DAYS days ago, by market.
// - risk (always <= 0, perps only): what the live perp stop orders of
//   /api/trading/perps/open would give back from current prices. Spot has no
//   price stops (Oct 2 ruling R2): its exit is the weekly trend, counted as
//   exit signals. Perp positions without a stop, with a partial stop or
//   without a price, and open manual perp trades, are counted, not summed.
function _dashTradingModel({ trades, perps, nowMs }) {
  if (!trades || trades.status !== 'ok' || !trades.data) {
    return { status: trades && trades.status === 'error' ? 'error' : 'loading' };
  }
  const summary = trades.data.summary || {};
  const list = (Array.isArray(trades.data.trades) ? trades.data.trades : []).filter(t => t && t.book === 'trading');

  const cut = new Date(nowMs);
  cut.setHours(0, 0, 0, 0);
  cut.setDate(cut.getDate() - DASH_TRADING_DAYS);
  const cutoff = cut.getTime();
  const net30 = { spot: { net: 0, n: 0 }, perp: { net: 0, n: 0 } };
  list.forEach(t => {
    if (t.status !== 'closed') return;
    const ms = _dashTradeMs(t.closed_at);
    const net = _dashFinite(t.net_pnl);
    const bucket = net30[t.market];
    if (ms == null || net == null || ms < cutoff || !bucket) return;
    bucket.net += net;
    bucket.n += 1;
  });

  const risk = { total: 0, noStop: 0, partial: 0, unpriced: 0,
                 pending: !perps || perps.status === 'loading', perpError: !!perps && perps.status === 'error' };
  list.forEach(t => {
    if (t.status !== 'closed' && t.market === 'perp' && t.source === 'manual') risk.unpriced += 1;   // no price feed
  });
  const positions = perps && perps.status === 'ok' && perps.data && Array.isArray(perps.data.positions)
    ? perps.data.positions : [];
  positions.forEach(p => {
    if (!p || typeof p !== 'object') return;
    const flags = Array.isArray(p.flags) ? p.flags : [];
    if (flags.includes('no_stop') || flags.includes('open_orders_unavailable')) { risk.noStop += 1; return; }
    if (flags.includes('stop_partial')) { risk.partial += 1; return; }
    const stop = _dashFinite(p.stop_px);
    const mark = _dashFinite(p.mark_px);
    const size = _dashFinite(p.size);
    if (stop == null || mark == null || size == null) { risk.unpriced += 1; return; }
    risk.total += Math.min(0, (stop - mark) * Math.abs(size) * (p.direction === 'short' ? -1 : 1));
  });

  const spot = summary.spot || {};
  const perp = summary.perp || {};
  const attention = {
    total: Number(summary.attention_count) || 0,
    stops: (Number(spot.needs_stop_count) || 0) + (Number(perp.needs_stop_count) || 0),
    reviews: (Number(spot.needs_review_count) || 0) + (Number(perp.needs_review_count) || 0),
    exits: (Number(spot.exit_signal_count) || 0) + (Number(perp.exit_signal_count) || 0),
  };
  return { status: 'ok', net30, risk, attention, gate: summary.gate || {} };
}

function DashTradingCard({ model, hideValues, onOpenSpot, onOpenPerps }) {
  const narrow = useDashNarrow();
  // The card covers both markets; its links open the Spot and Perps pages (Landing 3a).
  const header = (
    <div style={{ padding: '16px 20px 12px', display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
      <div className="dash-label">TRADING</div>
      <div style={{ flex: 1 }} />
      <button type="button" className="dash-link" onClick={onOpenSpot}>Open Spot →</button>
      <button type="button" className="dash-link" onClick={onOpenPerps}>Open Perps →</button>
    </div>
  );
  if (model.status !== 'ok') {
    return (
      <div className="dash-card" style={{ overflow: 'hidden' }}>
        {header}
        <div style={{ padding: '0 20px 16px', fontSize: 13, color: 'var(--dash-text3)' }}>
          {model.status === 'error' ? "Couldn't load trades." : 'Loading trading…'}
        </div>
      </div>
    );
  }
  // Signed money: "+$" / "-$", the mask when hidden, a neutral "$0.00".
  const money = (v) => _dashPerpsSigned(v, hideValues, DASH_MASK_MONEY);
  const plural = (n, one, many) => n + ' ' + (n === 1 ? one : many);
  const sub = (text, color, key) => (
    <div key={key} style={{ fontSize: 11, color: color || 'var(--dash-text3)', marginTop: 2 }}>{text}</div>
  );
  const tile = (label, value, color, subs, title) => (
    <div title={title} style={{ minWidth: 0 }}>
      <div style={{ fontSize: 11, color: 'var(--dash-text4)' }}>{label}</div>
      <div className="dash-num" style={{ fontSize: 18, color }}>{value}</div>
      {subs}
    </div>
  );

  const { net30, risk, attention, gate } = model;
  const spotNet = money(net30.spot.net);
  const perpNet = money(net30.perp.net);
  const riskVal = risk.pending ? { text: '…', color: 'var(--dash-text)' } : money(risk.total);
  const riskNotes = [];
  if (risk.noStop) riskNotes.push(risk.noStop + ' without a stop');
  if (risk.partial) riskNotes.push(risk.partial + ' with a partial stop');
  if (risk.unpriced) riskNotes.push(risk.unpriced + ' without a price');
  if (risk.perpError) riskNotes.push('perps unavailable');
  const attentionParts = [];
  if (attention.stops) attentionParts.push(plural(attention.stops, 'stop', 'stops'));
  if (attention.reviews) attentionParts.push(plural(attention.reviews, 'review', 'reviews'));
  if (attention.exits) attentionParts.push(plural(attention.exits, 'exit signal', 'exit signals'));
  const exp = _dashFinite(gate.expectancy_r);
  const expText = exp == null ? '—' : (exp > 0 ? '+' : '') + exp.toFixed(2) + 'R';
  const unlocked = !!gate.unlocked;
  const count = Number(gate.eligible_count) || 0;
  const target = Number(gate.target) || 0;
  // Landing 23: the server's three checks (count, average above min_avg_r, last recent_n above 0).
  const checks = gate.checks || {};
  const recentN = Number(gate.recent_n) || 0;
  const rText = v => v == null ? '—' : (v > 0 ? '+' : '') + v.toFixed(2) + 'R';
  const recentText = rText(_dashFinite(gate.recent_expectancy_r));
  const barText = rText(_dashFinite(gate.min_avg_r));
  const pending = Number(gate.pending_reviews) || 0;
  // Landing 15: the gate counts perp trades opened since gate.count_from ("YYYY-MM-DD", shown as written).
  const countDay = /^\d{4}-\d{2}-\d{2}$/.test(String(gate.count_from || ''))
    ? new Date(gate.count_from + 'T00:00:00').toLocaleDateString('en-US', { month: 'short', day: 'numeric' }) : null;
  const check = (ok, text, key) => (
    <div key={key} style={{ fontSize: 11, color: 'var(--dash-text3)', marginTop: 2 }}>
      <span style={{ fontWeight: 700, color: ok ? 'var(--dash-pos)' : 'var(--dash-neg)' }}>{ok ? '✓ ' : '✗ '}</span>
      {text}
    </div>
  );

  return (
    <div className="dash-card" style={{ overflow: 'hidden' }}>
      {header}
      <div style={{ display: 'grid', gridTemplateColumns: narrow ? 'repeat(2, minmax(0,1fr))' : 'repeat(5, minmax(0,1fr))',
                    gap: 12, padding: '0 20px 16px' }}>
        {tile('SPOT · 30D NET', spotNet.text, spotNet.color,
          sub(plural(net30.spot.n, 'trade closed', 'trades closed')),
          'Net P&L of trading spot trades closed in the last 30 days (whole trades, by close date)')}
        {tile('PERPS · 30D NET', perpNet.text, perpNet.color,
          sub(plural(net30.perp.n, 'trade closed', 'trades closed')),
          'Net P&L of perp trades closed in the last 30 days, after fees and funding')}
        {tile('OPEN RISK · PERPS', riskVal.text, riskVal.color,
          [sub('to stops from current prices', null, 'a'),
           riskNotes.length > 0 && sub(riskNotes.join(' · '), 'var(--dash-warn)', 'b')],
          'What every perp stop order would give back from current prices. Spot has no price stops: its exit is the weekly trend, shown as exit signals. Perp positions without a stop, with a partial stop or without a price are left out and counted underneath.')}
        {tile('NEEDS ATTENTION', String(attention.total), attention.total > 0 ? 'var(--dash-warn)' : 'var(--dash-text)',
          sub(attentionParts.length ? attentionParts.join(' · ') : 'nothing pending'),
          'Perp trades since the gate start that need a stop or a followed / deviated review, and spot trades whose weekly trend flipped bearish after they opened')}
        {tile('PERP RISK', unlocked ? '2% allowed' : 'Stay at 1%', unlocked ? 'var(--dash-pos)' : 'var(--dash-warn)',
          [check(!!checks.count, count + ' / ' + target + ' rule-following trades', 'a'),
           check(!!checks.average, 'average R ' + expText + ' (above ' + barText + ')', 'b'),
           check(!!checks.recent, 'last ' + recentN + ' average R ' + recentText + ' (above 0R)', 'c'),
           check(!!checks.reviews, pending ? pending + ' closed ' + (pending === 1 ? 'trade' : 'trades') + ' not reviewed'
             : 'closed trades reviewed', 'd')],
          'The perp risk step: 2% per trade is allowed once ' + target + '+ rule-following perp trades'
            + (countDay ? ' opened since ' + countDay + ' (UTC)' : '') + ' average above ' + barText
            + ' and the last ' + recentN + ' average above 0R, with every closed perp trade reviewed; it goes back to 1% '
            + 'as soon as one of these fails. '
            + 'Rule-following: marked Followed, tagged before the close, and passing the rule check')}
      </div>
    </div>
  );
}

/* ── ROW 1b: open perps card (GET /api/trading/perps/open) ── */
// A price at up to 6 significant digits ("$83,805", "$0.012345"); '—' for none.
function _dashPerpsPx(v) {
  const n = _dashFinite(v);
  return n == null ? '—' : '$' + n.toLocaleString('en-US', { maximumSignificantDigits: 6 });
}

function _dashPerpsUnits(v) {
  const n = _dashFinite(v);
  return n == null ? '—' : n.toLocaleString('en-US', { maximumSignificantDigits: 6 });
}

// A signed dollar amount and its color: '—' for none, the mask when hidden,
// '$0.00' (neutral) when it rounds to zero cents.
function _dashPerpsSigned(v, hide, mask) {
  if (v == null) return { text: '—', color: 'var(--dash-text3)' };
  if (hide) return { text: mask, color: 'var(--dash-text)' };
  if (!_dashNonZero(v)) return { text: '$0.00', color: 'var(--dash-text)' };
  return { text: (v > 0 ? '+' : '') + fmt(v, 2), color: _dashSignColor(v) };
}

// True while another read is worth making: a venue is still loading, or its snapshot is older than the server's refresh age (this request started a refresh).
function _dashPerpsWaiting(d, nowMs) {
  return (Array.isArray(d && d.venues) ? d.venues : []).some(v => {
    if (!v || typeof v !== 'object') return false;
    if (v.status === 'loading') return true;
    const t = v.status === 'ok' ? _dashParseUtc(v.as_of) : null;
    return !!t && nowMs - t.getTime() > DASH_PERPS_REFRESH_AGE_MS;
  });
}

// The card's model from { status, data } (the raw route answer). Numbers are
// parsed here; funding is shown as DASH_PERPS_FUNDING_SIGN x the raw value.
function _dashPerpsModel(state, nowMs) {
  const data = state && state.data;
  if (!state || state.status !== 'ok' || !data) return { status: state && state.status === 'error' ? 'error' : 'loading' };
  if (!(Array.isArray(data.positions) && data.totals && typeof data.totals === 'object' && Array.isArray(data.venues))) {
    return { status: 'error' };
  }
  const venues = data.venues.filter(v => v && typeof v === 'object').map(v => {
    const asOf = _dashParseUtc(v.as_of);
    return { name: String(v.venue || ''), status: v.status, error: v.error || null, asOf,
             stale: !!asOf && nowMs - asOf.getTime() > DASH_STALE_MS.hyperliquid };
  });
  const rows = data.positions.filter(p => p && typeof p === 'object').map(p => {
    const f = _dashFinite(p.funding_since_open);
    return { ...p, value: _dashFinite(p.position_value), size: _dashFinite(p.size), unreal: _dashFinite(p.unrealized_pnl),
             unrealPct: _dashFinite(p.unrealized_pct), stopDist: _dashFinite(p.stop_distance_pct),
             ifStopped: _dashFinite(p.if_stopped_pnl), funding: f == null ? null : DASH_PERPS_FUNDING_SIGN * f,
             flags: Array.isArray(p.flags) ? p.flags : [] };
  });
  const t = data.totals;
  const totals = { count: Number(t.open_count) || 0, notional: _dashFinite(t.notional), unreal: _dashFinite(t.unrealized),
                   ifStopped: _dashFinite(t.if_stopped), noStop: Number(t.no_stop_count) || 0 };
  return { status: 'ok', rows, totals, venues,
           allVenuesOk: venues.length > 0 && venues.every(v => v.status === 'ok'),
           anyStale: venues.some(v => v.stale) };
}

function DashOpenPerpsCard({ model, hideValues }) {
  const narrow = useDashNarrow();
  const ok = model.status === 'ok';
  const meta = ok ? model.venues.map(v => v.name + ' ' + (v.asOf ? _dashClock(v.asOf) : v.status === 'error' ? 'unavailable' : 'loading…')).join(' · ') : '';
  const header = (
    <div style={{ padding: '16px 20px 12px', display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
      <div className="dash-label">OPEN PERPS</div>
      <div style={{ flex: 1 }} />
      {ok && (
        <div className="dash-num" style={{ fontSize: 12, color: model.anyStale ? 'var(--dash-warn)' : 'var(--dash-text4)' }}
          title={model.anyStale ? 'Older than 30 minutes - the background refresh may be failing' : undefined}>{meta}</div>
      )}
    </div>
  );
  const line = (t) => <div style={{ padding: '0 20px 16px', fontSize: 13, color: 'var(--dash-text3)' }}>{t}</div>;
  if (!ok) {
    return <div className="dash-card" style={{ overflow: 'hidden' }}>{header}{line(model.status === 'error' ? "Couldn't load open perps." : 'Loading open perps…')}</div>;
  }

  const { totals } = model;
  const tile = (label, value, color, title, extra) => (
    <div title={title}>
      <div style={{ fontSize: 11, color: 'var(--dash-text4)' }}>{label}</div>
      <div className="dash-num" style={{ fontSize: 18, color }}>{value}</div>
      {extra}
    </div>
  );
  const unrealT = _dashPerpsSigned(totals.unreal, hideValues, DASH_MASK_MONEY);
  const stopT = _dashPerpsSigned(totals.ifStopped, hideValues, DASH_MASK_MONEY);

  const notes = [];
  for (const v of model.venues) {
    let text = null, color = 'var(--dash-warn)';
    if (v.status === 'loading') { text = v.name + ': loading positions…'; color = 'var(--dash-text3)'; }
    else if (v.status === 'error') text = v.name + ": couldn't read positions — " + (v.error || 'unknown error');
    else if (v.status === 'ok' && v.error) text = v.name + ': latest refresh failed, showing the ' + _dashClock(v.asOf) + ' values — ' + v.error;
    if (text) {
      notes.push(<div key={'note|' + v.name} title={text} style={{ padding: '0 20px 10px', fontSize: 12, color, whiteSpace: 'nowrap',
        overflow: 'hidden', textOverflow: 'ellipsis' }}>{text}</div>);
    }
  }

  const gridRow = { display: 'grid', gridTemplateColumns: DASH_PERPS_GRID, columnGap: 10, padding: '6px 20px', alignItems: 'center' };
  const right = { textAlign: 'right' };
  const two = (l1, l2, opts = {}) => (
    <div style={opts.left ? { minWidth: 0 } : right} title={opts.title}>
      {l1}
      <div className={opts.l2Num ? 'dash-num' : undefined}
        style={{ fontSize: 11, color: opts.l2Color || 'var(--dash-text3)', minHeight: 14 }}>{l2}</div>
    </div>
  );
  const num = (text, color, extra) => <div className="dash-num" style={{ fontSize: 12, color, ...extra }}>{text}</div>;
  const headCell = (text, title, left) => <div title={title} style={left ? undefined : right}>{text}</div>;

  const rowEl = (r) => {
    const unreal = _dashPerpsSigned(r.unreal, hideValues, DASH_MASK_SUB);
    const ifStop = _dashPerpsSigned(r.ifStopped, hideValues, DASH_MASK_SUB);
    const fund = _dashPerpsSigned(r.funding, hideValues, DASH_MASK_SUB);
    const long_ = r.direction === 'long';
    let stopCell;
    if (r.flags.includes('open_orders_unavailable')) {
      stopCell = two(num('unknown', 'var(--dash-text3)'), '',
        { title: 'Open orders could not be read' + (r.open_orders_error ? ': ' + r.open_orders_error : '') });
    } else if (r.flags.includes('no_stop')) {
      stopCell = two(num('NO STOP', 'var(--dash-warn)', { fontWeight: 700 }), '', { title: 'No stop order found for this position' });
    } else {
      const partial = r.flags.includes('stop_partial');
      stopCell = two(num(_dashPerpsPx(r.stop_px), 'var(--dash-text)'),
        <>{r.stopDist == null ? '' : _dashSignedPct(r.stopDist, 2)}
          {partial && <>{' · '}<span style={{ color: 'var(--dash-warn)' }} title="This stop covers only part of the position">partial</span></>}</>,
        { l2Num: true });
    }
    const tp = _dashPerpsPx(r.tp_px);
    const liq = _dashPerpsPx(r.liquidation_px);
    const lev = r.leverage != null ? (r.leverage + '× ' + (r.leverage_type || '')).trim() : '';
    return (
      <div key={r.venue + '|' + r.wallet_label + '|' + r.coin} style={{ ...gridRow, minHeight: 44, borderBottom: '1px solid var(--dash-line)' }}>
        {two(<div style={{ fontSize: 13, color: 'var(--dash-text2)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
               {(r.stale ? '⚠ ' : '') + r.wallet_label}</div>,
             <span style={{ color: 'var(--dash-text4)' }}>{r.venue}</span>,
             { left: true, title: r.wallet_label + (r.stale ? ' — latest refresh failed, showing last good values' : '') })}
        {two(<div style={{ display: 'flex', alignItems: 'center', gap: 6, minWidth: 0 }}>
               <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--dash-text)' }}>{r.coin}</span>
               <span style={{ fontSize: 11, fontWeight: 600, padding: '1px 6px', borderRadius: 4, border: '1px solid currentColor',
                 color: long_ ? 'var(--dash-pos)' : 'var(--dash-neg)' }}>{long_ ? 'LONG' : 'SHORT'}</span>
             </div>, lev, { left: true })}
        {two(num(hideValues ? DASH_MASK_SUB : r.value == null ? '—' : fmt(r.value, 2), 'var(--dash-text)'),
             (hideValues ? DASH_MASK_COUNT : _dashPerpsUnits(r.size)) + ' ' + r.coin, { l2Num: true })}
        {two(num(_dashPerpsPx(r.entry_px), 'var(--dash-text)'), '')}
        {two(num(_dashPerpsPx(r.mark_px), 'var(--dash-text)'), '')}
        {two(num(unreal.text, unreal.color),
             r.unrealPct == null ? '' : hideValues ? DASH_MASK_PCT : _dashSignedPct(r.unrealPct, 2), { l2Color: unreal.color, l2Num: true })}
        {stopCell}
        {two(num(ifStop.text, ifStop.color), '',
             { title: r.flags.includes('stop_partial') ? 'Covers only the stopped part of the position' : undefined })}
        {two(num(tp, tp === '—' ? 'var(--dash-text3)' : 'var(--dash-text)'), '')}
        {two(num(liq, liq === '—' ? 'var(--dash-text3)' : 'var(--dash-text)'), '',
             { title: liq === '—' ? "Hyperliquid gives no liquidation price for this position; in cross margin this usually means the account's equity covers it" : undefined })}
        {two(num(fund.text, fund.color), '',
             { title: !hideValues && r.funding != null ? 'Funding since open: ' + r.funding.toFixed(6) + ' USD (negative = paid, positive = received)' : undefined })}
      </div>
    );
  };

  return (
    <div className="dash-card" style={{ overflow: 'hidden' }}>
      {header}
      {(model.rows.length > 0 || model.allVenuesOk) && <div style={{ display: 'grid',
        gridTemplateColumns: narrow ? 'repeat(2, minmax(0,1fr))' : 'repeat(4, minmax(0,1fr))', gap: 12, padding: '0 20px 14px' }}>
        {tile('OPEN', hideValues ? DASH_MASK_COUNT : totals.count, 'var(--dash-text)')}
        {tile('NOTIONAL', hideValues ? DASH_MASK_MONEY : totals.notional == null ? '—' : fmt(totals.notional, 2),
              'var(--dash-text)', 'Sum of position values at mark')}
        {tile('UNREALIZED', unrealT.text, unrealT.color)}
        {tile('IF ALL STOPS HIT', stopT.text, stopT.color,
              'P&L if every live stop fills at its trigger price, before fees and funding',
              totals.noStop > 0 && <div style={{ fontSize: 11, color: 'var(--dash-warn)' }}>
                {'excludes ' + (hideValues ? DASH_MASK_COUNT : totals.noStop) + ' without a known stop'}</div>)}
      </div>}
      {notes}
      {model.rows.length === 0
        ? (model.allVenuesOk ? line('No open perp positions.') : null)
        : (
          <div style={{ overflowX: 'auto' }}>
            <div style={{ minWidth: DASH_PERPS_MIN_WIDTH }}>
              <div style={{ ...gridRow, minHeight: 30, background: 'var(--dash-band)', borderTop: '1px solid var(--dash-line)',
                borderBottom: '2px solid var(--dash-line)', fontSize: 11, fontWeight: 600, textTransform: 'uppercase',
                color: 'var(--dash-text4)' }}>
                {headCell('VENUE · WALLET', undefined, true)}
                {headCell('POSITION', undefined, true)}
                {headCell('SIZE')}
                {headCell('ENTRY')}
                {headCell('MARK')}
                {headCell('UNREALIZED')}
                {headCell('STOP', 'Tightest live stop order; second line = distance from mark')}
                {headCell('IF STOPPED', 'P&L if the stop fills at its trigger price, before fees and funding')}
                {headCell('TP')}
                {headCell('LIQ.')}
                {headCell('FUNDING', 'Funding since the position opened: negative = paid, positive = received')}
              </div>
              {model.rows.map(rowEl)}
            </div>
          </div>
        )}
    </div>
  );
}

/* ── ROW 2: equity card (complete-total history, GET /api/history/portfolio-total-chart) ── */
const DASH_DAY_MS = 86400000;
const DASH_RANGES = [['24H', 1], ['1W', 7], ['1M', 30], ['1Y', 365], ['ALL', null]];
const DASH_CROSSED_TITLE = ' · Across a definition change, both ends are compared on the old basis (old snapshot total + Hyperliquid)';
// What the points BEFORE a seam into definition version N leave out (the seam
// chip and legend use it; unknown versions fall back to generic text).
const DASH_SEAM_TEXT = { 1: 'Hyperliquid reconstructed, MaxFi fees not included', 2: 'DexFi bonds not counted' };

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
      {p.v === 1 && <div style={{ color: 'var(--dash-text3)' }}>DexFi bonds not counted</div>}
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
  const seams = chart.seams.map(s => ({ ...s, ms: Date.parse(s.t) })).filter(s => Number.isFinite(s.ms));

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
  // Every definition seam inside the visible range gets a line.
  const visibleSeams = firstMs == null ? [] : seams.filter(s => s.ms >= firstMs && s.ms <= lastMs);
  const latestSeam = visibleSeams.length ? visibleSeams[visibleSeams.length - 1] : null;
  const newestV = points.reduce((m, p) => (p.v != null && (m == null || p.v > m) ? p.v : m), null);

  let chip = null;
  if (points.length && first) {
    if (latestSeam && first.ms < latestSeam.ms) {
      chip = { tone: 'neutral', text: 'Before ' + _dashDateTime(new Date(latestSeam.ms)) + ': '
        + (DASH_SEAM_TEXT[latestSeam.to_v] || 'earlier definition') };
    } else if (inRange.every(p => p.v === 0)) {
      chip = { tone: 'neutral', text: DASH_SEAM_TEXT[1] };
    } else if (inRange.every(p => p.v === newestV)) {
      chip = { tone: 'pos', text: 'Same parts as the headline' };
    } else {
      chip = { tone: 'neutral', text: 'Earlier definition: ' + (DASH_SEAM_TEXT[first.v + 1] || 'parts differ') };
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
          {Customized && visibleSeams.map(s => <Customized key={s.t} component={<DashSeamLine x={s.ms} />} />)}
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
          {visibleSeams.length > 0 && (
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
              <span aria-hidden="true" style={{ width: 12, borderTop: '2px dashed var(--dash-text3)' }} />
              {(visibleSeams.length === 1 ? 'Definition change · ' : 'Definition changes · ')
                + visibleSeams.map(s => _dashDateTime(new Date(s.ms))).join(', ')}
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
function DashboardScreen({ hideValues, refreshTrigger, setActiveTab, setPortfolioSubTab }) {
  const [portfolio,   setPortfolio]   = useDashState(null);
  // Equity chart (GET /api/history/portfolio-total-chart); status 'loading' | 'ok' | 'error'.
  const [chart,       setChart]       = useDashState({ status: 'loading', points: [], seams: [], excluded: {}, benchmarks: [] });
  const [marketData,  setMarketData]  = useDashState(null);
  const [spotPnl,     setSpotPnl]     = useDashState([]);
  const [spotHistory, setSpotHistory] = useDashState([]);
  // 24h change per open spot position (GET /api/spot/change-24h): status 'loading' | 'ok' | 'error'.
  const [spotChange,  setSpotChange]  = useDashState({ status: 'loading', data: null });
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
  const [spotStatus,      setSpotStatus]      = useDashState('loading');
  const [historyStatus,   setHistoryStatus]   = useDashState('loading');
  // Alpha Chasers (GET /api/bittensor/performance): status 'loading' | 'ok' | 'cache_cold' | 'error'.
  const [btPerf,          setBtPerf]          = useDashState({ status: 'loading', data: null });
  // Open perps card (GET /api/trading/perps/open): status 'loading' | 'ok' | 'error'.
  const [perpsOpen, setPerpsOpen] = useDashState({ status: 'loading', data: null });
  // Trading card: the GET /api/trading/trades answer.
  const [tradesState, setTradesState] = useDashState({ status: 'loading', data: null });
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

  // Alpha Chasers data (cache-only on the server); again after each flow edit.
  const loadBtPerf = useDashCallback(() => fetch('/api/bittensor/performance').then(r => r.json()).then(
    d => setBtPerf(d && Array.isArray(d.wallets) ? { status: 'ok', data: d }
      : d && d.status === 'cache_cold' ? { status: 'cache_cold', data: null } : { status: 'error', data: null }),
    () => setBtPerf({ status: 'error', data: null })), []);

  // Re-reads every DASH_PERPS_RETRY_MS while _dashPerpsWaiting (a venue still loading, or a snapshot older than the server's refresh age), at most DASH_PERPS_MAX_ATTEMPTS reads. A newer fetchAll or unmount bumps allGenRef and ends the loop; a read that times out shows the error state.
  const loadPerpsOpen = useDashCallback(async (gen) => {
    for (let attempt = 1; attempt <= DASH_PERPS_MAX_ATTEMPTS; attempt++) {
      let d = null;
      const ctrl = new AbortController();
      const timer = setTimeout(() => ctrl.abort(), DASH_PERPS_TIMEOUT_MS);
      try { const r = await fetch('/api/trading/perps/open', { signal: ctrl.signal }); d = await r.json(); }
      catch (_) { d = null; }
      finally { clearTimeout(timer); }
      if (gen !== allGenRef.current) return;
      if (!d || !Array.isArray(d.positions) || !Array.isArray(d.venues)) { setPerpsOpen({ status: 'error', data: null }); return; }
      setPerpsOpen({ status: 'ok', data: d });
      if (!_dashPerpsWaiting(d, Date.now()) || attempt === DASH_PERPS_MAX_ATTEMPTS) return;
      await new Promise(res => setTimeout(res, DASH_PERPS_RETRY_MS));
      if (gen !== allGenRef.current) return;
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
    // Started, not returned: Refresh does not wait for the open-perps retry loop.
    loadPerpsOpen(gen);
    const load = (url, apply, fallbackValue) => fetch(url).then(r => r.json()).then(
      d => { if (live()) apply(d); },
      () => { if (live()) apply(fallbackValue); });
    return Promise.all([
      load('/api/portfolio', d => {
        setPortfolio(d);
        setPortfolioStatus(d && typeof d === 'object' && !d.error ? 'ok' : 'error');
      }, null).then(() => { if (live()) { fetchTotal(); loadBtPerf(); } }),
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
      load('/api/spot/pnl', d => { setSpotPnl(Array.isArray(d) ? d : []); setSpotStatus(Array.isArray(d) ? 'ok' : 'error'); }, null),
      load('/api/trading/trades', d => {
        const ok = !!(d && Array.isArray(d.trades) && d.summary && typeof d.summary === 'object');
        setTradesState(ok ? { status: 'ok', data: d } : { status: 'error', data: null });
        // Keep the nav's Spot and Perps badges in step (tradesNavCounts in utils.js).
        const counts = ok ? tradesNavCounts(d) : null;
        if (counts) window.dispatchEvent(new CustomEvent('trades-attention', { detail: counts }));
      }, null),
      load('/api/spot/change-24h', d => setSpotChange(d && d.positions && typeof d.positions === 'object'
        ? { status: 'ok', data: d } : { status: 'error', data: null }), null),
      load('/api/spot/history', d => { setSpotHistory(Array.isArray(d) ? d : []); setHistoryStatus(Array.isArray(d) ? 'ok' : 'error'); }, null),
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
  }, [fetchTotal, runRange, loadBtPerf, loadPerpsOpen]);

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
  const spotModel = _dashSpotModel((Array.isArray(spotPnl) ? spotPnl : []).filter(r => _dashBookOf(r) === 'trading'),
    (Array.isArray(spotHistory) ? spotHistory : []).filter(h => _dashBookOf(h) === 'trading'), historyStatus === 'ok', Date.now());
  const spotOther = _dashOtherBooksModel(spotPnl);
  const perpsModel = _dashPerpsModel(perpsOpen, Date.now());
  const tradingModel = _dashTradingModel({ trades: tradesState, perps: perpsOpen, nowMs: Date.now() });
  const hlModel = _dashHlModel(totalState, totalData, Date.now());
  const onOpenSpot = () => { setActiveTab && setActiveTab('spot'); };
  const maxfiModel = _dashMaxfiModel({ advisor, wallets: mxWallets, range: mxRange, hideValues, nowMs: Date.now() });
  const maxfiAttention = maxfiModel.status === 'ok'
    ? maxfiModel.rows.filter(x => x.state === 'out' || x.verdict === 'close').length : 0;
  const liveTotal = totalState === 'ok' && totalData ? _dashFinite(totalData.total_usd) : null;
  const spotCards = _dashSpotCardsModel(spotPnl, spotChange.data, liveTotal);
  const moversStatus = spotStatus === 'error' || spotChange.status === 'error' ? 'error'
    : spotStatus === 'ok' && spotChange.status === 'ok' ? 'ok' : 'loading';

  return (
    <div className="dash-page">

      {/* ── ROW 1 — Hero + right column ── */}
      <div className="dash-row1">
        <DashHeroCard model={heroModel} hideValues={hideValues} refreshing={refreshing}
          totalIdle={totalState === 'idle'} onRefresh={handleRefresh} maxfiAttention={maxfiAttention} />

        <div className="dash-right">
          <DashSpotMoversCard model={spotCards} status={moversStatus} hideValues={hideValues} onOpen={onOpenSpot} />
          <DashTopHoldingsCard model={spotCards} status={spotStatus} totalReady={totalState !== 'idle'}
            hideValues={hideValues} onOpen={onOpenSpot} />
        </div>
      </div>

      {/* ── ROW 1a — Trading (full width) ── */}
      <DashTradingCard model={tradingModel} hideValues={hideValues} onOpenSpot={onOpenSpot}
        onOpenPerps={() => setActiveTab && setActiveTab('perps')} />

      {/* ── ROW 1b — Open perps (full width) ── */}
      <DashOpenPerpsCard model={perpsModel} hideValues={hideValues} />

      {/* ── ROW 2 — Equity chart ── */}
      <DashEquityCard chart={chart} hideValues={hideValues} />

      {/* ── ROW 3 — Spot P&L + Hyperliquid / Alpha Chasers ── */}
      <div className="dash-row3">
        <DashSpotCard model={spotModel} status={spotStatus} hideValues={hideValues} onOpen={onOpenSpot} other={spotOther} />
        <div className="dash-row3-right">
          <DashHlCard model={hlModel} totalState={totalState} hideValues={hideValues} />
          <DashAlphaChasersCard perf={btPerf.status === 'ok' ? { status: 'ok', ...btPerf.data } : { status: btPerf.status }}
            hideValues={hideValues} onChanged={loadBtPerf} />
        </div>
      </div>

      {/* ── ROW 4 — MaxFi + Market + Lending ── */}
      <div className="dash-row4">
        <div id="dash-maxfi" tabIndex={-1}>
          <DashMaxfiCard model={maxfiModel} hideValues={hideValues} onOpen={() => setActiveTab && setActiveTab('maxfi')} />
        </div>
        <DashBtcCard snap={marketData?.snapshot || {}} status={marketStatus} />
        <DashLendingCard portfolio={portfolio} status={portfolioStatus} hideValues={hideValues} />
      </div>

    </div>
  );
}

window.DashboardScreen = DashboardScreen;
