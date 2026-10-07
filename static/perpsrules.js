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
     PerpsRulesTab    the Rules tab (Landing 8c-3): rule statuses, dated
                      capital for R2 and the change history

   Landing 8c-3 (HANDOFF_advisor_v1.md section 31): the Rules tab reads
   GET /api/trading/advisor/perps/settings and writes through
   PUT /api/trading/advisor/perps/rules/<rule_id>/status {status, reason} and
   PUT /api/trading/advisor/perps/capital {from, usd}. A status change applies
   to trades opened from the moment it is saved (earlier trades keep the
   status they were judged under); relaxing a rule (enforced -> tracking)
   needs a reason; M3 is fixed. Capital is dated by a UTC day. After a save
   the tab re-reads the settings and the page re-reads the rule check. The
   limits below mirror web_portfolio.py and perp_rules.py
   (tests/test_perps_rules_panel.py pins them). Hide values masks capital
   amounts, the dollar limits, and any reason that shows a dollar sign. The
   tally lists every rule with fails: a trade's fails use its status at the
   open, so a rule tracking now still lists the fails it had while enforced.

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
   PRP_SMALL_BTN, PRP_MONO, PRP_OPEN_TFS, PRP_LINE, PRP_HEAD_LINE,
   PRP_SAVED_MS, PRP_NOTE_MAX, prpUseFollowingDraft, PerpsStatus. */

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
  // Every rule with fails, in registry order (Landing 8c-3): enforced_fails already
  // uses each trade's status at its open, so a rule tracking now still lists the
  // fails it had while it was enforced.
  const ids = ((advisor && advisor.rules) || []).map(r => r.id);
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
    title="Counts the closed trades in this view that the rule check has read. An enforced fail is a Fail on a rule that was enforced when the trade opened; tracking rules never count.">
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
      if (!resp) { if (aliveRef.current) setSaving(false); return; }   // 401: api() is already sending the browser to the login page
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

/* ── the Rules tab (Landing 8c-3) ────────────────────────────────────── */

const PRP_RULE_REASON_MAX = 500;            // PERP_RULE_REASON_MAX in web_portfolio.py
const PRP_CAPITAL_MAX_USD = 100000000;      // PERP_CAPITAL_MAX_USD in web_portfolio.py
const PRP_CAPITAL_MAX_AHEAD_DAYS = 366;     // PERP_CAPITAL_MAX_AHEAD_DAYS in web_portfolio.py
const PRP_RISK_PER_TRADE_PCT = 1;           // RISK_PER_TRADE_PCT in perp_rules.py
const PRP_RISK_TOTAL_PCT = 5;               // RISK_TOTAL_PCT in perp_rules.py
const PRP_STATUS_WORD = { enforced: 'Enforced', tracking: 'Tracking' };
const PRP_SETTINGS_GRID = '44px minmax(170px,1.3fr) 150px minmax(110px,0.8fr) minmax(0,1.5fr) 36px';
const PRP_CAPITAL_GRID = 'minmax(120px,1fr) minmax(120px,1fr) minmax(130px,1fr) minmax(120px,0.8fr)';
const PRP_RULE_HINT = {
  R4: "Reads only on open trades: leverage isn't stored after a trade closes.",
};

// Whole dollars (capital) or up to cents (a limit); masked under Hide values.
function prpDollars(n, hide) {
  if (hide) return '••••';
  if (n === null || n === undefined || !isFinite(Number(n))) return '—';
  return '$' + Number(n).toLocaleString('en-US', { maximumFractionDigits: 2 });
}

// Today and the last allowed capital day, as UTC "YYYY-MM-DD".
function prpUtcDay(offsetDays) {
  const d = new Date();
  return new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate() + (offsetDays || 0))).toISOString().slice(0, 10);
}

// A typed capital amount -> a whole number of dollars, or a problem text.
function prpParseCapital(text) {
  const t = String(text || '').replace(/[,\s$]/g, '');
  if (t === '') return { problem: 'Enter the capital in dollars.' };
  if (!/^\d+$/.test(t)) return { problem: 'Whole dollars only (no cents).' };
  const n = Number(t);
  if (n <= 0 || n > PRP_CAPITAL_MAX_USD) return { problem: 'Capital must be above 0 and at most ' + PRP_CAPITAL_MAX_USD.toLocaleString('en-US') + '.' };
  return { usd: n };
}

function prpReasonText(reason, hide) {
  if (!reason) return '—';
  return hide && PRP_RULE_MONEY.test(reason) ? 'Reason hidden' : reason;
}

// onSaved() re-reads the settings (returns a promise) and the rule check.
function PerpsRuleStatusRow({ rule, hide, onSaved }) {
  const [pick, setPick] = prpUseFollowingDraft(rule.status);
  const [reason, setReason] = usePRPState('');
  const [saving, setSaving] = usePRPState(false);
  const [status, setStatus] = usePRPState(null);
  const [shown, setShown] = usePRPState(false);
  const aliveRef = usePRPRef(true);
  const timerRef = usePRPRef(null);
  const selectRef = usePRPRef(null);
  usePRPEffect(() => () => { aliveRef.current = false; clearTimeout(timerRef.current); }, []);

  const changing = pick !== rule.status;
  const relaxing = changing && rule.status === 'enforced' && pick === 'tracking';
  let problem = null;
  if (relaxing && !reason.trim()) problem = 'A reason is required to relax a rule.';
  const canSave = changing && !problem && !saving;
  const idBase = 'prp-rs-' + rule.id;
  const defId = idBase + '-def';

  function cancel() {
    setPick(rule.status); setReason(''); setStatus(null);
    if (selectRef.current) selectRef.current.focus();
  }
  function save() {
    if (!canSave) return;
    setSaving(true);
    setStatus(null);
    clearTimeout(timerRef.current);
    api('/api/trading/advisor/perps/rules/' + encodeURIComponent(rule.id) + '/status',
        { method: 'PUT', body: JSON.stringify({ status: pick, reason: reason.trim() || null }) })
      .then(resp => {
        if (!resp) return null;             // 401: api() is already sending the browser to the login page
        return Promise.resolve(onSaved()).then(() => {
          if (!aliveRef.current) return;
          setReason('');
          setSaving(false);
          setStatus('saved');
          timerRef.current = setTimeout(() => { if (aliveRef.current) setStatus(null); }, PRP_SAVED_MS);
          // The change panel and its Save button are gone: focus the picker once it is enabled again.
          setTimeout(() => { if (aliveRef.current && selectRef.current) selectRef.current.focus(); }, 0);
        });
      })
      .catch(e => { if (aliveRef.current) { setSaving(false); setStatus({ error: prpErr(e) }); } });
  }

  const changed = rule.status !== rule.default_status;
  return <div style={{ borderTop: PRP_LINE }}>
    <div className="spot-grid-row" style={{ gridTemplateColumns: PRP_SETTINGS_GRID, padding: '10px 16px', fontSize: 13, color: 'var(--text2)' }}>
      <div className="spot-cell" data-label="Rule" style={{ fontFamily: PRP_MONO, fontWeight: 600, color: 'var(--text)' }}>{rule.id}</div>
      <div className="spot-cell spot-span" title={rule.definition} style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
        <span style={{ color: 'var(--text)' }}>{rule.title}</span>
        {PRP_RULE_HINT[rule.id] && <span style={{ fontSize: 12, color: 'var(--text3)' }}>{PRP_RULE_HINT[rule.id]}</span>}
      </div>
      <div className="spot-cell" data-label="Status">
        {rule.flippable
          ? <select id={idBase} ref={selectRef} className="tv-select" aria-label={'Status of ' + rule.id + ', ' + rule.title} value={pick}
              disabled={saving} onChange={e => { setStatus(null); setPick(e.target.value); }} style={{ maxWidth: '100%' }}>
              <option value="enforced">Enforced</option>
              <option value="tracking">Tracking</option>
            </select>
          : <span title="This rule has no pass / fail test, so its status is fixed.">{PRP_STATUS_WORD[rule.status] + ' (fixed)'}</span>}
        {changed && <div style={{ fontSize: 12, color: 'var(--text3)', marginTop: 4 }}>{'Changed · default ' + PRP_STATUS_WORD[rule.default_status]}</div>}
      </div>
      <div className="spot-cell" data-label="Since">{rule.status_since ? prpDate(rule.status_since, true) : 'Default'}</div>
      <div className="spot-cell spot-span" data-label="Reason" style={{ overflowWrap: 'anywhere' }}>{prpReasonText(rule.status_reason, hide)}</div>
      <div className="spot-cell" style={{ textAlign: 'right' }}>
        <button type="button" className="tv-btn" aria-expanded={shown} aria-controls={defId}
          aria-label={'Definition of ' + rule.id + ', ' + rule.title} title={rule.definition}
          onClick={() => setShown(s => !s)} style={{ width: 32, height: 32, padding: 0, fontSize: 14, color: 'var(--text2)' }}>ⓘ</button>
      </div>
    </div>
    {shown && <div id={defId} style={{ fontSize: 13, lineHeight: '19px', color: 'var(--text2)', padding: '0 16px 10px 60px' }}>{rule.definition}</div>}
    {changing && <div role="group" aria-label={'Change ' + rule.id} style={{ display: 'flex', flexDirection: 'column', gap: 6, padding: '0 16px 12px 60px', fontSize: 13 }}>
      <div style={{ color: 'var(--text)' }}>
        {rule.id + ' goes from ' + PRP_STATUS_WORD[rule.status] + ' to ' + PRP_STATUS_WORD[pick] + ' for trades opened from now on'
          + (relaxing ? ': new trades no longer fail on it.' : ': new trades can fail on it.')
          + ' Earlier trades keep the status they were judged under.'}
      </div>
      <label htmlFor={idBase + '-reason'} style={{ color: 'var(--text2)' }}>{relaxing ? 'Reason (required)' : 'Reason (optional)'}</label>
      <input id={idBase + '-reason'} className="tv-input" maxLength={PRP_RULE_REASON_MAX} value={reason} disabled={saving}
        placeholder={relaxing ? 'Why this rule should stop counting as a fail' : 'Why you are enforcing it'}
        onChange={e => { setStatus(null); setReason(e.target.value); }} onKeyDown={e => { if (e.key === 'Enter') save(); }} />
      <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
        <button type="button" className="tv-btn primary" style={prpBtn(!canSave, PRP_SMALL_BTN)} disabled={!canSave} onClick={save}>Save status</button>
        <button type="button" className="tv-btn" style={prpBtn(saving, PRP_SMALL_BTN)} disabled={saving} onClick={cancel}>Cancel</button>
        {problem && <span style={{ fontSize: 12, color: 'var(--warn)' }}>{problem}</span>}
        <PerpsStatus saving={saving} status={status} />
      </div>
    </div>}
    {!changing && status && <div style={{ padding: '0 16px 10px 60px' }}><PerpsStatus saving={false} status={status} /></div>}
  </div>;
}

function PerpsCapitalEditor({ view, hide, onSaved }) {
  const [from, setFrom] = usePRPState('');
  const [amount, setAmount] = usePRPState('');
  const [saving, setSaving] = usePRPState(null);       // null, 'add' or the "from" day being removed
  const [status, setStatus] = usePRPState(null);
  const aliveRef = usePRPRef(true);
  const timerRef = usePRPRef(null);
  const fromRef = usePRPRef(null);
  usePRPEffect(() => () => { aliveRef.current = false; clearTimeout(timerRef.current); }, []);

  const start = view.capital_start;
  const today = prpUtcDay(0);
  const last = prpUtcDay(PRP_CAPITAL_MAX_AHEAD_DAYS);
  const periods = view.capital_periods || [];
  const now = view.capital || {};
  const parsed = prpParseCapital(amount);
  let problem = null;
  if (from || amount) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(from)) problem = 'Pick the day this capital applies from.';
    else if (from < start) problem = 'The day can’t be before ' + prpDate(start) + ', when the capital rule starts.';
    else if (from > last) problem = 'The day can’t be more than a year ahead.';
    else if (parsed.problem) problem = parsed.problem;
  }
  const canAdd = !!from && !!amount && !problem && saving === null;
  const same = periods.filter(p => p.from === from)[0];

  function send(body, which) {
    setSaving(which);
    setStatus(null);
    clearTimeout(timerRef.current);
    return api('/api/trading/advisor/perps/capital', { method: 'PUT', body: JSON.stringify(body) })
      .then(resp => {
        if (!resp) return false;
        return Promise.resolve(onSaved()).then(() => {
          if (!aliveRef.current) return true;
          setSaving(null);
          setStatus('saved');
          timerRef.current = setTimeout(() => { if (aliveRef.current) setStatus(null); }, PRP_SAVED_MS);
          // A removed row's button is gone: focus the day field once it is enabled again.
          setTimeout(() => { if (aliveRef.current && fromRef.current) fromRef.current.focus(); }, 0);
          return true;
        });
      })
      .catch(e => { if (aliveRef.current) { setSaving(null); setStatus({ error: prpErr(e) }); } return false; });
  }
  function add() {
    if (!canAdd) return;
    send({ from: from, usd: parsed.usd }, 'add').then(ok => { if (ok && aliveRef.current) { setFrom(''); setAmount(''); } });
  }
  function remove(day) { if (saving === null) send({ from: day, usd: null }, day); }

  const head = { fontSize: 12, lineHeight: '16px', fontWeight: 600, letterSpacing: '0.06em', textTransform: 'uppercase', color: 'var(--text3)' };
  const perTrade = now.usd ? now.usd * PRP_RISK_PER_TRADE_PCT / 100 : null;
  const total = now.usd ? now.usd * PRP_RISK_TOTAL_PCT / 100 : null;
  return <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
    <div style={{ fontSize: 14, color: 'var(--text)' }}>
      {'Capital now: ' + prpDollars(now.usd, hide) + ' from ' + prpDate(now.from) + ' (UTC)'}
      <span style={{ color: 'var(--text2)', fontSize: 13 }}>{' · per-trade limit ' + PRP_RISK_PER_TRADE_PCT + '% = ' + prpDollars(perTrade, hide)
        + ' · open in total ' + PRP_RISK_TOTAL_PCT + '% = ' + prpDollars(total, hide)}</span>
    </div>
    <div className="tv-card" style={{ padding: 0, overflow: 'hidden' }}>
      <div className="spot-grid-row spot-grid-head" style={{ ...head, gridTemplateColumns: PRP_CAPITAL_GRID, padding: '10px 16px', borderBottom: PRP_HEAD_LINE }}>
        <span>From (UTC day)</span><span>Capital</span><span>Entered</span><span />
      </div>
      {periods.map(p => {
        const isDefault = p.set_at === null || p.set_at === undefined;
        const inForce = p.from === now.from;
        return <div key={p.from} className="spot-grid-row" style={{ gridTemplateColumns: PRP_CAPITAL_GRID, padding: '10px 16px', borderTop: PRP_LINE, fontSize: 13, color: 'var(--text2)' }}>
          <div className="spot-cell" data-label="From (UTC day)" style={{ color: 'var(--text)' }}>
            {prpDate(p.from)}{inForce && <span className="tv-chip accent" style={{ marginLeft: 8, fontSize: 11, padding: '0 6px' }}>In force</span>}
          </div>
          <div className="spot-cell" data-label="Capital" style={{ fontFamily: PRP_MONO, color: 'var(--text)' }}>{prpDollars(p.usd, hide)}</div>
          <div className="spot-cell" data-label="Entered">{isDefault ? 'Default' : prpDate(p.set_at, true)}</div>
          <div className="spot-cell" style={{ textAlign: 'right' }}>
            {!isDefault && <button type="button" className="tv-btn" style={prpBtn(saving !== null, PRP_SMALL_BTN)} disabled={saving !== null}
              aria-label={(p.from === start ? 'Go back to the default capital from ' : 'Remove the capital entry from ') + prpDate(p.from)}
              onClick={() => remove(p.from)}>{saving === p.from ? 'Saving…' : (p.from === start ? 'Use default' : 'Remove')}</button>}
          </div>
        </div>;
      })}
    </div>
    <div role="group" aria-label="Add or replace capital" style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'flex-end' }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          <label htmlFor="prp-cap-from" style={{ fontSize: 13, color: 'var(--text2)' }}>From (UTC day)</label>
          <input id="prp-cap-from" ref={fromRef} type="date" className="tv-input" min={start} max={last} value={from} disabled={saving !== null}
            onChange={e => { setStatus(null); setFrom(e.target.value); }} />
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          <label htmlFor="prp-cap-usd" style={{ fontSize: 13, color: 'var(--text2)' }}>Capital (whole dollars)</label>
          <input id="prp-cap-usd" className="tv-input" inputMode="numeric" autoComplete="off" placeholder="50,000" value={amount}
            disabled={saving !== null} onChange={e => { setStatus(null); setAmount(e.target.value); }}
            onKeyDown={e => { if (e.key === 'Enter') add(); }} />
        </div>
        <button type="button" className="tv-btn primary" style={prpBtn(!canAdd, PRP_SMALL_BTN)} disabled={!canAdd} onClick={add}>
          {saving === 'add' ? 'Saving…' : (same ? 'Replace capital' : 'Save capital')}</button>
        <PerpsStatus saving={false} status={status} />
      </div>
      {problem && <span style={{ fontSize: 12, color: 'var(--warn)' }}>{problem}</span>}
      {!problem && from && same && <span style={{ fontSize: 13, color: 'var(--text2)' }}>
        {'Replaces ' + prpDollars(same.usd, hide) + ' from ' + prpDate(from) + '.'}</span>}
      {!problem && from && from <= today && <span style={{ fontSize: 13, color: 'var(--text2)' }}>
        Backdated: R2 on trades that opened before you save this gets a note saying the capital entry was made after they opened.</span>}
      {!problem && from && from > today && <span style={{ fontSize: 13, color: 'var(--text2)' }}>
        {'Applies to trades opened from ' + prpDate(from) + ' on.'}</span>}
    </div>
  </div>;
}

function PerpsSettingsHistory({ view, hide }) {
  const when = v => { const ms = Date.parse(v || ''); return isNaN(ms) ? -Infinity : ms; };
  const items = []
    .concat((view.status_changes || []).map((c, i) => ({ key: 's' + i, at: c.from,
      text: c.rule + ' set to ' + (PRP_STATUS_WORD[c.status] || c.status), reason: c.reason })))
    .concat((view.capital_changes || []).map((c, i) => ({ key: 'c' + i, at: c.set_at,
      text: c.usd === null || c.usd === undefined
        ? 'Capital entry from ' + prpDate(c.from) + ' removed'
        : 'Capital from ' + prpDate(c.from) + ' set to ' + prpDollars(c.usd, hide) })))
    .sort((a, b) => when(b.at) - when(a.at));
  if (!items.length) {
    return <div style={{ fontSize: 13, color: 'var(--text2)' }}>
      {'No changes yet: every rule is on its default, and capital is the default ' + prpDollars(view.capital && view.capital.usd, hide)
        + ' from ' + prpDate(view.capital_start) + '.'}</div>;
  }
  return <ul style={{ listStyle: 'none', margin: 0, padding: 0, display: 'flex', flexDirection: 'column' }}>
    {items.map(it => <li key={it.key} style={{ display: 'flex', gap: 12, flexWrap: 'wrap', padding: '8px 0', borderTop: PRP_LINE, fontSize: 13, color: 'var(--text2)' }}>
      <span style={{ minWidth: 130, color: 'var(--text3)' }}>{prpDate(it.at, true)}</span>
      <span style={{ color: 'var(--text)' }}>{it.text}</span>
      {it.reason && <span style={{ overflowWrap: 'anywhere' }}>{'Reason: ' + prpReasonText(it.reason, hide)}</span>}
    </li>)}
  </ul>;
}

// advisor: the page's rule-check read (version line); onChanged(): the page re-reads the rule check.
function PerpsRulesTab({ advisor, hide, onChanged }) {
  const [view, setView] = usePRPState(null);
  const [loading, setLoading] = usePRPState(false);
  const [error, setError] = usePRPState(null);
  const reqRef = usePRPRef(0);

  function load() {
    const mine = ++reqRef.current;
    setLoading(true);
    return api('/api/trading/advisor/perps/settings').then(d => {
      if (mine !== reqRef.current) return;
      if (!d || !Array.isArray(d.rules) || !Array.isArray(d.capital_periods)) throw new Error('Unexpected response');
      setView(d);
      setError(null);
      setLoading(false);
    }).catch(e => {
      if (mine !== reqRef.current) return;
      setLoading(false);
      setError(prpErr(e));
    });
  }
  usePRPEffect(() => { load(); return () => { reqRef.current += 1; }; }, []);
  function onSaved() { onChanged(); return load(); }

  const head = { fontSize: 12, lineHeight: '16px', fontWeight: 600, letterSpacing: '0.06em', textTransform: 'uppercase', color: 'var(--text3)' };
  if (!view) {
    return <div className="tv-card" style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap', fontSize: 14 }}>
      {error
        ? <React.Fragment><span role="alert" style={{ color: 'var(--fail)' }}>{"Couldn't load the rule settings: " + error}</span>
            <button type="button" className="tv-btn" style={prpBtn(loading)} disabled={loading} onClick={load}>Retry</button></React.Fragment>
        : <span role="status" style={{ color: 'var(--text3)' }}>Loading rule settings…</span>}
    </div>;
  }
  const version = advisor && advisor.data ? 'Rules v' + advisor.data.definition_version : 'Rules';
  return <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: 13, color: 'var(--text2)' }}>
      <span style={{ color: 'var(--text)', fontSize: 14 }}>
        {version + (view.settings_changed_at ? ' · settings last changed ' + prpDate(view.settings_changed_at, true) : ' · all defaults')}</span>
      <span>A change applies to trades opened from the moment you save it. Earlier trades keep the status they were judged under, and every change stays in the history below. Relaxing a rule (Enforced to Tracking) needs a reason.</span>
      {loading && <span role="status" style={{ color: 'var(--text3)' }}>Updating…</span>}
      {error && <span role="alert" style={{ color: 'var(--fail)' }}>{'Update failed: ' + error}</span>}
    </div>

    <section aria-labelledby="prp-rules-statuses" style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <h2 id="prp-rules-statuses" style={{ ...PRP_SECTION, margin: 0 }}>Rule statuses</h2>
      <div className="tv-card" style={{ padding: 0, overflow: 'hidden' }}>
        <div className="spot-grid-row spot-grid-head" style={{ ...head, gridTemplateColumns: PRP_SETTINGS_GRID, padding: '10px 16px', borderBottom: PRP_HEAD_LINE }}>
          <span>Rule</span><span>What it checks</span><span>Status</span><span>Since</span><span>Reason</span><span />
        </div>
        {view.rules.map(r => <PerpsRuleStatusRow key={r.id} rule={r} hide={hide} onSaved={onSaved} />)}
      </div>
    </section>

    <section aria-labelledby="prp-rules-capital" style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <h2 id="prp-rules-capital" style={{ ...PRP_SECTION, margin: 0 }}>Capital for R2</h2>
      <PerpsCapitalEditor view={view} hide={hide} onSaved={onSaved} />
    </section>

    <section aria-labelledby="prp-rules-history" style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <h2 id="prp-rules-history" style={{ ...PRP_SECTION, margin: 0 }}>Change history</h2>
      <PerpsSettingsHistory view={view} hide={hide} />
    </section>
  </div>;
}
