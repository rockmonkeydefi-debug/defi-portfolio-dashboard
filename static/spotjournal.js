/* ===== SPOT NOTES JOURNAL — Landing 2a (HANDOFF_spot_perps_rebuild.md 3.1) =====
   One spot position's journal: an undated Summary (PUT /api/spot/position-notes)
   plus dated updates (/api/spot/note-updates, newest first). Spot only.

   Formatting is markdown-style markers, rendered as React elements (never raw
   HTML): **bold**, *italic*, and lines starting "- " (or "* " / "• ") as
   bullets. No numbered lists. A marker only counts when the opening one is not
   right after a letter, digit, underscore or "*", the closing one is not right
   before one, and the text inside does not start or end with a space - so
   2*3*4 and ***x*** stay plain text.

   Loaded before static/spotpnl.js (templates/index.html). Every top-level name
   here starts with sj / SJ / SpotJournal: Babel turns top-level declarations
   into shared globals, so a name used in another static/*.js file would be
   silently overwritten. */

const { useState: useSJState, useEffect: useSJEffect, useRef: useSJRef } = React;

const SJ_MAX = 2000;            // characters per Summary and per update (SPOT_NOTE_MAX on the server)
const SJ_PREVIEW_MAX = 300;     // ✎ hover preview, per part
const SJ_EDITOR_ROWS = 8;
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

// ── Editor ──────────────────────────────────────────────────────────────────

// The line range [start, end) around positions a..b of text.
function sjLineRange(text, a, b) {
  const start = text.lastIndexOf('\n', a - 1) + 1;
  let end = text.indexOf('\n', b);
  if (end === -1) end = text.length;
  return [start, end];
}

// Textarea with the B / I / • toolbar and a character counter. Keys:
// Ctrl/Cmd+B bold, Ctrl/Cmd+I italic, Ctrl/Cmd+Enter submit, Esc onEscape,
// Enter continues a bullet and Enter on an empty bullet ends the list.
// Edits go through execCommand('insertText') so Ctrl+Z still undoes them;
// where that is unavailable the value is set directly.
function SJEditor({ value, onChange, onSubmit, onEscape, label, placeholder, disabled }) {
  const ref = useSJRef(null);
  const pendingSel = useSJRef(null);

  useSJEffect(() => {
    const el = ref.current;
    if (el && pendingSel.current) {
      el.setSelectionRange(pendingSel.current[0], pendingSel.current[1]);
      pendingSel.current = null;
    }
  });

  // Replace [a, b) with text, then select [selA, selB).
  function replace(a, b, text, selA, selB) {
    const el = ref.current;
    if (!el || (a === b && text === '')) return;
    const cur = el.value;
    if (cur.length - (b - a) + text.length > SJ_MAX) return;   // would pass the limit: do nothing
    el.focus();
    el.setSelectionRange(a, b);
    let ok = false;
    try {
      ok = text === '' ? document.execCommand('delete', false) : document.execCommand('insertText', false, text);
    } catch (_e) { ok = false; }
    if (!ok || el.value === cur) {
      onChange(cur.slice(0, a) + text + cur.slice(b));
      pendingSel.current = [selA, selB];
      return;
    }
    el.setSelectionRange(selA, selB);
  }

  function wrap(marker) {
    const el = ref.current;
    if (!el || disabled) return;
    const a = el.selectionStart;
    const b = el.selectionEnd;
    const sel = el.value.slice(a, b);
    const n = marker.length;
    replace(a, b, marker + sel + marker, a + n, b + n);
  }

  function toggleBullets() {
    const el = ref.current;
    if (!el || disabled) return;
    const text = el.value;
    const caret = el.selectionStart;
    const collapsed = caret === el.selectionEnd;
    const [start, end] = sjLineRange(text, el.selectionStart, el.selectionEnd);
    const lines = text.slice(start, end).split('\n');
    const all = lines.every(l => SJ_BULLET_RE.test(l));
    const next = lines.map(l => {
      if (all) return l.replace(/^(\s*)[-•*]\s+/, '$1');
      return SJ_BULLET_RE.test(l) ? l : '- ' + l;
    }).join('\n');
    if (collapsed && lines.length === 1) {
      // One line, no selection: keep the caret where it was in the text.
      const pos = Math.max(start, caret + next.length - (end - start));
      replace(start, end, next, pos, pos);
    } else {
      replace(start, end, next, start, start + next.length);
    }
  }

  function onKeyDown(e) {
    if (e.nativeEvent && e.nativeEvent.isComposing) return;
    const mod = e.ctrlKey || e.metaKey;
    if (mod && e.key === 'Enter') { e.preventDefault(); if (onSubmit) onSubmit(); return; }
    if (e.key === 'Escape') { e.preventDefault(); if (onEscape) onEscape(); return; }
    if (mod && !e.shiftKey && !e.altKey && (e.key === 'b' || e.key === 'B')) { e.preventDefault(); wrap('**'); return; }
    if (mod && !e.shiftKey && !e.altKey && (e.key === 'i' || e.key === 'I')) { e.preventDefault(); wrap('*'); return; }
    if (e.key === 'Enter' && !mod && !e.shiftKey && !e.altKey) {
      const el = ref.current;
      const a = el.selectionStart;
      if (a !== el.selectionEnd) return;
      const text = el.value;
      const lineStart = text.lastIndexOf('\n', a - 1) + 1;
      let lineEnd = text.indexOf('\n', a);
      if (lineEnd === -1) lineEnd = text.length;
      const line = text.slice(lineStart, lineEnd);
      const bm = line.match(SJ_BULLET_RE);
      const bare = /^\s*[-•*]\s+$/.test(line);
      if (bare && a === lineEnd) {
        // Enter on an empty bullet ends the list: remove the marker.
        e.preventDefault();
        replace(lineStart, lineEnd, '', lineStart, lineStart);
        return;
      }
      if (bm && a > lineStart + bm[1].length + 1) {
        e.preventDefault();
        const insert = '\n' + bm[1] + bm[2] + ' ';
        replace(a, a, insert, a + insert.length, a + insert.length);
      }
    }
  }

  const tool = (txt, title, onClick, style) => <button type="button" className="tv-btn" title={title} aria-label={title}
    disabled={disabled} onMouseDown={e => e.preventDefault()} onClick={onClick}
    style={{ minWidth: 34, minHeight: 32, padding: '2px 10px', fontSize: 14, ...style }}>{txt}</button>;
  const len = value.length;
  const countColor = len >= SJ_MAX ? 'var(--fail)' : len >= SJ_MAX - 100 ? 'var(--warn)' : 'var(--text3)';

  return <div className="spot-j75" style={{ display: 'flex', flexDirection: 'column', gap: 6, width: '100%' }}>
    <div role="toolbar" aria-label={'Formatting for ' + label} style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
      {tool('B', 'Bold (Ctrl+B)', () => wrap('**'), { fontWeight: 700 })}
      {tool('I', 'Italic (Ctrl+I)', () => wrap('*'), { fontStyle: 'italic', fontFamily: 'Georgia, serif' })}
      {tool('•', 'Bullet list', toggleBullets)}
      <span style={{ flex: 1 }} />
      <span aria-live="polite" style={{ fontSize: 12, color: countColor }}>{len + ' / ' + SJ_MAX}</span>
    </div>
    <textarea ref={ref} className="tv-input" rows={SJ_EDITOR_ROWS} maxLength={SJ_MAX} value={value} autoFocus
      aria-label={label} placeholder={placeholder} disabled={disabled}
      onChange={e => onChange(e.target.value)} onKeyDown={onKeyDown}
      style={{ fontSize: 14, lineHeight: '21px', resize: 'vertical', fontFamily: 'inherit', display: 'block' }} />
  </div>;
}

// ── The journal ─────────────────────────────────────────────────────────────

function sjTrimEnd(s) { return String(s || '').replace(/\s+$/, ''); }

// Props: row (a /api/spot/pnl row with a "chain address" position_key),
// updates (this position's updates, newest first), notesError (the updates
// list failed to load), onSummarySaved(key, note), onUpdatesChanged(key, fn),
// draft / onDraftChange (the composer draft, kept by the page until reload),
// composing / setComposing (composer open, kept by the page).
function SpotJournal({ row, updates, notesError, onSummarySaved, onUpdatesChanged, draft, onDraftChange,
                       composing, setComposing }) {
  const key = row.position_key;
  // position_key is chain and contract_address joined by one literal space.
  // Split on the FIRST space and never change case (Solana addresses are case-sensitive).
  const sep = key.indexOf(' ');
  const chain = key.slice(0, sep);
  const contract_address = key.slice(sep + 1);
  const symbol = String(row.symbol || '').toUpperCase();
  const summary = row.note || '';

  const [sumEditing, setSumEditing] = useSJState(false);
  const [sumDraft, setSumDraft] = useSJState('');
  const [sumBusy, setSumBusy] = useSJState(false);
  const [sumError, setSumError] = useSJState('');
  const [addBusy, setAddBusy] = useSJState(false);
  const [addError, setAddError] = useSJState('');
  const [editId, setEditId] = useSJState(null);
  const [editDraft, setEditDraft] = useSJState('');
  const [editBusy, setEditBusy] = useSJState(false);
  const [editError, setEditError] = useSJState('');
  const [confirmId, setConfirmId] = useSJState(null);
  const [deleteBusy, setDeleteBusy] = useSJState(false);
  const [deleteError, setDeleteError] = useSJState('');

  const failed = d => d === undefined || (d && d.error);

  async function saveSummary() {
    if (sumBusy) return;
    const note = sjTrimEnd(sumDraft);
    if (note === summary) { setSumEditing(false); setSumError(''); return; }
    setSumBusy(true);
    try {
      const d = await api('/api/spot/position-notes', { method: 'PUT', body: JSON.stringify({ chain, contract_address, note }) });
      if (failed(d)) setSumError(extractApiErrorMessage(d));
      else { setSumError(''); setSumEditing(false); onSummarySaved(key, note); }
    } catch (err) { setSumError(extractApiErrorMessage(err)); }
    finally { setSumBusy(false); }
  }

  async function addUpdate() {
    const body = sjTrimEnd(draft);
    if (addBusy || !body.trim()) return;
    setAddBusy(true);
    try {
      const d = await api('/api/spot/note-updates', { method: 'POST', body: JSON.stringify({ chain, contract_address, body }) });
      if (failed(d)) setAddError(extractApiErrorMessage(d));
      else {
        setAddError('');
        onUpdatesChanged(key, list => [d].concat(list));
        onDraftChange('');
        setComposing(false);
      }
    } catch (err) { setAddError(extractApiErrorMessage(err)); }
    finally { setAddBusy(false); }
  }

  async function saveEdit(u) {
    const body = sjTrimEnd(editDraft);
    if (editBusy || !body.trim()) return;
    if (body === u.body) { setEditId(null); setEditError(''); return; }
    setEditBusy(true);
    try {
      const d = await api('/api/spot/note-updates/' + u.id, { method: 'PUT', body: JSON.stringify({ body }) });
      if (failed(d)) setEditError(extractApiErrorMessage(d));
      else {
        setEditError('');
        setEditId(null);
        onUpdatesChanged(key, list => list.map(x => x.id === u.id ? d : x));
      }
    } catch (err) { setEditError(extractApiErrorMessage(err)); }
    finally { setEditBusy(false); }
  }

  async function deleteUpdate(u) {
    if (deleteBusy) return;
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
    {/* Summary */}
    <div className="spot-j75" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12 }}>
      <span style={SJ_SECTION}>Summary</span>
      {!sumEditing && <button type="button" className="tv-btn" style={SJ_SMALL_BTN}
        aria-label={'Edit summary for ' + symbol}
        onClick={() => { setSumDraft(summary); setSumError(''); setSumEditing(true); }}>Edit</button>}
    </div>
    {sumEditing ? <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        <SJEditor value={sumDraft} onChange={setSumDraft} onSubmit={saveSummary}
          onEscape={() => { setSumEditing(false); setSumError(''); }}
          label={'Summary for ' + symbol} disabled={sumBusy}
          placeholder="What doesn't change day to day: where it's held, why you own it." />
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
          <button type="button" className="tv-btn primary" style={SJ_SMALL_BTN}
            disabled={sumBusy || sjTrimEnd(sumDraft) === summary} onClick={saveSummary}>{sumBusy ? 'Saving…' : 'Save'}</button>
          <button type="button" className="tv-btn" style={SJ_SMALL_BTN} disabled={sumBusy}
            onClick={() => { setSumEditing(false); setSumError(''); }}>Cancel</button>
          <span style={{ fontSize: 12, color: 'var(--text3)' }}>Ctrl+Enter to save · Esc to cancel</span>
        </div>
        {errLine(sumError)}
      </div>
      : summary.trim()
        ? <div className="spot-j75"><SJNoteText text={summary} /></div>
        : <div style={{ fontSize: 13, color: 'var(--text3)' }}>No summary yet. Use it for what doesn't change day to day: where it's held, why you own it.</div>}

    {/* Updates */}
    <div className="spot-j75" style={{ borderTop: SJ_LINE_STRONG, paddingTop: 12, display: 'flex', alignItems: 'center',
                                       justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 10 }}>
        <span style={SJ_SECTION}>Updates</span>
        <span style={{ fontSize: 13, color: 'var(--text3)' }}>{notesError ? 'not loaded' : count}</span>
      </div>
      {!composing && <button type="button" className="tv-btn" style={SJ_SMALL_BTN}
        aria-label={'Add update for ' + symbol} onClick={() => { setAddError(''); setComposing(true); }}>+ Add update</button>}
    </div>
    {notesError && <div role="alert" style={{ color: 'var(--fail)', fontSize: 13 }}>Couldn't load the updates. Refresh to try again.</div>}
    {composing && <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <SJEditor value={draft} onChange={onDraftChange} onSubmit={addUpdate} onEscape={() => setComposing(false)}
        label={'New update for ' + symbol} disabled={addBusy}
        placeholder="Add an update. It is stamped with today's date and time when you add it." />
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <button type="button" className="tv-btn primary" style={SJ_SMALL_BTN} disabled={addBusy || !draft.trim()}
          onClick={addUpdate}>{addBusy ? 'Adding…' : 'Add update'}</button>
        <button type="button" className="tv-btn" style={SJ_SMALL_BTN} disabled={addBusy}
          onClick={() => setComposing(false)}>Cancel</button>
        <span style={{ fontSize: 12, color: 'var(--text3)' }}>Cancel and Esc keep your draft until you add it · Ctrl+Enter to add</span>
      </div>
      {errLine(addError)}
    </div>}
    {updates.map(u => {
      const at = sjParseTime(u.created_at);
      const edited = sjParseTime(u.edited_at);
      const editing = editId === u.id;
      const confirming = confirmId === u.id;
      return <div key={u.id} className="spot-j75" style={{ display: 'flex', flexDirection: 'column', gap: 6, paddingTop: 10, borderTop: SJ_LINE }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, flexWrap: 'wrap' }}>
          <span style={{ fontFamily: "'Fira Code', monospace", fontSize: 13, fontWeight: 500, color: 'var(--text)' }}>{sjStamp(at)}</span>
          <span style={{ fontSize: 13, color: 'var(--text3)' }}>{sjAgo(at)}</span>
          {isFinite(edited) && <span style={{ fontSize: 13, color: 'var(--text3)' }} title={'Edited ' + sjStamp(edited)}>{'· edited ' + sjAgo(edited)}</span>}
          <span style={{ flex: 1 }} />
          {!editing && !confirming && <span style={{ display: 'inline-flex', gap: 6 }}>
            <button type="button" className="tv-btn" style={SJ_SMALL_BTN} aria-label={'Edit update from ' + sjStamp(at)}
              onClick={() => { setEditId(u.id); setEditDraft(u.body); setEditError(''); setConfirmId(null); }}>Edit</button>
            <button type="button" className="tv-btn danger" style={SJ_SMALL_BTN} aria-label={'Delete update from ' + sjStamp(at)}
              onClick={() => { setConfirmId(u.id); setDeleteError(''); setEditId(null); }}>Delete</button>
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
        {editing ? <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <SJEditor value={editDraft} onChange={setEditDraft} onSubmit={() => saveEdit(u)}
              onEscape={() => { setEditId(null); setEditError(''); }}
              label={'Edit update from ' + sjStamp(at)} disabled={editBusy} />
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
              <button type="button" className="tv-btn primary" style={SJ_SMALL_BTN}
                disabled={editBusy || !editDraft.trim() || sjTrimEnd(editDraft) === u.body}
                onClick={() => saveEdit(u)}>{editBusy ? 'Saving…' : 'Save'}</button>
              <button type="button" className="tv-btn" style={SJ_SMALL_BTN} disabled={editBusy}
                onClick={() => { setEditId(null); setEditError(''); }}>Cancel</button>
              <span style={{ fontSize: 12, color: 'var(--text3)' }}>Ctrl+Enter to save · Esc to cancel</span>
            </div>
            {errLine(editError)}
          </div>
          : <SJNoteText text={u.body} />}
      </div>;
    })}
  </div>;
}

window.SpotJournal = SpotJournal;
window.SJNoteText = SJNoteText;
window.sjParseNote = sjParseNote;
window.sjInline = sjInline;
window.sjPlain = sjPlain;
window.sjParseTime = sjParseTime;
window.sjStamp = sjStamp;
window.sjAgo = sjAgo;
window.sjShortAge = sjShortAge;
