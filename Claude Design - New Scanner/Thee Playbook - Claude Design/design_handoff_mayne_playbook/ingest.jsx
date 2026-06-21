// ingest.jsx — Extraction Review screen (dark hi-fi)
// The state AFTER a summary doc is pasted into Transcript admin and Claude has
// parsed it. Shows what the pipeline pulled OUT of the real "Consolidated
// Trading Plan" (eps 1–4): concepts + definitions, glossary terms, trading
// rules, and sample quiz questions — all derived from the actual document.
// This is the answer to "how does my content get into the app?"

// ============ EXTRACTED DATA — verbatim / derived from the user's PDF ============

const EX_SOURCE = {
  file: 'Consolidated Trading Plan.pdf',
  type: 'Consolidated playbook',
  coverage: 'Episodes 1–4',
  timestamps: 'None — cite by section',
  words: 1180,
  model: 'claude · parsed in 4.2s',
};

// Concepts the extractor pulled. `state` = new | merge (folds into an existing concept).
const EX_CONCEPTS = [
  { name: 'HTF Bias', short: 'Bias', family: 'structure', state: 'merge', conf: 0.97,
    def: 'The directional conclusion drawn from top-down analysis (Weekly → Daily → H4). If Weekly and Daily are bearish, only short setups are valid on lower timeframes — even if the 15m looks bullish.',
    span: '“If the Weekly and Daily are bearish, only look for short setups on lower timeframes, even if the 15-minute chart appears bullish.”',
    from: 'Fundamentals · Determine HTF Bias' },
  { name: 'Dealing Range', short: 'DR', family: 'structure', state: 'merge', conf: 0.98,
    def: 'The most recent significant swing high to swing low (or vice versa). Every market structure break forms a new dealing range. A lick sweep does NOT reset it.',
    span: '“Every time price makes a market structure break (MSB), a new dealing range forms.”',
    from: 'Fundamentals · Map the Dealing Range' },
  { name: 'Equilibrium (EQ)', short: 'EQ', family: 'structure', state: 'new', conf: 0.99,
    def: 'The 50% midpoint of the dealing range. Separates premium from discount. Price at EQ = no action.',
    span: '“Equilibrium: Mark the 50% line to separate the range.”',
    from: 'References · glossary' },
  { name: 'Premium / Discount', short: 'P/D', family: 'structure', state: 'merge', conf: 0.98,
    def: 'Premium = above EQ, the optimal area to short. Discount = below EQ, the optimal area to long. In a bullish bias you only long from discount; the higher low forms there.',
    span: '“If HTF is bullish but price is in the premium → wait. Do not long — the pullback will come.”',
    from: 'Pre-Entry Checklist · Dealing Range' },
  { name: 'Internal Range Liquidity (IRL)', short: 'IRL', family: 'liquidity', state: 'new', conf: 0.96,
    def: 'Liquidity inside the current range — order blocks, FVGs, swing highs/lows within the range. Used for entries, not targets.',
    span: '“Internal Range Liquidity: Inside the range; Used for Entries.”',
    from: 'Locate Liquidity & Entry Zones' },
  { name: 'External Range Liquidity (ERL)', short: 'ERL', family: 'liquidity', state: 'new', conf: 0.96,
    def: 'Liquidity outside the range boundaries (the highs/lows). This is the trade target — never close the full position at internal liquidity.',
    span: '“External Range Liquidity: Outside the range boundaries (Highs/Lows); Used for Targets.”',
    from: 'Locate Liquidity & Entry Zones' },
  { name: 'The Liquidity Cycle', short: 'Cycle', family: 'liquidity', state: 'new', conf: 0.94,
    def: 'Price endlessly rotates Internal → External → New Range → Internal → External. Holds on all timeframes and all assets. If external was just taken, the next target is internal (a new range is forming).',
    span: '“Internal → External → New Range → Internal → External → Repeat.”',
    from: 'Locate Liquidity & Entry Zones' },
  { name: 'Buy / Sell Side Liquidity', short: 'BSL/SSL', family: 'liquidity', state: 'new', conf: 0.95,
    def: 'BSL sits above swing highs and range highs; SSL sits below swing lows and range lows. A long should target buy-side/external above the market; a short, sell-side below.',
    span: '“BSL: Liquidity above swing highs and range highs. SSL: Liquidity below swing lows and range lows.”',
    from: 'References · glossary' },
  { name: 'Market Structure Break (MSB)', short: 'MSB', family: 'structure', state: 'new', conf: 0.97,
    def: 'Price takes out a prior significant high/low in the same direction as the current trend — trend continuation. Each MSB forms a fresh dealing range.',
    span: '“MSB: when price takes out a prior significant high/low in the same direction as the current trend.”',
    from: 'References · glossary' },
  { name: 'Market Structure Shift (MSS)', short: 'MSS', family: 'structure', state: 'new', conf: 0.93,
    def: 'A reversal signal — a lower high or higher low forms against the prevailing trend. Distinct from MSB (continuation). Maps to the CHoCH concept already in the library.',
    span: '“MSS: Market Structure Shift; reversal signal (lower high/higher low formed).”',
    from: 'References · glossary' },
  { name: 'Swing Failure Pattern (SFP)', short: 'SFP', family: 'liquidity', state: 'new', conf: 0.92,
    def: 'A lick sweep with no real displacement — price briefly trades beyond a high/low then snaps back. The range stays intact; it does NOT reset the dealing range.',
    span: '“SFP: lick sweep with no real displacement; range stays.”',
    from: 'References · glossary' },
  { name: 'Order Block', short: 'OB', family: 'entries', state: 'merge', conf: 0.91,
    def: 'Valid order blocks sit at a High Volume Node (HVN); the highest-probability OBs sit at the Point of Control (POC). Used as an internal POI for entries.',
    span: '“Valid OBs are at High Volume Node (HVN); highest setups are OBs that sit at the POC.”',
    from: 'Caspar Tips' },
  { name: 'Fair Value Gap', short: 'FVG', family: 'imbalance', state: 'merge', conf: 0.90,
    def: 'A price imbalance used as an internal POI. Only high-probability when it overlaps a Low Volume Node (LVN).',
    span: '“FVGs: only high-probability if it overlaps with a Low Volume Node (LVN).”',
    from: 'Caspar Tips' },
  { name: 'CVD (Cumulative Volume Delta)', short: 'CVD', family: 'orderflow', state: 'new', conf: 0.88,
    def: 'Order-flow confirmation at a POI. Continuation = CVD flat/up while price holds (buyers in control). Absorption = price ranges while CVD rises (sellers absorbing). Divergence = price higher-low while CVD lower-low (smart-money buyers absorbing retail).',
    span: '“CVD Divergence: Price makes a Higher Low while CVD makes a Lower Low → Bullish.”',
    from: 'CVD' },
];

// Glossary terms lifted straight from the References section.
const EX_GLOSSARY = [
  ['Dealing Range', 'Most recent significant swing high to swing low.'],
  ['EQ / Equilibrium', 'The 50% midpoint of the dealing range.'],
  ['Premium', 'Above EQ; optimal area to SHORT.'],
  ['Discount', 'Below EQ; optimal area to LONG.'],
  ['BSL', 'Buy Side Liquidity — above swing/range highs.'],
  ['SSL', 'Sell Side Liquidity — below swing/range lows.'],
  ['IRL', 'Internal Range Liquidity — inside the range; entries.'],
  ['ERL', 'External Range Liquidity — outside the range; targets.'],
  ['MSB', 'Market Structure Break — continuation.'],
  ['MSS', 'Market Structure Shift — reversal signal.'],
  ['SFP', 'Swing Failure Pattern — lick sweep, range stays.'],
  ['HTF Bias', 'Directional conclusion from the highest timeframe.'],
];

// Trading rules detected — these become rule-based quiz questions + validator criteria.
const EX_RULES = [
  { rule: 'If checklist items are not ticked → NO TRADE. Zero exceptions.', tag: 'Discipline', sev: 'hard' },
  { rule: 'HTF bullish but price in premium → wait. Do not long; the pullback will come.', tag: 'Entry filter', sev: 'hard' },
  { rule: 'Risk:Reward must be ≥ 2:1; 3:1 is better.', tag: 'Risk', sev: 'hard' },
  { rule: 'Target external range liquidity, not internal. Partials at IRL are OK; hold the core.', tag: 'Management', sev: 'soft' },
  { rule: "If you can't point to WHERE price is going → there is no trade.", tag: 'Targeting', sev: 'hard' },
  { rule: 'If HTF bias shifts (MSB against the trade) → reassess immediately.', tag: 'Management', sev: 'soft' },
  { rule: 'A lick sweep does NOT reset the dealing range.', tag: 'Structure', sev: 'soft' },
  { rule: 'Big wicks indicate weakness.', tag: 'Price action', sev: 'soft' },
  { rule: 'Entry TF hierarchy — W→H4, D→H1, H4→M15, H1→M5.', tag: 'Process', sev: 'soft' },
];

// Sample quiz questions Claude can already generate from this doc.
const EX_QUESTIONS = [
  {
    concept: 'Premium / Discount · HTF Bias',
    type: 'Scenario',
    q: 'Weekly and Daily are both bullish, but price has rallied into the premium zone of the daily dealing range. What is the play?',
    options: [
      'Long now — bias is bullish',
      'Wait for the pullback into discount, where the higher low forms',
      'Short the premium against the trend',
      'Skip the asset entirely',
    ],
    correct: 1,
    source: 'Pre-Entry Checklist · Dealing Range',
  },
  {
    concept: 'The Liquidity Cycle',
    type: 'Definition',
    q: 'Price has just swept external range liquidity above the range high. What is the next most likely target?',
    options: [
      'The next external pool higher',
      'Internal range liquidity, as a new range forms',
      'The equilibrium of the old range',
      'There is no target — stand aside',
    ],
    correct: 1,
    source: 'Locate Liquidity & Entry Zones',
  },
  {
    concept: 'Swing Failure Pattern',
    type: 'True / False',
    q: 'Price trades briefly beyond the range high, then snaps back with no displacement. Does this reset the dealing range?',
    options: [
      'Yes — a new range forms from the new high',
      'No — it is a lick sweep / SFP, the range stays intact',
    ],
    correct: 1,
    source: 'References · SFP',
  },
];

// ====================== SCREEN ======================
const IngestReviewHF = () => {
  const counts = {
    concepts: EX_CONCEPTS.length,
    neu: EX_CONCEPTS.filter(c => c.state === 'new').length,
    merge: EX_CONCEPTS.filter(c => c.state === 'merge').length,
    glossary: EX_GLOSSARY.length,
    rules: EX_RULES.length,
  };

  return (
    <div className="tv-frame" style={{display: 'flex', flexDirection: 'column', minHeight: 0}}>
      <TVNav active="Settings"/>

      {/* breadcrumb */}
      <div style={{padding: '10px 28px', borderBottom: `1px solid ${TV.line}`, background: TV.bg,
          display: 'flex', alignItems: 'center', gap: 10, fontSize: 12, color: TV.text3}}>
        <span style={{cursor: 'pointer'}}>Settings</span>
        <span style={{color: TV.text4}}>/</span>
        <span style={{cursor: 'pointer'}}>Documents</span>
        <span style={{color: TV.text4}}>/</span>
        <span style={{color: TV.text}}>Extraction review</span>
        <div style={{flex: 1}}/>
        <span style={{color: TV.text4}}>step 2 of 2 · review before commit</span>
      </div>

      <div style={{padding: '24px 80px 80px', background: TV.bg, display: 'flex', flexDirection: 'column',
          gap: 22, maxWidth: 1180, margin: '0 auto', width: '100%'}}>

        {/* ===== HEADER ===== */}
        <div style={{display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between', gap: 24}}>
          <div>
            <div className="tv-uppercase" style={{marginBottom: 8}}>Transcript ingest · extraction</div>
            <div style={{fontSize: 30, fontWeight: 600, color: TV.text, letterSpacing: '-.4px'}}>Extraction review</div>
            <div style={{fontSize: 14, color: TV.text2, marginTop: 8, maxWidth: 640, lineHeight: 1.5}}>
              Claude read your summary and pulled out the structured knowledge below. Nothing is saved yet —
              review, edit, and commit what's right to the concept library and quiz engine.
            </div>
          </div>
          <span className="tv-chip ok" style={{flexShrink: 0}}><span className="tv-dot"/>Parsed · ready to commit</span>
        </div>

        {/* ===== SOURCE + STAT TILES ===== */}
        <div style={{display: 'grid', gridTemplateColumns: '1.5fr 1fr', gap: 16}}>
          {/* source doc excerpt */}
          <div className="tv-card" style={{padding: 0, overflow: 'hidden', display: 'flex', flexDirection: 'column'}}>
            <div style={{padding: '11px 16px', borderBottom: `1px solid ${TV.line}`, display: 'flex',
                alignItems: 'center', gap: 10, background: TV.panel2}}>
              <span style={{width: 8, height: 8, borderRadius: 2, background: TV.accent}}/>
              <span style={{fontSize: 13, color: TV.text, fontWeight: 600}}>{EX_SOURCE.file}</span>
              <span className="tv-chip adapt" style={{fontSize: 10}}>{EX_SOURCE.type}</span>
              <div style={{flex: 1}}/>
              <span style={{fontSize: 11, color: TV.text3}}>excerpt · highlighted = extracted</span>
            </div>
            <SourceExcerpt/>
          </div>

          {/* meta + stats */}
          <div style={{display: 'flex', flexDirection: 'column', gap: 16}}>
            <div className="tv-card" style={{padding: 16}}>
              <div className="tv-uppercase" style={{marginBottom: 12}}>Source detected</div>
              <div style={{display: 'flex', flexDirection: 'column', gap: 9}}>
                {[
                  ['Type', EX_SOURCE.type],
                  ['Coverage', EX_SOURCE.coverage],
                  ['Timestamps', EX_SOURCE.timestamps],
                  ['Length', `${EX_SOURCE.words.toLocaleString()} words`],
                  ['Processed', EX_SOURCE.model],
                ].map(([k, v]) => (
                  <div key={k} style={{display: 'flex', justifyContent: 'space-between', alignItems: 'baseline'}}>
                    <span style={{fontSize: 12, color: TV.text3}}>{k}</span>
                    <span className="tv-num" style={{fontSize: 13, color: TV.text, fontWeight: 500, textAlign: 'right'}}>{v}</span>
                  </div>
                ))}
              </div>
              <div style={{marginTop: 12, padding: '8px 10px', borderRadius: 5, background: TV.warnSoft,
                  border: `1px solid rgba(224,179,65,.25)`, fontSize: 11.5, color: TV.text2, lineHeight: 1.5}}>
                <span style={{color: TV.warn, fontWeight: 600}}>No timestamps in this source.</span> Citations
                will reference the section heading (e.g. “Pre-Entry Checklist”) instead of an episode timecode.
              </div>
            </div>

            <div style={{display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10}}>
              <StatTile n={counts.concepts} label="concepts" sub={`${counts.neu} new · ${counts.merge} merge`} tone={TV.accent}/>
              <StatTile n={counts.glossary} label="glossary terms" sub="from References" tone={TV.adapt}/>
              <StatTile n={counts.rules} label="trading rules" sub="checklist + discipline" tone={TV.ok}/>
              <StatTile n="~40" label="quiz questions" sub="ready to generate" tone={TV.warn}/>
            </div>
          </div>
        </div>

        {/* ===== CONCEPTS EXTRACTED ===== */}
        <IngestSection
          label="Concepts extracted"
          right={
            <div style={{display: 'flex', alignItems: 'center', gap: 10, fontSize: 12, color: TV.text3}}>
              <span className="tv-chip accent" style={{fontSize: 10}}>{counts.neu} new</span>
              <span className="tv-chip" style={{fontSize: 10}}>{counts.merge} merge into existing</span>
              <span style={{cursor: 'pointer', color: TV.text2}}>Accept all</span>
            </div>
          }
          summary="Each is editable before commit. “Merge” folds new detail into a concept already in your library; “New” creates a fresh entry."
        >
          <div style={{display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12}}>
            {EX_CONCEPTS.map(c => <ConceptExtractCard key={c.name} c={c}/>)}
          </div>
        </IngestSection>

        {/* ===== GLOSSARY + RULES (two col) ===== */}
        <div style={{display: 'grid', gridTemplateColumns: '1fr 1.25fr', gap: 22}}>
          <IngestSection label="Glossary terms" summary="Lifted from the References section — seed every definition.">
            <div className="tv-card" style={{padding: 0, overflow: 'hidden'}}>
              {EX_GLOSSARY.map(([term, def], i) => (
                <div key={term} style={{display: 'grid', gridTemplateColumns: '120px 1fr', gap: 12,
                    padding: '9px 14px', borderBottom: i < EX_GLOSSARY.length - 1 ? `1px solid ${TV.lineSoft}` : 'none',
                    alignItems: 'baseline'}}>
                  <span style={{fontSize: 12.5, color: TV.text, fontWeight: 600}}>{term}</span>
                  <span style={{fontSize: 12.5, color: TV.text2, lineHeight: 1.45}}>{def}</span>
                </div>
              ))}
            </div>
          </IngestSection>

          <IngestSection label="Trading rules detected" summary="Become rule-based quiz questions and validator criteria.">
            <div style={{display: 'flex', flexDirection: 'column', gap: 8}}>
              {EX_RULES.map((r, i) => (
                <div key={i} style={{display: 'flex', alignItems: 'flex-start', gap: 12, padding: '10px 14px',
                    borderRadius: 6, background: TV.panel, border: `1px solid ${TV.line}`}}>
                  <span style={{width: 6, height: 6, borderRadius: '50%', marginTop: 6, flexShrink: 0,
                      background: r.sev === 'hard' ? TV.fail : TV.warn}}/>
                  <span style={{flex: 1, fontSize: 13, color: TV.text, lineHeight: 1.5}}>{r.rule}</span>
                  <span className="tv-chip" style={{fontSize: 10, flexShrink: 0}}>{r.tag}</span>
                </div>
              ))}
              <div style={{fontSize: 11, color: TV.text4, paddingLeft: 14, display: 'flex', gap: 14}}>
                <span><span style={{color: TV.fail}}>●</span> hard rule (NO TRADE)</span>
                <span><span style={{color: TV.warn}}>●</span> soft / management</span>
              </div>
            </div>
          </IngestSection>
        </div>

        {/* ===== SAMPLE QUIZ QUESTIONS ===== */}
        <IngestSection
          label="Sample quiz questions"
          right={<span style={{fontSize: 12, color: TV.text3}}>generated live from this doc · no placeholders</span>}
          summary="A preview of what tomorrow's daily quiz can draw from. Every question traces back to a section of your summary."
        >
          <div style={{display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12}}>
            {EX_QUESTIONS.map((q, i) => <SampleQuestion key={i} q={q} n={i + 1}/>)}
          </div>
        </IngestSection>

        {/* ===== COMMIT FOOTER ===== */}
        <div style={{position: 'sticky', bottom: 0, display: 'flex', alignItems: 'center', gap: 14,
            padding: '16px 20px', borderRadius: 10, background: TV.panel2, border: `1px solid ${TV.line}`,
            boxShadow: '0 -8px 24px rgba(0,0,0,.35)'}}>
          <div style={{display: 'flex', flexDirection: 'column'}}>
            <span style={{fontSize: 14, color: TV.text, fontWeight: 600}}>
              Commit <span className="tv-num">{counts.concepts}</span> concepts ·
              <span className="tv-num"> {counts.rules}</span> rules ·
              <span className="tv-num"> {counts.glossary}</span> definitions
            </span>
            <span style={{fontSize: 12, color: TV.text3}}>
              {counts.neu} new concepts created · {counts.merge} merged into existing · quiz pool grows by ~40 questions
            </span>
          </div>
          <div style={{flex: 1}}/>
          <button className="tv-btn ghost" style={{fontSize: 13}}>Discard</button>
          <button className="tv-btn ghost" style={{fontSize: 13}}>Edit before commit</button>
          <button className="tv-btn primary" style={{fontSize: 13, padding: '9px 18px'}}>Commit to library →</button>
        </div>
      </div>
    </div>
  );
};

// ====================== SUB-COMPONENTS ======================

const IngestSection = ({label, summary, right, children}) => (
  <section>
    <div style={{display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: 16,
        marginBottom: summary ? 4 : 12}}>
      <div style={{fontSize: 14, fontWeight: 600, color: TV.text, letterSpacing: '.02em', textTransform: 'uppercase'}}>{label}</div>
      {right}
    </div>
    {summary && <div style={{fontSize: 12, color: TV.text3, marginBottom: 14, maxWidth: 760}}>{summary}</div>}
    {children}
  </section>
);

const StatTile = ({n, label, sub, tone}) => (
  <div className="tv-card" style={{padding: 14, display: 'flex', flexDirection: 'column', gap: 2}}>
    <div className="tv-num" style={{fontSize: 26, fontWeight: 700, color: tone, letterSpacing: '-.5px', lineHeight: 1}}>{n}</div>
    <div style={{fontSize: 12, color: TV.text, fontWeight: 500, marginTop: 4}}>{label}</div>
    <div style={{fontSize: 11, color: TV.text3}}>{sub}</div>
  </div>
);

const ConceptExtractCard = ({c}) => {
  const isNew = c.state === 'new';
  return (
    <div className="tv-card" style={{padding: 14, display: 'flex', flexDirection: 'column', gap: 8}}>
      <div style={{display: 'flex', alignItems: 'center', gap: 8}}>
        <span style={{fontSize: 14.5, color: TV.text, fontWeight: 600}}>{c.name}</span>
        <span style={{fontSize: 10, color: TV.text4, padding: '1px 5px', borderRadius: 3,
            background: TV.panel2, textTransform: 'capitalize'}}>{c.family}</span>
        <div style={{flex: 1}}/>
        <span className={isNew ? 'tv-chip accent' : 'tv-chip adapt'} style={{fontSize: 10}}>
          {isNew ? 'NEW' : 'MERGE'}
        </span>
      </div>

      <div style={{fontSize: 13, color: TV.text2, lineHeight: 1.55}}>{c.def}</div>

      {/* source span */}
      <div style={{fontSize: 11.5, color: TV.text3, lineHeight: 1.5, paddingLeft: 10,
          borderLeft: `2px solid ${TV.line}`, fontStyle: 'italic'}}>
        {c.span}
      </div>

      <div style={{display: 'flex', alignItems: 'center', gap: 10, marginTop: 2}}>
        <span style={{fontSize: 11, color: TV.text4}}>↳ {c.from}</span>
        <div style={{flex: 1}}/>
        {/* confidence */}
        <div style={{display: 'flex', alignItems: 'center', gap: 6}}>
          <div style={{width: 44, height: 4, background: TV.panel3, borderRadius: 2, overflow: 'hidden'}}>
            <div style={{height: '100%', width: `${c.conf * 100}%`,
                background: c.conf > 0.95 ? TV.ok : c.conf > 0.9 ? TV.warn : TV.text3}}/>
          </div>
          <span className="tv-num" style={{fontSize: 10, color: TV.text3}}>{Math.round(c.conf * 100)}%</span>
        </div>
        <span style={{fontSize: 11, color: TV.text3, cursor: 'pointer'}}>edit ✎</span>
      </div>
    </div>
  );
};

const SampleQuestion = ({q, n}) => (
  <div className="tv-card" style={{padding: 14, display: 'flex', flexDirection: 'column', gap: 10}}>
    <div style={{display: 'flex', alignItems: 'center', gap: 8}}>
      <span style={{fontSize: 11, color: TV.text3, fontWeight: 600}}>Q{n}</span>
      <span className="tv-chip" style={{fontSize: 10}}>{q.type}</span>
      <div style={{flex: 1}}/>
    </div>
    <div style={{fontSize: 10, color: TV.accent, fontWeight: 600, letterSpacing: '.06em', textTransform: 'uppercase'}}>{q.concept}</div>
    <div style={{fontSize: 13.5, color: TV.text, lineHeight: 1.5, fontWeight: 500}}>{q.q}</div>
    <div style={{display: 'flex', flexDirection: 'column', gap: 6, marginTop: 2}}>
      {q.options.map((o, i) => {
        const right = i === q.correct;
        return (
          <div key={i} style={{display: 'flex', alignItems: 'flex-start', gap: 8, padding: '7px 10px',
              borderRadius: 5, fontSize: 12.5, lineHeight: 1.4,
              background: right ? TV.okSoft : TV.panel2,
              border: `1px solid ${right ? 'rgba(63,178,127,.35)' : TV.lineSoft}`,
              color: right ? TV.text : TV.text2}}>
            <span style={{width: 16, height: 16, borderRadius: 3, flexShrink: 0, marginTop: 1,
                display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 10, fontWeight: 700,
                background: right ? TV.ok : 'transparent', color: right ? '#0d1018' : TV.text4,
                border: right ? 'none' : `1px solid ${TV.line}`}}>
              {right ? '✓' : String.fromCharCode(65 + i)}
            </span>
            <span>{o}</span>
          </div>
        );
      })}
    </div>
    <div style={{fontSize: 11, color: TV.text4, marginTop: 2}}>↳ source · {q.source}</div>
  </div>
);

// Source excerpt with highlighted (extracted) spans.
const HL = ({children, tone = TV.accent}) => (
  <span style={{background: tone === TV.accent ? TV.accentSoft : TV.adaptSoft,
      color: TV.text, borderRadius: 2, padding: '0 2px',
      boxShadow: `inset 0 -1px 0 ${tone}`}}>{children}</span>
);

const SourceExcerpt = () => (
  <div style={{padding: '14px 16px', fontSize: 12.5, color: TV.text2, lineHeight: 1.7,
      overflow: 'hidden', position: 'relative', maxHeight: 470}}>
    <div style={{fontWeight: 700, color: TV.text3, fontSize: 11, letterSpacing: '.08em',
        textTransform: 'uppercase', marginBottom: 6}}>Pre-Entry Checklist</div>
    <p style={{margin: '0 0 10px'}}>
      Is the overall <HL>HTF structure</HL> bullish or bearish? Where was the most recent
      market structure break — this dictates trading direction. What's the current
      <HL> dealing range</HL> and where is price within it? Are we in the
      <HL tone={TV.adapt}> discount</HL> (below EQ → acceptable for longs) or the
      <HL tone={TV.adapt}> premium</HL> (above EQ → acceptable for shorts)?
    </p>
    <p style={{margin: '0 0 10px'}}>
      What liquidity was JUST taken out — <HL>internal or external</HL>, buy side or sell side?
      What's the NEXT most likely target? If we just took internal → next target is external.
      If we just took external → next target is internal (a <HL>new range</HL> forms).
    </p>
    <div style={{fontWeight: 700, color: TV.text3, fontSize: 11, letterSpacing: '.08em',
        textTransform: 'uppercase', margin: '14px 0 6px'}}>References</div>
    <p style={{margin: 0}}>
      <HL>MSB</HL>: Market Structure Break; price takes out a prior significant high/low in the same
      direction as the trend. <HL>MSS</HL>: Market Structure Shift; reversal signal. <HL>SFP</HL>:
      Swing Failure Pattern; lick sweep with no real displacement; range stays. <HL tone={TV.adapt}>IRL</HL> /
      <HL tone={TV.adapt}>ERL</HL>: internal vs external range liquidity…
    </p>
    {/* fade */}
    <div style={{position: 'absolute', left: 0, right: 0, bottom: 0, height: 80,
        background: `linear-gradient(transparent, ${TV.panel})`, pointerEvents: 'none'}}/>
    <div style={{position: 'absolute', bottom: 10, left: 0, right: 0, textAlign: 'center',
        fontSize: 11, color: TV.text3}}>+ 980 more words</div>
  </div>
);

Object.assign(window, {IngestReviewHF});
