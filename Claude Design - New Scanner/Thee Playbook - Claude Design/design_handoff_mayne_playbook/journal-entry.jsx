// journal-entry.jsx — Full-page trade journal entry (dark hi-fi).
// Opens when a trade row is selected from the Journal list. Designed to scroll
// indefinitely so an entry can hold as much narrative + chart context as needed.
// Multiple drag-drop screenshot slots are grouped by trade phase
// (HTF setup · LTF entry · Management · Exit · Post-trade review).
// Each slot persists what the user drops via the <image-slot> sidecar.

const JournalEntryFull = () => {
  // Mock entry — May 23 BTC long, the "best case" entry to show off the layout.
  const e = {
    id: 't-may23-btc',
    date: 'May 23, 2026',
    weekday: 'Friday',
    ticker: 'BTCUSD',
    htf: '4H', ltf: '15m',
    dir: 'long',
    readiness: 'READY',
    passed: 6, total: 6,
    opened: '09:12',
    closed: '12:48',
    duration: '3h 36m',
    session: 'London → NY overlap',
    entry: '70,940', stop: '70,720', target: '71,500', exitPx: '71,510',
    risk: '1.2%', size: '0.45 BTC',
    rr: '2.6R', pnl: '+1.8R',
    mae: '-0.3R', mfe: '+2.1R',
    outcome: 'win',
    concepts: ['Order Block', 'FVG', 'BOS / CHoCH', 'Liquidity Sweep', 'Killzone'],
    thesis: 'Long off the daily OB tap at 70,920. HTF clearly bullish on 4H — premium-to-discount return complete after the swing high sweep at 71,640. Strong LTF confirmation: 5m sell-side sweep, CHoCH up through 70,985, then re-entry into the 5m bullish FVG at 70,920–70,945. Risk to under the OB low at 70,720. First target the recent high at 71,500.',
  };

  // Phase blocks — each is a group of named, drop-fillable screenshot slots.
  // Slot ids include the trade id so persistence is per-entry.
  const phases = [
    {
      key: 'htf',
      label: 'HTF setup',
      tf: '4H · Daily',
      tone: 'adapt',
      summary: 'Where the bias and the point of interest were formed before I cared about timing.',
      slots: [
        { id: `${e.id}-htf-1`, caption: 'Daily — bullish structure, swing high sweep tagged @ 71,640 then PD return into the 4H OB',
          tags: ['Daily', 'Bias: bullish', 'Sweep + PD return'] },
        { id: `${e.id}-htf-2`, caption: '4H — order block 70,860–70,990 marked. Killzone overlay shown.',
          tags: ['4H', 'OB', 'Killzone overlay'] },
      ],
    },
    {
      key: 'ltf',
      label: 'LTF entry trigger',
      tf: '15m · 5m',
      tone: 'ok',
      summary: 'The exact sequence that gave me permission to size in.',
      slots: [
        { id: `${e.id}-ltf-1`, caption: '15m — sell-side liquidity at 70,898 swept, then CHoCH through 70,985.',
          tags: ['15m', 'Sweep', 'CHoCH'] },
        { id: `${e.id}-ltf-2`, caption: '5m — virgin bullish FVG @ 70,920–70,945. Entry marked with arrow.',
          tags: ['5m', 'FVG', 'Entry'] },
        { id: `${e.id}-ltf-3`, caption: 'Validator summary screenshot — READY · 6/6 criteria',
          tags: ['Validator', 'READY 6/6'] },
      ],
    },
    {
      key: 'manage',
      label: 'In-trade management',
      tf: 'live',
      tone: 'warn',
      summary: 'How the trade behaved between entry and exit — anything I had to decide while it was on.',
      slots: [
        { id: `${e.id}-manage-1`, caption: '10:24 — first pullback held the 15m FVG. Stop tightened to BE.',
          tags: ['Stop → BE', '15m hold'] },
        { id: `${e.id}-manage-2`, caption: '11:55 — push into 71,420. Held partial through, no early trim.',
            tags: ['No early trim'] },
      ],
    },
    {
      key: 'exit',
      label: 'Exit',
      tf: '15m',
      tone: 'ok',
      summary: 'Where I came off the trade and why.',
      slots: [
        { id: `${e.id}-exit-1`, caption: 'Filled at 71,510 — 10 ticks past planned target, lined up with daily resistance.',
          tags: ['Target hit', '+1.8R'] },
      ],
    },
    {
      key: 'post',
      label: 'Post-trade review',
      tf: 'next session',
      tone: 'accent',
      summary: 'What I looked back at the next morning, with hindsight markup.',
      slots: [
        { id: `${e.id}-post-1`, caption: 'Same 5m, annotated next day. Would I do anything different? See lesson →',
          tags: ['Hindsight markup'] },
        { id: `${e.id}-post-2`, caption: 'Daily after close — bigger picture. The 4H OB held and continued.',
          tags: ['Daily after'] },
      ],
    },
  ];

  return (
    <div className="tv-frame" style={{display: 'flex', flexDirection: 'column', minHeight: 0}}>
      <TVNav active="Journal"/>
    <TTSubNav active="Journal"/>

      {/* breadcrumb / sub-nav */}
      <div style={{
        padding: '10px 28px',
        borderBottom: `1px solid ${TV.line}`,
        background: TV.bg,
        display: 'flex', alignItems: 'center', gap: 10,
        fontSize: 12, color: TV.text3,
      }}>
        <span style={{color: TV.text3, cursor: 'pointer'}}>← Journal</span>
        <span style={{color: TV.text4}}>/</span>
        <span style={{color: TV.text3}}>Trade</span>
        <span style={{color: TV.text4}}>/</span>
        <span className="tv-num" style={{color: TV.text}}>{e.ticker}</span>
        <span style={{color: TV.text4}}>·</span>
        <span style={{color: TV.text2}}>{e.date}</span>
        <div style={{flex: 1}}/>
        <span style={{color: TV.text4}}>id · {e.id}</span>
        <div style={{width: 1, height: 14, background: TV.line, margin: '0 6px'}}/>
        <span style={{color: TV.text3, cursor: 'pointer'}}>‹ prev</span>
        <span style={{color: TV.text3, cursor: 'pointer'}}>next ›</span>
      </div>

      {/* page body */}
      <div style={{padding: '28px 80px 80px', background: TV.bg, display: 'flex',
          flexDirection: 'column', gap: 28, maxWidth: 1120, margin: '0 auto', width: '100%'}}>

        {/* ============ HERO ============ */}
        <EntryHero entry={e}/>

        {/* ============ THESIS + PLAN ============ */}
        <ThesisAndPlan entry={e}/>

        {/* ============ CONCEPTS ============ */}
        <Section label="Concepts referenced">
          <div style={{display: 'flex', gap: 6, flexWrap: 'wrap'}}>
            {e.concepts.map(c => <span key={c} className="tv-chip">{c}</span>)}
            <span className="tv-chip" style={{borderStyle: 'dashed', color: TV.text3, cursor: 'pointer'}}>+ tag a concept</span>
          </div>
        </Section>

        {/* ============ SCREENSHOTS (the centerpiece) ============ */}
        <Section
          label="Screenshots"
          right={<ShotControls/>}
          summary="Drop charts here as you go — each phase keeps its own group. Drag to reorder · double-click a slot to reframe."
        >
          <div style={{display: 'flex', flexDirection: 'column', gap: 26}}>
            {phases.map(p => <PhaseGroup key={p.key} phase={p}/>)}
            <AddPhaseRow/>
          </div>
        </Section>

        {/* ============ EXECUTION TIMELINE ============ */}
        <Section label="Execution timeline">
          <ExecutionTimeline entry={e}/>
        </Section>

        {/* ============ OUTCOME ============ */}
        <Section label="Outcome">
          <OutcomeCard entry={e}/>
        </Section>

        {/* ============ LESSON ============ */}
        <Section label="Lesson" right={<span style={{fontSize: 11, color: TV.text4}}>shown in Reports → Lesson themes</span>}>
          <Lesson/>
        </Section>

        {/* ============ NOTES (long-form, editable) ============ */}
        <Section label="Notes" summary="Free-form, markdown supported · everything below this header is just for you.">
          <LongNotes/>
        </Section>

        {/* ============ LINKED ============ */}
        <Section label="Linked">
          <LinkedItems/>
        </Section>

        {/* ============ FOOTER ============ */}
        <div style={{display: 'flex', gap: 10, alignItems: 'center',
            paddingTop: 22, borderTop: `1px solid ${TV.line}`}}>
          <button className="tv-btn ghost" style={{fontSize: 13}}>← Back to journal</button>
          <button className="tv-btn ghost" style={{fontSize: 13}}>Copy as markdown</button>
          <button className="tv-btn ghost" style={{fontSize: 13}}>Export as PDF</button>
          <div style={{flex: 1}}/>
          <button className="tv-btn ghost" style={{fontSize: 13, color: TV.fail, borderColor: 'rgba(217,83,79,.3)'}}>Delete entry</button>
          <button className="tv-btn" style={{fontSize: 13}}>Re-open in validator</button>
          <button className="tv-btn primary" style={{fontSize: 13}}>Save · ⌘S</button>
        </div>
      </div>
    </div>
  );
};

// =================== HERO ===================
const EntryHero = ({entry: e}) => {
  const oColor = e.outcome === 'win' ? TV.ok : e.outcome === 'loss' ? TV.fail : e.outcome === 'open' ? TV.warn : TV.text3;
  const oSoft  = e.outcome === 'win' ? TV.okSoft : e.outcome === 'loss' ? TV.failSoft : e.outcome === 'open' ? TV.warnSoft : 'transparent';
  return (
    <div style={{display: 'grid', gridTemplateColumns: '1fr auto', gap: 28, alignItems: 'flex-end'}}>
      <div>
        <div className="tv-uppercase" style={{marginBottom: 8}}>Pre-trade reasoning record</div>
        <div style={{display: 'flex', alignItems: 'baseline', gap: 14, flexWrap: 'wrap'}}>
          <div className="tv-num" style={{fontSize: 36, fontWeight: 600, color: TV.text, letterSpacing: '.01em'}}>
            {e.ticker}
          </div>
          <TfPair htf={e.htf} ltf={e.ltf}/>
          <div style={{fontSize: 13, fontWeight: 600, color: e.dir === 'long' ? TV.ok : TV.fail,
              textTransform: 'uppercase', letterSpacing: '.08em'}}>{e.dir}</div>
          <div style={{fontSize: 13, color: TV.text3}}>{e.weekday} · {e.date}</div>
        </div>
        <div style={{display: 'flex', alignItems: 'center', gap: 10, marginTop: 14, flexWrap: 'wrap'}}>
          <span className="tv-chip" style={{color: TV.ok, borderColor: 'rgba(63,178,127,.4)', background: TV.okSoft}}>
            <span className="tv-dot"/>{e.readiness} · {e.passed}/{e.total}
          </span>
          <span className="tv-chip" style={{color: oColor, borderColor: oColor,
              background: oSoft, textTransform: 'uppercase', letterSpacing: '.06em', fontWeight: 600}}>
            <span className="tv-dot"/>{e.outcome} · <span className="tv-num">{e.pnl}</span>
          </span>
          <span style={{fontSize: 12, color: TV.text3}}>{e.opened} → {e.closed}  ·  held {e.duration}  ·  {e.session}</span>
        </div>
      </div>

      <div style={{display: 'grid', gridTemplateColumns: 'repeat(4, auto)', gap: '10px 22px',
          padding: '14px 18px', border: `1px solid ${TV.line}`, borderRadius: 8, background: TV.panel}}>
        {[
          ['Risk', e.risk], ['Size', e.size],
          ['Entry', e.entry], ['Stop', e.stop],
          ['Target', e.target], ['Exit', e.exitPx],
          ['R:R', e.rr], ['MAE → MFE', `${e.mae} / ${e.mfe}`],
        ].map(([k, v]) => (
          <div key={k} style={{display: 'flex', flexDirection: 'column', gap: 2, minWidth: 92}}>
            <div style={{fontSize: 10, color: TV.text3, textTransform: 'uppercase', letterSpacing: '.08em', fontWeight: 600}}>{k}</div>
            <div className="tv-num" style={{fontSize: 14, color: TV.text, fontWeight: 600}}>{v}</div>
          </div>
        ))}
      </div>
    </div>
  );
};

// =================== THESIS + PLAN ===================
const ThesisAndPlan = ({entry: e}) => (
  <div style={{display: 'grid', gridTemplateColumns: '1.6fr 1fr', gap: 22}}>
    <div>
      <div className="tv-uppercase" style={{marginBottom: 8}}>Thesis</div>
      <div
        contentEditable
        suppressContentEditableWarning
        spellCheck={false}
        style={{
          fontSize: 15, color: TV.text, lineHeight: 1.6,
          padding: '14px 16px', borderRadius: 8,
          border: `1px dashed ${TV.line}`, background: 'rgba(255,255,255,.015)',
          outline: 'none', cursor: 'text',
        }}>
        {e.thesis}
      </div>
      <div style={{fontSize: 11, color: TV.text4, marginTop: 6, display: 'flex', gap: 14}}>
        <span>drafted from validator answers · last edited 23h ago</span>
        <span style={{color: TV.text3, cursor: 'pointer'}}>↻ regenerate from validator</span>
        <span style={{color: TV.text3, cursor: 'pointer'}}>↩ revert to draft</span>
      </div>
    </div>
    <div className="tv-card" style={{padding: 16, display: 'flex', flexDirection: 'column', gap: 10}}>
      <div className="tv-uppercase">Plan vs result</div>
      {[
        ['Entry', e.entry, e.entry, 'hit'],
        ['Stop', e.stop, '—', 'untouched'],
        ['Target', e.target, e.exitPx, 'hit + 10 ticks'],
      ].map(([k, planned, actual, note]) => (
        <div key={k} style={{display: 'grid', gridTemplateColumns: '64px 1fr 1fr', gap: 10, alignItems: 'baseline', fontSize: 13}}>
          <div style={{color: TV.text3, fontSize: 11, textTransform: 'uppercase', letterSpacing: '.08em', fontWeight: 600}}>{k}</div>
          <div className="tv-num" style={{color: TV.text2}}>{planned}</div>
          <div className="tv-num" style={{color: TV.text, display: 'flex', justifyContent: 'space-between', gap: 6}}>
            <span>{actual}</span>
            <span style={{fontSize: 11, color: TV.text3}}>{note}</span>
          </div>
        </div>
      ))}
      <div style={{height: 1, background: TV.line, margin: '4px 0'}}/>
      <div style={{display: 'flex', justifyContent: 'space-between', fontSize: 13}}>
        <span style={{color: TV.text3}}>Realised</span>
        <span className="tv-num" style={{color: TV.ok, fontWeight: 700}}>{e.pnl} · {e.rr} planned</span>
      </div>
    </div>
  </div>
);

// =================== SECTION SHELL ===================
const Section = ({label, summary, right, children}) => (
  <section>
    <div style={{display: 'flex', alignItems: 'baseline', justifyContent: 'space-between',
        marginBottom: summary ? 4 : 12, gap: 16}}>
      <div style={{fontSize: 14, fontWeight: 600, color: TV.text, letterSpacing: '.02em', textTransform: 'uppercase'}}>{label}</div>
      {right}
    </div>
    {summary && (
      <div style={{fontSize: 12, color: TV.text3, marginBottom: 14, maxWidth: 720}}>{summary}</div>
    )}
    {children}
  </section>
);

// =================== SCREENSHOTS · PHASE GROUP ===================
const PhaseGroup = ({phase: p}) => {
  const toneColor = p.tone === 'adapt' ? TV.adapt :
                    p.tone === 'ok'    ? TV.ok    :
                    p.tone === 'warn'  ? TV.warn  :
                    p.tone === 'accent'? TV.accent: TV.text3;
  const toneSoft  = p.tone === 'adapt' ? TV.adaptSoft :
                    p.tone === 'ok'    ? TV.okSoft    :
                    p.tone === 'warn'  ? TV.warnSoft  :
                    p.tone === 'accent'? TV.accentSoft: 'transparent';

  // Layout: HTF + post + exit phases get 2-up; LTF & manage get a featured + supporting layout.
  const isFeatured = p.key === 'ltf' || p.key === 'manage';

  return (
    <div className="tv-card" style={{padding: 0, overflow: 'hidden'}}>
      {/* phase header */}
      <div style={{
        padding: '12px 18px',
        background: toneSoft,
        borderBottom: `1px solid ${TV.line}`,
        display: 'flex', alignItems: 'center', gap: 12,
      }}>
        <div style={{width: 8, height: 8, borderRadius: 2, background: toneColor}}/>
        <div style={{fontSize: 14, fontWeight: 600, color: TV.text}}>{p.label}</div>
        <div style={{fontSize: 11, color: TV.text3, letterSpacing: '.06em', textTransform: 'uppercase'}}>{p.tf}</div>
        <div style={{flex: 1}}/>
        <div style={{fontSize: 11, color: TV.text3}}>{p.slots.length} shot{p.slots.length !== 1 ? 's' : ''}</div>
        <div style={{width: 1, height: 12, background: TV.line}}/>
        <span style={{fontSize: 11, color: TV.text3, cursor: 'pointer'}}>＋ Add</span>
        <span style={{fontSize: 11, color: TV.text4, cursor: 'pointer'}}>⋯</span>
      </div>

      <div style={{padding: '14px 18px 18px'}}>
        <div style={{fontSize: 12, color: TV.text3, marginBottom: 14, fontStyle: 'italic'}}>{p.summary}</div>

        {isFeatured && p.slots.length > 1 ? (
          // Featured layout — first shot big, the rest in a side stack
          <div style={{display: 'grid', gridTemplateColumns: '1.7fr 1fr', gap: 14}}>
            <ShotSlot slot={p.slots[0]} height={360} featured/>
            <div style={{display: 'flex', flexDirection: 'column', gap: 14}}>
              {p.slots.slice(1).map(s => <ShotSlot key={s.id} slot={s} height={170}/>)}
              <AddShot height={170}/>
            </div>
          </div>
        ) : (
          // Even grid — 2 columns (1 if single shot)
          <div style={{
            display: 'grid',
            gridTemplateColumns: p.slots.length === 1 ? '1fr' : 'repeat(2, 1fr)',
            gap: 14,
          }}>
            {p.slots.map(s => <ShotSlot key={s.id} slot={s} height={p.slots.length === 1 ? 380 : 240}/>)}
            <AddShot height={p.slots.length === 1 ? 380 : 240}/>
          </div>
        )}
      </div>
    </div>
  );
};

// =================== ONE SCREENSHOT SLOT ===================
const ShotSlot = ({slot, height, featured}) => {
  return (
    <figure style={{margin: 0, display: 'flex', flexDirection: 'column', gap: 8}}>
      <div style={{
        position: 'relative',
        borderRadius: 6,
        overflow: 'hidden',
        border: `1px solid ${TV.line}`,
        background: TV.panel2,
      }}>
        {/* The <image-slot> custom element handles drag/drop persistence. */}
        <image-slot
          id={slot.id}
          shape="rect"
          placeholder={`Drop screenshot · ${slot.tags?.[0] || ''}`}
          style={{display: 'block', width: '100%', height: `${height}px`}}
        ></image-slot>
        {/* Top-right action chips, click affordances on the user's filled image */}
        <div style={{
          position: 'absolute', top: 8, right: 8,
          display: 'flex', gap: 4, pointerEvents: 'none',
        }}>
          {(slot.tags || []).slice(0, 3).map(t => (
            <span key={t} className="tv-chip" style={{
              fontSize: 10, padding: '1px 6px',
              background: 'rgba(13,16,24,.78)', borderColor: 'rgba(255,255,255,.08)',
              backdropFilter: 'blur(4px)',
              color: TV.text2,
            }}>{t}</span>
          ))}
        </div>
        {/* corner index for ordering */}
        <div style={{
          position: 'absolute', top: 8, left: 8,
          fontSize: 10, color: TV.text3, fontWeight: 600,
          background: 'rgba(13,16,24,.78)', padding: '2px 6px', borderRadius: 3,
          letterSpacing: '.08em', textTransform: 'uppercase',
        }}>{featured ? 'Primary' : 'Drop chart'}</div>
      </div>
      <figcaption style={{display: 'flex', alignItems: 'flex-start', gap: 8}}>
        <span style={{fontSize: 12, color: TV.text2, lineHeight: 1.5, flex: 1}}>
          {slot.caption}
        </span>
        <span style={{fontSize: 11, color: TV.text4, cursor: 'pointer', whiteSpace: 'nowrap'}}>edit ✎</span>
      </figcaption>
    </figure>
  );
};

// =================== ADD-A-SHOT (dashed empty) ===================
const AddShot = ({height}) => (
  <div style={{
    height: `${height}px`,
    border: `1px dashed ${TV.line}`,
    borderRadius: 6,
    display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
    gap: 8,
    background: 'rgba(255,255,255,.012)',
    cursor: 'pointer',
    color: TV.text3,
  }}>
    <div style={{
      width: 32, height: 32, borderRadius: 6,
      border: `1px dashed ${TV.line}`,
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      fontSize: 18, color: TV.text3,
    }}>＋</div>
    <div style={{fontSize: 12, color: TV.text3}}>Add screenshot</div>
    <div style={{fontSize: 11, color: TV.text4}}>drop · paste · or click</div>
  </div>
);

// =================== "+ Add another phase" affordance ===================
const AddPhaseRow = () => (
  <div style={{
    padding: 14,
    border: `1px dashed ${TV.line}`,
    borderRadius: 8,
    display: 'flex', alignItems: 'center', gap: 12,
    color: TV.text3,
    cursor: 'pointer',
  }}>
    <div style={{
      width: 28, height: 28, borderRadius: 6,
      border: `1px dashed ${TV.line}`,
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      fontSize: 16, color: TV.text3,
    }}>＋</div>
    <div style={{display: 'flex', flexDirection: 'column'}}>
      <div style={{fontSize: 13, color: TV.text2, fontWeight: 500}}>New phase</div>
      <div style={{fontSize: 11, color: TV.text4}}>e.g. “News reaction” · “Scaled in” · “Post-mortem 2”</div>
    </div>
    <div style={{flex: 1}}/>
    <div style={{display: 'flex', gap: 6}}>
      {['News', 'Scaled in', 'Re-entry', 'Hedged', 'External read'].map(s => (
        <span key={s} className="tv-chip" style={{borderStyle: 'dashed', color: TV.text3, fontSize: 11}}>{s}</span>
      ))}
    </div>
  </div>
);

// =================== SCREENSHOTS · TOP-RIGHT CONTROLS ===================
const ShotControls = () => (
  <div style={{display: 'flex', alignItems: 'center', gap: 10, fontSize: 12, color: TV.text3}}>
    <span style={{display: 'inline-flex', alignItems: 'center', gap: 6}}>
      <span style={{width: 6, height: 6, borderRadius: '50%', background: TV.ok}}/>
      <span><span className="tv-num" style={{color: TV.text2}}>9</span> shots · <span className="tv-num" style={{color: TV.text2}}>4.2 MB</span></span>
    </span>
    <div style={{width: 1, height: 12, background: TV.line}}/>
    <span style={{cursor: 'pointer'}}>Filmstrip view</span>
    <span style={{cursor: 'pointer'}}>Light table ⊞</span>
    <span style={{cursor: 'pointer', color: TV.text2}}>＋ Paste from clipboard ⌘V</span>
  </div>
);

// =================== EXECUTION TIMELINE ===================
const ExecutionTimeline = ({entry: e}) => {
  const events = [
    {t: '08:50', tag: 'Plan',    body: 'Saw the 4H setup pre-market. Daily plan flagged the OB at 70,860–70,990.', tone: TV.text3},
    {t: '09:08', tag: 'Trigger', body: '15m sweep into 70,898, CHoCH printed at 70,985. Stalking 5m FVG.',         tone: TV.adapt},
    {t: '09:12', tag: 'Entry',   body: 'Filled at 70,940 inside 5m FVG. Stop at 70,720, target 71,500.',           tone: TV.ok},
    {t: '10:24', tag: 'Manage',  body: 'First pullback held the 15m FVG — pulled stop to BE.',                     tone: TV.warn},
    {t: '11:55', tag: 'Manage',  body: 'Push into 71,420. Considered partial. Held everything.',                   tone: TV.warn},
    {t: '12:48', tag: 'Exit',    body: 'Filled at 71,510. +1.8R. Closed at daily resistance.',                      tone: TV.ok},
  ];
  return (
    <div className="tv-card" style={{padding: 0, overflow: 'hidden'}}>
      {events.map((ev, i) => (
        <div key={i} style={{
          display: 'grid', gridTemplateColumns: '72px 110px 1fr auto',
          gap: 14, alignItems: 'center',
          padding: '12px 18px',
          borderBottom: i < events.length - 1 ? `1px solid ${TV.lineSoft}` : 'none',
        }}>
          <div className="tv-num" style={{fontSize: 13, color: TV.text2}}>{ev.t}</div>
          <div style={{display: 'flex', alignItems: 'center', gap: 8}}>
            <span style={{width: 6, height: 6, borderRadius: '50%', background: ev.tone}}/>
            <span style={{fontSize: 11, color: ev.tone, textTransform: 'uppercase', letterSpacing: '.08em', fontWeight: 600}}>{ev.tag}</span>
          </div>
          <div style={{fontSize: 13, color: TV.text, lineHeight: 1.5}}>{ev.body}</div>
          <span style={{fontSize: 11, color: TV.text4, cursor: 'pointer'}}>attach shot</span>
        </div>
      ))}
      <div style={{padding: '10px 18px', display: 'flex', alignItems: 'center', gap: 10, color: TV.text3, fontSize: 12, cursor: 'pointer'}}>
        <span>＋</span><span>Add timeline event</span>
      </div>
    </div>
  );
};

// =================== OUTCOME CARD ===================
const OutcomeCard = ({entry: e}) => (
  <div className="tv-card" style={{padding: 18, borderColor: TV.ok, background: TV.okSoft}}>
    <div style={{display: 'flex', alignItems: 'center', gap: 12, marginBottom: 12}}>
      <div style={{width: 36, height: 36, borderRadius: 6,
          background: TV.ok, color: '#0d1018', fontSize: 18, fontWeight: 700,
          display: 'flex', alignItems: 'center', justifyContent: 'center'}}>✓</div>
      <div>
        <div style={{fontSize: 16, fontWeight: 600, color: TV.text}}>Win · <span className="tv-num">{e.pnl}</span></div>
        <div style={{fontSize: 12, color: TV.text2}}>Target hit at <span className="tv-num">{e.exitPx}</span> · held {e.duration}</div>
      </div>
      <div style={{flex: 1}}/>
      <div style={{display: 'grid', gridTemplateColumns: 'repeat(3, auto)', gap: '0 28px', fontSize: 12}}>
        {[['MAE', e.mae], ['MFE', e.mfe], ['Efficiency', '86%']].map(([k,v]) => (
          <div key={k} style={{textAlign: 'right'}}>
            <div style={{color: TV.text3, fontSize: 11, textTransform: 'uppercase', letterSpacing: '.08em'}}>{k}</div>
            <div className="tv-num" style={{color: TV.text, fontWeight: 600, fontSize: 14}}>{v}</div>
          </div>
        ))}
      </div>
    </div>
    <div style={{fontSize: 13, color: TV.text, lineHeight: 1.6, borderLeft: `2px solid ${TV.ok}`, paddingLeft: 12}}>
      Hit planned target with 10 ticks of extra fill. No drawdown beyond 0.3R — entry was clean. Hold time matched the
      expected London → NY window. This is the platonic OB tap + LTF CHoCH continuation that the playbook is built around.
    </div>
  </div>
);

// =================== LESSON ===================
const Lesson = () => (
  <div
    contentEditable
    suppressContentEditableWarning
    spellCheck={false}
    style={{
      fontSize: 14, color: TV.text, lineHeight: 1.65,
      padding: '14px 16px', borderRadius: 8,
      border: `1px dashed ${TV.line}`, background: 'rgba(255,255,255,.015)',
      outline: 'none', cursor: 'text',
      borderLeft: `3px solid ${TV.accent}`,
    }}>
    OB tap + LTF CHoCH continues to be the highest-conviction setup in my playbook. Sizing felt comfortable at 1.2%
    risk — I should make that the standard for READY + 6/6 trades rather than the 0.8% I've been defaulting to.
    The one thing to keep an eye on: I held through the 71,420 push without trimming. It worked this time, but if the
    daily resistance had been 30 ticks lower I would've given back most of the trade. Codify a rule: when MFE crosses
    2R and price approaches a daily level, take 50% off.
  </div>
);

// =================== LONG-FORM NOTES ===================
const LongNotes = () => (
  <div style={{display: 'flex', flexDirection: 'column', gap: 12}}>
    <div
      contentEditable
      suppressContentEditableWarning
      spellCheck={false}
      style={{
        fontSize: 14, color: TV.text, lineHeight: 1.7,
        padding: '16px 18px', borderRadius: 8,
        border: `1px dashed ${TV.line}`, background: 'rgba(255,255,255,.015)',
        outline: 'none', cursor: 'text',
        minHeight: 260,
        fontFamily: TV.font,
      }}>
      <div style={{fontWeight: 600, marginBottom: 6, color: TV.text}}>How I felt</div>
      <div style={{color: TV.text2, marginBottom: 14}}>
        Calm. No FOMO entering. Saw the setup form on the 15m and waited the full 12 minutes between sweep and CHoCH
        before sizing in. The 4H structure made this obvious in retrospect — every box checked.
      </div>

      <div style={{fontWeight: 600, marginBottom: 6, color: TV.text}}>What I noticed mid-trade</div>
      <div style={{color: TV.text2, marginBottom: 14}}>
        Around 10:30 there was a fast 30-tick wick into the BE stop. Held. The 15m FVG defended it cleanly. Worth
        remembering: a wick is not a flush. Don't move the stop tighter pre-emptively.
      </div>

      <div style={{fontWeight: 600, marginBottom: 6, color: TV.text}}>What I'd do differently</div>
      <div style={{color: TV.text2, marginBottom: 14}}>
        Closed at the daily resistance instead of waiting for the last tick into 71,500. Better to take the obvious exit
        than wait for the last 10 ticks — got lucky on the fill, but rule-of-thumb: when target = daily level, scale
        50% in front of the level.
      </div>

      <div style={{fontWeight: 600, marginBottom: 6, color: TV.text}}>External read</div>
      <div style={{color: TV.text2}}>
        DXY was rolling over on the 1H — tailwind for BTC longs. Funding flat. No major news on the schedule until
        14:30 NY. Conditions were as clean as they get for an Asia → London continuation play.
      </div>
    </div>
    <div style={{fontSize: 11, color: TV.text4, display: 'flex', justifyContent: 'space-between'}}>
      <span>auto-saved · last edit 14m ago</span>
      <span>{`words · 187 · markdown supported · #tags become filterable in Reports`}</span>
    </div>
  </div>
);

// =================== LINKED ITEMS ===================
const LinkedItems = () => {
  const links = [
    {kind: 'Validator session', label: 'val-2026-05-23-094 · BTCUSD · READY 6/6', meta: 'started 09:01 · 5m flow'},
    {kind: 'Daily quiz',        label: 'Quiz #47 · 7/8 · same morning',          meta: 'covered Order Block · FVG · CHoCH'},
    {kind: 'Concept · OB',      label: 'Order Block · mastery 78% (+4 this week)', meta: '12 trades using this concept'},
    {kind: 'Concept · CHoCH',   label: 'BOS / CHoCH · mastery 71%',               meta: '8 trades using this concept'},
    {kind: 'Previous trade',    label: 'BTCUSD · May 19 · win +1.2R',             meta: 'same setup family'},
  ];
  return (
    <div style={{display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10}}>
      {links.map((l, i) => (
        <div key={i} style={{
          padding: 12,
          borderRadius: 6,
          border: `1px solid ${TV.line}`,
          background: TV.panel,
          display: 'flex', alignItems: 'center', gap: 12,
          cursor: 'pointer',
        }}>
          <div style={{width: 6, height: 30, borderRadius: 2, background: TV.accent, opacity: .55}}/>
          <div style={{flex: 1, minWidth: 0}}>
            <div style={{fontSize: 10, color: TV.text3, textTransform: 'uppercase', letterSpacing: '.08em', fontWeight: 600, marginBottom: 2}}>{l.kind}</div>
            <div style={{fontSize: 13, color: TV.text, fontWeight: 500, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap'}}>{l.label}</div>
            <div style={{fontSize: 11, color: TV.text3, marginTop: 1}}>{l.meta}</div>
          </div>
          <span style={{fontSize: 14, color: TV.text3}}>›</span>
        </div>
      ))}
    </div>
  );
};

Object.assign(window, {JournalEntryFull});
