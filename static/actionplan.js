/* ===== ACTION PLAN SCREEN ===== */
//
// Phase E v2 Commit 3: a frontend-only decision surface over GET
// /api/maxfi/advisor and GET/POST /api/settings/advisor. This screen NEVER
// recomputes verdict/gate/floor logic - every verdict, gate, floor, and
// score value rendered here is read straight off those two payloads. The
// ONLY derivation this file performs is the CLOSE-list Bucket A/B split
// (see the comment at _apCloseBucket below); everything else is a filter/
// sort/sum over already-computed fields.
//
// Styling convention follows scout.js/checklist.js: React.createElement,
// tv-* shared classes for chrome, inline styles for bespoke bits.

/* ── judgment-set display constants (NOT verdict/gate logic - tunable,
   same treatment as maxfi_advisor.ADVISOR_DECAY_MULTIPLIER's 2.0) ── */
const AP_STALE_VALUE_HOURS = 24;
const AP_PROBE_MIN = 25;
const AP_PROBE_MAX = 50;
const AP_SHORTLIST_N = 5;

/* ── pure helpers ── */

// api() throws Error(<raw response text>) on any non-2xx - same JSON-first
// extraction as scout.js's _scoutExtractErr/pl.js's _plExtractErr.
function _apExtractErr(e) {
  let msg = (e && e.message) ? e.message : String(e);
  try {
    const j = JSON.parse(msg);
    if (j) msg = j.detail || j.error || msg;
  } catch (e2) {}
  return msg;
}

// Defensive date parsing, verbatim from scout.js's _scoutParseDate - never
// produces "Invalid Date".
function _apParseDate(iso) {
  if (!iso) return null;
  const d = new Date(iso);
  return isNaN(d.getTime()) ? null : d;
}

// Display label only, same convention as scout.js's SCOUT_CHAIN_LABELS -
// an unrecognized slug still renders (falls back to the raw string).
const AP_CHAIN_LABELS = { robinhood: 'RH', base: 'Base' };
function _apChainLabel(chain) {
  return AP_CHAIN_LABELS[chain] || chain || '—';
}

function _apTruncateAddr(addr) {
  if (!addr) return '—';
  if (addr.length <= 12) return addr;
  return addr.slice(0, 6) + '…' + addr.slice(-4);
}

// Shared by positions and entry_candidates - both carry symbols{token0,
// token1} + pool_address in the same shape.
function _apPoolLabel(row) {
  const t0 = row.symbols && row.symbols.token0;
  const t1 = row.symbols && row.symbols.token1;
  if (t0 && t1) return t0 + '/' + t1;
  return _apTruncateAddr(row.pool_address);
}

function _apShortWallet(wallet) {
  if (!wallet || wallet.length <= 10) return wallet || '—';
  return wallet.slice(0, 6) + '…' + wallet.slice(-4);
}

function _apPctDay(v) {
  return typeof v === 'number' ? v.toFixed(2) + '%/day' : '—';
}

// Held-join, verbatim from scout.js's _scoutIsHeld: a candidate's pool is
// "held" iff some position in the SAME payload (any verdict) shares
// (chain, lowercased pool_address).
function _apIsHeld(cand, positions) {
  const addr = String(cand.pool_address || '').toLowerCase();
  return (positions || []).some((p) =>
    p.chain === cand.chain && String(p.pool_address || '').toLowerCase() === addr);
}

// Bucket A/B split - the ONLY derivation this screen performs beyond
// reading payload fields, per checklist.js's own documented discipline:
// "Bucket it. Run-rate below 1x decay (Bucket A): close. Between 1x and
// 2x (Bucket B): hold, and log it to the flagged-vs-resolved cohort that
// tunes the 2.0 multiplier." A row already carries verdict CLOSE here (it
// is already below the multiplier-scaled threshold_pct_day) - this split
// further distinguishes rows below the token's RAW 1x decay
// (decay_raw_pct_day, NOT threshold_pct_day) from rows between the raw
// 1x line and the multiplier threshold. Rows missing either number are
// never silently bucketed - they go to a third "incomplete" group.
function _apCloseBucket(pos) {
  if (typeof pos.run_rate_7d_pct_day !== 'number' || typeof pos.decay_raw_pct_day !== 'number') {
    return 'incomplete';
  }
  return pos.run_rate_7d_pct_day < pos.decay_raw_pct_day ? 'A' : 'B';
}

// A row's current_value_usd is STALE iff the value itself is null, its
// uncollected-fee figure is flagged unavailable, or the last valuation is
// older than AP_STALE_VALUE_HOURS before the payload's as_of. An
// unparseable/missing current_value_at never counts as stale on its own -
// only a value this function can actually compare and find too old does.
function _apIsStaleValue(pos, asOfDate) {
  if (pos.current_value_usd == null) return true;
  if ((pos.data_flags || []).includes('uncollected_unavailable')) return true;
  const valueAt = _apParseDate(pos.current_value_at);
  if (valueAt && asOfDate) {
    const hoursOld = (asOfDate.getTime() - valueAt.getTime()) / 3600000;
    if (hoursOld > AP_STALE_VALUE_HOURS) return true;
  }
  return false;
}

// Probe-candidate eligibility. Ruling: an ungated young token (null
// downtrend_gate.blocked, awaiting token-daily history) is uncleared, not
// blocked, and deliberately does NOT appear on a recommendation surface -
// both null and true are excluded here, only an explicit false passes.
// Same strictness for below_liquidity_floor. The probe rule: full size
// only ever ships as scale-up on a measured probe, so this list never
// phrases anything larger than a probe (see AP_PROBE_MIN/MAX below).
function _apProbeEligible(cand) {
  const gate = cand.downtrend_gate;
  if (!gate || gate.blocked !== false) return false;
  if (cand.below_liquidity_floor !== false) return false;
  if (typeof cand.entry_score !== 'number' || !isFinite(cand.entry_score)) return false;
  return true;
}

/* ── Section 1: Close list ── */

function APCloseTable({ rows, caption }) {
  return React.createElement('div', { style: { marginBottom: 16 } },
    caption && React.createElement('div', { style: { fontSize: 13, color: 'var(--text3)', marginBottom: 8 } }, caption),
    rows.length === 0
      ? React.createElement('div', { style: { fontSize: 13, color: 'var(--text4)' } }, 'None.')
      : React.createElement('div', { style: { overflowX: 'auto' } },
          React.createElement('table', { className: 'tv-table', style: { width: '100%' } },
            React.createElement('thead', null,
              React.createElement('tr', null,
                React.createElement('th', null, 'POOL'),
                React.createElement('th', null, 'CHAIN'),
                React.createElement('th', null, 'WALLET'),
                React.createElement('th', null, 'VALUE'),
                React.createElement('th', null, 'RUN-RATE vs THRESHOLD'),
                React.createElement('th', null, 'MARGIN')
              )
            ),
            React.createElement('tbody', null,
              rows.map((pos) => React.createElement('tr', { key: pos.id },
                React.createElement('td', null, _apPoolLabel(pos)),
                React.createElement('td', null, _apChainLabel(pos.chain)),
                React.createElement('td', null, _apShortWallet(pos.wallet)),
                React.createElement('td', null, fmt(pos.current_value_usd, 0)),
                React.createElement('td', null, _apPctDay(pos.run_rate_7d_pct_day) + ' vs ' + _apPctDay(pos.threshold_pct_day)),
                React.createElement('td', null, _apPctDay(pos.margin_pct_day))
              ))
            )
          )
        )
  );
}

function APCloseSection({ positions }) {
  const closePositions = positions.filter((p) => p.verdict === 'CLOSE');
  const bucketA = [], bucketB = [], incomplete = [];
  closePositions.forEach((p) => {
    const b = _apCloseBucket(p);
    if (b === 'A') bucketA.push(p);
    else if (b === 'B') bucketB.push(p);
    else incomplete.push(p);
  });

  return React.createElement('div', { className: 'tv-card', style: { padding: 20 } },
    React.createElement('div', { className: 'tv-section-title' }, 'Close list'),
    closePositions.length === 0
      ? React.createElement('div', { style: { fontSize: 13, color: 'var(--text4)' } }, 'No positions currently verdict CLOSE.')
      : React.createElement(React.Fragment, null,
          React.createElement(APCloseTable, { rows: bucketA, caption: 'below raw 1x decay — close list' }),
          React.createElement(APCloseTable, { rows: bucketB, caption: 'between 1x and 2x — tracked cohort (Bucket B)' }),
          incomplete.length > 0 && React.createElement(APCloseTable, { rows: incomplete, caption: 'incomplete data — run-rate or decay figure unavailable' })
        )
  );
}

/* ── Section 2: Freed capital ── */

function APFreedCapitalSection({ positions, asOf }) {
  const asOfDate = _apParseDate(asOf);
  const bucketed = positions.filter((p) => p.verdict === 'CLOSE' && _apCloseBucket(p) !== 'incomplete');

  let freed = 0;
  let staleCount = 0;
  bucketed.forEach((p) => {
    if (_apIsStaleValue(p, asOfDate)) {
      staleCount += 1;
    } else {
      freed += p.current_value_usd;
    }
  });

  return React.createElement('div', { className: 'tv-card', style: { padding: 20 } },
    React.createElement('div', { className: 'tv-section-title' }, 'Freed capital'),
    React.createElement('div', { style: { fontSize: 22, fontWeight: 700, color: 'var(--text)' } }, fmt(freed, 0)),
    staleCount > 0 && React.createElement('div', { style: { fontSize: 13, color: 'var(--text4)', marginTop: 8 } },
      staleCount + ' positions excluded from this sum (stale valuation — refresh valuations first)')
  );
}

/* ── Section 3: Probe candidates ── */

function APProbeSection({ candidates, positions, overCap }) {
  const eligible = candidates.filter((c) => _apProbeEligible(c) && !_apIsHeld(c, positions));
  const shortlist = eligible.slice().sort((a, b) => b.entry_score - a.entry_score).slice(0, AP_SHORTLIST_N);
  const excludedCount = candidates.length - eligible.length;

  return React.createElement('div', { className: 'tv-card', style: { padding: 20 } },
    React.createElement('div', { className: 'tv-section-title' }, 'Probe candidates'),
    overCap && React.createElement('div', {
      style: {
        fontSize: 13, fontWeight: 600, color: 'var(--fail)',
        background: 'rgba(255,138,138,0.16)', border: '1px solid var(--fail)',
        borderRadius: 6, padding: '10px 14px', marginBottom: 12,
      },
    }, 'Over the exposure cap — sizing shown for reference only, no new probes until under cap.'),
    shortlist.length === 0
      ? React.createElement('div', { style: { fontSize: 13, color: 'var(--text4)' } }, 'No eligible probe candidates right now.')
      : React.createElement('div', { style: { overflowX: 'auto' } },
          React.createElement('table', { className: 'tv-table', style: { width: '100%' } },
            React.createElement('thead', null,
              React.createElement('tr', null,
                React.createElement('th', null, 'POOL'),
                React.createElement('th', null, 'CHAIN'),
                React.createElement('th', null, 'ENTRY SCORE'),
                React.createElement('th', null, 'FEE APR EST'),
                React.createElement('th', null, 'LIQUIDITY'),
                React.createElement('th', null, 'SIZE')
              )
            ),
            React.createElement('tbody', null,
              shortlist.map((c) => React.createElement('tr', { key: c.chain + ':' + c.pool_address },
                React.createElement('td', null, _apPoolLabel(c)),
                React.createElement('td', null, _apChainLabel(c.chain)),
                React.createElement('td', null, c.entry_score.toFixed(1)),
                React.createElement('td', null, typeof c.fee_apr_est_pct === 'number' ? c.fee_apr_est_pct.toFixed(1) + '%' : '—'),
                React.createElement('td', null, typeof c.liquidity_usd === 'number' ? fmt(c.liquidity_usd, 0) : '—'),
                React.createElement('td', null, '$' + AP_PROBE_MIN + '–' + AP_PROBE_MAX + ' probe')
              ))
            )
          )
        ),
    React.createElement('div', { style: { fontSize: 13, color: 'var(--text4)', marginTop: 12 } },
      excludedCount + ' candidates excluded (gate-blocked, ungated/awaiting history, below floor, or held) — browse in Scout')
  );
}

/* ── Section 4: Dry powder ── */

function APDryPowderSection({ positions, settings, exposure, hasCapital, capAmount, dryPowder, overCap, onSettingsSaved }) {
  const [capitalInput, setCapitalInput] = React.useState('');
  const [capPctInput, setCapPctInput] = React.useState('');
  const [saving, setSaving] = React.useState(false);
  const [saveError, setSaveError] = React.useState(null);

  const mountedRef = React.useRef(true);
  React.useEffect(() => { return () => { mountedRef.current = false; }; }, []);

  // Prefill/resync from settings - runs on mount and again after a
  // successful save updates the parent's settings state (the merged dict
  // the route returns), never on every keystroke.
  React.useEffect(() => {
    setCapitalInput(settings.total_capital_usd != null ? String(settings.total_capital_usd) : '');
    setCapPctInput(settings.maxfi_exposure_cap_pct != null ? String(settings.maxfi_exposure_cap_pct) : '');
  }, [settings.total_capital_usd, settings.maxfi_exposure_cap_pct]);

  async function handleSave() {
    setSaveError(null);
    const initialCapitalStr = settings.total_capital_usd != null ? String(settings.total_capital_usd) : '';
    const initialCapPctStr = settings.maxfi_exposure_cap_pct != null ? String(settings.maxfi_exposure_cap_pct) : '';
    const body = {};
    if (capitalInput.trim() !== initialCapitalStr) {
      body.total_capital_usd = capitalInput.trim() === '' ? null : Number(capitalInput);
    }
    if (capPctInput.trim() !== initialCapPctStr) {
      body.maxfi_exposure_cap_pct = capPctInput.trim() === '' ? null : Number(capPctInput);
    }
    if (Object.keys(body).length === 0) return;

    setSaving(true);
    try {
      const d = await api('/api/settings/advisor', { method: 'POST', body: JSON.stringify(body) });
      if (!mountedRef.current) return;
      if (d === undefined || d === null) {
        setSaveError('session expired');
        setSaving(false);
        return;
      }
      onSettingsSaved(d);
      setSaving(false);
    } catch (e) {
      if (!mountedRef.current) return;
      setSaveError(_apExtractErr(e));
      setSaving(false);
    }
  }

  return React.createElement('div', { className: 'tv-card', style: { padding: 20 } },
    React.createElement('div', { className: 'tv-section-title' }, 'Dry powder'),
    React.createElement('div', { style: { fontSize: 13, color: 'var(--text3)', marginBottom: 12 } },
      'MaxFi exposure: ' + fmt(exposure, 0)),
    !hasCapital
      ? React.createElement('div', { style: { fontSize: 13, color: 'var(--text4)', marginBottom: 12 } },
          'Set your total capital figure to compute dry powder')
      : React.createElement(React.Fragment, null,
          overCap && React.createElement('div', {
            style: {
              fontSize: 13, fontWeight: 600, color: 'var(--fail)',
              background: 'rgba(255,138,138,0.16)', border: '1px solid var(--fail)',
              borderRadius: 6, padding: '10px 14px', marginBottom: 12,
            },
          }, 'MaxFi exposure exceeds the ' + settings.maxfi_exposure_cap_pct + '% cap — no new probes until under cap'),
          React.createElement('div', { style: { fontSize: 13, color: 'var(--text3)', marginBottom: 4 } },
            'Cap: ' + fmt(capAmount, 0) + ' (' + settings.maxfi_exposure_cap_pct + '%)'),
          React.createElement('div', { style: { fontSize: 22, fontWeight: 700, color: overCap ? 'var(--fail)' : 'var(--text)' } },
            'Dry powder: ' + fmt(dryPowder, 0))
        ),
    React.createElement('div', {
      style: {
        display: 'flex', gap: 16, flexWrap: 'wrap', alignItems: 'flex-end',
        marginTop: 16, paddingTop: 16, borderTop: '1px solid rgba(255,255,255,0.25)',
      },
    },
      React.createElement('div', null,
        React.createElement('div', { className: 'tv-label', style: { fontSize: 13, marginBottom: 4 } }, 'Total capital ($)'),
        React.createElement('input', {
          type: 'number', className: 'tv-input', style: { width: 160 },
          value: capitalInput, onChange: (e) => setCapitalInput(e.target.value),
        })
      ),
      React.createElement('div', null,
        React.createElement('div', { className: 'tv-label', style: { fontSize: 13, marginBottom: 4 } }, 'Exposure cap (%)'),
        React.createElement('input', {
          type: 'number', className: 'tv-input', style: { width: 120 },
          value: capPctInput, onChange: (e) => setCapPctInput(e.target.value),
        })
      ),
      React.createElement('button', {
        className: 'tv-btn', style: { fontSize: 13, padding: '6px 14px' },
        disabled: saving, onClick: handleSave,
      }, saving ? 'Saving…' : 'Save')
    ),
    saveError && React.createElement('div', { style: { fontSize: 13, color: 'var(--fail)', marginTop: 8 } }, saveError)
  );
}

/* ── main screen ── */

function ActionPlanScreen() {
  const [data, setData] = React.useState({ as_of: null, positions: [], entry_candidates: [] });
  const [settings, setSettings] = React.useState(null);
  const [loading, setLoading] = React.useState(true);
  const [loadError, setLoadError] = React.useState(null);

  // Same unmount-guard shape as scout.js's ScoutScreen mountedRef.
  const mountedRef = React.useRef(true);
  React.useEffect(() => {
    return () => { mountedRef.current = false; };
  }, []);

  React.useEffect(() => {
    async function load() {
      try {
        const [advisor, advisorSettings] = await Promise.all([
          api('/api/maxfi/advisor'),
          api('/api/settings/advisor'),
        ]);
        if (!mountedRef.current) return;
        if (advisor === undefined || advisor === null || advisorSettings === undefined || advisorSettings === null) {
          setLoadError('session expired');
          setLoading(false);
          return;
        }
        setData({
          as_of: advisor.as_of,
          positions: advisor.positions || [],
          entry_candidates: advisor.entry_candidates || [],
        });
        setSettings(advisorSettings);
        setLoading(false);
      } catch (e) {
        if (!mountedRef.current) return;
        setLoadError(_apExtractErr(e));
        setLoading(false);
      }
    }
    load();
  }, []);

  if (loading) {
    return React.createElement('div', {
      style: { display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: 320, color: 'var(--text3)', fontSize: 14 },
    }, 'Loading Action Plan…');
  }

  if (loadError) {
    return React.createElement('div', { style: { color: 'var(--fail)', fontSize: 13 } }, loadError);
  }

  const positions = data.positions;
  const entryCandidates = data.entry_candidates;
  const asOfDisplay = _apParseDate(data.as_of);

  const exposure = positions.reduce(
    (sum, p) => sum + (typeof p.current_value_usd === 'number' ? p.current_value_usd : 0), 0);
  const hasCapital = settings.total_capital_usd != null;
  const capAmount = hasCapital ? settings.total_capital_usd * settings.maxfi_exposure_cap_pct / 100 : null;
  const dryPowder = hasCapital ? capAmount - exposure : null;
  const overCap = hasCapital && exposure > capAmount;

  return React.createElement('div', { style: { display: 'flex', flexDirection: 'column', gap: 20 } },
    React.createElement('div', null,
      React.createElement('div', { className: 'tv-page-title', style: { marginBottom: 4 } }, 'Action Plan'),
      React.createElement('div', { style: { fontSize: 13, color: 'var(--text3)' } },
        asOfDisplay ? 'As of ' + asOfDisplay.toLocaleString() : '')
    ),
    React.createElement(APCloseSection, { positions }),
    React.createElement(APFreedCapitalSection, { positions, asOf: data.as_of }),
    React.createElement(APProbeSection, { candidates: entryCandidates, positions, overCap }),
    React.createElement(APDryPowderSection, {
      positions, settings, exposure, hasCapital, capAmount, dryPowder, overCap,
      onSettingsSaved: (merged) => setSettings(merged),
    })
  );
}

window.ActionPlanScreen = ActionPlanScreen;
