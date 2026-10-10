/* ===== NOTES PAGE — Landing 24 =====
   The Trading menu's Notes page: two tabs, Watchlist and Nuggets, each a
   formatted note of its own (static/pagenotes.js, PageNotesPanel with
   variant="page"), saved through /api/page-notes/<page> under the page names
   in NB_TABS (web_portfolio.PAGE_NOTE_PAGES; a test pins them together).
   Every saved version is kept, as for the Spot note.

   - The tab you had open is remembered per browser (localStorage notesTab).
   - The panel is keyed by its page, so switching tabs gives the other tab a
     fresh editor. An unsaved draft stays with its own tab (pnDrafts in
     pagenotes.js), and that tab's button says "unsaved" while you are on the
     other one. While this page is open, an unsaved edit on either tab makes
     the browser ask before a reload or leaving the app.
   - Hide values hides both notes (the panel's own rule).

   Loaded after static/pagenotes.js (templates/index.html). Every top-level
   name here starts with nb / NB / Notes: Babel turns top-level declarations
   into shared globals, so a name used in another static/*.js file would be
   silently overwritten. */

const NB_TABS = [
  { id: 'watchlist', page: 'notes-watchlist', label: 'Watchlist' },
  { id: 'nuggets', page: 'notes-nuggets', label: 'Nuggets' },
];
const NB_TAB_KEY = 'notesTab';

function nbReadTab() {
  try {
    const v = localStorage.getItem(NB_TAB_KEY);
    return NB_TABS.some(t => t.id === v) ? v : NB_TABS[0].id;
  } catch (e) { return NB_TABS[0].id; }
}

function nbWriteTab(v) {
  try { localStorage.setItem(NB_TAB_KEY, v); } catch (e) { /* storage blocked: the choice lasts this visit only */ }
}

function NotesScreen({ hideValues }) {
  const [tab, setTab] = React.useState(nbReadTab);
  const current = NB_TABS.find(t => t.id === tab) || NB_TABS[0];
  const Panel = window.PageNotesPanel;
  const hasDraft = window.PageNotesHasDraft || (() => false);
  // Both tabs' unsaved edits count for the leave-page warning while this page
  // is open, including the tab you are not on.
  React.useEffect(() => (window.PageNotesShowPages ? window.PageNotesShowPages(NB_TABS.map(t => t.page)) : undefined), []);

  function change(id) {
    setTab(id);
    nbWriteTab(id);
  }

  return <div className="nb-page">
    <div className="nb-head">
      <h1 style={{ margin:0, fontSize:20, lineHeight:'26px', fontWeight:700, color:'var(--text)' }}>Notes</h1>
      <div style={{ fontSize:13, lineHeight:'18px', color:'var(--text3)' }}>Prep notes: tokens you're watching, and trading nuggets worth keeping.</div>
    </div>
    <div className="nb-tabs" role="group" aria-label="Notes pages">
      {NB_TABS.map(t => {
        const on = t.id === current.id;
        const unsaved = !on && hasDraft(t.page);
        return <button key={t.id} type="button" className="tv-btn" aria-pressed={on}
          title={unsaved ? t.label + ' has unsaved edits' : undefined}
          style={{ background:on?'var(--panel3)':'transparent', borderColor:on?'var(--accent-line)':'var(--line)',
            color:on?'var(--text)':'var(--text3)', fontWeight:on?600:400 }}
          onClick={() => change(t.id)}>
          {t.label}{unsaved && <span className="nb-unsaved"> · unsaved</span>}
        </button>;
      })}
    </div>
    {Panel
      ? <Panel key={current.page} page={current.page} hideValues={hideValues} label={current.label} variant="page" />
      : <div role="alert" className="pn-muted">The notes editor didn't load. Reload the page to try again.</div>}
  </div>;
}

window.NotesScreen = NotesScreen;
