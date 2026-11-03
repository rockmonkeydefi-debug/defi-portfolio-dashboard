/* ===== SPOT NOTES JOURNAL — Landing 2a (HANDOFF_spot_perps_rebuild.md 3.1) =====
   One spot position's journal: an undated Summary (PUT /api/spot/position-notes)
   plus dated updates (/api/spot/note-updates, newest first). Spot only.

   Formatting is markdown-style markers, rendered as React elements (never raw
   HTML): **bold**, *italic*, and lines starting "- " (or "* " / "• ") as
   bullets. No numbered lists. A marker only counts when the opening one is not
   right after a letter, digit, underscore or "*", the closing one is not right
   before one, and the text inside does not start or end with a space - so
   2*3*4 and ***x*** stay plain text.

   Landing 88: the Summary is written in the Notes page editor (static/pagenotes.js,
   PageNotesPanel with an io prop; SJSummary below). A Summary saved there is a
   document (GET / PUT /api/spot/position-notes with {delta, base_id}) with images,
   tables and colour; one written before still reads as the markers above until you
   save it in the editor (sjToDelta opens it with its bold, italic and bullets).

   Landing 89: the dated updates are written in the same editor: each update is a
   panel of its own (SJUpdateDoc), a new one is composed in a panel too (SJNewUpdate),
   both through the update routes (GET / POST / PUT /api/spot/note-updates with
   {delta, base_id}); an update written before still reads as the markers above until
   you save it in the editor.

   Loaded before static/spotpnl.js (templates/index.html). Every top-level name
   here starts with sj / SJ / SpotJournal: Babel turns top-level declarations
   into shared globals, so a name used in another static/*.js file would be
   silently overwritten. */

const { useState: useSJState } = React;

const SJ_PREVIEW_MAX = 300;     // ✎ hover preview, per part
const SJ_BULLET_RE = /^(\s*)([-•*])\s+(.*)$/;
const SJ_LINE = '2px solid rgba(255,255,255,0.25)';          // between updates
const SJ_LINE_STRONG = '2px solid rgba(255,255,255,0.4)';    // between the Summary and the updates
const SJ_SECTION = { fontSize: 12, lineHeight: '16px', fontWeight: 600, letterSpacing: '0.08em',
                     textTransform: 'uppercase', color: 'var(--text3)' };
const SJ_SMALL_BTN = { fontSize: 13, padding: '4px 12px', minHeight: 32 };

// ── Parsing ─────────────────────────────────────────────────────────────────

// Inline segments of one line: [{t, b?, i?}]. See the file header for the rules.
function sjInline(text) {
  const out = [];
  const re = /\*\*([^*\n]+)\*\*|\*([^*\n]+)\*/g;
  let last = 0;
  let m;
  while ((m = re.exec(text)) !== null) {
    const start = m.index;
    const end = re.lastIndex;
    const bold = m[1] != null;
    const inner = bold ? m[1] : m[2];
    const before = start > 0 ? text[start - 1] : '';
    const after = end < text.length ? text[end] : '';
    if (/[\w*]/.test(before) || /[\w*]/.test(after) || inner.trim() !== inner) {
      re.lastIndex = start + 1;
      continue;
    }
    if (start > last) out.push({ t: text.slice(last, start) });
    out.push(bold ? { t: inner, b: true } : { t: inner, i: true });
    last = end;
  }
  if (last < text.length) out.push({ t: text.slice(last) });
  return out;
}

// Lines of a note: [{kind: 'bullet' | 'plain' | 'blank', segs}].
function sjParseNote(text) {
  return String(text == null ? '' : text).replace(/\r\n?/g, '\n').split('\n').map(raw => {
    const bm = raw.match(SJ_BULLET_RE);
    if (bm) return { kind: 'bullet', segs: sjInline(bm[3]) };
    if (!raw.trim()) return { kind: 'blank', segs: [] };
    return { kind: 'plain', segs: sjInline(raw) };
  });
}

// Plain text with the markers stripped, lines joined with " · ", cut at max with "…".
function sjPlain(text, max) {
  const limit = max == null ? SJ_PREVIEW_MAX : max;
  const flat = sjParseNote(text).filter(l => l.kind !== 'blank')
    .map(l => l.segs.map(s => s.t).join('').replace(/\s+/g, ' ').trim()).filter(Boolean).join(' · ');
  return flat.length > limit ? flat.slice(0, limit).replace(/\s+$/, '') + '…' : flat;
}

function SJSegs({ segs }) {
  return segs.map((s, i) => s.b ? <strong key={i} style={{ fontWeight: 700, color: 'var(--text)' }}>{s.t}</strong>
    : s.i ? <em key={i}>{s.t}</em> : <React.Fragment key={i}>{s.t}</React.Fragment>);
}

// A rendered note. Consecutive bullet lines become one list.
function SJNoteText({ text }) {
  const lines = sjParseNote(text);
  const blocks = [];
  for (let i = 0; i < lines.length; i++) {
    const l = lines[i];
    if (l.kind === 'bullet') {
      const items = [];
      while (i < lines.length && lines[i].kind === 'bullet') { items.push(lines[i]); i++; }
      i--;
      blocks.push(<ul key={i} style={{ margin: 0, paddingLeft: 22, listStyle: 'disc' }}>
        {items.map((it, k) => <li key={k} style={{ whiteSpace: 'pre-wrap' }}><SJSegs segs={it.segs} /></li>)}
      </ul>);
    } else if (l.kind === 'blank') {
      blocks.push(<div key={i} style={{ height: 8 }} />);
    } else {
      blocks.push(<div key={i} style={{ whiteSpace: 'pre-wrap' }}><SJSegs segs={l.segs} /></div>);
    }
  }
  return <div style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: 14, lineHeight: '21px',
                       color: 'var(--text2)', overflowWrap: 'anywhere' }}>{blocks}</div>;
}

// ── Times ───────────────────────────────────────────────────────────────────

// Epoch ms for a stored time, NaN when unreadable. A time without an offset
// (the Summary's SQLite CURRENT_TIMESTAMP) is UTC.
function sjParseTime(s) {
  if (!s) return NaN;
  const str = String(s).trim();
  if (/^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(:\d{2}(\.\d+)?)?$/.test(str)) return Date.parse(str.replace(' ', 'T') + 'Z');
  return Date.parse(str);
}

// "Oct 2, 2026 · 8:40 AM" in local time.
function sjStamp(ms) {
  if (!isFinite(ms)) return '';
  const d = new Date(ms);
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' }) + ' · '
    + d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' }).replace(/ /g, ' ');
}

function sjAgo(ms) {
  if (!isFinite(ms)) return '';
  const sec = Math.max(0, (Date.now() - ms) / 1000);
  if (sec < 90) return 'just now';
  const min = sec / 60;
  if (min < 60) return Math.round(min) + ' min ago';
  const hr = min / 60;
  if (hr < 24) return Math.round(hr) + ' h ago';
  const days = Math.floor(hr / 24);
  return days === 1 ? '1 day ago' : days + ' days ago';
}

// The row's ✎ age: "now", "5h", "3d".
function sjShortAge(ms) {
  if (!isFinite(ms)) return '';
  const hr = Math.max(0, (Date.now() - ms) / 3600000);
  if (hr < 1) return 'now';
  if (hr < 24) return Math.round(hr) + 'h';
  return Math.floor(hr / 24) + 'd';
}

// -- The Summary in the Notes page editor (Landing 88) --------------------

const SJ_SUMMARY_EMPTY = "No summary yet. Use it for what doesn't change day to day: where it's held, why you own it.";

// A Summary written before the full editor (the markers above) as an editor document: **bold** and *italic* become
// formats and "- " lines become bullets. Nothing is saved by this: it is what the editor opens with, and a Summary
// is converted for good only when you save it there.
function sjToDelta(text) {
  const ops = [];
  sjParseNote(text).forEach(line => {
    line.segs.forEach(sg => {
      if (!sg.t) return;
      ops.push(sg.b ? { insert: sg.t, attributes: { bold: true } }
        : sg.i ? { insert: sg.t, attributes: { italic: true } } : { insert: sg.t });
    });
    ops.push(line.kind === 'bullet' ? { insert: '\n', attributes: { list: 'bullet' } } : { insert: '\n' });
  });
  return { ops: ops.length ? ops : [{ insert: '\n' }] };
}

// The server's Summary view with a document in it: text written before the full editor is converted (sjToDelta).
function sjSummaryView(v) {
  return v && v.legacy && !v.delta ? { ...v, delta: sjToDelta(v.text) } : v;
}

// The Summary of one position: the Notes page editor with the Summary routes behind it. The panel keeps the draft
// (pnDrafts, key 'spot-summary:<scope>:<position key>'), the conflict prompt and the images; onSaved(text, delta) tells
// the page what was saved (the plain-text mirror for the row's tooltip, the document for History). scope tells apart
// panels of ONE position that are on screen together (History shows the position's Summary under every closed trade):
// each has its own draft and its own uploads, so one panel's editor can never open, overwrite or lose the images of
// another's. The Open positions row has one panel per position (no scope).
function SJSummary({ chain, contract_address, symbol, scope, onSaved }) {
  const Panel = window.PageNotesPanel;
  if (!Panel) return <div style={{ fontSize: 13, color: 'var(--fail)' }}>The notes editor didn't load. Refresh to try again.</div>;
  const query = '?chain=' + encodeURIComponent(chain) + '&contract_address=' + encodeURIComponent(contract_address);
  const io = {
    async get() {
      const res = await pnRequest('GET', '/api/spot/position-notes/view' + query);
      if (res && res.status === 200) res.data = sjSummaryView(res.data);
      return res;
    },
    async put(delta, baseId) {
      const res = await pnRequest('PUT', '/api/spot/position-notes', { chain, contract_address, delta, base_id: baseId });
      if (res && res.status === 200 && res.data && onSaved) onSaved(res.data.text, res.data.delta);
      if (res && res.status === 409 && res.data && res.data.current) res.data = { ...res.data, current: sjSummaryView(res.data.current) };
      return res;
    },
  };
  return <div className="sj-summary">
    <Panel page={'spot-summary:' + (scope || 'open') + ':' + chain + ' ' + contract_address} label={'Summary for ' + symbol} variant="page" io={io}
      emptyText={SJ_SUMMARY_EMPTY} />
  </div>;
}

// -- A dated update in the Notes page editor (Landing 89) -----------------

// An update row (as the list, POST and PUT answer) as the editor's note view: {id (the version token), delta, text,
// saved_at, empty, legacy, row}. An update written before the full editor opens converted (sjToDelta); nothing is
// saved by this, it is converted for good only when saved in the editor. row is the update itself, so the page can
// replace its copy when the editor closes with the stored version ("Use theirs" on a conflict).
function sjUpdateView(u) {
  if (!u) return u;
  return { id: u.version, delta: u.delta || sjToDelta(u.body), text: u.body, saved_at: u.edited_at || u.created_at,
           empty: !String(u.body || '').trim(), legacy: !!u.legacy, row: u };
}

// One dated update as a Notes page panel. pageKey is the panel's draft key ('spot-update:<scope>:<id>': scope tells
// apart journals of ONE position that are on screen together, History shows it under every closed trade); editing
// opens the panel in edit mode (the journal remounts the panel with a new key when its own Edit is pressed). The
// update's own row (stamp, Edit, Delete) is the journal's; the panel's header shows only while editing.
// onSaved(update) hands the page the stored update, onClosed(view | null) says the editor closed.
function SJUpdateDoc({ u, pageKey, stamp, editing, onSaved, onClosed }) {
  const Panel = window.PageNotesPanel;
  if (!Panel) return <div role="alert" style={{ fontSize: 13, color: 'var(--fail)' }}>The notes editor didn't load. Refresh to try again.</div>;
  const io = {
    async get() { return { status: 200, data: sjUpdateView(u) }; },
    async put(delta, baseId) {
      const res = await pnRequest('PUT', '/api/spot/note-updates/' + u.id, { delta, base_id: baseId });
      if (res && res.status === 200 && res.data) { onSaved(res.data); res.data = sjUpdateView(res.data); }
      else if (res && res.status === 409 && res.data && res.data.current) res.data = { ...res.data, current: sjUpdateView(res.data.current) };
      return res;
    },
  };
  return <div className="sj-update">
    <Panel page={pageKey} label={'Update from ' + stamp} variant="page" io={io} startInEdit={editing} onClosed={onClosed} />
  </div>;
}

// The composer of a new update: an empty note that is created, with the server's time, when it is saved. The first
// save is a POST and closes the composer (onAdded(update) puts the new update in the list, onClosed() removes the
// composer); Cancel and Esc go through the editor's own discard question.
function SJNewUpdate({ chain, contract_address, symbol, pageKey, onAdded, onClosed }) {
  const Panel = window.PageNotesPanel;
  if (!Panel) return <div role="alert" style={{ fontSize: 13, color: 'var(--fail)' }}>The notes editor didn't load. Refresh to try again.</div>;
  const io = {
    async get() { return { status: 200, data: { id: null, delta: null, text: '', saved_at: null, empty: true, legacy: false } }; },
    async put(delta) {
      const res = await pnRequest('POST', '/api/spot/note-updates', { chain, contract_address, delta });
      if (res && res.status === 201 && res.data) {
        onAdded(res.data);
        delete pnDrafts[pageKey];      // stored: this draft must never come back (the panel may be gone already, and then nothing else would close it)
        return { status: 200, data: sjUpdateView(res.data) };
      }
      return res;
    },
  };
  return <div className="sj-update">
    <div style={{ fontSize: 12, color: 'var(--text3)', marginBottom: 6 }}>It is stamped with the date and time when you save it.</div>
    <Panel page={pageKey} label={'New update for ' + symbol} variant="page" io={io} startInEdit={true} onClosed={() => onClosed()} />
  </div>;
}

// After an editor closes the journal's own button is back: give it the focus.
function sjFocusLater(attr, value) {
  let tries = 0;
  const timer = setInterval(() => {
    const el = document.querySelector('[' + attr + '="' + value + '"]');
    tries += 1;
    if (el) { el.focus(); clearInterval(timer); }
    else if (tries > 30) clearInterval(timer);      // the page re-draws first: wait for the button, for about 1.5 s
  }, 50);
}

// ── The journal ─────────────────────────────────────────────────────────────

// Props: row (a /api/spot/pnl row with a "chain address" position_key),
// updates (this position's updates, newest first), notesError (the updates
// list failed to load), onSummarySaved(key, note, delta) (Landing 88: the saved
// plain text and document), onUpdatesChanged(key, fn), scope (Landing 88: tells
// apart journals of one position shown together; History passes the trade),
// editing / setEditing(panelKey, open) (Landing 89: the page's map of open
// editors, keyed by each panel's draft key: the composer and every update
// being edited stay open across tab switches until the page reloads, as their
// drafts do).
function SpotJournal({ row, updates, notesError, onSummarySaved, onUpdatesChanged, editing, setEditing, scope }) {
  const key = row.position_key;
  // position_key is chain and contract_address joined by one literal space.
  // Split on the FIRST space and never change case (Solana addresses are case-sensitive).
  const sep = key.indexOf(' ');
  const chain = key.slice(0, sep);
  const contract_address = key.slice(sep + 1);
  const symbol = String(row.symbol || '').toUpperCase();
  const where = scope || 'open';
  const open = editing || {};
  const composeKey = 'spot-update-new:' + where + ':' + key;
  const composing = !!open[composeKey];

  const [confirmId, setConfirmId] = useSJState(null);
  const [deleteBusy, setDeleteBusy] = useSJState(false);
  const [deleteError, setDeleteError] = useSJState('');

  const failed = d => d === undefined || (d && d.error);

  function replaceUpdate(next) {
    onUpdatesChanged(key, list => list.map(x => x.id === next.id ? next : x));
  }

  async function deleteUpdate(u) {
    if (deleteBusy) return;
    // The Closed tab shows one update under every closed trade of its position: unsaved changes typed in another of
    // those views (a draft of 'spot-update:<scope>:<id>') would vanish with the update, so refuse until they are dealt with.
    const unsaved = Object.keys(pnDrafts).filter(k => k.indexOf('spot-update:') === 0 && k.slice(k.lastIndexOf(':') + 1) === String(u.id) && pnDrafts[k].dirty);
    if (unsaved.length) { setDeleteError('This update has unsaved changes open in another view. Save or discard them there first.'); return; }
    setDeleteBusy(true);
    try {
      const d = await api('/api/spot/note-updates/' + u.id, { method: 'DELETE' });
      if (failed(d)) setDeleteError(extractApiErrorMessage(d));
      else {
        setDeleteError('');
        setConfirmId(null);
        onUpdatesChanged(key, list => list.filter(x => x.id !== u.id));
      }
    } catch (err) { setDeleteError(extractApiErrorMessage(err)); }
    finally { setDeleteBusy(false); }
  }

  const errLine = msg => msg ? <div role="alert" style={{ color: 'var(--fail)', fontSize: 13 }}>{msg}</div> : null;
  const count = updates.length === 1 ? '1 update' : updates.length + ' updates';

  return <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
    {/* Summary (Landing 88: the Notes page editor) */}
    <SJSummary key={key} chain={chain} contract_address={contract_address} symbol={symbol} scope={scope}
      onSaved={(text, delta) => onSummarySaved(key, text, delta)} />

    {/* Updates */}
    <div className="spot-j75" style={{ borderTop: SJ_LINE_STRONG, paddingTop: 12, display: 'flex', alignItems: 'center',
                                       justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 10 }}>
        <span style={SJ_SECTION}>Updates</span>
        <span style={{ fontSize: 13, color: 'var(--text3)' }}>{notesError ? 'not loaded' : count}</span>
      </div>
      {!composing && <button type="button" className="tv-btn" style={SJ_SMALL_BTN} data-sj-add={composeKey}
        aria-label={'Add update for ' + symbol} onClick={() => setEditing(composeKey, true)}>+ Add update</button>}
    </div>
    {notesError && <div role="alert" style={{ color: 'var(--fail)', fontSize: 13 }}>Couldn't load the updates. Refresh to try again.</div>}
    {composing && <SJNewUpdate chain={chain} contract_address={contract_address} symbol={symbol} pageKey={composeKey}
      onAdded={added => { onUpdatesChanged(key, list => [added].concat(list)); setEditing(composeKey, false); }}
      onClosed={() => { setEditing(composeKey, false); sjFocusLater('data-sj-add', composeKey); }} />}
    {updates.map(u => {
      const at = sjParseTime(u.created_at);
      const edited = sjParseTime(u.edited_at);
      const pageKey = 'spot-update:' + where + ':' + u.id;
      const isEditing = !!open[pageKey];
      const confirming = confirmId === u.id;
      return <div key={u.id} className="spot-j75" style={{ display: 'flex', flexDirection: 'column', gap: 6, paddingTop: 10, borderTop: SJ_LINE }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, flexWrap: 'wrap' }}>
          <span style={{ fontFamily: "'Fira Code', monospace", fontSize: 13, fontWeight: 500, color: 'var(--text)' }}>{sjStamp(at)}</span>
          <span style={{ fontSize: 13, color: 'var(--text3)' }}>{sjAgo(at)}</span>
          {isFinite(edited) && <span style={{ fontSize: 13, color: 'var(--text3)' }} title={'Edited ' + sjStamp(edited)}>{'· edited ' + sjAgo(edited)}</span>}
          <span style={{ flex: 1 }} />
          {!isEditing && !confirming && <span style={{ display: 'inline-flex', gap: 6 }}>
            <button type="button" className="tv-btn" style={SJ_SMALL_BTN} aria-label={'Edit update from ' + sjStamp(at)} data-sj-edit={pageKey}
              onClick={() => { setConfirmId(null); setEditing(pageKey, true); }}>Edit</button>
            <button type="button" className="tv-btn danger" style={SJ_SMALL_BTN} aria-label={'Delete update from ' + sjStamp(at)}
              onClick={() => { setConfirmId(u.id); setDeleteError(''); }}>Delete</button>
          </span>}
        </div>
        {confirming && <div role="group" aria-label="Confirm delete" style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap',
                                    padding: '8px 10px', border: '1px solid var(--fail)', borderRadius: 8, background: 'var(--fail-soft)' }}>
          <span style={{ fontSize: 13, color: 'var(--text)' }}>Delete this update? It disappears from the journal; its text is kept in the history.</span>
          <button type="button" className="tv-btn danger" style={SJ_SMALL_BTN} disabled={deleteBusy} autoFocus
            onClick={() => deleteUpdate(u)}>{deleteBusy ? 'Deleting…' : 'Delete'}</button>
          <button type="button" className="tv-btn" style={SJ_SMALL_BTN} disabled={deleteBusy}
            onClick={() => { setConfirmId(null); setDeleteError(''); }}>Keep</button>
          {errLine(deleteError)}
        </div>}
        {isEditing || u.delta
          ? <SJUpdateDoc key={pageKey + (isEditing ? ':edit' : ':read:' + u.version)} u={u} pageKey={pageKey} stamp={sjStamp(at)} editing={isEditing}
              onSaved={replaceUpdate}
              onClosed={view => { if (view && view.row) replaceUpdate(view.row); setEditing(pageKey, false); sjFocusLater('data-sj-edit', pageKey); }} />
          : <SJNoteText text={u.body} />}
      </div>;
    })}
  </div>;
}

window.SpotJournal = SpotJournal;
window.SJNoteText = SJNoteText;
window.sjParseNote = sjParseNote;
window.sjToDelta = sjToDelta;
window.sjInline = sjInline;
window.sjPlain = sjPlain;
window.sjParseTime = sjParseTime;
window.sjStamp = sjStamp;
window.sjAgo = sjAgo;
window.sjShortAge = sjShortAge;
