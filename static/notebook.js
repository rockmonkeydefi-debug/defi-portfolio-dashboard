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
   - Copy tab (Landing 81, in Tab options): a new tab "<name> (copy)" right
     after the open tab, holding a copy of its latest saved note (one saved
     version; the images are shared, not stored twice). With unsaved edits on
     the tab it asks first, since only the saved version can be copied.
   - Delete (Landing 83, in Tab options and on each archived tab): removes a
     tab for good, Watchlist and Nuggets included, with its notes, every saved
     version and the images no other note uses. The question shows the exact
     counts (/api/note-tabs/<key>/delete-preview); the last open tab can't be
     deleted. Images in this browser's unsaved notes on other pages are kept
     (nbDraftImageIds). Afterwards the next tab opens, or the Archived list
     comes back while archived tabs remain, with a line saying what was freed.
   - If the tab list can't be read, the two default tabs are shown on their
     own with a notice, and tabs can't be changed. (Since Landing 83 a default
     tab can be deleted: one deleted earlier shows there too, and its note
     can't load until the list does.)
   - The tab you had open is remembered per browser (localStorage notesTab,
     the tab's key; the ids remembered before Landing 31 still work).
   - The panel is keyed by its page, so switching tabs gives the other tab a
     fresh editor. An unsaved draft stays with its own tab (pnDrafts in
     pagenotes.js), and that tab's button says "unsaved" while you are on
     another one. While this page is open, an unsaved edit on any open tab
     makes the browser ask before a reload or leaving the app.
   - Hide values hides the notes (the panel's own rule), not the tab names.
   - Layout (Landing 35): from NB_SIDE_QUERY (900px of window width; the
     .nb-layout rule in static/style.css uses the same figure) the tabs and
     their tools are a column left of the note, staying in view while a long
     note scrolls; there a long name wraps instead of being cut, and Tab
     options moves a tab up or down. Narrower, they stay a row above the
     note and move left or right.

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
const NB_TAB_MODES = ['options', 'rename', 'archive', 'copy', 'delete'];
// Landing 83: the delete question for an archived tab (opened from the Archived list, not tied to the open tab).
const NB_DELETE_ARCHIVED = 'delete-archived';
const NB_KEEP_IDS_MAX = 2000;   // WATCH_KEEP_IDS_MAX: image ids a delete may be asked to keep
const NB_DEL_IDLE = { step: 'idle', key: null, data: null, error: '', keep: [], gone: false };
// Landing 35: from this window width the tabs are a column left of the note.
const NB_SIDE_QUERY = '(min-width: 900px)';

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

function nbPlural(n, word) {
  return n + ' ' + word + (n === 1 ? '' : 's');
}

function nbMb(bytes) {
  if (typeof pnMegabytes === 'function') return pnMegabytes(bytes);
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
}

// Landing 83: the image ids in this browser's unsaved note drafts on other pages (pnDrafts in pagenotes.js), which a
// delete must keep. The same reading as the Watch List's wlDraftImageIds.
function nbDraftImageIds(exceptPage) {
  const ids = new Set();
  try {
    if (typeof pnDrafts === 'undefined' || !pnDrafts) return [];
    Object.keys(pnDrafts).forEach(page => {
      if (page === exceptPage || !pnDrafts[page] || !pnDrafts[page].delta) return;
      const text = JSON.stringify(pnDrafts[page].delta);
      const re = /\/api\/note-images\/([1-9][0-9]{0,9})/g;
      let m;
      while ((m = re.exec(text)) !== null) ids.add(Number(m[1]));
    });
  } catch (e) { /* no drafts to read: nothing extra is kept */ }
  return Array.from(ids).slice(0, NB_KEEP_IDS_MAX);
}

// Landing 83: true while an image is still uploading into any note (pnUploads in pagenotes.js); it is in no draft yet.
function nbUploadsBusy() {
  try {
    if (typeof pnUploads === 'undefined' || !pnUploads || typeof pnUploadCount !== 'function') return false;
    return Object.keys(pnUploads).some(p => pnUploadCount(p) > 0);
  } catch (e) { return false; }
}

function nbDate(iso) {
  const ms = Date.parse(iso || '');
  if (isNaN(ms)) return '';
  const d = new Date(ms);
  const opts = { month: 'short', day: 'numeric' };
  if (d.getFullYear() !== new Date().getFullYear()) opts.year = 'numeric';
  return d.toLocaleDateString(undefined, opts);
}

// true at NB_SIDE_QUERY widths (the tabs are a column); follows window resizes.
function nbUseSide() {
  const [side, setSide] = React.useState(() =>
    typeof window.matchMedia === 'function' && window.matchMedia(NB_SIDE_QUERY).matches);
  React.useEffect(() => {
    if (typeof window.matchMedia !== 'function') return undefined;
    const mq = window.matchMedia(NB_SIDE_QUERY);
    const on = e => setSide(!!e.matches);
    if (mq.addEventListener) mq.addEventListener('change', on); else mq.addListener(on);
    setSide(mq.matches);
    return () => { if (mq.removeEventListener) mq.removeEventListener('change', on); else mq.removeListener(on); };
  }, []);
  return side;
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
  // Landing 83: the delete question's state: {step: 'idle' | 'loading' | 'ready' | 'error' | 'deleting', key, data
  // (the delete-preview reply, with its stamp), error, keep (image ids kept for unsaved notes elsewhere), gone (the
  // tab was already deleted)}.
  const [del, setDel] = React.useState(NB_DEL_IDLE);
  // Where the focus goes once a change has rendered: {tab: key} or {move: -1 | 1}.
  // State, not a ref, so it lands in the same render as the new tab list.
  const [focusReq, setFocusReq] = React.useState(null);
  const openerRef = React.useRef(null);                     // the button that opened the panel (focus returns there)
  const boxRef = React.useRef(null);
  const tabRefs = React.useRef({});
  const Panel = window.PageNotesPanel;
  const hasDraft = window.PageNotesHasDraft || (() => false);
  const side = nbUseSide();                                 // Landing 35: the tabs are a column

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
  // Landing 83: the tab shown and the panel as of the latest render (a delete's reply reads them after its wait).
  const liveRef = React.useRef({ page: null, box: null });
  liveRef.current = { page: current ? current.page : null, box };

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

  // Landing 83: Keep gets the focus once the delete question is ready (Try again after an error).
  React.useEffect(() => {
    if ((del.step !== 'ready' && del.step !== 'error') || !boxRef.current) return;
    const el = boxRef.current.querySelector('[data-nb-first]');
    if (el && el !== document.activeElement) el.focus();
  }, [del.step]);

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
    if (res.status === 404) load();       // Landing 83: the tab was deleted (in another window): show the list as it is now
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

  // Landing 81: a copy of the open tab, right after it. Unsaved edits are only in
  // this browser, so the copy holds the last saved version (the question says so).
  async function copyTab(confirmed) {
    if (busy) return;
    if (!confirmed && hasDraft(current.page)) { switchBox('copy'); return; }
    const from = current.label;
    const data = await write('POST', '/api/note-tabs/' + encodeURIComponent(current.page) + '/copy');
    if (!data || !data.key) return;
    setBox(null);
    openerRef.current = null;
    show(data.key);
    setFocusReq({ tab: data.key });
    setNotice('\u201c' + (data.label || 'The copy') + '\u201d was added after \u201c' + from + '\u201d'
      + (data.copied_note ? ' with its saved notes.' : '. That tab had no saved notes, so the copy is empty.'));
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

  // Landing 83: the delete question for tab t (mode 'delete' from Tab options, NB_DELETE_ARCHIVED from the Archived
  // list). The counts are read fresh, with this browser's unsaved notes elsewhere named, so the question is exact.
  function startDelete(t, mode) {
    if (busy) return;
    loadDelete(t, mode, '');
  }

  // note: a line shown with the counts (the tab changed after the question first opened).
  async function loadDelete(t, mode, note) {
    const keep = nbDraftImageIds(t.page);
    setError('');
    setNotice('');
    setBox(prev => ({ mode, text: '', page: mode === 'delete' ? (prev && prev.page) || t.page : null, target: t.page }));
    setDel({ ...NB_DEL_IDLE, step: 'loading', key: t.page, keep });
    const res = await nbRequest('GET', '/api/note-tabs/' + encodeURIComponent(t.page) + '/delete-preview'
      + (keep.length ? '?keep=' + keep.join(',') : ''), undefined, NB_LIST_TIMEOUT_MS);
    if (!res) return;
    const ok = res.status === 200 && res.data && res.data.images;
    setDel(d => (d.key !== t.page || d.step !== 'loading' ? d : ok ? { ...d, step: 'ready', data: res.data, error: note || '' }
      : { ...d, step: 'error', gone: res.status === 404, error: res.status === 404 ? 'This tab was already deleted, maybe in another window.'
        : "Couldn't read what would be deleted. Check the connection and try again." }));
    if (res.status === 404) load();
  }

  // Keep: back to where the question came from (the Archived list, or closed).
  function keepTab() {
    setDel(NB_DEL_IDLE);
    if (box && box.mode === NB_DELETE_ARCHIVED && archived.length > 0) { switchBox('archived'); return; }
    closeBox();
  }

  async function deleteTab() {
    if (busy || del.step !== 'ready' || !del.data || del.data.last_open) return;
    // An image still on its way into a note is in no draft yet, so it couldn't be kept: wait for it.
    if (nbUploadsBusy()) {
      setDel(d => ({ ...d, error: 'An image is still uploading into a note. Wait for it to finish, then delete.' }));
      return;
    }
    const key = del.key;
    const keep = nbDraftImageIds(key);              // read again at the click: a paste since the question opened counts
    const t = tabs.find(x => x.page === key) || { page: key, label: labelsRef.current[key] || '' };
    const fromArchived = !!(box && box.mode === NB_DELETE_ARCHIVED);
    const next = active[at + 1] || active[at - 1] || null;
    setDel(d => ({ ...d, step: 'deleting', error: '' }));
    setBusy(true);
    const res = await nbRequest('DELETE', '/api/note-tabs/' + encodeURIComponent(key), { keep_image_ids: keep, stamp: del.data.stamp });
    setBusy(false);
    if (!res) return;
    const ok = res.status === 200 && res.data && Array.isArray(res.data.tabs);
    // What the page shows now: clicks made while the delete was on its way count.
    const live = liveRef.current;
    const asking = !!(live.box && (live.box.mode === 'delete' || live.box.mode === NB_DELETE_ARCHIVED) && live.box.target === key);
    if (!ok && res.status !== 404) {
      if (res.data && Array.isArray(res.data.tabs)) setList({ status: 'ok', ...nbFromReply(res.data) });
      if (res.status === 409 && res.data && res.data.changed) {
        // The tab's notes or state changed after the counts were read: nothing was deleted; show the counts now.
        if (asking) loadDelete(t, live.box.mode, 'Not deleted: the tab changed after this question opened (a save or a change in another window). These are the counts now.');
        else setDel(NB_DEL_IDLE);
        return;
      }
      // A reply without the server's own message (no answer, or a proxy error) can't say whether the delete happened.
      const known = res.data && typeof res.data.error === 'string' && res.data.error;
      setDel(d => (d.key !== key ? d : { ...d, step: 'ready', error: known ? 'Not deleted: ' + nbSentence(res.data.error)
        : "The server didn't confirm the delete. Reload the page to see whether it went through." }));
      return;
    }
    if (ok) setList({ status: 'ok', ...nbFromReply(res.data) }); else load();     // 404: deleted in another window
    try { if (typeof pnDrafts !== 'undefined' && pnDrafts) delete pnDrafts[key]; } catch (e) { /* nothing to drop */ }
    const label = (ok && res.data.label) || t.label || 'The tab';
    const f = ok && res.data.freed ? res.data.freed : { count: 0, bytes: 0 };
    const msg = '\u201c' + label + '\u201d was deleted. ' + (!ok ? 'It had already been deleted, maybe in another window.'
      : f.count > 0 ? 'Freed ' + nbPlural(f.count, 'image') + ' (' + nbMb(f.bytes) + ').' : 'No images were freed.');
    setDel(NB_DEL_IDLE);
    if (live.page === key && next) show(next.page);         // the deleted tab was still the one shown
    const left = ok ? res.data.tabs.filter(x => x.archived).length : archived.filter(x => x.page !== key).length;
    if (asking && fromArchived && left > 0) { setBox({ mode: 'archived', text: '', page: null, info: msg }); return; }
    if (asking) setBox(null);
    setNotice(msg);
    if (!asking) return;                                    // the question was left while the delete ran: no focus move
    const el = openerRef.current;
    openerRef.current = null;
    if (live.page === key && next) setFocusReq({ tab: next.page });
    else if (live.page && live.page !== key) setFocusReq({ tab: live.page });
    else if (el && document.contains(el)) setTimeout(() => el.focus(), 0);
  }

  // The delete question (Landing 83), for the open tab or an archived one.
  function deleteBody() {
    const t = tabs.find(x => x.page === del.key) || { label: labelsRef.current[del.key] || '', archived: false };
    const d = del.data;
    const dirty = hasDraft(del.key);
    const titleId = 'nb-del-title', descId = 'nb-del-desc';
    const working = del.step === 'deleting';
    let text = null;
    if (d) {
      const shared = d.images.count - d.frees.count - d.kept_for_drafts.count;
      text = 'This removes ' + (d.note_versions > 0 ? 'its ' + nbPlural(d.note_versions, 'saved note version') : 'the tab (it has no saved notes)')
        + (d.frees.count > 0 ? ', and ' + nbPlural(d.frees.count, 'image') + ' (' + nbMb(d.frees.bytes) + ') that no other note uses' : '') + '.'
        + (shared > 0 ? ' ' + nbPlural(shared, 'image') + ' also used by other notes will stay.' : '')
        + (d.kept_for_drafts.count > 0 ? ' ' + nbPlural(d.kept_for_drafts.count, 'image') + ' will stay because an unsaved note elsewhere in this browser uses '
          + (d.kept_for_drafts.count === 1 ? 'it.' : 'them.') : '')
        + " This can't be undone. For a copy first, use Settings, Export DB."
        + (dirty ? ' Your unsaved edits on this tab will be lost too.' : '')
        + (!t.archived && !d.last_open ? ' To hide the tab and keep its notes, archive it instead.' : '');
    }
    return <div role="alertdialog" aria-labelledby={titleId} aria-describedby={d ? descId : undefined}>
      <div className="nb-box-title" id={titleId}>{'Delete the \u201c' + t.label + '\u201d tab permanently?'}</div>
      {/* A live region: the counts are read out when they arrive (Keep already has the focus). */}
      <div aria-live="polite">
        {del.step === 'loading' && <p className="nb-box-text">{'Checking what would be deleted\u2026'}</p>}
        {d && (del.step === 'ready' || working) && <p className="nb-box-text" id={descId}>{text}</p>}
      </div>
      {del.step === 'error' && <div role="alert" className="pn-alert">{del.error}</div>}
      {d && d.last_open && <div role="alert" className="pn-alert">This is the only open tab. Add another tab before deleting it.</div>}
      {del.error && del.step === 'ready' && <div role="alert" className="pn-error">{del.error}</div>}
      <div className="pn-actions">
        {del.gone
          ? <button type="button" className="tv-btn pn-btn" data-nb-first="" onClick={keepTab}>Close</button>
          : <>
            {del.step === 'error'
              ? <button type="button" className="tv-btn pn-btn" data-nb-first="" onClick={() => startDelete({ ...t, page: del.key }, box.mode)}>Try again</button>
              : <button type="button" className="tv-btn danger pn-btn" disabled={!d || working || d.last_open || busy}
                  aria-busy={working} onClick={deleteTab}>{working ? 'Deleting\u2026' : 'Delete permanently'}</button>}
            <button type="button" className="tv-btn pn-btn" data-nb-first={del.step === 'error' ? undefined : ''}
              disabled={working} onClick={keepTab}>Keep</button>
          </>}
      </div>
    </div>;
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
          <button type="button" className="tv-btn pn-btn" data-nb-move="-1" disabled={at <= 0} onClick={() => moveTab(-1)}>{side ? 'Move up' : 'Move left'}</button>
          <button type="button" className="tv-btn pn-btn" data-nb-move="1" disabled={at >= active.length - 1} onClick={() => moveTab(1)}>{side ? 'Move down' : 'Move right'}</button>
          <button type="button" className="tv-btn pn-btn" disabled={full || busy} onClick={() => copyTab(false)}
            title={full ? 'The tab bar is full (' + activeMax + ' tabs): archive a tab to copy one' : 'A new tab with a copy of this tab\u2019s notes, right after it'}>Copy tab</button>
          <button type="button" className="tv-btn pn-btn pn-btn-del" onClick={() => switchBox('archive')}>Archive…</button>
          <button type="button" className="tv-btn pn-btn pn-btn-del" disabled={busy} onClick={() => startDelete(current, 'delete')}>{'Delete\u2026'}</button>
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
    if (box.mode === 'copy') {
      return <>
        <div className="nb-box-title">{'Copy the \u201c' + current.label + '\u201d tab?'}</div>
        <p className="nb-box-text">This tab has unsaved edits. The copy takes the last saved version of its notes, not your unsaved edits. Save first to include them.</p>
        <div className="pn-actions">
          <button type="button" className="tv-btn primary pn-btn" disabled={busy || full} onClick={() => copyTab(true)}>Copy saved version</button>
          <button type="button" className="tv-btn pn-btn" data-nb-first="" onClick={closeBox}>Cancel</button>
        </div>
      </>;
    }
    if (box.mode === 'delete' || box.mode === NB_DELETE_ARCHIVED) return deleteBody();
    if (box.mode === 'archived') {
      return <>
        <div className="nb-box-title">Archived tabs</div>
        {box.info && <div role="status" className="nb-box-text">{box.info}</div>}
        {full && <div className="pn-alert">The tab bar is full ({activeMax} tabs). Archive a tab before restoring one.</div>}
        <ul className="nb-archived">
          {archived.map(t => <li key={t.page}>
            <span className="nb-archived-label">{t.label}</span>
            {hasDraft(t.page) && <span className="nb-unsaved">unsaved edits: restore it to save them</span>}
            {t.changedAt && <span className="nb-archived-when">archived {nbDate(t.changedAt)}</span>}
            <button type="button" className="tv-btn pn-btn" disabled={full} aria-label={'Restore the ' + t.label + ' tab'}
              onClick={() => restoreTab(t)}>Restore</button>
            <button type="button" className="tv-btn pn-btn pn-btn-del" disabled={busy} aria-label={'Delete the ' + t.label + ' tab'}
              onClick={() => startDelete(t, NB_DELETE_ARCHIVED)}>{'Delete\u2026'}</button>
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
  // Landing 83: the names of the tabs seen so far, so a tab deleted in another window can be named.
  const labelsRef = React.useRef({});
  tabs.forEach(t => { labelsRef.current[t.page] = t.label; });
  React.useEffect(() => {
    if (list.status === 'ok' && shownPage && want !== shownPage) setWant(shownPage);
    if (box && box.page && shownPage && box.page !== shownPage) {
      const gone = tabs.find(t => t.page === box.page);
      const name = labelsRef.current[box.page];
      setBox(null);
      setError('');
      openerRef.current = null;
      setNotice(gone && gone.archived ? '\u201c' + gone.label + '\u201d was archived in another window. Restore it from Archived.'
        : !gone && name ? '\u201c' + name + '\u201d was deleted, maybe in another window.' : '');
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
    {/* Landing 35: the tabs (nb-side) and the note (nb-main); style.css makes them two columns at NB_SIDE_QUERY widths. */}
    <div className="nb-layout">
      {current && <div className="nb-side">
        <div className="nb-bar">
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
            {archived.length > 0 && <button type="button" className="tv-btn nb-tool" aria-expanded={boxFor(['archived', NB_DELETE_ARCHIVED])}
              aria-controls={boxFor(['archived', NB_DELETE_ARCHIVED]) ? 'nb-box' : undefined}
              title={archivedDraft ? 'An archived tab has unsaved edits' : undefined}
              onClick={e => openBox('archived', e)}>Archived ({archived.length}){archivedDraft && <span className="nb-unsaved">{'\u00a0· unsaved'}</span>}</button>}
          </div>}
        </div>
      </div>}
      <div className="nb-main">
        {notice && !showBox && <div role="status" className="pn-alert nb-notice">{notice}</div>}
        {showBox && <div id="nb-box" className="nb-box" ref={boxRef}
          onKeyDown={e => {
            if (e.key !== 'Escape') return;
            e.stopPropagation();
            // Landing 83: Escape on the delete question is Keep (not while the delete is on its way).
            if (box.mode === 'delete' || box.mode === NB_DELETE_ARCHIVED) { if (del.step !== 'deleting') keepTab(); }
            else closeBox();
          }}>
          {boxBody()}
          {error && <div role="alert" className="pn-error">{error}</div>}
        </div>}
        {current && (Panel
          ? <Panel key={current.page} page={current.page} hideValues={hideValues} label={current.label} variant="page" />
          : <div role="alert" className="pn-muted">The notes editor didn't load. Reload the page to try again.</div>)}
      </div>
    </div>
  </div>;
}

window.NotesScreen = NotesScreen;
