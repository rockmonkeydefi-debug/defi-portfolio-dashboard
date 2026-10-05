/* ===== PERPS PAGE: RULE CHECK, TALLY AND TAG CONTROLS — Landing 8c-1 =====
   (HANDOFF_advisor_v1.md section 25). Loaded after static/perps.js, which
   owns the page state and passes these components what they need.

   Reads:  GET /api/trading/advisor/perps  (the rule registry, every perp
           trade's verdicts and evidence, the tally)
           GET /api/trading/trade-tags     (current setup / POI tag per trade)
   Writes: PUT /api/trading/trades/<trade_id>/tags
           body {setup, break_what: {kind, timeframe}, poi: {type, timeframe}};
           a part not sent carries over, identical state writes nothing.

   Components (all take plain props, no globals of their own):
     PerpsRuleCheck   the "Rule check" block inside an expanded row
     PerpsRulesTally  the one-block tally above the History table
     PerpsTagEditor   setup and point-of-interest tags for one trade
     PerpsExitReason  why a revised exit happened (Landing 8c-2)

   Landing 8c-2 (Rules v2): X1 passes when a revised exit has an exit reason
   picked; notes no longer count. The reason and its optional note are saved
   through the row's annotation saver (PUT .../annotation with exit_reason and
   exit_reason_note), so the trades and the rule check reload after a save.
   The field shows on closed synced trades whose X1 reads pass or fail (a
   revised exit); when the rule check failed to load it shows on every closed
   synced trade, so a reason can still be recorded. PRP_EXIT_REASONS mirrors
   perp_rules.EXIT_REASONS (tests/test_exit_reason.py pins it).

   Hide values: only R2's evidence carries dollar amounts (and "% of capital",
   which gives them away). prpRuleEvidence rewrites R2's evidence wholesale
   when Hide is on, and masks any other rule's evidence that ever shows a
   dollar sign (tests/test_perp_rules_masking.py pins that none does today).
   Verdicts are chips with a text label, never colour alone; tracking rules
   never use the pass / fail colours. Evidence times are UTC as sent.

   Every top-level name starts with prp / PRP / Perps (shared Babel globals).
   Helpers used from perps.js: prpBtn, prpDate, prpErr, PRP_SECTION,
   PRP_SMALL_BTN, PRP_MONO, PRP_OPEN_TFS, PerpsStatus. */

const PRP_RULE_CHIP = {
  pass: { label: 'Pass', cls: 'tv-chip ok' },
  fail: { label: 'Fail', cls: 'tv-chip fail' },
  neutral: { label: 'Neutral', cls: 'tv-chip' },
  self_reported: { label: 'Self-reported', cls: 'tv-chip accent' },
  not_tagged: { label: 'Not tagged', muted: true },
  no_plan: { label: 'No plan', muted: true },
  not_measurable: { label: 'Not measurable', muted: true },
  tracking: { label: 'Tracking', muted: true },
};
const PRP_RULE_MUTED_CHIP = { fontSize: 12, color: 'var(--text3)', border: '1px dashed var(--text3)', background: 'transparent' };
const PRP_RULE_NEUTRAL_CHIP = { fontSize: 12, color: 'var(--text2)', borderColor: 'var(--text3)', background: 'transparent' };
const PRP_RULE_GRID = '44px minmax(150px,1fr) 150px minmax(0,2fr) 36px';
const PRP_RULE_MONEY = /\$|of capital/i;
const PRP_RULE_SOLID = '1px solid rgba(255,255,255,0.25)';
const PRP_RULE_DASHED = '1px dashed rgba(255,255,255,0.35)';

const PRP_TAG_SETUPS = [['retest', 'Retest'], ['breakout', 'Breakout'], ['other', 'Other']];
const PRP_TAG_BREAKS = [['trendline', 'Trendline'], ['supply_level', 'Supply level'], ['other', 'Other']];
const PRP_TAG_POIS = [['breaker', 'Breaker'], ['order_block', 'Order block'], ['fvg', 'FVG'], ['sfp', 'SFP'],
                      ['supply_demand', 'Supply / demand'], ['other', 'Other']];
const PRP_TAG_SETTLE_MS = 10 * 60000;   // SETTLE_MIN in src/engines/perp_rules.py

const PRP_EXIT_REASONS = [
  ['fundamental_thesis_changed', 'Fundamental thesis changed'],
  ['sd_level_broke', 'S/D level broke'],
  ['reversal_pattern', 'Topping pattern'],
  ['took_profit_early', 'Took profit early (no signal)'],
  ['time_stop', 'Time stop (not moving)'],
  ['cut_risk', 'Cut risk (news or event)'],
  ['resized', 'Resized (size or leverage too high)'],
  ['emotional', 'Emotional'],
  ['other', 'Other'],
];
const PRP_EXIT_PATTERNS = 'Rounding/Momentum Loss, 3 Drive Pattern, SFP';
const PRP_EXIT_HINT = {
  sd_level_broke: 'A significant supply/demand level broke. The stop should have handled this, so the entry was probably poor.',
  reversal_pattern: 'Price was rounding off or showing a reversal, so you took profit early.',
  took_profit_early: 'Use only when no other reason applies: you closed in profit without a signal.',
  resized: 'Closed because the size or leverage was too high (e.g. the liquidation price was too close); usually re-entered smaller.',
  other: 'Say what it was in the note.',
};

/* ── helpers ─────────────────────────────────────────────────────────── */

// What the Evidence cell shows. Under Hide values R2 is rewritten from its
// verdict (no dollar amount, no "% of capital"); anything else that still
// shows a dollar sign is replaced by a neutral line.
function prpRuleEvidence(res, hide) {
  const text = String((res && res.evidence) || '');
  if (!hide) return text;
  if (res && res.rule === 'R2') {
    const over = /^over (\d+(?:\.\d+)?)% (per trade|open in total)/i.exec(text);
    if (over) return 'Over ' + over[1] + '% ' + over[2] + ' (amounts hidden)';
    if (res.verdict === 'pass') return 'Within the per-trade and total limits (amounts hidden)';
    if (PRP_RULE_MONEY.test(text)) return 'Not measurable: 1R is too small to count (amounts hidden)';
    return text;
  }
  return PRP_RULE_MONEY.test(text) ? 'Evidence hidden' : text;
}

// Mirrors rule_e3: a tag counts as live when it was set within 10 minutes of
// the open, or before the close (always, for a trade still open).
function prpTagLive(trade, atIso) {
  const at = Date.parse(atIso || '');
  const opened = Date.parse(trade.opened_at || '');
  const closed = trade.closed_at ? Date.parse(trade.closed_at) : NaN;
  if (isNaN(at)) return false;
  if (!isNaN(opened) && at <= opened + PRP_TAG_SETTLE_MS) return true;
  return isNaN(closed) || at < closed;
}

// Counts for the tally line. rows: the closed trades in view; advisor: the
// advisor response; tags: {trade_id: tag}.
function prpRulesTally(rows, advisor, tags) {
  const per = (advisor && advisor.trades) || {};
  const evaluated = rows.filter(t => per[t.trade_id]);
  const enforced = {};
  ((advisor && advisor.rules) || []).forEach(r => { if (r.status === 'enforced') enforced[r.id] = true; });
  let clean = 0;
  const failBy = {};
  const e2 = {};
  evaluated.forEach(t => {
    const ev = per[t.trade_id];
    if (!ev.enforced_fails || !ev.enforced_fails.length) clean += 1;
    (ev.enforced_fails || []).forEach(id => { failBy[id] = (failBy[id] || 0) + 1; });
    const r = (ev.rules || []).filter(x => x.rule === 'E2')[0];
    if (r) e2[r.verdict] = (e2[r.verdict] || 0) + 1;
  });
  const tagged = (key) => rows.filter(t => tags && tags[t.trade_id] && tags[t.trade_id][key]).length;
  const exitBy = {};
  let revised = 0;
  evaluated.forEach(t => {
    const x1 = (per[t.trade_id].rules || []).filter(x => x.rule === 'X1')[0];
    if (!x1 || (x1.verdict !== 'pass' && x1.verdict !== 'fail')) return;
    revised += 1;
    const key = (t.annotation || {}).exit_reason;
    const k = prpExitReasonLabel(key) ? key : '';
    exitBy[k] = (exitBy[k] || 0) + 1;
  });
  const ids = Object.keys(enforced);
  return {
    total: rows.length, evaluated: evaluated.length, clean,
    failBy: ids.filter(id => failBy[id]).map(id => [id, failBy[id]]),
    e2, setupTagged: tagged('setup'), poiTagged: tagged('poi'),
    revised,
    exitBy: PRP_EXIT_REASONS.map(r => r[0]).concat(['']).filter(k => exitBy[k]).map(k => [k, exitBy[k]]),
  };
}

// The label for an exit reason; the reversal pattern reads by direction.
function prpExitReasonLabel(key, direction, withExamples) {
  if (key === 'reversal_pattern') {
    const word = direction === 'short' ? 'Bottoming pattern' : direction === 'long' ? 'Topping pattern' : 'Topping / bottoming pattern';
    return withExamples ? word + ' (' + PRP_EXIT_PATTERNS + ')' : word;
  }
  const hit = PRP_EXIT_REASONS.filter(r => r[0] === key)[0];
  return hit ? hit[1] : null;
}

// Is this trade's close a revised exit, per the rule check? null = unknown.
function prpIsRevisedExit(trade, advisor) {
  const data = advisor && advisor.data;
  if (!data) return null;
  const ev = (data.trades || {})[trade.trade_id];
  if (!ev) return null;
  const x1 = (ev.rules || []).filter(r => r.rule === 'X1')[0];
  return !!x1 && (x1.verdict === 'pass' || x1.verdict === 'fail');
}

/* ── the verdict chip ────────────────────────────────────────────────── */

function PerpsRuleChip({ verdict, tracking }) {
  const def = PRP_RULE_CHIP[verdict] || { label: String(verdict || '—'), muted: true };
  // A tracking rule never wears the pass / fail colours.
  if (tracking || def.muted) {
    return <span className="tv-chip" style={PRP_RULE_MUTED_CHIP}>{tracking ? 'Tracking' : def.label}</span>;
  }
  return <span className={def.cls} style={def.cls === 'tv-chip' ? PRP_RULE_NEUTRAL_CHIP : { fontSize: 12, fontWeight: 600 }}>{def.label}</span>;
}

/* ── Rule check block ────────────────────────────────────────────────── */

function PerpsRuleRow({ res, reg, hide, tracking }) {
  const [shown, setShown] = usePRPState(false);
  const id = 'prp-rule-def-' + res.rule + '-' + (reg ? reg.id : '');
  const border = tracking ? PRP_RULE_DASHED : PRP_RULE_SOLID;
  const textColor = tracking ? 'var(--text3)' : 'var(--text2)';
  const evidence = prpRuleEvidence(res, hide);
  const title = reg ? reg.title : res.rule;
  return <React.Fragment>
    <div className="spot-grid-row" style={{ gridTemplateColumns: PRP_RULE_GRID, padding: '8px 0', borderTop: border, fontSize: 13, color: textColor }}>
      <div className="spot-cell" data-label="Rule" style={{ fontFamily: PRP_MONO, fontWeight: 600, color: tracking ? 'var(--text3)' : 'var(--text)' }}>{res.rule}</div>
      <div className="spot-cell spot-span" title={reg ? reg.definition : undefined}
        style={{ color: tracking ? 'var(--text3)' : 'var(--text)' }}>{title}</div>
      <div className="spot-cell" data-label="Result"><PerpsRuleChip verdict={res.verdict} tracking={tracking} /></div>
      <div className="spot-cell spot-span" data-label="Evidence" style={{ overflowWrap: 'anywhere' }}>
        <div>{evidence || '—'}</div>
        {Array.isArray(res.notes) && res.notes.map((n, i) => <div key={i} style={{ marginTop: 4, color: 'var(--text3)', fontSize: 12 }}>{'Note: ' + n}</div>)}
      </div>
      <div className="spot-cell" style={{ textAlign: 'right' }}>
        {reg && <button type="button" className="tv-btn" aria-expanded={shown} aria-controls={id}
          aria-label={'Definition of ' + res.rule + ', ' + title} title={reg.definition}
          onClick={() => setShown(s => !s)}
          style={{ width: 32, height: 32, padding: 0, fontSize: 14, color: 'var(--text2)' }}>ⓘ</button>}
      </div>
    </div>
    {shown && reg && <div id={id} style={{ fontSize: 13, lineHeight: '19px', color: 'var(--text2)', padding: '6px 0 10px 44px' }}>
      {reg.definition}
    </div>}
  </React.Fragment>;
}

function PerpsRuleCheck({ trade, advisor, hide }) {
  const data = advisor.data;
  const head = { fontSize: 12, lineHeight: '16px', fontWeight: 600, letterSpacing: '0.06em', textTransform: 'uppercase', color: 'var(--text3)' };
  const box = { display: 'flex', flexDirection: 'column', gap: 8, width: '100%' };
  const title = <span style={PRP_SECTION}>Rule check</span>;

  if (!data) {
    if (advisor.error) {
      return <div style={box}>{title}
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
          <span role="alert" style={{ fontSize: 13, color: 'var(--fail)' }}>{"Couldn't load the rule check: " + advisor.error}</span>
          <button type="button" className="tv-btn" style={prpBtn(advisor.loading, PRP_SMALL_BTN)} disabled={advisor.loading} onClick={advisor.reload}>Retry</button>
        </div></div>;
    }
    return <div style={box}>{title}<span role="status" style={{ fontSize: 13, color: 'var(--text3)' }}>Loading rule check…</span></div>;
  }
  const ev = (data.trades || {})[trade.trade_id];
  if (!ev) {
    return <div style={box}>{title}
      <span style={{ fontSize: 13, color: 'var(--text3)' }}>
        {advisor.loading ? 'Updating rule check…' : 'Rule check not loaded for this trade yet. It appears after the next reload.'}</span></div>;
  }
  const regById = {};
  (data.rules || []).forEach(r => { regById[r.id] = r; });
  const results = ev.rules || [];
  const enforced = results.filter(r => r.status === 'enforced');
  const tracking = results.filter(r => r.status !== 'enforced');
  const fails = ev.enforced_fails || [];
  return <div style={box}>
    <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, flexWrap: 'wrap' }}>
      {title}
      <span style={{ fontSize: 13, color: fails.length ? 'var(--fail)' : 'var(--text2)' }}>
        {'Rules v' + data.definition_version + ' · ' + (fails.length
          ? fails.length + ' enforced fail' + (fails.length === 1 ? '' : 's') + ': ' + fails.join(', ') : 'no enforced fails')}</span>
      {advisor.loading && <span role="status" style={{ fontSize: 13, color: 'var(--text3)' }}>Updating rule check…</span>}
      {advisor.error && <span style={{ fontSize: 13, color: 'var(--warn)' }}>
        <span role="alert">{'Update failed: ' + advisor.error + ' · '}</span>
        <button type="button" className="tv-btn" style={prpBtn(advisor.loading, PRP_SMALL_BTN)} disabled={advisor.loading} onClick={advisor.reload}>Retry</button></span>}
    </div>
    <div className="spot-grid-row spot-grid-head" style={{ ...head, gridTemplateColumns: PRP_RULE_GRID, alignItems: 'end', padding: '4px 0' }}>
      <span>Rule</span><span>What it checks</span><span>Result</span><span>Evidence</span><span />
    </div>
    <div>
      {enforced.map(r => <PerpsRuleRow key={r.rule} res={r} reg={regById[r.rule]} hide={hide} tracking={false} />)}
    </div>
    {tracking.length > 0 && <div>
      <div style={{ ...PRP_SECTION, padding: '10px 0 2px' }}>Tracking only · not counted as fails</div>
      {tracking.map(r => <PerpsRuleRow key={r.rule} res={r} reg={regById[r.rule]} hide={hide} tracking={true} />)}
    </div>}
  </div>;
}

/* ── tally above the History table ───────────────────────────────────── */

function PerpsRulesTally({ rows, advisor, tags }) {
  const data = advisor.data;
  if (!rows.length) return null;
  const style = { fontSize: 13, color: 'var(--text2)', marginBottom: 12, display: 'flex', flexDirection: 'column', gap: 4 };
  if (!data) {
    if (!advisor.error) return null;
    return <div style={style}><span>
      <span role="alert" style={{ color: 'var(--fail)' }}>{'Rules tally unavailable: ' + advisor.error + ' '}</span>
      <button type="button" className="tv-btn" style={prpBtn(advisor.loading, PRP_SMALL_BTN)} disabled={advisor.loading} onClick={advisor.reload}>Retry</button></span></div>;
  }
  const t = prpRulesTally(rows, data, tags);
  if (!t.evaluated) return null;
  const e2 = t.e2;
  const e2Parts = [['pass', 'pass'], ['self_reported', 'self-reported'], ['not_tagged', 'not tagged'], ['fail', 'fail'], ['not_measurable', 'not measurable']]
    .filter(p => e2[p[0]] || p[0] !== 'not_measurable').map(p => p[1] + ' ' + (e2[p[0]] || 0));
  return <div style={style}
    title="Counts the closed trades in this view that the rule check has read. An enforced fail is a Fail on any enforced rule; tracking rules never count.">
    <strong style={{ color: 'var(--text)', fontWeight: 600 }}>
      {'Rules v' + data.definition_version + ': ' + t.clean + ' of ' + t.evaluated + ' closed trades have no enforced fail'
        + (t.evaluated < t.total ? ' (' + (t.total - t.evaluated) + ' not read yet)' : '')}</strong>
    <span>{'Enforced fails by rule: ' + (t.failBy.length ? t.failBy.map(p => p[0] + ' ' + p[1]).join(' · ') : 'none')}</span>
    <span>{'E2 setup check: ' + e2Parts.join(' · ') + ' | Tagged: setup ' + t.setupTagged + ' of ' + t.total
      + ' · point of interest ' + t.poiTagged + ' of ' + t.total}</span>
    {t.revised > 0 && <span>{'Revised exits: ' + t.revised + ' · by reason: '
      + t.exitBy.map(p => (p[0] ? prpExitReasonLabel(p[0]) : 'no reason yet') + ' ' + p[1]).join(' · ')}</span>}
    <span style={{ color: 'var(--text3)' }}>{data.note || 'lead only: small sample, one market period'}</span>
  </div>;
}

/* ── setup and point-of-interest tags ────────────────────────────────── */

function prpTagDraft(tag) {
  const t = tag || {};
  const b = t.break_what || {};
  const p = t.poi || {};
  return { setup: t.setup || '', kind: b.kind || '', btf: b.timeframe || '', poiType: p.type || '', poiTf: p.timeframe || '' };
}

function prpTagSelect(id, label, value, options, onChange, disabled, firstLabel) {
  return <div style={{ display: 'flex', flexDirection: 'column', gap: 4, minWidth: 130 }}>
    <label htmlFor={id} style={{ fontSize: 13, color: 'var(--text2)' }}>{label}</label>
    <select id={id} className="tv-select" value={value} disabled={disabled} onChange={e => onChange(e.target.value)}>
      <option value="">{firstLabel}</option>
      {options.map(o => <option key={o[0]} value={o[0]}>{o[1]}</option>)}
    </select>
  </div>;
}

// onSaved(response) runs after a successful PUT, with the saved tag.
function PerpsTagEditor({ trade, tag, onSaved }) {
  const stored = prpTagDraft(tag);
  const sig = JSON.stringify(stored);
  const [draft, setDraft] = usePRPState(stored);
  const prevRef = usePRPRef(sig);
  const [saving, setSaving] = usePRPState(false);
  const [status, setStatus] = usePRPState(null);
  const aliveRef = usePRPRef(true);
  const timerRef = usePRPRef(null);
  usePRPEffect(() => () => { aliveRef.current = false; clearTimeout(timerRef.current); }, []);
  // Follow the stored tag unless there is an unsaved edit.
  usePRPEffect(() => {
    if (sig === prevRef.current) return;
    const prev = JSON.parse(prevRef.current);
    prevRef.current = sig;
    setDraft(d => (JSON.stringify(d) === JSON.stringify(prev) || JSON.stringify(d) === sig) ? stored : d);
  }, [sig]);

  const idBase = 'prp-tag-' + trade.trade_id + '-';
  const set = patch => { setStatus(null); setDraft(d => Object.assign({}, d, patch)); };
  const setupDirty = draft.setup !== stored.setup || (draft.setup === 'breakout' && (draft.kind !== stored.kind || draft.btf !== stored.btf));
  const poiDirty = draft.poiType !== stored.poiType || draft.poiTf !== stored.poiTf;
  const dirty = setupDirty || poiDirty;
  let problem = null;
  if (draft.setup === 'breakout' && (!draft.kind || !draft.btf)) problem = 'A breakout needs what broke and the timeframe it broke on.';
  else if (!!draft.poiType !== !!draft.poiTf) problem = 'A point of interest needs both a type and a timeframe.';
  const canSave = dirty && !problem && !saving;

  function save() {
    if (!canSave) return;
    const body = {};
    if (setupDirty) {
      body.setup = draft.setup || null;
      if (draft.setup === 'breakout') body.break_what = { kind: draft.kind, timeframe: draft.btf };
    }
    if (poiDirty) body.poi = draft.poiType ? { type: draft.poiType, timeframe: draft.poiTf } : null;
    setSaving(true);
    setStatus(null);
    clearTimeout(timerRef.current);
    api('/api/trading/trades/' + encodeURIComponent(trade.trade_id) + '/tags', { method: 'PUT', body: JSON.stringify(body) }).then(resp => {
      if (aliveRef.current) {
        setSaving(false);
        setStatus('saved');
        timerRef.current = setTimeout(() => { if (aliveRef.current) setStatus(null); }, PRP_SAVED_MS);
      }
      onSaved(trade.trade_id, resp);
    }).catch(e => {
      if (aliveRef.current) { setSaving(false); setStatus({ error: prpErr(e) }); }
    });
  }

  const t = tag || {};
  const stamp = (iso) => iso ? (prpTagLive(trade, iso) ? 'tagged live' : 'tagged after close') + ' · ' + prpDate(iso, true) : null;
  const setupStatus = t.setup ? 'Setup: ' + (PRP_TAG_SETUPS.filter(s => s[0] === t.setup)[0] || [0, t.setup])[1]
    + (t.break_what ? ' (' + (PRP_TAG_BREAKS.filter(b => b[0] === t.break_what.kind)[0] || [0, t.break_what.kind])[1] + ' broke on ' + t.break_what.timeframe + ')' : '')
    + ' · ' + stamp(t.setup_tagged_at) : 'Setup: not tagged';
  const poiStatus = t.poi ? 'Point of interest: ' + (PRP_TAG_POIS.filter(p => p[0] === t.poi.type)[0] || [0, t.poi.type])[1] + ' ' + t.poi.timeframe
    + ' · ' + stamp(t.poi_tagged_at) : 'Point of interest: not tagged';

  return <div style={{ display: 'flex', flexDirection: 'column', gap: 10, minWidth: 0 }}>
    <span style={PRP_SECTION}>Setup and entry zone</span>
    <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'flex-end' }}>
      {prpTagSelect(idBase + 'setup', 'Setup', draft.setup, PRP_TAG_SETUPS, v => set({ setup: v }), saving, 'Not tagged')}
      {draft.setup === 'breakout' && prpTagSelect(idBase + 'kind', 'What broke (required)', draft.kind, PRP_TAG_BREAKS, v => set({ kind: v }), saving, 'Choose…')}
      {draft.setup === 'breakout' && prpTagSelect(idBase + 'btf', 'Broke on (required)', draft.btf, PRP_OPEN_TFS, v => set({ btf: v }), saving, 'Choose…')}
    </div>
    <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'flex-end' }}>
      {prpTagSelect(idBase + 'poi', 'Point of interest', draft.poiType, PRP_TAG_POIS, v => set(v ? { poiType: v } : { poiType: '', poiTf: '' }), saving, 'Not tagged')}
      {prpTagSelect(idBase + 'poitf', 'POI timeframe', draft.poiTf, PRP_OPEN_TFS, v => set({ poiTf: v }), saving, 'Choose…')}
    </div>
    <div style={{ fontSize: 13, color: 'var(--text2)', display: 'flex', flexDirection: 'column', gap: 2 }}>
      <span>{setupStatus}</span><span>{poiStatus}</span>
    </div>
    <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
      <button type="button" className="tv-btn primary" style={prpBtn(!canSave, PRP_SMALL_BTN)} disabled={!canSave} onClick={save}>Save tags</button>
      {dirty && !problem && !saving && <span style={{ fontSize: 12, color: 'var(--warn)' }}>Unsaved changes</span>}
      {problem && <span style={{ fontSize: 12, color: 'var(--warn)' }}>{problem}</span>}
      <PerpsStatus saving={saving} status={status} />
    </div>
    <div style={{ fontSize: 12, color: 'var(--text3)' }}>
      Choosing Not tagged and saving clears that tag. A tag set after the trade closed is marked "tagged after close".
    </div>
  </div>;
}

/* ── exit reason for a revised exit (Landing 8c-2) ───────────────────── */

// saver: the row's prpUseSaver (annotation route); its status line is shown by the row.
function PerpsExitReason({ trade, advisor, saver }) {
  const ann = trade.annotation || {};
  const [reason, setReason] = prpUseFollowingDraft(ann.exit_reason || '');
  const [note, setNote] = prpUseFollowingDraft(ann.exit_reason_note || '');
  if (trade.source === 'manual' || trade.status !== 'closed') return null;
  const revised = prpIsRevisedExit(trade, advisor);
  const fallback = revised === null && !!advisor.error && !advisor.data;
  if (!revised && !fallback) return null;

  const storedReason = ann.exit_reason || '';
  const storedNote = ann.exit_reason_note || '';
  const dirty = reason !== storedReason || (reason !== '' && note !== storedNote);
  let problem = null;
  if (reason === 'other' && !note.trim()) problem = 'Other needs a short note.';
  const canSave = dirty && !problem && !saver.saving;
  const idR = 'prp-exit-' + trade.trade_id;
  const idN = 'prp-exit-note-' + trade.trade_id;
  function save() {
    if (!canSave) return;
    saver.annotate({ exit_reason: reason || null, exit_reason_note: reason && note.trim() ? note : null });
  }
  return <div style={{ display: 'flex', flexDirection: 'column', gap: 6, minWidth: 0 }}>
    <label htmlFor={idR} style={PRP_SECTION}>Why did you exit early?</label>
    <div style={{ fontSize: 13, color: 'var(--text2)' }}>
      {fallback ? "The rule check didn't load, so this shows on every closed trade. Use it only for a revised exit."
        : 'Revised exit: closed by a market or limit order instead of your stop or take-profit. Rule X1 passes once a reason is picked.'}
    </div>
    <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
      <select id={idR} className="tv-select" style={{ maxWidth: '100%' }} value={reason} disabled={saver.saving}
        onChange={e => setReason(e.target.value)}>
        <option value="">No reason yet</option>
        {PRP_EXIT_REASONS.map(r => <option key={r[0]} value={r[0]}>{prpExitReasonLabel(r[0], trade.direction, true)}</option>)}
      </select>
    </div>
    {reason && PRP_EXIT_HINT[reason] && <div style={{ fontSize: 12, color: 'var(--text2)' }}>{PRP_EXIT_HINT[reason]}</div>}
    {reason && <React.Fragment>
      <label htmlFor={idN} style={{ fontSize: 13, color: 'var(--text2)' }}>{reason === 'other' ? 'Note (required)' : 'Note (optional)'}</label>
      <input id={idN} className="tv-input" maxLength={PRP_NOTE_MAX} value={note} disabled={saver.saving}
        placeholder={reason === 'other' ? 'What made you exit' : 'Anything specific about this exit'}
        onChange={e => setNote(e.target.value)} onKeyDown={e => { if (e.key === 'Enter') save(); }} />
    </React.Fragment>}
    <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
      <button type="button" className="tv-btn primary" style={prpBtn(!canSave, PRP_SMALL_BTN)} disabled={!canSave} onClick={save}>Save exit reason</button>
      {dirty && !problem && !saver.saving && <span style={{ fontSize: 12, color: 'var(--warn)' }}>Unsaved changes</span>}
      {problem && <span style={{ fontSize: 12, color: 'var(--warn)' }}>{problem}</span>}
    </div>
    {!reason && storedReason !== '' && <div style={{ fontSize: 12, color: 'var(--text3)' }}>Saving "No reason yet" clears the reason and its note.</div>}
  </div>;
}
