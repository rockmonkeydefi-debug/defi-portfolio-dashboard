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

function DashSpotCard({ model, status, hideValues, onOpen }) {
  const signed = (v, d) => (v >= 0 ? '+' : '') + fmt(v, d);
  const signColor = (v) => (v >= 0 ? 'var(--dash-pos)' : 'var(--dash-neg)');
  const header = (
    <div style={{ padding: '16px 20px 12px', display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
      <div className="dash-label">SPOT P&amp;L</div>
      <div style={{ flex: 1 }} />
      <div className="dash-num" style={{ fontSize: 12, color: 'var(--dash-text4)' }}>{_dashClock(model.stamp) + ' · spot prices'}</div>
      <button type="button" className="dash-link" onClick={onOpen}>Open Spot →</button>
    </div>
  );
  const msg = (t) => <div style={{ padding: '0 20px 16px', fontSize: 13, color: 'var(--dash-text3)' }}>{t}</div>;
  if (status === 'error') return <div className="dash-card" style={{ overflow: 'hidden' }}>{header}{msg('Spot P&L unavailable.')}</div>;
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
      return { symbol: r.symbol, pct, value, usd24: value * pct / (100 + pct), position_key: r.position_key };
    })
    .sort((a, b) => Math.abs(b.pct) - Math.abs(a.pct))
    .slice(0, 5);
  const holdings = list
    .filter(r => _dashFinite(r.current_value_usd) != null)
    .map(r => {
      const value = _dashFinite(r.current_value_usd);
      return { symbol: r.symbol, value, share: totalUsd > 0 ? value / totalUsd * 100 : null,
               unrealized_pct: _dashFinite(r.unrealized_pct), position_key: r.position_key };
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
          <div title={r.symbol} style={{ fontSize: 13, color: 'var(--dash-text2)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{r.symbol}</div>
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
            <div title={r.symbol} style={{ fontSize: 13, color: 'var(--dash-text2)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{r.symbol}</div>
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
      load('/api/spot/pnl', d => { setSpotPnl(Array.isArray(d) ? d : []); setSpotStatus(Array.isArray(d) ? 'ok' : 'error'); }, null),
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
  const spotModel = _dashSpotModel(spotPnl, spotHistory, historyStatus === 'ok', Date.now());
  const hlModel = _dashHlModel(totalState, totalData, Date.now());
  const onOpenSpot = () => { setPortfolioSubTab && setPortfolioSubTab('spot'); setActiveTab && setActiveTab('portfolio'); };
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

      {/* ── ROW 2 — Equity chart ── */}
      <DashEquityCard chart={chart} hideValues={hideValues} />

      {/* ── ROW 3 — Spot P&L + Hyperliquid ── */}
      <div className="dash-row3">
        <DashSpotCard model={spotModel} status={spotStatus} hideValues={hideValues} onOpen={onOpenSpot} />
        <DashHlCard model={hlModel} totalState={totalState} hideValues={hideValues} />
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
