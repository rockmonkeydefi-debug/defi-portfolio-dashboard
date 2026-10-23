/* ===== SPOT PLAN - Landing 59 (Oct 23 rulings, HANDOFF_current.md section 3) =====
   A short plan per spot trade, for tracking, discipline and thinking it
   through: the basis (own chart setup / analyst call / other; generic, no
   names), a setup from Glenn's list for an own chart setup, a one-line
   thesis (required for an analyst call, optional otherwise), and for every
   trade the exit plan, an optional invalidation price, conviction and
   horizon. Saved with PUT /api/trading/trades/<id>/spot-plan (append-only on
   the server: the latest row is the plan). An open Trading-book spot trade
   without a plan carries plan_missing: a reminder only, it never blocks
   anything.

   Trends at Open, under the plan: the noodle at the trade's open (the
   trade-open snapshot, passed in as atOpen) and Doc's Daily and Weekly band
   states (doc_bands_at_open; captured in the background for Trading-book
   trades of Hyperliquid-listed tokens, with the two-close rule). No live
   bands.

   Landing 60 (Oct 23): an expanded Spot row shows its sections as cards
   (SpotCard): a header strip with the title and the section's buttons, then
   the content; the plan reads as a label / value list. Spot Cyclical and
   Other joined the setups, and a form that can't be saved yet says what it
   still needs, in yellow next to Save.

   Used in the Open positions row detail (static/spotpnl.js) and in Closed
   trades by trade (static/spothistory.js). Loaded after static/spotjournal.js
   and before static/spothistory.js; it uses api, extractApiErrorMessage,
   spotFmtDay, spotFmtPx and shxDayKey at render time only. Every top-level
   name here starts with spl / SPL / SpotPlan, or is SpotCard: Babel turns
   top-level declarations into shared globals. */

const { useState: useSPLState } = React;

// [value, label, description]; the values are the server's (web_portfolio.py SPOT_PLAN_*).
const SPL_BASES = [['own_setup', 'Own chart setup'], ['analyst_call', 'Analyst call'], ['other', 'Other']];
const SPL_SETUPS = [['trend_retest_poi', 'Trend continuation retest with POI'],
  ['trend_retest_sfp', 'Trend continuation retest with SFP/Sweep'], ['range_deviation', 'Range Deviation'],
  ['range_3_drives_msb', 'Range: 3 drives & MSB'], ['expansion_candle', 'Expansion Candle'], ['compression', 'Compression'],
  ['vwap_trend_continuation', 'VWAP Trend Continuation'], ['vwap_range_reversion', 'VWAP Range Reversion'],
  ['spot_cyclical', 'Spot Cyclical'], ['other', 'Other']];
const SPL_EXITS = [['weekly_flip', 'Weekly trend flip'], ['target', 'Target or thesis done'],
  ['analyst_exit', "Analyst's exit call"], ['price_level', 'Price level']];
const SPL_CONVICTIONS = [['high', 'High'], ['normal', 'Normal'], ['low', 'Low']];
const SPL_HORIZONS = [
  ['cyclical', 'Cyclical', 'About 6 to 12 months; mostly majors.'],
  ['positional', 'Positional', 'About 1 to 3 months; a pullback in a strong coin already up 50% to 3x.'],
  ['narrative', 'Narrative/Trenches', 'A newer, smaller coin riding a sector story.']];
const SPL_THESIS_MAX = 200;      // SPOT_PLAN_THESIS_MAX on the server
const SPL_PX_CHARS = 40;         // SPOT_PLAN_PX_CHARS on the server
const SPL_FIELDS = ['basis', 'setup', 'thesis', 'exit_plan', 'invalidation_px', 'conviction', 'horizon'];

const SPL_FIELD = { fontSize: 13, color: 'var(--text3)', minWidth: 104 };
const SPL_SMALL_BTN = { fontSize: 13, padding: '4px 12px', minHeight: 32 };
const SPL_DOT = { BULLISH: 'var(--ok)', BEARISH: 'var(--fail)' };
// The label / value list: small uppercase labels, larger white values.
const SPL_ROWS = { display: 'grid', gridTemplateColumns: '112px minmax(0, 1fr)', columnGap: 14, rowGap: 8, alignItems: 'baseline' };
const SPL_ROW_LABEL = { fontSize: 12, fontWeight: 600, letterSpacing: '0.06em', textTransform: 'uppercase', color: 'var(--text3)' };
const SPL_ROW_VALUE = { fontSize: 14, fontWeight: 500, color: 'var(--text)', overflowWrap: 'anywhere', minWidth: 0 };
const SPL_LINE = '2px solid rgba(255,255,255,0.25)';
// Typographic characters, built from code points so this file's own text stays plain ASCII.
const SPL_SEP = ' ' + String.fromCharCode(0xB7) + ' ';          // " . " middle dot
const SPL_DASH = String.fromCharCode(0x2014);                   // em dash
const SPL_MASK = String.fromCharCode(0x2022).repeat(4);         // four bullets (Hide values)
const SPL_LQ = String.fromCharCode(0x201C);                     // curly quotes around the thesis
const SPL_RQ = String.fromCharCode(0x201D);
const SPL_ELLIPSIS = String.fromCharCode(0x2026);

function splLabel(list, v) {
  const x = list.find(o => o[0] === v);
  return x ? x[1] : null;
}

// A form draft from a stored plan (or none): every field a string, '' for nothing.
function splDraft(plan) {
  const p = plan || {};
  const d = {};
  for (const k of SPL_FIELDS) d[k] = p[k] == null ? '' : String(p[k]);
  return d;
}

// Picking a basis: the setup is only for an own chart setup, and an own
// chart setup preselects the weekly trend flip when no exit is picked yet.
function splPickBasis(draft, basis) {
  const d = { ...draft, basis };
  if (basis !== 'own_setup') d.setup = '';
  if (basis === 'own_setup' && !d.exit_plan) d.exit_plan = 'weekly_flip';
  return d;
}

// The thesis as the server stores it: runs of whitespace become one space, trimmed.
function splThesis(s) {
  const words = [];
  let word = '';
  for (const c of String(s == null ? '' : s)) {
    if (c.trim() === '') {                 // a whitespace character
      if (word) words.push(word);
      word = '';
    } else word += c;
  }
  if (word) words.push(word);
  return words.join(' ');
}

// The invalidation price: null when empty, the number when it is a plain
// positive decimal ("1.25", ".5", "3") of up to 40 characters, from 1e-30 up
// to (not including) 1e16 as the server allows; NaN otherwise.
function splPx(s) {
  const str = String(s == null ? '' : s).trim();
  if (!str) return null;
  if (str.length > SPL_PX_CHARS || !/^([0-9]+[.]?[0-9]*|[.][0-9]+)$/.test(str)) return NaN;
  const n = Number(str);
  return isFinite(n) && n >= 1e-30 && n < 1e16 ? n : NaN;
}

// What a draft still needs before it can be saved (the server's rules), in
// form order, as short phrases; [] when it can be saved.
function splProblems(d) {
  const out = [];
  if (!d.basis) out.push('a basis');
  if (d.basis === 'own_setup' && !d.setup) out.push('the setup');
  const thesis = splThesis(d.thesis);
  if (d.basis === 'analyst_call' && !thesis) out.push('a one-line thesis (an analyst call needs one)');
  if ([...thesis].length > SPL_THESIS_MAX) out.push('a shorter thesis (' + SPL_THESIS_MAX + ' characters at most)');
  if (!d.exit_plan) out.push('an exit plan');
  const px = splPx(d.invalidation_px);
  if (Number.isNaN(px)) out.push('a valid invalidation price (a positive number)');
  else if (d.exit_plan === 'price_level' && px == null) out.push('the invalidation price (a price-level exit needs one)');
  if (!d.conviction) out.push('conviction');
  if (!d.horizon) out.push('a horizon');
  return out;
}

// "Still needed: the setup, conviction and a horizon." for a non-empty list.
function splNeeds(problems) {
  if (!problems.length) return '';
  const last = problems[problems.length - 1];
  const list = problems.length === 1 ? last : problems.slice(0, -1).join(', ') + ' and ' + last;
  return 'Still needed: ' + list + '.';
}

// The PUT body for a draft that can be saved.
function splBody(d) {
  const thesis = splThesis(d.thesis);
  const px = String(d.invalidation_px == null ? '' : d.invalidation_px).trim();
  return { basis: d.basis, setup: d.basis === 'own_setup' ? d.setup : null, thesis: thesis || null,
           exit_plan: d.exit_plan, invalidation_px: px || null, conviction: d.conviction, horizon: d.horizon };
}

// Whether a draft would save the stored plan unchanged (the price compared as a number).
function splSame(plan, d) {
  if (!plan) return false;
  const b = splBody(d);
  return SPL_FIELDS.every(k => {
    const a = plan[k] == null ? null : plan[k];
    if (k !== 'invalidation_px') return a === b[k];
    return a == null ? b[k] == null : b[k] != null && Number(a) === Number(b[k]);
  });
}

// A stored plan as [label, value] rows, in form order. hideValues masks the invalidation price.
function splRows(plan, hideValues) {
  const rows = [['Basis', splLabel(SPL_BASES, plan.basis) || 'Not set']];
  if (plan.basis === 'own_setup') rows.push(['Setup', splLabel(SPL_SETUPS, plan.setup) || plan.setup || SPL_DASH]);
  if (plan.thesis) rows.push(['Thesis', SPL_LQ + plan.thesis + SPL_RQ]);
  rows.push(['Exit', splLabel(SPL_EXITS, plan.exit_plan) || 'Not set']);
  if (plan.invalidation_px != null) {
    rows.push(['Invalidation', hideValues ? SPL_MASK : spotFmtPx(Number(plan.invalidation_px))]);
  }
  rows.push(['Conviction', splLabel(SPL_CONVICTIONS, plan.conviction) || SPL_DASH]);
  rows.push(['Horizon', splLabel(SPL_HORIZONS, plan.horizon) || SPL_DASH]);
  return rows;
}

// plan_missing as the server works it out, for a trade whose plan just changed.
function splMissing(t, plan) {
  return !plan && t.book === 'trading' && t.status !== 'closed';
}

// "Saved Oct 23", plus "after the trade closed" when the plan was saved on a later day than the close.
function splSavedText(plan, t) {
  const day = shxDayKey(plan.saved_at);
  const closed = t.status === 'closed' ? shxDayKey(t.closed_at) : null;
  const text = 'Saved ' + (spotFmtDay(day) || SPL_DASH);
  return closed && day && day > closed ? text + ', after the trade closed' : text;
}

const SPL_BAND_STATE = { BULLISH: 'held', BEARISH: 'lost' };
const SPL_CROSS = { BULLISH: 'above', BEARISH: 'below' };
const SPL_BAND_REASON = {
  not_on_hyperliquid: "Not listed on Hyperliquid, so there are no Doc bands.",
  price_mismatch: "Hyperliquid's price for this ticker was far from the entry (likely a different token), so there are no Doc bands.",
  no_open_time: 'No open time, so there are no Doc bands.',
};

// Doc's band states at the trade's open. null when they are not captured for
// this trade (not a Trading-book spot_tx trade); otherwise
// {kind: 'pending' | 'reason' | 'ok', text} and, for 'ok', parts
// [{label, state, value, text}] and the EMA 100/200 line.
function splBands(t) {
  const doc = t.doc_bands_at_open;
  if (!doc || typeof doc !== 'object') {
    return t.source === 'spot_tx' && (t.book || 'trading') === 'trading'
      ? { kind: 'pending', text: 'Not captured yet' } : null;
  }
  if (doc.reason) return { kind: 'reason', text: SPL_BAND_REASON[doc.reason] || 'No Doc bands for this trade.' };
  const parts = [['daily', 'Daily'], ['weekly', 'Weekly']].map(([k, label]) => {
    const x = doc[k] || {};
    if (!x.position) {
      return { label, state: null, cross: null, value: 'Too few candles before the trade day',
               text: label + ': too few candles before the trade day' };
    }
    const st = SPL_BAND_STATE[x.state];
    const value = (st || 'not set') + ', close ' + x.position;
    return { label, state: st ? x.state : null, cross: SPL_CROSS[x.cross_state] || null,
             value: value.charAt(0).toUpperCase() + value.slice(1), text: label + ' ' + value };
  });
  const crosses = parts.filter(p => p.cross).map(p => p.label + ' ' + p.cross);
  const day = spotFmtDay(String(doc.as_of || '').slice(0, 10));
  const market = doc.market && String(doc.market).toUpperCase() !== String(t.symbol || '').toUpperCase()
    ? SPL_SEP + 'Hyperliquid market ' + doc.market : '';
  const ema = (crosses.length ? 'EMA 100 vs 200: ' + crosses.join(', ') + SPL_SEP : '')
    + 'candles closed before ' + (day || 'the trade day') + ' (UTC)' + market;
  return { kind: 'ok', parts, ema,
           text: 'Trends at Open: ' + parts.map(p => p.text).join('; ') + '. ' + ema + '.' };
}

const SPL_BANDS_TIP = 'Noodle: price vs the noodle on 1D and 1W at the open. '
  + "Doc's Daily band is EMA 100 and 200 of 4H closes; his Weekly band is EMA 100 and 200 of daily closes. "
  + 'Held: two closes in a row above the band. Lost: two closes in a row below it. A close inside changes nothing. '
  + 'Not set: no two-close run yet in the data. Close: where the last close before the trade day sat.';

// A section card for an expanded Spot row: a header strip (title, extra
// badges, and the section's buttons on the right) over the content.
function SpotCard({ title, accent, extra, actions, children, ...rest }) {
  return <section className="spot-card" {...rest}
    style={{ background: 'var(--panel)', border: '1px solid var(--line)', borderLeft: '4px solid ' + (accent || 'var(--line)'),
             borderRadius: 10, minWidth: 0 }}>
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10, flexWrap: 'wrap',
                  padding: '10px 14px', minHeight: 52, background: 'var(--panel2)', borderBottom: SPL_LINE,
                  borderRadius: '0 9px 0 0' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap', minWidth: 0 }}>
        <h3 style={{ margin: 0, fontSize: 13, lineHeight: '18px', fontWeight: 700, letterSpacing: '0.08em',
                     textTransform: 'uppercase', color: 'var(--text)' }}>{title}</h3>
        {extra}
      </div>
      {actions}
    </div>
    <div style={{ padding: '12px 14px 14px', display: 'flex', flexDirection: 'column', gap: 12 }}>{children}</div>
  </section>;
}

function SpotPlanRows({ rows }) {
  return <div style={SPL_ROWS}>
    {rows.map(([label, value]) => <React.Fragment key={label}>
      <span style={SPL_ROW_LABEL}>{label}</span>
      <span style={SPL_ROW_VALUE}>{value}</span>
    </React.Fragment>)}
  </div>;
}

function splDot(state) {
  return <span style={{ width: 10, height: 10, borderRadius: 999, display: 'inline-block', flex: 'none',
                        background: SPL_DOT[state] || 'transparent', border: SPL_DOT[state] ? 'none' : '1.5px solid rgba(255,255,255,0.6)' }} />;
}

// Trends at Open: the noodle (atOpen, when the trade has an open snapshot) and Doc's bands.
function SpotPlanBands({ trade, atOpen }) {
  const b = splBands(trade);
  const noodle = atOpen && trade.open_snapshot ? atOpen : null;
  if (!b && !noodle) return null;
  return <div style={{ borderTop: SPL_LINE, paddingTop: 12, display: 'flex', flexDirection: 'column', gap: 8 }}>
    <span style={{ ...SPL_ROW_LABEL, color: 'var(--text)' }} title={SPL_BANDS_TIP}>Trends at Open</span>
    <div role="img" aria-label={b ? b.text : 'Trends at Open'} style={SPL_ROWS}>
      {noodle && <React.Fragment>
        <span style={SPL_ROW_LABEL}>Noodle</span>
        <span style={{ ...SPL_ROW_VALUE, fontSize: 13 }}>{noodle}</span>
      </React.Fragment>}
      {b && b.kind === 'ok' && b.parts.map(p => <React.Fragment key={p.label}>
        <span style={SPL_ROW_LABEL}>{'Doc ' + p.label}</span>
        <span style={{ ...SPL_ROW_VALUE, display: 'inline-flex', alignItems: 'center', gap: 8 }} title={p.text}>{splDot(p.state)}{p.value}</span>
      </React.Fragment>)}
      {b && b.kind !== 'ok' && <React.Fragment>
        <span style={SPL_ROW_LABEL}>Doc bands</span>
        <span style={{ ...SPL_ROW_VALUE, fontSize: 13, fontWeight: 400, color: 'var(--text3)' }}
          title={b.kind === 'pending' ? 'Captured in the background after each Hyperliquid fill sync, a few trades at a time.' : undefined}>{b.text}</span>
      </React.Fragment>}
    </div>
    {b && b.kind === 'ok' && <span style={{ fontSize: 12, color: 'var(--text3)' }}>{b.ema}</span>}
  </div>;
}

// One row of toggle buttons (aria-pressed) with its label in front.
function SpotPlanPicks({ label, options, value, onPick, disabled, note }) {
  return <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
    <span style={SPL_FIELD}>{label}</span>
    <span role="group" aria-label={label} style={{ display: 'inline-flex', gap: 6, flexWrap: 'wrap' }}>
      {options.map(o => <button key={o[0]} type="button" className="tv-btn" aria-pressed={value === o[0]} disabled={disabled}
        title={o[2]} onClick={() => onPick(o[0])}
        style={{ ...SPL_SMALL_BTN, background: value === o[0] ? 'var(--panel3)' : 'transparent',
                 borderColor: value === o[0] ? 'var(--accent)' : 'var(--line)', color: value === o[0] ? 'var(--text)' : 'var(--text3)',
                 fontWeight: value === o[0] ? 600 : 400 }}>{o[1]}</button>)}
    </span>
    {note && <span style={{ fontSize: 12, color: 'var(--text3)' }}>{note}</span>}
  </div>;
}

// The plan for one spot trade, as a card: the plan as a list with Edit, or
// the form. onSaved(trade_id, plan or null). atOpen: the noodle-at-open line
// for Trends at Open (optional).
function SpotPlan({ trade: t, hideValues, onSaved, atOpen }) {
  const plan = t.plan || null;
  const [editing, setEditing] = useSPLState(false);
  const [draft, setDraft] = useSPLState(() => splDraft(plan));
  const [busy, setBusy] = useSPLState(false);
  const [error, setError] = useSPLState('');
  const [saved, setSaved] = useSPLState('');
  const [confirmClear, setConfirmClear] = useSPLState(false);
  const sym = String(t.symbol || '').toUpperCase();

  function start() { setDraft(splDraft(plan)); setError(''); setConfirmClear(false); setEditing(true); }
  function cancel() { setEditing(false); setError(''); setConfirmClear(false); }
  function set(k, v) { setDraft(prev => ({ ...prev, [k]: v })); }
  async function send(body, word) {
    if (busy) return;
    setBusy(true);
    try {
      const d = await api('/api/trading/trades/' + encodeURIComponent(t.trade_id) + '/spot-plan',
                          { method: 'PUT', body: JSON.stringify(body) });
      if (!d || d.error || !Object.prototype.hasOwnProperty.call(d, 'plan')) { setError(extractApiErrorMessage(d)); return; }
      setError('');
      setEditing(false);
      setConfirmClear(false);
      setSaved(word);
      setTimeout(() => setSaved(''), 2500);
      onSaved(t.trade_id, d.plan || null);
    } catch (err) { setError(extractApiErrorMessage(err)); }
    finally { setBusy(false); }
  }

  const extra = <React.Fragment>
    {t.plan_missing && <span className="tv-chip warn" style={{ fontSize: 12, fontWeight: 600 }}>Plan missing</span>}
    {saved && <span role="status" style={{ fontSize: 13, color: 'var(--ok)' }}>{saved}</span>}
  </React.Fragment>;

  if (!editing) {
    const actions = <span style={{ display: 'inline-flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
      {plan && <span style={{ fontSize: 12, color: 'var(--text3)' }}>{splSavedText(plan, t)}</span>}
      <button type="button" className="tv-btn" style={SPL_SMALL_BTN} onClick={start}
        aria-label={(plan ? 'Edit the plan' : 'Add a plan') + ' for the ' + sym + ' trade'}>{plan ? 'Edit plan' : 'Add plan'}</button>
    </span>;
    return <SpotCard title="Plan" accent="var(--accent)" extra={extra} actions={actions} data-spot-plan={t.trade_id}>
      {plan ? <SpotPlanRows rows={splRows(plan, hideValues)} />
        : <div style={{ fontSize: 13, color: 'var(--text3)' }}>
            {t.plan_missing ? 'No plan yet: the basis, how you exit, conviction and horizon. A reminder only; nothing is blocked.'
              : 'No plan for this trade.'}</div>}
      {error && <div role="alert" style={{ fontSize: 13, color: 'var(--fail)' }}>{error}</div>}
      <SpotPlanBands trade={t} atOpen={atOpen} />
    </SpotCard>;
  }

  const problems = splProblems(draft);
  const same = splSame(plan, draft);
  const horizon = SPL_HORIZONS.find(o => o[0] === draft.horizon);
  const thesisNeeded = draft.basis === 'analyst_call';
  return <SpotCard title="Plan" accent="var(--accent)" extra={extra} data-spot-plan={t.trade_id}>
    <SpotPlanPicks label="Basis" options={SPL_BASES} value={draft.basis} disabled={busy}
      onPick={v => setDraft(prev => splPickBasis(prev, v))} />
    {draft.basis === 'own_setup' && <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
      <span style={SPL_FIELD}>Setup</span>
      <select className="tv-input" value={draft.setup} disabled={busy} aria-label={'Setup for ' + sym}
        onChange={e => set('setup', e.target.value)} style={{ width: 'auto', minWidth: 200, maxWidth: '100%' }}>
        <option value="">Pick a setup</option>
        {SPL_SETUPS.map(o => <option key={o[0]} value={o[0]}>{o[1]}</option>)}
      </select>
    </div>}
    {draft.basis && <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
      <span style={SPL_FIELD}>Thesis</span>
      <input className="tv-input" maxLength={SPL_THESIS_MAX} value={draft.thesis} disabled={busy}
        aria-label={'Thesis for ' + sym} style={{ flex: '1 1 260px', minWidth: 0 }}
        placeholder={thesisNeeded ? 'Required: one line in your own words, the call and why (no names)' : 'Optional: one line on why this trade'}
        onChange={e => set('thesis', e.target.value)} />
    </div>}
    <SpotPlanPicks label="Exit plan" options={SPL_EXITS} value={draft.exit_plan} disabled={busy} onPick={v => set('exit_plan', v)} />
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
      <span style={SPL_FIELD}>Invalidation</span>
      <input className="tv-input" inputMode="decimal" value={draft.invalidation_px} disabled={busy}
        aria-label={'Invalidation price for ' + sym}
        placeholder={draft.exit_plan === 'price_level' ? 'Required: the price you exit at' : 'Optional: price that proves it wrong'}
        style={{ width: 240, maxWidth: '100%' }} onChange={e => set('invalidation_px', e.target.value)} />
    </div>
    <SpotPlanPicks label="Conviction" options={SPL_CONVICTIONS} value={draft.conviction} disabled={busy} onPick={v => set('conviction', v)} />
    <SpotPlanPicks label="Horizon" options={SPL_HORIZONS} value={draft.horizon} disabled={busy} onPick={v => set('horizon', v)}
      note={horizon ? horizon[1] + ': ' + horizon[2] : null} />
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', borderTop: SPL_LINE, paddingTop: 12 }}>
      <button type="button" className="tv-btn primary" style={SPL_SMALL_BTN} disabled={busy || problems.length > 0 || same}
        onClick={() => send(splBody(draft), 'Plan saved')}>{busy ? 'Saving' + SPL_ELLIPSIS : 'Save plan'}</button>
      <button type="button" className="tv-btn" style={SPL_SMALL_BTN} disabled={busy} onClick={cancel}>Cancel</button>
      {plan && !confirmClear && <button type="button" className="tv-btn danger" style={SPL_SMALL_BTN} disabled={busy}
        onClick={() => setConfirmClear(true)}>Clear plan</button>}
      {plan && confirmClear && <span role="group" aria-label="Confirm clearing the plan" style={{ display: 'inline-flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
        <span style={{ fontSize: 13, color: 'var(--text2)' }}>Clear this plan?</span>
        <button type="button" className="tv-btn danger" style={SPL_SMALL_BTN} disabled={busy}
          onClick={() => send({ basis: null }, 'Plan cleared')}>Clear</button>
        <button type="button" className="tv-btn" style={SPL_SMALL_BTN} disabled={busy} onClick={() => setConfirmClear(false)}>Keep</button>
      </span>}
      {problems.length > 0 && <span data-plan-needs style={{ fontSize: 13, fontWeight: 600, color: 'var(--warn)' }}>{splNeeds(problems)}</span>}
      {!problems.length && same && <span style={{ fontSize: 13, color: 'var(--text3)' }}>No changes to save.</span>}
    </div>
    {error && <div role="alert" style={{ fontSize: 13, color: 'var(--fail)' }}>{error}</div>}
  </SpotCard>;
}

window.SpotPlan = SpotPlan;
window.SpotCard = SpotCard;
window.splMissing = splMissing;
