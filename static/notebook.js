/* ===== NOTES PAGE — Landing 24; tabs you manage: Landing 31 =====
   The Trading menu's Notes page: tabs, each a formatted note of its own
   (static/pagenotes.js, PageNotesPanel with variant="page"), saved through
   /api/page-notes/<page> under the tab's key. Every saved version is kept, as
   for the Spot note.

   - Tabs (Landing 31): Watchlist and Nuggets exist from the start
     (NB_DEFAULT_TABS, web_portfolio.NOTE_TAB_DEFAULTS; a test pins them
     together). "+ New tab" adds one at the end; "Tab options" renames the
     open tab, moves it left or right, or archives it; "Archived (N)" lists
     archived tabs to restore. The list comes from /api/note-tabs and every
     change answers with the whole list, so the bar always shows the server's
     state. An archived tab leaves the bar with its note and every saved
     version kept, and comes back at the end of the bar. A tab with unsaved
     edits can't be archived (its draft would lose the leave-page warning),
     nor can the last open tab.
   - If the tab list can't be read, the two default tabs are shown on their
     own (their notes always exist) with a notice, and tabs can't be changed.
   - The tab you had open is remembered per browser (localStorage notesTab,
     the tab's key; the ids remembered before Landing 31 still work).
   - The panel is keyed by its page, so switching tabs gives the other tab a
     fresh editor. An unsaved draft stays with its own tab (pnDrafts in
     pagenotes.js), and that tab's button says "unsaved" while you are on
     another one. While this page is open, an unsaved edit on any open tab
     makes the browser ask before a reload or leaving the app.
   - Hide values hides the notes (the panel's own rule), not the tab names.

   Loaded after static/pagenotes.js (templates/index.html). Every top-level
   name here starts with nb / NB / Notes: Babel turns top-level declarations
   into shared globals, so a name used in another static/*.js file would be
   silently overwritten. */

// The tabs that exist from the start. id is the name a browser remembered
// before Landing 31 (localStorage notesTab).
const NB_DEFAULT_TABS = [
  { id: 'watchlist', page: 'notes-watchlist', label: 'Watchlist' },
  { id: 'nuggets', page: 'notes-nuggets', label: 'Nuggets' },
];
const NB_TAB_KEY = 'notesTab';
const NB_LABEL_MAX = 40;        // NOTE_TAB_LABEL_MAX (the server's reply carries its own limits)
const NB_ACTIVE_MAX = 20;       // NOTE_TABS_ACTIVE_MAX
const NB_LIST_TIMEOUT_MS = 10000;   // a tab list that hasn't arrived by then shows the default tabs
// The panel's modes that belong to the open tab (they close if that tab leaves the bar).
const NB_TAB_MODES = ['options', 'rename', 'archive'];

function nbReadTab() {
  try {
    const v = localStorage.getItem(NB_TAB_KEY) || '';
    const legacy = NB_DEFAULT_TABS.find(t => t.id === v);
    return legacy ? legacy.page : v;
  } catch (e) { return ''; }
}

function nbWriteTab(page) {
  try { localStorage.setItem(NB_TAB_KEY, page); } catch (e) { /* storage blocked: the choice lasts this visit only */ }
}

// A tab name as the server stores it: trimmed, each run of spaces made one.
function nbCleanLabel(s) {
  return String(s || '').split(/\s+/).filter(Boolean).join(' ');
}

// Characters as the server counts them (code points, not UTF-16 units).
function nbLength(s) {
  return Array.from(s).length;
}

function nbSentence(s) {
  const t = String(s || '').trim();
  if (!t) return t;
  return t.charAt(0).toUpperCase() + t.slice(1) + (/[.!?]$/.test(t) ? '' : '.');
}

function nbDate(iso) {
  const ms = Date.parse(iso || '');
  if (isNaN(ms)) return '';
  const d = new Date(ms);
  const opts = { month: 'short', day: 'numeric' };
  if (d.getFullYear() !== new Date().getFullYear()) opts.year = 'numeric';
  return d.toLocaleDateString(undefined, opts);
}

// {status, data} (status 0 when the request failed or ran past timeoutMs);
// null after a 401 (the page goes to the login screen, as api() does).
async function nbRequest(method, path, body, timeoutMs) {
  let res;
  const ctrl = timeoutMs && typeof AbortController !== 'undefined' ? new AbortController() : null;
  const timer = ctrl ? setTimeout(() => ctrl.abort(), timeoutMs) : null;
  try {
    res = await fetch(path, { method, headers: { 'Content-Type': 'application/json' },
                              body: body === undefined ? undefined : JSON.stringify(body),
                              signal: ctrl ? ctrl.signal : undefined });
  } catch (e) {
    return { status: 0, data: null };
  } finally {
    if (timer) clearTimeout(timer);
  }
  if (res.status === 401) { window.location.href = '/login'; return null; }
  let data = null;
  try { data = await res.json(); } catch (e) { /* not JSON */ }
  return { status: res.status, data };
}

function nbFromReply(data) {
  return {
    tabs: data.tabs.map(t => ({ page: t.key, label: t.label, archived: !!t.archived, changedAt: t.changed_at })),
    limits: data.limits || null,
  };
}

function NotesScreen({ hideValues }) {
  const [list, setList] = React.useState({ status: 'loading', tabs: [], limits: null });
  const [want, setWant] = React.useState(nbReadTab);        // the key of the tab to show
  const [box, setBox] = React.useState(null);               // null | {mode, text}: the tab tools' panel
  const [busy, setBusy] = React.useState(false);            // a tab change is on its way (clicks wait)
  const [error, setError] = React.useState('');
  const [notice, setNotice] = React.useState('');          // a note outside the panel (its tab left the bar)
  // Where the focus goes once a change has rendered: {tab: key} or {move: -1 | 1}.
  // State, not a ref, so it lands in the same render as the new tab list.
  const [focusReq, setFocusReq] = React.useState(null);
  const openerRef = React.useRef(null);                     // the button that opened the panel (focus returns there)
  const boxRef = React.useRef(null);
  const tabRefs = React.useRef({});
  const Panel = window.PageNotesPanel;
  const hasDraft = window.PageNotesHasDraft || (() => false);

  const [retrying, setRetrying] = React.useState(false);
  function load() {
    nbRequest('GET', '/api/note-tabs', undefined, NB_LIST_TIMEOUT_MS).then(res => {
      setRetrying(false);
      if (!res) return;
      if (res.status === 200 && res.data && Array.isArray(res.data.tabs)) setList({ status: 'ok', ...nbFromReply(res.data) });
      else setList(prev => (prev.status === 'ok' ? prev : { status: 'error', tabs: [], limits: null }));
    });
  }
  React.useEffect(load, []);
  // Try again keeps the default tabs (and an open editor) on screen while it
  // asks, and stays on the tab shown when the full list arrives.
  function retry() {
    if (retrying) return;
    if (current) setWant(current.page);
    setRetrying(true);
    load();
  }

  const fallback = list.status === 'error';
  const tabs = list.status === 'ok' ? list.tabs
    : fallback ? NB_DEFAULT_TABS.map(t => ({ page: t.page, label: t.label, archived: false, changedAt: null })) : [];
  const active = tabs.filter(t => !t.archived);
  const archived = tabs.filter(t => t.archived);
  const current = active.find(t => t.page === want) || active[0] || null;
  const at = current ? active.indexOf(current) : -1;
  const labelMax = (list.limits && list.limits.label_max) || NB_LABEL_MAX;
  const activeMax = (list.limits && list.limits.active_max) || NB_ACTIVE_MAX;
  const full = active.length >= activeMax;

  // Every tab's unsaved edits count for the leave-page warning while this
  // page is open: the tabs you are not on, and archived ones too (another
  // window may archive a tab that has unsaved edits here).
  const pagesKey = tabs.map(t => t.page).join('|');
  React.useEffect(() => (window.PageNotesShowPages && pagesKey ? window.PageNotesShowPages(pagesKey.split('|')) : undefined), [pagesKey]);

  // Focus after a change: the tab just added, restored or shown in place of
  // an archived one; after a move, the same Move button, or the other one
  // when the tab reached the end of the bar.
  React.useEffect(() => {
    if (!focusReq) return;
    if (focusReq.tab && tabRefs.current[focusReq.tab]) tabRefs.current[focusReq.tab].focus();
    if (focusReq.move && boxRef.current) {
      const q = s => boxRef.current.querySelector('[data-nb-move="' + s + '"]:not(:disabled)');
      const b = q(focusReq.move) || q(-focusReq.move);
      if (b && b !== document.activeElement) b.focus();
    }
  }, [focusReq]);
  // The panel's field, or its first button (Cancel on the archive question), when it opens.
  const boxMode = box ? box.mode : null;
  React.useEffect(() => {
    if (!boxMode || !boxRef.current) return;
    const el = boxRef.current.querySelector('[data-nb-first]') || boxRef.current.querySelector('input, button:not(:disabled)');
    if (el) el.focus();
  }, [boxMode]);

  function show(page) {
    setWant(page);
    nbWriteTab(page);
  }

  function pick(page) {
    show(page);
    setBox(null);
    setError('');
    setNotice('');
    openerRef.current = null;
  }

  // The opener toggles its panel: pressed again, it closes (Tab options also
  // closes the Rename and Archive steps it led to). The open tab's modes
  // remember which tab they are for.
  function openBox(mode, e, text) {
    const family = m => (NB_TAB_MODES.includes(m) ? 'tab' : m);
    if (showBox && family(box.mode) === family(mode) && e && openerRef.current === e.currentTarget) { closeBox(); return; }
    if (e) openerRef.current = e.currentTarget;
    setError('');
    setNotice('');
    setBox({ mode, text: text || '', page: NB_TAB_MODES.includes(mode) && current ? current.page : null });
  }

  function switchBox(mode, text) {
    setError('');
    setBox(prev => ({ mode, text: text || '', page: prev ? prev.page : null }));
  }

  function closeBox() {
    setBox(null);
    setError('');
    const el = openerRef.current;
    openerRef.current = null;
    if (el && document.contains(el)) setTimeout(() => el.focus(), 0);
  }

  // A tab change: the reply is always the whole tab list (a refusal too), so
  // the bar shows the server's state. Returns the reply on success, else null
  // with the reason shown in the panel.
  async function write(method, path, body) {
    setBusy(true);
    setError('');
    const res = await nbRequest(method, path, body);
    setBusy(false);
    if (!res) return null;
    if (res.data && Array.isArray(res.data.tabs)) setList({ status: 'ok', ...nbFromReply(res.data) });
    if (res.status >= 200 && res.status < 300) return res.data || {};
    if (res.status === 0) setError("Couldn't reach the server. Check the connection and try again.");
    else setError('Not changed: ' + nbSentence((res.data && res.data.error) || 'the server answered ' + res.status));
    return null;
  }

  function nameProblem(label) {
    if (!label) return 'Type a name for the tab.';
    const n = nbLength(label);
    if (n > labelMax) return 'A tab name is limited to ' + labelMax + ' characters (this one has ' + n + ').';
    return '';
  }

  async function addTab() {
    if (busy) return;
    const label = nbCleanLabel(box.text);
    const problem = nameProblem(label);
    if (problem) { setError(problem); return; }
    const data = await write('POST', '/api/note-tabs', { label });
    if (!data || !data.key) return;
    setBox(null);
    openerRef.current = null;
    show(data.key);
    setFocusReq({ tab: data.key });
  }

  async function renameTab() {
    if (busy) return;
    const label = nbCleanLabel(box.text);
    const problem = nameProblem(label);
    if (problem) { setError(problem); return; }
    const data = await write('PUT', '/api/note-tabs/' + encodeURIComponent(current.page), { label });
    if (data) closeBox();
  }

  async function moveTab(step) {
    if (busy) return;
    const keys = active.map(t => t.page);
    const to = at + step;
    if (at < 0 || to < 0 || to >= keys.length) return;
    [keys[at], keys[to]] = [keys[to], keys[at]];
    if (await write('PUT', '/api/note-tabs/order', { keys })) setFocusReq({ move: step });
  }

  async function archiveTab() {
    if (busy) return;
    // Read again at the click: the draft may have changed since the question opened.
    if (hasDraft(current.page)) {
      setError('This tab has unsaved edits. Save or discard them, then archive it.');
      return;
    }
    const next = active[at + 1] || active[at - 1] || null;
    // This window's own archive: the question stays up (for an error) but is
    // no longer tied to the tab, so it isn't taken for an archive made elsewhere.
    setBox(prev => (prev ? { ...prev, page: null } : prev));
    const data = await write('PUT', '/api/note-tabs/' + encodeURIComponent(current.page), { archived: true });
    if (!data) return;
    setBox(null);
    openerRef.current = null;
    if (next) { show(next.page); setFocusReq({ tab: next.page }); }
  }

  async function restoreTab(t) {
    if (busy) return;
    const data = await write('PUT', '/api/note-tabs/' + encodeURIComponent(t.page), { archived: false });
    if (!data) return;
    setBox(null);
    openerRef.current = null;
    show(t.page);
    setFocusReq({ tab: t.page });
  }

  function nameForm(title, submitText, onSubmit) {
    const n = nbLength(nbCleanLabel(box.text));
    return <form className="nb-form" onSubmit={e => { e.preventDefault(); onSubmit(); }}>
      <label className="nb-field">
        <span className="nb-box-title">{title}</span>
        <input type="text" value={box.text} autoComplete="off" spellCheck={true} aria-describedby="nb-name-count"
          onChange={e => { setError(''); setBox({ ...box, text: e.target.value }); }} />
      </label>
      <span id="nb-name-count" className={'nb-count' + (n > labelMax ? ' nb-over' : '')}>{n} / {labelMax} characters</span>
      <div className="pn-actions">
        <button type="submit" className="tv-btn primary pn-btn">{busy ? 'Saving…' : submitText}</button>
        <button type="button" className="tv-btn pn-btn" onClick={closeBox}>Cancel</button>
      </div>
    </form>;
  }

  function boxBody() {
    if (box.mode === 'new') return nameForm('New tab name', 'Add tab', addTab);
    if (box.mode === 'rename') return nameForm('Rename the “' + current.label + '” tab', 'Save name', renameTab);
    if (box.mode === 'options') {
      return <>
        <div className="nb-box-title">{'“' + current.label + '” tab'}</div>
        <div className="pn-actions">
          <button type="button" className="tv-btn pn-btn" onClick={() => switchBox('rename', current.label)}>Rename</button>
          <button type="button" className="tv-btn pn-btn" data-nb-move="-1" disabled={at <= 0} onClick={() => moveTab(-1)}>Move left</button>
          <button type="button" className="tv-btn pn-btn" data-nb-move="1" disabled={at >= active.length - 1} onClick={() => moveTab(1)}>Move right</button>
          <button type="button" className="tv-btn pn-btn pn-btn-del" onClick={() => switchBox('archive')}>Archive…</button>
          <button type="button" className="tv-btn pn-btn" onClick={closeBox}>Close</button>
        </div>
      </>;
    }
    if (box.mode === 'archive') {
      const dirty = hasDraft(current.page);
      const last = active.length <= 1;
      return <>
        <div className="nb-box-title">{'Archive the “' + current.label + '” tab?'}</div>
        <p className="nb-box-text">It leaves the tab bar. Its notes and every saved version are kept, and you can restore it from Archived.</p>
        {dirty && <div className="pn-alert">This tab has unsaved edits. Save or discard them, then archive it.</div>}
        {last && <div className="pn-alert">This is the only open tab. Add another tab before archiving it.</div>}
        <div className="pn-actions">
          {/* Unsaved edits are checked again at the click (saving below doesn't redraw this question). */}
          <button type="button" className="tv-btn danger pn-btn" disabled={last} onClick={archiveTab}>Archive tab</button>
          <button type="button" className="tv-btn pn-btn" data-nb-first="" onClick={closeBox}>Cancel</button>
        </div>
      </>;
    }
    if (box.mode === 'archived') {
      return <>
        <div className="nb-box-title">Archived tabs</div>
        {full && <div className="pn-alert">The tab bar is full ({activeMax} tabs). Archive a tab before restoring one.</div>}
        <ul className="nb-archived">
          {archived.map(t => <li key={t.page}>
            <span className="nb-archived-label">{t.label}</span>
            {hasDraft(t.page) && <span className="nb-unsaved">unsaved edits: restore it to save them</span>}
            {t.changedAt && <span className="nb-archived-when">archived {nbDate(t.changedAt)}</span>}
            <button type="button" className="tv-btn pn-btn" disabled={full} aria-label={'Restore the ' + t.label + ' tab'}
              onClick={() => restoreTab(t)}>Restore</button>
          </li>)}
        </ul>
        <div className="pn-actions">
          <button type="button" className="tv-btn pn-btn" onClick={closeBox}>Close</button>
        </div>
      </>;
    }
    return null;
  }

  // A panel for a tab that left the bar (archived in another window, seen on
  // the next reply) closes instead of acting on the tab shown in its place.
  const showBox = box && current && !fallback && (box.mode !== 'archived' || archived.length > 0)
    && (!box.page || box.page === current.page);
  const boxFor = m => !!(showBox && (Array.isArray(m) ? m.includes(boxMode) : boxMode === m));

  // The open tab's panel is for one tab: when a reply shows that tab gone
  // from the bar (archived in another window), the panel closes and a note
  // says why. Once the list is known, the tab shown is the one remembered,
  // so a tab restored elsewhere later doesn't take its place by surprise.
  const shownPage = current ? current.page : null;
  React.useEffect(() => {
    if (list.status === 'ok' && shownPage && want !== shownPage) setWant(shownPage);
    if (box && box.page && shownPage && box.page !== shownPage) {
      const gone = tabs.find(t => t.page === box.page);
      setBox(null);
      setError('');
      openerRef.current = null;
      setNotice(gone && gone.archived ? '\u201c' + gone.label + '\u201d was archived in another window. Restore it from Archived.' : '');
    }
  }, [list, shownPage, box, want]);
  const archivedDraft = archived.some(t => hasDraft(t.page));

  return <div className="nb-page">
    <div className="nb-head">
      <h1 style={{ margin:0, fontSize:20, lineHeight:'26px', fontWeight:700, color:'var(--text)' }}>Notes</h1>
      <div style={{ fontSize:13, lineHeight:'18px', color:'var(--text3)' }}>Prep notes, one tab per topic: tokens you're watching, trading nuggets worth keeping, and any tab you add.</div>
    </div>
    {list.status === 'loading' && <div role="status" className="pn-muted">Loading tabs…</div>}
    {fallback && <div role="alert" className="pn-alert">
      The tab list didn't load, so only Watchlist and Nuggets are shown and tabs can't be changed.{' '}
      <button type="button" className="pn-textbtn" onClick={retry}>{retrying ? 'Trying again…' : 'Try again'}</button>
    </div>}
    {current && <div className="nb-bar">
      <div className="nb-tabs" role="group" aria-label="Notes pages">
        {active.map(t => {
          const on = t.page === current.page;
          const unsaved = !on && hasDraft(t.page);
          return <button key={t.page} type="button" className="tv-btn nb-tab" aria-pressed={on}
            ref={el => { if (el) tabRefs.current[t.page] = el; else delete tabRefs.current[t.page]; }}
            title={unsaved ? t.label + ' has unsaved edits' : t.label}
            style={{ background:on?'var(--panel3)':'transparent', borderColor:on?'var(--accent-line)':'var(--line)',
              color:on?'var(--text)':'var(--text3)', fontWeight:on?600:400 }}
            onClick={() => pick(t.page)}>
            <span className="nb-tab-label">{t.label}</span>{unsaved && <span className="nb-unsaved">{'\u00a0· unsaved'}</span>}
          </button>;
        })}
        {!fallback && <button type="button" className="tv-btn nb-tool" aria-expanded={boxFor('new')}
          aria-controls={boxFor('new') ? 'nb-box' : undefined}
          disabled={full} title={full ? 'The tab bar is full (' + activeMax + ' tabs): archive a tab to add another' : undefined}
          onClick={e => openBox('new', e)}>+ New tab</button>}
      </div>
      {!fallback && <div className="nb-tools">
        <button type="button" className="tv-btn nb-tool" aria-expanded={boxFor(NB_TAB_MODES)}
          aria-controls={boxFor(NB_TAB_MODES) ? 'nb-box' : undefined} aria-label={'Options for the ' + current.label + ' tab'}
          onClick={e => openBox('options', e)}>Tab options</button>
        {archived.length > 0 && <button type="button" className="tv-btn nb-tool" aria-expanded={boxFor('archived')}
          aria-controls={boxFor('archived') ? 'nb-box' : undefined}
          title={archivedDraft ? 'An archived tab has unsaved edits' : undefined}
          onClick={e => openBox('archived', e)}>Archived ({archived.length}){archivedDraft && <span className="nb-unsaved">{'\u00a0· unsaved'}</span>}</button>}
      </div>}
    </div>}
    {notice && !showBox && <div role="status" className="pn-alert nb-notice">{notice}</div>}
    {showBox && <div id="nb-box" className="nb-box" ref={boxRef}
      onKeyDown={e => { if (e.key === 'Escape') { e.stopPropagation(); closeBox(); } }}>
      {boxBody()}
      {error && <div role="alert" className="pn-error">{error}</div>}
    </div>}
    {current && (Panel
      ? <Panel key={current.page} page={current.page} hideValues={hideValues} label={current.label} variant="page" />
      : <div role="alert" className="pn-muted">The notes editor didn't load. Reload the page to try again.</div>)}
  </div>;
}

window.NotesScreen = NotesScreen;
