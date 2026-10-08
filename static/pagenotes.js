/* ===== PAGE NOTES — Landing 19 =====
   A formatted notes box at the top of a page (the Spot page today), saved
   through GET / PUT /api/page-notes/<page> (web_portfolio.py, append-only
   page_notes table: every saved version is kept).

   - Read view: the saved document (a Quill Delta, {"ops": [...]}) is turned
     into React elements here (pnLines / PageNotesRead), never into HTML, so
     it shows fully formatted even when the editor library can't load.
   - Editing: Quill 2.0.3 (BSD-3), loaded from unpkg only when Edit is first
     clicked (pnLoadQuill). Formats are limited to PN_FORMATS, colours to the
     two palettes below (readable on the dark theme); pasted text keeps bold,
     lists and links but drops its colours. pnCleanDelta repeats the
     server's rules before a save; the server (_page_note_check) is the gate.
   - A save carries the id of the version the edit started from; the server
     answers 409 when another tab saved since, and the panel offers "Save mine
     over it" or "Discard mine".
   - Unsaved edits live in pnDrafts until the page reloads, so they survive a
     tab change, leaving the page, and Hide values.
   - Hide values hides the whole note (a free-form note can't be masked
     piece by piece).
   - Tables come from Quill's table module: each cell is one line whose line
     break carries {"table": "<row id>"}, shared by the cells of one row. The
     Table button inserts one (rows x columns picked in the panel); while the
     cursor is in a table, a table bar adds or deletes rows and columns, and
     line formats (heading, lists, indent, quote) are refused there because
     they would break the table. Row ids are renumbered row-1, row-2, ... on
     save (pasted tables arrive with numeric ids).

   Loaded before static/spotpnl.js (templates/index.html). Every top-level name
   here starts with pn / PN / PageNotes: Babel turns top-level declarations
   into shared globals, so a name used in another static/*.js file would be
   silently overwritten. */

const { useState: usePNState, useEffect: usePNEffect, useRef: usePNRef, useLayoutEffect: usePNLayoutEffect } = React;

const PN_QUILL_JS = 'https://unpkg.com/quill@2.0.3/dist/quill.js';
const PN_QUILL_CSS = 'https://unpkg.com/quill@2.0.3/dist/quill.snow.css';
const PN_QUILL_TIMEOUT_MS = 20000;
const PN_TEXT_MAX = 10000;                 // PAGE_NOTE_TEXT_MAX on the server
const PN_TEXT_WARN = 9000;
const PN_LINE_PX = 22;                     // read view line height
const PN_READ_LINES = 5;                   // lines shown before "Show all"
const PN_INDENT_MAX = 8;                   // PAGE_NOTE_INDENT_MAX
const PN_HEADERS = [1, 2, 3];
const PN_LISTS = ['bullet', 'ordered', 'checked', 'unchecked'];
const PN_FORMATS = ['header', 'bold', 'italic', 'underline', 'strike', 'color', 'background',
                    'list', 'indent', 'blockquote', 'link', 'table'];
const PN_TABLE_MAX_ROWS = 30;              // the insert form's limits (more rows can be added after)
const PN_TABLE_MAX_COLS = 10;
// [value, name]: text colours and highlights, all readable on the dark theme
// (text colours at least 4.8:1 on the panel; white text at least 8.5:1 on
// every highlight). false = the default (no colour / no highlight).
const PN_TEXT_COLOURS = [[false, 'Default'], ['#c9d1d9', 'Light grey'], ['#ff8a8a', 'Red'], ['#ffb52e', 'Amber'],
  ['#ffd23f', 'Yellow'], ['#4fdd8e', 'Green'], ['#5ee6e6', 'Cyan'], ['#8cc8ff', 'Blue'], ['#c9a6ff', 'Purple'],
  ['#ff9bd2', 'Pink']];
const PN_HIGHLIGHTS = [[false, 'No highlight'], ['#6b2121', 'Red'], ['#5e4a0c', 'Amber'], ['#1b5435', 'Green'],
  ['#0f5555', 'Teal'], ['#4b2a70', 'Purple'], ['#3d4a59', 'Grey']];
const PN_TOOLBAR = [
  [{ header: [1, 2, 3, false] }],
  ['bold', 'italic', 'underline', 'strike'],
  [{ color: PN_TEXT_COLOURS.map(c => c[0]) }, { background: PN_HIGHLIGHTS.map(c => c[0]) }],
  [{ list: 'bullet' }, { list: 'ordered' }, { list: 'check' }, { indent: '-1' }, { indent: '+1' }],
  ['blockquote', 'link', 'table'],
  ['clean'],
];
const PN_BUTTON_LABELS = {
  bold: 'Bold (Ctrl+B)', italic: 'Italic (Ctrl+I)', underline: 'Underline (Ctrl+U)', strike: 'Strikethrough',
  blockquote: 'Quote', link: 'Link (Ctrl+K)', clean: 'Clear formatting', table: 'Insert table',
  'list:bullet': 'Bulleted list', 'list:ordered': 'Numbered list', 'list:check': 'Checklist',
  'indent:-1': 'Decrease indent', 'indent:+1': 'Increase indent',
};
const PN_LINK_RE = /^(?:https?:\/\/|mailto:)[^\s\x00-\x1f\x7f]+$/i;
const PN_SCHEME_RE = /^[a-z][a-z0-9+.-]*:/i;
const PN_HEX_RE = /^#[0-9a-f]{6}$/i;
const PN_INLINE = ['bold', 'italic', 'underline', 'strike', 'color', 'background', 'link'];
const PN_ROW_RE = /^row-[a-z0-9]{1,16}$/;
const PN_ORDER_STYLES = ['decimal', 'lower-alpha', 'lower-roman'];

// page -> {delta, baseId, dirty}: the edit in progress, kept until the page reloads.
const pnDrafts = {};
let pnQuillPromise = null;

// ── Quill, loaded on first use ─────────────────────────────────────────────

function pnLoadQuill() {
  if (window.Quill) return Promise.resolve(window.Quill);
  if (pnQuillPromise) return pnQuillPromise;
  pnQuillPromise = new Promise((resolve, reject) => {
    if (!document.querySelector('link[data-pn-quill]')) {
      const css = document.createElement('link');
      css.rel = 'stylesheet';
      css.href = PN_QUILL_CSS;
      css.setAttribute('data-pn-quill', '1');
      document.head.appendChild(css);
    }
    const s = document.createElement('script');
    s.src = PN_QUILL_JS;
    s.async = true;
    s.setAttribute('data-pn-quill', '1');
    let done = false;
    const fail = () => {
      if (done) return;
      done = true;
      clearTimeout(timer);
      s.remove();
      pnQuillPromise = null;          // a later Try again loads it afresh
      reject(new Error('The editor could not load'));
    };
    const timer = setTimeout(fail, PN_QUILL_TIMEOUT_MS);
    s.onload = () => {
      if (done) return;
      if (!window.Quill) { fail(); return; }
      done = true;
      clearTimeout(timer);
      resolve(window.Quill);
    };
    s.onerror = fail;
    document.head.appendChild(s);
  });
  return pnQuillPromise;
}

// ── The document ────────────────────────────────────────────────────────────

// A link as the server accepts it, or null: "example.com" becomes
// "https://example.com"; other schemes (javascript:, tel:, ...) are dropped.
function pnCleanLink(v) {
  if (typeof v !== 'string') return null;
  let s = v.trim();
  if (!s) return null;
  if (!PN_SCHEME_RE.test(s)) s = 'https://' + s.replace(/^\/+/, '');
  return PN_LINK_RE.test(s) && s.length <= 2000 ? s : null;
}

// The editor's document cut down to what the server accepts (the same rules
// as _page_note_check): text inserts only, the allowed formats with valid
// values, line formats only on line breaks, no empty attribute objects. A
// table cell keeps no other line format, and row ids are renumbered row-1,
// row-2, ... in order (a new row starts wherever the id changes or the line
// before was not a cell), so a pasted table's numeric ids are saved too.
function pnCleanDelta(delta) {
  const ops = [];
  let rows = 0;
  let prevCellRow = null;        // the source row id of the line before, when it was a table cell
  for (const op of (delta && Array.isArray(delta.ops) ? delta.ops : [])) {
    if (!op || typeof op.insert !== 'string' || op.insert === '') continue;
    const lineBreaks = op.insert.replace(/\n/g, '') === '';
    const a = op.attributes || {};
    const clean = {};
    for (const k of ['bold', 'italic', 'underline', 'strike']) if (a[k] === true) clean[k] = true;
    for (const k of ['color', 'background']) if (typeof a[k] === 'string' && PN_HEX_RE.test(a[k])) clean[k] = a[k].toLowerCase();
    const link = a.link != null ? pnCleanLink(a.link) : null;
    if (link) clean.link = link;
    if (lineBreaks) {
      const cell = (typeof a.table === 'string' && a.table !== '') || typeof a.table === 'number' ? String(a.table) : null;
      if (cell) {
        if (cell !== prevCellRow) rows += 1;
        clean.table = 'row-' + rows.toString(36);
        prevCellRow = cell;
      } else {
        if (PN_HEADERS.includes(a.header)) clean.header = a.header;
        if (PN_LISTS.includes(a.list)) clean.list = a.list;
        if (Number.isInteger(a.indent) && a.indent >= 1 && a.indent <= PN_INDENT_MAX) clean.indent = a.indent;
        if (a.blockquote === true) clean.blockquote = true;
        prevCellRow = null;
      }
    } else if (op.insert.includes('\n')) {
      prevCellRow = null;        // a plain line ended inside this text
    }
    ops.push(Object.keys(clean).length ? { insert: op.insert, attributes: clean } : { insert: op.insert });
  }
  if (!ops.length) ops.push({ insert: '\n' });
  return { ops };
}

// The plain text the server counts: inserts joined, trailing line breaks removed;
// characters counted as the server does (code points, not UTF-16 units).
function pnTextLength(delta) {
  const text = (delta && Array.isArray(delta.ops) ? delta.ops : [])
    .map(op => (typeof op.insert === 'string' ? op.insert : '')).join('').replace(/\n+$/, '');
  return Array.from(text).length;
}

// The document as lines: [{segs: [{t, a}], a}] - each line's own attributes
// are those of the line break that ends it (where Quill keeps line formats).
function pnLines(delta) {
  const lines = [];
  let segs = [];
  for (const op of (delta && Array.isArray(delta.ops) ? delta.ops : [])) {
    if (!op || typeof op.insert !== 'string') continue;
    const attrs = op.attributes || {};
    const parts = op.insert.split('\n');
    parts.forEach((part, i) => {
      if (part) segs.push({ t: part, a: attrs });
      if (i < parts.length - 1) { lines.push({ segs, a: attrs }); segs = []; }
    });
  }
  if (segs.length) lines.push({ segs, a: {} });
  return lines;
}

function pnOrderLabel(n, level) {
  const style = PN_ORDER_STYLES[level % 3];
  if (style === 'decimal') return n + '.';
  if (style === 'lower-alpha') {
    let s = '';
    for (let x = n; x > 0; x = Math.floor((x - 1) / 26)) s = String.fromCharCode(97 + ((x - 1) % 26)) + s;
    return s + '.';
  }
  const romans = [[1000, 'm'], [900, 'cm'], [500, 'd'], [400, 'cd'], [100, 'c'], [90, 'xc'], [50, 'l'], [40, 'xl'],
                  [10, 'x'], [9, 'ix'], [5, 'v'], [4, 'iv'], [1, 'i']];
  let s = '';
  let x = n;
  for (const [v, r] of romans) while (x >= v) { s += r; x -= v; }
  return s + '.';
}

function pnSegment(seg, key) {
  const a = seg.a || {};
  const style = {};
  if (a.bold === true) style.fontWeight = 700;
  if (a.italic === true) style.fontStyle = 'italic';
  const deco = [a.underline === true && 'underline', a.strike === true && 'line-through'].filter(Boolean).join(' ');
  if (deco) style.textDecoration = deco;
  if (typeof a.color === 'string' && PN_HEX_RE.test(a.color)) style.color = a.color;
  if (typeof a.background === 'string' && PN_HEX_RE.test(a.background)) style.backgroundColor = a.background;
  const link = typeof a.link === 'string' && PN_LINK_RE.test(a.link) ? a.link : null;
  if (link) {
    return <a key={key} className="pn-link" href={link} target="_blank" rel="noopener noreferrer" style={style}>{seg.t}</a>;
  }
  return <span key={key} style={style}>{seg.t}</span>;
}

function pnCellContent(segs) {
  return segs.length ? segs.map((sg, j) => pnSegment(sg, j)) : <br />;
}

// The saved document as React elements (never HTML). Ordered lists number
// per indent level the way Quill does: a line that is not a list item ends
// the list; an item resets the numbering of deeper levels. Consecutive table
// cells form one table; a new row starts where the row id changes. Short
// rows are padded with empty cells.
function PageNotesRead({ delta }) {
  const counters = [];
  const out = [];
  let table = null;              // {rows: [{id, cells: [segs]}]}
  const flush = () => {
    if (!table) return;
    const cols = Math.max(...table.rows.map(r => r.cells.length));
    out.push(<table key={'t' + out.length} className="pn-table"><tbody>
      {table.rows.map((r, ri) => <tr key={ri}>
        {Array.from({ length: cols }, (_, ci) => <td key={ci}>{pnCellContent(r.cells[ci] || [])}</td>)}
      </tr>)}
    </tbody></table>);
    table = null;
  };
  // Empty plain lines at the end (Quill always ends a document with a line
  // break, and a table inserted after text leaves one below it) aren't shown.
  const lines = pnLines(delta);
  while (lines.length) {
    const last = lines[lines.length - 1];
    const la = last.a || {};
    if (last.segs.length || la.table || la.list || la.header || la.blockquote) break;
    lines.pop();
  }
  lines.forEach((ln, i) => {
    const a = ln.a || {};
    const cell = typeof a.table === 'string' && PN_ROW_RE.test(a.table) ? a.table : null;
    if (cell) {
      counters.length = 0;
      if (!table) table = { rows: [] };
      const last = table.rows[table.rows.length - 1];
      if (last && last.id === cell) last.cells.push(ln.segs);
      else table.rows.push({ id: cell, cells: [ln.segs] });
      return;
    }
    flush();
    const indent = Number.isInteger(a.indent) && a.indent >= 1 && a.indent <= PN_INDENT_MAX ? a.indent : 0;
    const list = PN_LISTS.includes(a.list) ? a.list : null;
    const header = PN_HEADERS.includes(a.header) ? a.header : null;
    let marker = null;
    if (list) {
      counters.length = Math.min(counters.length, indent + 1);
      if (list === 'ordered') {
        counters[indent] = (counters[indent] || 0) + 1;
        marker = pnOrderLabel(counters[indent], indent);
      } else {
        marker = list === 'bullet' ? '\u2022' : list === 'checked' ? '\u2611' : '\u2610';
      }
    } else {
      counters.length = 0;
    }
    const cls = ['pn-line', header ? 'pn-h' + header : '', a.blockquote === true ? 'pn-quote' : '', list ? 'pn-li' : '']
      .filter(Boolean).join(' ');
    // Quill's indents: a list item's text starts 3em in (+3em per level), a plain line 3em per level.
    const pad = list ? (indent * 3 + 3) + 'em' : indent ? indent * 3 + 'em' : undefined;
    out.push(<div key={i} className={cls} style={pad ? { paddingLeft: pad } : undefined}>
      {marker && <span className="pn-marker" aria-hidden={list === 'bullet' ? 'true' : undefined}
        aria-label={list === 'checked' ? 'Done:' : list === 'unchecked' ? 'To do:' : undefined}>{marker}</span>}
      {pnCellContent(ln.segs)}
    </div>);
  });
  flush();
  return out;
}

// True when the range (or the cursor) touches a table cell.
function pnRangeInTable(quill, range) {
  if (!quill || !range) return false;
  return quill.getLines(range.index, Math.max(range.length, 1)).some(l => l && l.statics && l.statics.blotName === 'table');
}

// ── Requests ────────────────────────────────────────────────────────────────

// {status, data} (status 0 when the request failed); null after a 401 (the
// page goes to the login screen, as api() does).
async function pnRequest(method, path, body) {
  let res;
  try {
    res = await fetch(path, { method, headers: { 'Content-Type': 'application/json' },
                              body: body === undefined ? undefined : JSON.stringify(body) });
  } catch (e) {
    return { status: 0, data: null };
  }
  if (res.status === 401) { window.location.href = '/login'; return null; }
  let data = null;
  try { data = await res.json(); } catch (e) { /* not JSON */ }
  return { status: res.status, data };
}

function pnSavedLabel(iso) {
  const ms = Date.parse(iso || '');
  if (isNaN(ms)) return null;
  const d = new Date(ms);
  const opts = { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' };
  if (d.getFullYear() !== new Date().getFullYear()) opts.year = 'numeric';
  return d.toLocaleString('en-US', opts);
}

function pnReadExpanded(page) {
  try { return localStorage.getItem('pageNotesExpanded:' + page) === '1'; } catch (e) { return false; }
}

function pnWriteExpanded(page, v) {
  try { localStorage.setItem('pageNotesExpanded:' + page, v ? '1' : '0'); } catch (e) { /* the toggle still works */ }
}

// Names on the toolbar's buttons and pickers (Quill gives them bare format names).
function pnLabelToolbar(toolbar) {
  if (!toolbar) return;
  toolbar.querySelectorAll('button').forEach(b => {
    const fmt = Array.from(b.classList).find(c => c.startsWith('ql-'));
    if (!fmt) return;
    const name = fmt.slice(3);
    const label = PN_BUTTON_LABELS[b.value ? name + ':' + b.value : name] || PN_BUTTON_LABELS[name];
    if (label) { b.setAttribute('title', label); b.setAttribute('aria-label', label); }
  });
  const pickers = [['.ql-header', 'Text style', null], ['.ql-color', 'Text colour', PN_TEXT_COLOURS],
                   ['.ql-background', 'Highlight colour', PN_HIGHLIGHTS]];
  for (const [sel, label, palette] of pickers) {
    const picker = toolbar.querySelector('.ql-picker' + sel);
    if (!picker) continue;
    const lab = picker.querySelector('.ql-picker-label');
    if (lab) { lab.setAttribute('title', label); lab.setAttribute('aria-label', label); }
    picker.querySelectorAll('.ql-picker-item').forEach(item => {
      const v = item.getAttribute('data-value');
      let name;
      if (palette) {
        const hit = palette.find(c => (c[0] || null) === (v || null));
        name = label + ': ' + (hit ? hit[1] : v);
      } else {
        name = v ? 'Heading ' + v : 'Normal text';
      }
      item.setAttribute('title', name);
      item.setAttribute('aria-label', name);
    });
  }
}

// ── The panel ───────────────────────────────────────────────────────────────

function PageNotesPanel({ page, hideValues, label }) {
  const [load, setLoad] = usePNState({ status: 'loading', error: false });
  const [note, setNote] = usePNState(null);
  const [mode, setMode] = usePNState(() => (pnDrafts[page] ? 'edit' : 'read'));
  const [restored, setRestored] = usePNState(() => !!(pnDrafts[page] && pnDrafts[page].dirty));
  const [quillState, setQuillState] = usePNState('idle');      // idle | loading | ready | failed
  const [saving, setSaving] = usePNState(false);
  const [error, setError] = usePNState('');
  const [conflict, setConflict] = usePNState(null);
  const [confirmDiscard, setConfirmDiscard] = usePNState(false);
  const [count, setCount] = usePNState(0);
  const [dirty, setDirty] = usePNState(() => !!(pnDrafts[page] && pnDrafts[page].dirty));
  const [expanded, setExpanded] = usePNState(() => pnReadExpanded(page));
  const [tall, setTall] = usePNState(false);
  const [inTable, setInTable] = usePNState(false);             // the cursor is in a table cell
  const [tableForm, setTableForm] = usePNState(null);          // null | {rows, cols}: the insert form
  const [hint, setHint] = usePNState('');
  const hostRef = usePNRef(null);
  const lastRangeRef = usePNRef(null);                         // the editor's last selection (kept while it is blurred)
  const rowsInputRef = usePNRef(null);
  const quillRef = usePNRef(null);
  const readRef = usePNRef(null);
  const editBtnRef = usePNRef(null);
  const saveRef = usePNRef(() => {});
  const noteRef = usePNRef(null);
  noteRef.current = note;

  function loadNote() {
    setLoad(prev => ({ ...prev, status: prev.status === 'ok' ? 'ok' : 'loading', error: false }));
    pnRequest('GET', '/api/page-notes/' + page).then(res => {
      if (!res) return;
      if (res.status === 200 && res.data) { setNote(res.data); setLoad({ status: 'ok', error: false }); }
      else setLoad(prev => ({ status: prev.status === 'ok' ? 'ok' : 'error', error: true }));
    });
  }
  usePNEffect(loadNote, [page]);

  // The editor: load Quill when edit mode opens.
  usePNEffect(() => {
    if (mode !== 'edit' || quillState !== 'idle') return;
    setQuillState('loading');
    pnLoadQuill().then(() => setQuillState('ready')).catch(() => setQuillState('failed'));
  }, [mode, quillState]);

  // Build the editor once Quill is ready, the note is loaded, and values are shown.
  const editorOpen = mode === 'edit' && !hideValues && quillState === 'ready' && load.status === 'ok';
  usePNEffect(() => {
    if (!editorOpen || !hostRef.current) return undefined;
    const host = hostRef.current;
    const el = document.createElement('div');
    host.appendChild(el);
    const Quill = window.Quill;
    const draft = pnDrafts[page];
    const start = draft ? draft.delta : (noteRef.current && noteRef.current.delta) || { ops: [{ insert: '\n' }] };
    if (!draft) pnDrafts[page] = { delta: start, baseId: noteRef.current ? noteRef.current.id : null, dirty: false };
    // Toolbar handlers: the line formats are refused inside a table (they
    // would turn its cells into ordinary lines), Clear formatting keeps the
    // table, and Table opens the insert form.
    const refuse = what => setHint(what + " can't go inside a table. Put the cursor outside the table first.");
    const handlers = {
      header(value) {
        const q = this.quill;
        if (pnRangeInTable(q, q.getSelection())) { refuse('Headings'); return; }
        q.format('header', value, 'user');
      },
      blockquote(value) {
        const q = this.quill;
        if (pnRangeInTable(q, q.getSelection())) { refuse('Quotes'); return; }
        q.format('blockquote', value, 'user');
      },
      list(value) {
        const q = this.quill;
        const range = q.getSelection();
        if (pnRangeInTable(q, range)) { refuse('Lists'); return; }
        const formats = q.getFormat(range);
        if (value === 'check') {
          q.format('list', formats.list === 'checked' || formats.list === 'unchecked' ? false : 'unchecked', 'user');
        } else {
          q.format('list', value, 'user');
        }
      },
      indent(value) {
        const q = this.quill;
        const range = q.getSelection();
        if (pnRangeInTable(q, range)) { refuse('Indents'); return; }
        const level = parseInt(q.getFormat(range).indent || 0, 10);
        if (value === '+1' || value === '-1') q.format('indent', level + (value === '+1' ? 1 : -1), 'user');
      },
      clean() {
        const q = this.quill;
        const range = q.getSelection();
        if (range == null) return;
        if (range.length === 0) {
          PN_INLINE.forEach(k => { if (q.getFormat()[k] != null) q.format(k, false, 'user'); });
        } else if (pnRangeInTable(q, range)) {
          PN_INLINE.forEach(k => q.formatText(range.index, range.length, k, false, 'user'));
        } else {
          q.removeFormat(range.index, range.length, 'user');
        }
      },
      table() {
        const q = this.quill;
        if (pnRangeInTable(q, q.getSelection())) {
          setHint("A table can't go inside a table. Use the table bar below the editor to add rows or columns.");
          return;
        }
        setHint('');
        setTableForm({ rows: '3', cols: '3' });
      },
    };
    const quill = new Quill(el, {
      theme: 'snow',
      formats: PN_FORMATS,
      placeholder: 'Write your notes. Select text to format it; Ctrl+Enter saves.',
      modules: {
        toolbar: { container: PN_TOOLBAR, handlers },
        table: true,
        keyboard: { bindings: { pnSave: { key: 'Enter', shortKey: true, handler: () => { saveRef.current(); return false; } } } },
      },
    });
    // Pasted text keeps its bold, lists and links but not its colours (web
    // pages are usually dark text on white, unreadable on this theme).
    quill.clipboard.addMatcher(Node.ELEMENT_NODE, (node, delta) => {
      delta.ops.forEach(op => {
        if (op.attributes) { delete op.attributes.color; delete op.attributes.background; }
      });
      return delta;
    });
    quill.setContents(start, 'silent');
    quill.history.clear();
    pnLabelToolbar(host.querySelector('.ql-toolbar'));
    const linkBox = host.querySelector('.ql-tooltip input[type=text]');
    if (linkBox) { linkBox.setAttribute('data-link', 'https://…'); linkBox.setAttribute('aria-label', 'Link address'); }
    const editor = host.querySelector('.ql-editor');
    if (editor) { editor.setAttribute('aria-label', (label || 'Notes') + ' editor'); editor.setAttribute('role', 'textbox');
                  editor.setAttribute('aria-multiline', 'true'); }
    setCount(pnTextLength(start));
    const onChange = () => {
      const d = quill.getContents();
      pnDrafts[page] = { delta: d, baseId: pnDrafts[page] ? pnDrafts[page].baseId : null, dirty: true };
      setDirty(true);
      setCount(pnTextLength(d));
    };
    quill.on('text-change', onChange);
    // Where the cursor is: kept while the editor is blurred, so the table bar's
    // buttons act on the cell the cursor was in.
    const onEditorChange = (eventName, range) => {
      const r = eventName === 'selection-change' ? range : quill.getSelection();
      if (!r) return;
      lastRangeRef.current = r;
      const inside = pnRangeInTable(quill, r);
      setInTable(inside);
      if (eventName === 'selection-change') setHint('');
    };
    quill.on('editor-change', onEditorChange);
    quillRef.current = quill;
    quill.focus();
    quill.setSelection(quill.getLength(), 0, 'silent');
    lastRangeRef.current = { index: Math.max(quill.getLength() - 1, 0), length: 0 };
    setInTable(pnRangeInTable(quill, lastRangeRef.current));
    return () => {
      quill.off('text-change', onChange);
      quill.off('editor-change', onEditorChange);
      quillRef.current = null;
      lastRangeRef.current = null;
      setInTable(false);
      setTableForm(null);
      setHint('');
      host.innerHTML = '';
    };
  }, [editorOpen]);

  usePNEffect(() => {
    if (tableForm && rowsInputRef.current && document.activeElement !== rowsInputRef.current
        && !(document.activeElement && document.activeElement.closest && document.activeElement.closest('.pn-tableform'))) {
      rowsInputRef.current.focus();
      rowsInputRef.current.select();
    }
  }, [tableForm]);

  // Insert a rows x cols table on its own lines: at an empty line it takes
  // that line's place; after a line with text it goes below it, followed by
  // an empty line to keep writing under the table.
  function insertTable() {
    const quill = quillRef.current;
    if (!quill || !tableForm) return;
    const rows = Math.min(Math.max(parseInt(tableForm.rows, 10) || 0, 1), PN_TABLE_MAX_ROWS);
    const cols = Math.min(Math.max(parseInt(tableForm.cols, 10) || 0, 1), PN_TABLE_MAX_COLS);
    const range = lastRangeRef.current || { index: Math.max(quill.getLength() - 1, 0), length: 0 };
    const [line] = quill.getLine(range.index);
    const Delta = window.Quill.import('delta');
    const lineStart = line ? quill.getIndex(line) : Math.max(quill.getLength() - 1, 0);
    const emptyLine = !line || line.length() <= 1;
    const at = emptyLine ? lineStart : lineStart + line.length();
    let delta = new Delta().retain(at);
    for (let r = 0; r < rows; r++) {
      delta = delta.insert('\n'.repeat(cols), { table: 'row-' + Math.random().toString(36).slice(2, 8) });
    }
    if (!emptyLine) delta = delta.insert('\n');
    quill.updateContents(delta, 'user');
    setTableForm(null);
    quill.setSelection(at, 0, 'user');
    quill.focus();
  }

  function tableAction(fn) {
    const quill = quillRef.current;
    const range = lastRangeRef.current;
    if (!quill || !range) return;
    quill.setSelection(range.index, range.length, 'silent');
    const table = quill.getModule('table');
    if (table && typeof table[fn] === 'function') table[fn]();
    quill.focus();
    const r = quill.getSelection();
    if (r) { lastRangeRef.current = r; setInTable(pnRangeInTable(quill, r)); }
  }

  // Read view: is the note taller than PN_READ_LINES?
  usePNLayoutEffect(() => {
    const el = readRef.current;
    if (!el) { setTall(false); return undefined; }
    const measure = () => setTall(el.scrollHeight > PN_READ_LINES * PN_LINE_PX + 2);
    measure();
    if (typeof ResizeObserver === 'undefined') return undefined;
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  });

  function startEdit() {
    setError('');
    setConflict(null);
    setConfirmDiscard(false);
    setRestored(false);
    pnDrafts[page] = { delta: (note && note.delta) || { ops: [{ insert: '\n' }] }, baseId: note ? note.id : null, dirty: false };
    setDirty(false);
    setMode('edit');
  }

  function closeEditor(newNote) {
    delete pnDrafts[page];
    if (newNote) setNote(newNote);
    setMode('read');
    setDirty(false);
    setRestored(false);
    setConflict(null);
    setConfirmDiscard(false);
    setError('');
    setTimeout(() => { if (editBtnRef.current) editBtnRef.current.focus(); }, 0);
  }

  async function save(overrideBase) {
    const quill = quillRef.current;
    if (saving || !quill) return;
    const delta = pnCleanDelta(quill.getContents());
    const len = pnTextLength(delta);
    if (len > PN_TEXT_MAX) {
      setError('Not saved: the note is limited to ' + PN_TEXT_MAX.toLocaleString('en-US') + ' characters (it has '
               + len.toLocaleString('en-US') + ').');
      return;
    }
    const draft = pnDrafts[page];
    const baseId = overrideBase !== undefined ? overrideBase : draft ? draft.baseId : note ? note.id : null;
    if (len === 0 && baseId == null && (!note || note.id == null)) { closeEditor(null); return; }   // nothing to keep
    setSaving(true);
    setError('');
    const res = await pnRequest('PUT', '/api/page-notes/' + page, { delta, base_id: baseId });
    setSaving(false);
    if (!res) return;
    if (res.status === 200 && res.data) { closeEditor(res.data); return; }
    if (res.status === 409 && res.data && res.data.current) {
      setConflict(res.data.current);
      return;
    }
    if (res.status === 0) { setError("Couldn't reach the server. Your edits are still here; try Save again."); return; }
    setError('Not saved: ' + ((res.data && res.data.error) || 'the server answered ' + res.status) + '. Your edits are still here.');
  }
  saveRef.current = () => save();

  function saveOverConflict() {
    const base = conflict ? conflict.id : null;
    if (pnDrafts[page]) pnDrafts[page] = { ...pnDrafts[page], baseId: base };
    setConflict(null);
    save(base);
  }

  function discardMine() {
    const theirs = conflict;
    closeEditor(theirs);
  }

  function cancel() {
    if (dirty) { setConfirmDiscard(true); return; }
    closeEditor(null);
  }

  const savedText = note && note.saved_at ? pnSavedLabel(note.saved_at) : null;
  const titleText = label || 'Notes';
  const head = <div className="pn-head">
    <span className="pn-title">{titleText}</span>
    {savedText && mode === 'read' && <span className="pn-saved" title={note.saved_at}>Saved {savedText}</span>}
    {mode === 'edit' && <span className="pn-saved">Editing{restored ? ' · unsaved draft restored' : dirty ? ' · unsaved changes' : ''}</span>}
    {mode === 'read' && load.status === 'ok' && !hideValues &&
      <button ref={editBtnRef} type="button" className="tv-btn pn-btn" style={{ marginLeft: 'auto' }}
        aria-label={(note && !note.empty ? 'Edit ' : 'Add ') + titleText.toLowerCase()}
        onClick={startEdit}>{note && !note.empty ? 'Edit' : 'Add notes'}</button>}
  </div>;

  let body;
  if (hideValues) {
    body = <div className="pn-muted">Notes hidden while Hide values is on.{mode === 'edit' ? ' Your unsaved edits are kept.' : ''}</div>;
  } else if (load.status === 'loading') {
    body = <div className="pn-muted">Loading notes…</div>;
  } else if (load.status === 'error') {
    body = <div role="alert" className="pn-muted">Couldn't load the notes.{' '}
      <button type="button" className="pn-textbtn" onClick={loadNote}>Try again</button></div>;
  } else if (mode === 'read') {
    if (!note || note.empty) {
      body = <div className="pn-muted">No notes yet.</div>;
    } else {
      const clamp = !expanded && tall;
      body = <React.Fragment>
        <div ref={readRef} className={'pn-read' + (clamp ? ' pn-clamped' : '')}
          style={!expanded ? { maxHeight: PN_READ_LINES * PN_LINE_PX } : undefined}>
          <PageNotesRead delta={note.delta} />
        </div>
        {(tall || expanded) && <button type="button" className="pn-textbtn" aria-expanded={expanded}
          onClick={() => { const v = !expanded; setExpanded(v); pnWriteExpanded(page, v); }}>
          {expanded ? 'Show less' : 'Show all'}</button>}
      </React.Fragment>;
    }
  } else {
    const over = count > PN_TEXT_MAX;
    body = <div className="pn-edit">
      {conflict && <div role="alert" className="pn-alert">
        This note was saved from another tab or device{conflict.saved_at ? ' (' + pnSavedLabel(conflict.saved_at) + ')' : ''} after
        you started editing. Your version is still in the editor.
        <span className="pn-actions">
          <button type="button" className="tv-btn pn-btn" onClick={saveOverConflict} disabled={saving}>Save mine over it</button>
          <button type="button" className="tv-btn pn-btn" onClick={discardMine} disabled={saving}>Discard mine, show theirs</button>
        </span>
      </div>}
      {error && <div role="alert" className="pn-error">{error}</div>}
      {quillState === 'loading' && <div className="pn-muted">Loading the editor…</div>}
      {quillState === 'failed' && <div role="alert" className="pn-error">
        The editor couldn't load (it comes from unpkg.com). Check the connection, then{' '}
        <button type="button" className="pn-textbtn" onClick={() => setQuillState('idle')}>try again</button>.
      </div>}
      <div ref={hostRef} className="pn-host" />
      {tableForm && <form className="pn-tablebar pn-tableform" aria-label="Insert a table"
          onSubmit={e => { e.preventDefault(); insertTable(); }}
          onKeyDown={e => { if (e.key === 'Escape') { e.preventDefault(); setTableForm(null); if (quillRef.current) quillRef.current.focus(); } }}>
        <span className="pn-tablebar-label">Insert a table</span>
        <label className="pn-num">Rows
          <input ref={rowsInputRef} type="number" min="1" max={PN_TABLE_MAX_ROWS} value={tableForm.rows}
            onChange={e => setTableForm({ ...tableForm, rows: e.target.value })} /></label>
        <label className="pn-num">Columns
          <input type="number" min="1" max={PN_TABLE_MAX_COLS} value={tableForm.cols}
            onChange={e => setTableForm({ ...tableForm, cols: e.target.value })} /></label>
        <button type="submit" className="tv-btn primary pn-btn">Insert table</button>
        <button type="button" className="tv-btn pn-btn"
          onClick={() => { setTableForm(null); if (quillRef.current) quillRef.current.focus(); }}>Cancel</button>
        <span className="pn-tablebar-help">Up to {PN_TABLE_MAX_ROWS} rows and {PN_TABLE_MAX_COLS} columns; add more later from the table bar.</span>
      </form>}
      {!tableForm && inTable && quillState === 'ready' && <div className="pn-tablebar" role="toolbar" aria-label="Table">
        <span className="pn-tablebar-label">Table</span>
        {[['insertRowAbove', 'Row above'], ['insertRowBelow', 'Row below'], ['insertColumnLeft', 'Column left'],
          ['insertColumnRight', 'Column right'], ['deleteRow', 'Delete row'], ['deleteColumn', 'Delete column'],
          ['deleteTable', 'Delete table']].map(([fn, text]) =>
          <button key={fn} type="button" className={'tv-btn pn-btn' + (fn.startsWith('delete') ? ' pn-btn-del' : '')}
            onMouseDown={e => e.preventDefault()} onClick={() => tableAction(fn)}>{text}</button>)}
        <span className="pn-tablebar-help">Tab moves to the next cell.</span>
      </div>}
      {hint && <div role="status" className="pn-hint">{hint}</div>}
      {confirmDiscard
        ? <div role="alert" className="pn-foot">
            <span className="pn-confirm">Discard your unsaved changes?</span>
            <button type="button" className="tv-btn pn-btn danger" onClick={() => closeEditor(null)}>Discard changes</button>
            <button type="button" className="tv-btn pn-btn" onClick={() => setConfirmDiscard(false)}>Keep editing</button>
          </div>
        : <div className="pn-foot">
            <span className={'pn-count' + (over ? ' pn-over' : count > PN_TEXT_WARN ? ' pn-near' : '')}
              aria-live="polite">{count.toLocaleString('en-US')} / {PN_TEXT_MAX.toLocaleString('en-US')} characters</span>
            <button type="button" className="tv-btn pn-btn" onClick={cancel} disabled={saving}>Cancel</button>
            <button type="button" className="tv-btn primary pn-btn" onClick={() => save()}
              disabled={saving || over || quillState !== 'ready'}>{saving ? 'Saving…' : 'Save'}</button>
          </div>}
    </div>;
  }

  return <section className={'pn-panel' + (mode === 'edit' && !hideValues ? ' pn-editing' : '')} aria-label={titleText}>
    {head}
    {body}
  </section>;
}

window.PageNotesPanel = PageNotesPanel;
