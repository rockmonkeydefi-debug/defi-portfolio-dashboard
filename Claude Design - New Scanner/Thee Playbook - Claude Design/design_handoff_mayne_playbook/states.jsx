// states.jsx — Empty / loading / error states across screens
// Single artboard with a grid of compact state mocks for handoff/QA reference.

const StatesHF = () => (
  <div className="tv-frame" style={{display: 'flex', flexDirection: 'column'}}>
    <TVNav active="States"/>

    <div style={{flex: 1, overflow: 'auto', padding: '20px 28px'}}>
      <div style={{marginBottom: 18}}>
        <div className="tv-uppercase">States library</div>
        <div style={{fontSize: 22, fontWeight: 600, color: TV.text, marginTop: 4}}>
          Empty · Loading · Error
        </div>
        <div style={{fontSize: 13, color: TV.text3, marginTop: 4}}>
          Reference patterns for every primary screen. Same TV.* tokens as the live screens; drop these in when the page has no data yet, is fetching, or hit an error.
        </div>
      </div>

      <div style={{display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 14}}>

        {/* ---- EMPTY ---- */}
        <StateGroup label="Empty">
          <StateCard title="Dashboard · first install"
              context="Day 1, no transcripts ingested yet.">
            <EmptyDashboardState/>
          </StateCard>
          <StateCard title="Journal · no entries"
              context="No trades or quizzes recorded.">
            <EmptyJournalState/>
          </StateCard>
          <StateCard title="Scanner · empty watchlist"
              context="Watchlist has no tickers.">
            <EmptyScannerState/>
          </StateCard>
          <StateCard title="Concept library · no transcripts"
              context="Concept set is empty until first ingest.">
            <EmptyConceptsState/>
          </StateCard>
        </StateGroup>

        {/* ---- LOADING ---- */}
        <StateGroup label="Loading">
          <StateCard title="Quiz · generating"
              context="06:00 cron is composing today's quiz.">
            <LoadingQuizState/>
          </StateCard>
          <StateCard title="Transcript · saving"
              context="Pasted transcript is being saved & concepts extracted.">
            <LoadingTranscriptState/>
          </StateCard>
          <StateCard title="Scanner · scanning"
              context="Mid-scan sweep across watchlist.">
            <LoadingScannerState/>
          </StateCard>
          <StateCard title="Reports · computing"
              context="Switching range to Lifetime — recomputing.">
            <LoadingReportsState/>
          </StateCard>
        </StateGroup>

        {/* ---- ERROR ---- */}
        <StateGroup label="Error">
          <StateCard title="Scanner · offline"
              context="Market data feed unreachable.">
            <ErrorScannerState/>
          </StateCard>
          <StateCard title="Quiz · Claude API failed"
              context="Generation errored — fall back to retry.">
            <ErrorQuizState/>
          </StateCard>
          <StateCard title="Transcript · parse failed"
              context="Pasted content didn't parse as a transcript.">
            <ErrorTranscriptState/>
          </StateCard>
          <StateCard title="Validator · no transcripts"
              context="Can't run validation without concept corpus.">
            <ErrorValidatorState/>
          </StateCard>
        </StateGroup>

      </div>
    </div>
  </div>
);

// ---------- shells ----------
const StateGroup = ({label, children}) => (
  <div style={{display: 'flex', flexDirection: 'column', gap: 14}}>
    <div className="tv-uppercase" style={{
      padding: '6px 10px', background: TV.panel2, borderRadius: 4,
      border: `1px solid ${TV.line}`, color: TV.text, textAlign: 'center',
    }}>{label}</div>
    {children}
  </div>
);

const StateCard = ({title, context, children}) => (
  <div className="tv-card" style={{padding: 0, overflow: 'hidden'}}>
    <div style={{padding: '10px 14px', borderBottom: `1px solid ${TV.line}`, background: TV.panel2}}>
      <div style={{fontSize: 13, fontWeight: 600, color: TV.text}}>{title}</div>
      <div style={{fontSize: 11, color: TV.text3, marginTop: 2}}>{context}</div>
    </div>
    <div style={{padding: 16, minHeight: 200}}>{children}</div>
  </div>
);

// ---------- empty state mocks ----------
const EmptyDashboardState = () => (
  <div style={{display: 'flex', flexDirection: 'column', alignItems: 'center', textAlign: 'center', gap: 12, padding: '12px 0'}}>
    <div style={{
      width: 52, height: 52, borderRadius: 10, border: `1.5px dashed ${TV.line}`,
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      fontSize: 24, color: TV.text3,
    }}>📚</div>
    <div style={{fontSize: 15, fontWeight: 600, color: TV.text}}>No quizzes yet</div>
    <div style={{fontSize: 12, color: TV.text2, maxWidth: 280, lineHeight: 1.5}}>
      Paste your first transcript to ingest concepts. Once you have at least one episode loaded, a daily quiz will be generated at 06:00 UTC.
    </div>
    <button className="tv-btn primary" style={{padding: '7px 14px', fontSize: 13}}>Add transcript →</button>
  </div>
);

const EmptyJournalState = () => (
  <div style={{display: 'flex', flexDirection: 'column', alignItems: 'center', textAlign: 'center', gap: 12, padding: '12px 0'}}>
    <div style={{
      width: 52, height: 52, borderRadius: 10, border: `1.5px dashed ${TV.line}`,
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      fontSize: 22, color: TV.text3,
    }}>📓</div>
    <div style={{fontSize: 15, fontWeight: 600, color: TV.text}}>Journal is empty</div>
    <div style={{fontSize: 12, color: TV.text2, maxWidth: 280, lineHeight: 1.5}}>
      Validator summaries and completed quizzes land here automatically. Run your first validator session or finish a quiz to start the record.
    </div>
    <div style={{display: 'flex', gap: 8}}>
      <button className="tv-btn primary" style={{padding: '7px 14px', fontSize: 13}}>Open validator →</button>
      <button className="tv-btn" style={{padding: '7px 14px', fontSize: 13}}>Start a quiz →</button>
    </div>
  </div>
);

const EmptyScannerState = () => (
  <div style={{display: 'flex', flexDirection: 'column', alignItems: 'center', textAlign: 'center', gap: 12, padding: '12px 0'}}>
    <div style={{
      width: 52, height: 52, borderRadius: 10, border: `1.5px dashed ${TV.line}`,
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      fontSize: 22, color: TV.text3,
    }}>📡</div>
    <div style={{fontSize: 15, fontWeight: 600, color: TV.text}}>No tickers to scan</div>
    <div style={{fontSize: 12, color: TV.text2, maxWidth: 300, lineHeight: 1.5}}>
      Add tickers in Settings → Watchlist. Bulk-import a preset (Crypto majors, FX majors, Index futures) or paste your own list.
    </div>
    <div style={{display: 'flex', gap: 8}}>
      <button className="tv-btn primary" style={{padding: '7px 14px', fontSize: 13}}>Add tickers →</button>
      <button className="tv-btn" style={{padding: '7px 14px', fontSize: 13}}>Load preset</button>
    </div>
  </div>
);

const EmptyConceptsState = () => (
  <div style={{display: 'flex', flexDirection: 'column', alignItems: 'center', textAlign: 'center', gap: 12, padding: '12px 0'}}>
    <div style={{
      width: 52, height: 52, borderRadius: 10, border: `1.5px dashed ${TV.line}`,
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      fontSize: 22, color: TV.text3,
    }}>🧩</div>
    <div style={{fontSize: 15, fontWeight: 600, color: TV.text}}>No concepts yet</div>
    <div style={{fontSize: 12, color: TV.text2, maxWidth: 300, lineHeight: 1.5}}>
      Concepts are extracted from your ingested transcripts. Paste a Mayne episode in Transcript admin and Claude will pull definitions, examples, and tagged segments.
    </div>
    <button className="tv-btn primary" style={{padding: '7px 14px', fontSize: 13}}>Open transcripts →</button>
  </div>
);

// ---------- loading state mocks ----------
const Shimmer = ({width = '100%', height = 12}) => (
  <div style={{
    width, height,
    background: `linear-gradient(90deg, ${TV.panel2} 0%, ${TV.panel3} 50%, ${TV.panel2} 100%)`,
    backgroundSize: '200% 100%',
    borderRadius: 3,
    animation: 'shimmer 1.4s infinite',
  }}/>
);

const LoadingQuizState = () => (
  <div style={{display: 'flex', flexDirection: 'column', gap: 10}}>
    <style>{`@keyframes shimmer { 0% { background-position: -100% 0; } 100% { background-position: 100% 0; } }`}</style>
    <div style={{display: 'flex', alignItems: 'center', gap: 8}}>
      <Spinner color={TV.accent}/>
      <span style={{fontSize: 13, color: TV.text, fontWeight: 500}}>Composing today's quiz…</span>
    </div>
    <div style={{fontSize: 11, color: TV.text3}}>
      Claude is weighting toward Order Block & FVG · ~10s remaining
    </div>
    <div style={{padding: 12, borderRadius: 6, background: TV.panel2, border: `1px solid ${TV.lineSoft}`,
        display: 'flex', flexDirection: 'column', gap: 8}}>
      <Shimmer width="60%" height={14}/>
      <Shimmer width="100%" height={10}/>
      <Shimmer width="90%" height={10}/>
      <Shimmer width="70%" height={10}/>
    </div>
    <div style={{display: 'flex', gap: 6, fontSize: 11, color: TV.text3}}>
      <span>✓ sourced eps 14, 18, 22</span>
      <span style={{color: TV.text4}}>·</span>
      <span>generating 8 questions</span>
    </div>
  </div>
);

const LoadingTranscriptState = () => (
  <div style={{display: 'flex', flexDirection: 'column', gap: 10}}>
    <div style={{display: 'flex', alignItems: 'center', gap: 8}}>
      <Spinner color={TV.accent}/>
      <span style={{fontSize: 13, color: TV.text, fontWeight: 500}}>Saving transcript &amp; extracting concepts…</span>
    </div>
    <ProgressLine pct={62} label="Parsing transcript"/>
    <ProgressLine pct={48} label="Extracting concepts"/>
    <ProgressLine pct={20} label="Indexing for quiz generation"/>
    <div style={{fontSize: 11, color: TV.text3}}>~25s remaining · don't close the tab</div>
  </div>
);

const LoadingScannerState = () => (
  <div style={{display: 'flex', flexDirection: 'column', gap: 10}}>
    <div style={{display: 'flex', alignItems: 'center', gap: 8}}>
      <Spinner color={TV.accent}/>
      <span style={{fontSize: 13, color: TV.text, fontWeight: 500}}>Scanning watchlist…</span>
      <div style={{flex: 1}}/>
      <span className="tv-num" style={{fontSize: 11, color: TV.text3}}>7 of 12</span>
    </div>
    <div style={{height: 4, background: TV.panel3, borderRadius: 2, overflow: 'hidden'}}>
      <div style={{height: '100%', width: '58%', background: TV.accent}}/>
    </div>
    <div style={{display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 6}}>
      {['BTC','ETH','ES','TSLA','AAPL','NQ','GOLD','EUR','GBP'].map((s,i) => (
        <div key={s} style={{
          padding: '6px 8px', borderRadius: 4, background: TV.panel2, border: `1px solid ${TV.lineSoft}`,
          display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 6,
        }}>
          <span className="tv-num" style={{fontSize: 11, fontWeight: 600, color: TV.text}}>{s}</span>
          {i < 7
            ? <span style={{fontSize: 10, color: TV.ok}}>✓</span>
            : <Spinner size={10} color={TV.text3}/>}
        </div>
      ))}
    </div>
  </div>
);

const LoadingReportsState = () => (
  <div style={{display: 'flex', flexDirection: 'column', gap: 10}}>
    <div style={{display: 'flex', alignItems: 'center', gap: 8}}>
      <Spinner color={TV.accent}/>
      <span style={{fontSize: 13, color: TV.text, fontWeight: 500}}>Recomputing analytics…</span>
    </div>
    <div style={{fontSize: 11, color: TV.text3}}>187 trades · 48 quizzes · range = Lifetime</div>
    <div style={{display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 6}}>
      {[0,1,2,3].map(i => (
        <div key={i} style={{padding: 10, borderRadius: 5, background: TV.panel2, border: `1px solid ${TV.lineSoft}`,
            display: 'flex', flexDirection: 'column', gap: 4}}>
          <Shimmer width="60%" height={8}/>
          <Shimmer width="90%" height={18}/>
        </div>
      ))}
    </div>
    <Shimmer width="100%" height={64}/>
  </div>
);

// ---------- error state mocks ----------
const ErrorScannerState = () => (
  <div style={{display: 'flex', flexDirection: 'column', gap: 12,
      padding: 14, border: `1px solid ${TV.fail}`, background: TV.failSoft, borderRadius: 6}}>
    <div style={{display: 'flex', alignItems: 'center', gap: 8}}>
      <ErrorBadge/>
      <span style={{fontSize: 14, fontWeight: 600, color: TV.text}}>Scanner offline</span>
      <div style={{flex: 1}}/>
      <span className="tv-num" style={{fontSize: 11, color: TV.text3}}>14:22:08 UTC</span>
    </div>
    <div style={{fontSize: 12, color: TV.text2, lineHeight: 1.55}}>
      Market data feed timed out after 30s. No fresh signals are being produced; the table shows the last successful scan.
    </div>
    <div className="tv-num" style={{fontSize: 11, color: TV.text3, padding: '6px 8px',
        background: TV.bg, borderRadius: 4, border: `1px solid ${TV.lineSoft}`}}>
      ECONNRESET · upstream tradingview-md · retry 3 of 5
    </div>
    <div style={{display: 'flex', gap: 8}}>
      <button className="tv-btn" style={{padding: '6px 12px', fontSize: 12}}>↻ Retry now</button>
      <button className="tv-btn ghost" style={{padding: '6px 12px', fontSize: 12}}>View status</button>
    </div>
  </div>
);

const ErrorQuizState = () => (
  <div style={{display: 'flex', flexDirection: 'column', gap: 12,
      padding: 14, border: `1px solid ${TV.warn}`, background: TV.warnSoft, borderRadius: 6}}>
    <div style={{display: 'flex', alignItems: 'center', gap: 8}}>
      <ErrorBadge color={TV.warn}/>
      <span style={{fontSize: 14, fontWeight: 600, color: TV.text}}>Quiz generation failed</span>
    </div>
    <div style={{fontSize: 12, color: TV.text2, lineHeight: 1.55}}>
      Claude API returned 429 (rate limited) at 06:00. Today's quiz wasn't created. Streak is paused — not broken.
    </div>
    <div className="tv-num" style={{fontSize: 11, color: TV.text3, padding: '6px 8px',
        background: TV.bg, borderRadius: 4, border: `1px solid ${TV.lineSoft}`}}>
      anthropic-rate-limit-error · retry-after 47s
    </div>
    <div style={{display: 'flex', gap: 8}}>
      <button className="tv-btn primary" style={{padding: '6px 12px', fontSize: 12}}>↻ Regenerate</button>
      <button className="tv-btn" style={{padding: '6px 12px', fontSize: 12}}>Skip today</button>
    </div>
  </div>
);

const ErrorTranscriptState = () => (
  <div style={{display: 'flex', flexDirection: 'column', gap: 12,
      padding: 14, border: `1px solid ${TV.warn}`, background: TV.warnSoft, borderRadius: 6}}>
    <div style={{display: 'flex', alignItems: 'center', gap: 8}}>
      <ErrorBadge color={TV.warn}/>
      <span style={{fontSize: 14, fontWeight: 600, color: TV.text}}>Couldn't parse transcript</span>
    </div>
    <div style={{fontSize: 12, color: TV.text2, lineHeight: 1.55}}>
      The text you pasted doesn't look like a transcript. We didn't find time-stamps or coherent paragraphs to extract concepts from.
    </div>
    <div className="tv-num" style={{fontSize: 11, color: TV.text2, padding: '6px 8px',
        background: TV.bg, borderRadius: 4, border: `1px solid ${TV.lineSoft}`}}>
      detected · 12 lines · 0 timestamps · 0 quoted definitions
    </div>
    <div style={{display: 'flex', gap: 8}}>
      <button className="tv-btn" style={{padding: '6px 12px', fontSize: 12}}>Edit &amp; retry</button>
      <button className="tv-btn ghost" style={{padding: '6px 12px', fontSize: 12}}>Save anyway</button>
    </div>
  </div>
);

const ErrorValidatorState = () => (
  <div style={{display: 'flex', flexDirection: 'column', gap: 12,
      padding: 14, border: `1px solid ${TV.line}`, background: TV.panel2, borderRadius: 6}}>
    <div style={{display: 'flex', alignItems: 'center', gap: 8}}>
      <ErrorBadge color={TV.text3}/>
      <span style={{fontSize: 14, fontWeight: 600, color: TV.text}}>Validator unavailable</span>
    </div>
    <div style={{fontSize: 12, color: TV.text2, lineHeight: 1.55}}>
      The validator references concepts from your transcript corpus. None are ingested yet, so the question flow has nothing to validate against.
    </div>
    <button className="tv-btn primary" style={{padding: '6px 12px', fontSize: 12, alignSelf: 'flex-start'}}>Ingest first transcript →</button>
  </div>
);

// ---------- shared ----------
const Spinner = ({size = 14, color = TV.accent}) => (
  <svg width={size} height={size} viewBox="0 0 24 24">
    <style>{`@keyframes spinner-rot { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }`}</style>
    <circle cx="12" cy="12" r="9" fill="none" stroke={TV.lineSoft} strokeWidth="2.5"/>
    <path d="M 12 3 A 9 9 0 0 1 21 12" fill="none" stroke={color} strokeWidth="2.5" strokeLinecap="round"
          style={{transformOrigin: 'center', animation: 'spinner-rot 1s linear infinite'}}/>
  </svg>
);

const ErrorBadge = ({color}) => {
  const c = color || TV.fail;
  return (
    <div style={{
      width: 22, height: 22, borderRadius: '50%',
      background: c === TV.fail ? TV.failSoft : c === TV.warn ? TV.warnSoft : TV.panel3,
      border: `1px solid ${c}`,
      color: c, fontWeight: 700, fontSize: 13,
      display: 'flex', alignItems: 'center', justifyContent: 'center',
    }}>!</div>
  );
};

const ProgressLine = ({pct, label}) => (
  <div>
    <div style={{display: 'flex', justifyContent: 'space-between', fontSize: 11, color: TV.text3, marginBottom: 3}}>
      <span>{label}</span>
      <span className="tv-num">{pct}%</span>
    </div>
    <div style={{height: 4, background: TV.panel3, borderRadius: 2, overflow: 'hidden'}}>
      <div style={{height: '100%', width: `${pct}%`, background: TV.accent,
          transition: 'width .2s'}}/>
    </div>
  </div>
);

Object.assign(window, {StatesHF});
