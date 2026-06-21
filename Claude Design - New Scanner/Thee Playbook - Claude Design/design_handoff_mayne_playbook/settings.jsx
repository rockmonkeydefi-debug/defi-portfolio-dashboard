// settings.jsx — Settings screen (dark hi-fi)
// Left rail sections, right detail. Auto-save UX with subtle saved indicator.

const SETTINGS_SECTIONS = [
  {id: 'schedule',   label: 'Schedule',         hint: 'Daily quiz time, length'},
  {id: 'watchlist',  label: 'Watchlist',        hint: 'Tickers, timeframes'},
  {id: 'validator',  label: 'Validator',        hint: 'Thresholds, defaults'},
  {id: 'quiz',       label: 'Quiz preferences', hint: 'Types, weighting'},
  {id: 'concepts',   label: 'Concepts',         hint: 'Mastery thresholds'},
  {id: 'transcripts',label: 'Documents',        hint: 'Upload & manage source docs'},
  {id: 'account',    label: 'Account',          hint: 'Password, API keys'},
  {id: 'data',       label: 'Data',             hint: 'Export, backup, reset'},
];

const SettingsHF = () => {
  const [section, setSection] = React.useState('schedule');

  return (
    <div className="tv-frame" style={{display: 'flex', flexDirection: 'column'}}>
      <TVNav active="Trading Settings"/>
      <TTSubNav active="Trading Settings"/>

      <div style={{flex: 1, display: 'flex', minHeight: 0, overflow: 'hidden'}}>
        {/* LEFT RAIL */}
        <div style={{width: 260, borderRight: `1px solid ${TV.line}`, background: TV.panel,
            display: 'flex', flexDirection: 'column', minHeight: 0, overflow: 'hidden'}}>
          <div style={{padding: '18px 18px 12px', borderBottom: `1px solid ${TV.line}`}}>
            <div className="tv-uppercase">Settings</div>
            <div style={{fontSize: 18, fontWeight: 600, color: TV.text, marginTop: 4}}>Configuration</div>
          </div>
          <div style={{flex: 1, overflow: 'auto', padding: '8px 8px'}}>
            {SETTINGS_SECTIONS.map(s => {
              const sel = section === s.id;
              return (
                <div key={s.id} onClick={() => setSection(s.id)} style={{
                  padding: '10px 12px', borderRadius: 5, marginBottom: 2, cursor: 'pointer',
                  background: sel ? TV.panel3 : 'transparent',
                  borderLeft: sel ? `2px solid ${TV.accent}` : '2px solid transparent',
                }}>
                  <div style={{fontSize: 14, color: sel ? TV.text : TV.text2, fontWeight: sel ? 600 : 500}}>{s.label}</div>
                  <div style={{fontSize: 11, color: TV.text3, marginTop: 1}}>{s.hint}</div>
                </div>
              );
            })}
          </div>
          <div style={{padding: '10px 14px', borderTop: `1px solid ${TV.line}`, background: TV.panel2,
              fontSize: 11, color: TV.text3, display: 'flex', alignItems: 'center', gap: 8}}>
            <span style={{width: 6, height: 6, borderRadius: '50%', background: TV.ok}}/>
            All changes auto-saved
          </div>
        </div>

        {/* RIGHT — selected section content */}
        <div style={{flex: 1, overflow: 'auto', minHeight: 0}}>
          {section === 'schedule'   && <SchedulePanel/>}
          {section === 'watchlist'  && <WatchlistPanel/>}
          {section === 'validator'  && <ValidatorPanel/>}
          {section === 'quiz'       && <QuizPanel/>}
          {section === 'concepts'   && <ConceptsPanel/>}
          {section === 'transcripts'&& <TranscriptsPanel/>}
          {section === 'account'    && <AccountPanel/>}
          {section === 'data'       && <DataPanel/>}
        </div>
      </div>
    </div>
  );
};

// ============================================
// Shared form primitives
// ============================================
const SectionHeader = ({title, subtitle}) => (
  <div style={{padding: '20px 32px 16px', borderBottom: `1px solid ${TV.line}`}}>
    <div className="tv-uppercase">Settings · {title.toLowerCase()}</div>
    <div style={{fontSize: 22, fontWeight: 600, color: TV.text, marginTop: 4}}>{title}</div>
    {subtitle && <div style={{fontSize: 13, color: TV.text3, marginTop: 4, maxWidth: 720}}>{subtitle}</div>}
  </div>
);

const Group = ({title, children}) => (
  <div style={{padding: '20px 32px', borderBottom: `1px solid ${TV.line}`}}>
    {title && <div className="tv-uppercase" style={{marginBottom: 14}}>{title}</div>}
    {children}
  </div>
);

const Row = ({label, desc, children}) => (
  <div style={{display: 'grid', gridTemplateColumns: '300px 1fr', gap: 28, padding: '12px 0',
      borderBottom: `1px solid ${TV.lineSoft}`, alignItems: 'center'}}>
    <div>
      <div style={{fontSize: 14, color: TV.text, fontWeight: 500}}>{label}</div>
      {desc && <div style={{fontSize: 12, color: TV.text3, marginTop: 3, lineHeight: 1.45}}>{desc}</div>}
    </div>
    <div style={{display: 'flex', alignItems: 'center', gap: 10}}>{children}</div>
  </div>
);

const TextField = ({value, width = 200, placeholder, mono}) => (
  <div className="tv-card" style={{padding: '8px 12px', background: TV.panel2, width, fontSize: 14, color: TV.text,
      fontFamily: mono ? TV.font : TV.font, ...(mono ? {fontVariantNumeric: 'tabular-nums'} : {})}}>
    {value || <span style={{color: TV.text3}}>{placeholder}</span>}
  </div>
);

const Toggle = ({on}) => (
  <div style={{
    width: 38, height: 22, borderRadius: 12,
    background: on ? TV.accent : TV.panel3,
    border: `1px solid ${on ? TV.accent : TV.line}`,
    position: 'relative', cursor: 'pointer', flexShrink: 0,
  }}>
    <div style={{
      width: 16, height: 16, borderRadius: '50%',
      background: on ? '#0d1018' : TV.text2,
      position: 'absolute', top: 2, left: on ? 18 : 2,
      transition: 'left .15s',
    }}/>
  </div>
);

const SelectField = ({value, width = 'auto'}) => (
  <div className="tv-card" style={{padding: '7px 12px', background: TV.panel2, width,
      fontSize: 13, color: TV.text, display: 'inline-flex', alignItems: 'center', gap: 10, cursor: 'pointer'}}>
    <span>{value}</span>
    <span style={{color: TV.text4}}>▾</span>
  </div>
);

const Segmented = ({options, value}) => (
  <div style={{display: 'inline-flex', border: `1px solid ${TV.line}`, borderRadius: 5, padding: 2,
      background: TV.panel2}}>
    {options.map(o => {
      const sel = o === value;
      return (
        <div key={o} style={{
          padding: '5px 12px', borderRadius: 3, fontSize: 12, fontWeight: 500, cursor: 'pointer',
          color: sel ? TV.text : TV.text3,
          background: sel ? TV.panel3 : 'transparent',
          borderBottom: sel ? `1.5px solid ${TV.accent}` : '1.5px solid transparent',
        }}>{o}</div>
      );
    })}
  </div>
);

const Slider = ({value, min = 0, max = 100, unit = '%', width = 240}) => {
  const pct = ((value - min) / (max - min)) * 100;
  return (
    <div style={{display: 'flex', alignItems: 'center', gap: 12, width}}>
      <div style={{flex: 1, height: 4, background: TV.panel3, borderRadius: 2, position: 'relative'}}>
        <div style={{position: 'absolute', left: 0, top: 0, height: '100%', width: `${pct}%`, background: TV.accent, borderRadius: 2}}/>
        <div style={{position: 'absolute', left: `calc(${pct}% - 7px)`, top: -5, width: 14, height: 14, borderRadius: '50%',
            background: TV.accent, border: `2px solid ${TV.bg}`}}/>
      </div>
      <span className="tv-num" style={{fontSize: 13, color: TV.text, fontWeight: 600, width: 50, textAlign: 'right'}}>{value}{unit}</span>
    </div>
  );
};

// ============================================
// Schedule
// ============================================
const SchedulePanel = () => (
  <>
    <SectionHeader title="Schedule"
      subtitle="When and how the daily quiz is generated. Cron runs in your local timezone."/>

    <Group title="Daily quiz">
      <Row label="Generate at"
          desc="Time of day the cron runs and posts a new quiz to the dashboard.">
        <TextField value="06:00" width={80} mono/>
        <SelectField value="America/New_York (UTC-04)"/>
      </Row>
      <Row label="Quiz length"
          desc="Number of questions in each daily quiz.">
        <Segmented options={['5', '8', '10', '12']} value="8"/>
      </Row>
      <Row label="Time limit"
          desc="Soft limit shown in the quiz UI. Doesn't block submission.">
        <Segmented options={['none', '5m', '8m', '12m']} value="8m"/>
      </Row>
      <Row label="Skip weekends"
          desc="No quiz generated on Saturday/Sunday.">
        <Toggle on={false}/>
      </Row>
      <Row label="Skip on holidays"
          desc="No quiz on US market holidays.">
        <Toggle on={true}/>
      </Row>
    </Group>

    <Group title="Catch-up behavior">
      <Row label="Missed quiz"
          desc="If you didn't complete yesterday's quiz, what happens today?">
        <Segmented options={['stack', 'replace', 'skip']} value="replace"/>
      </Row>
      <Row label="Streak resets"
          desc="Days you can miss before the streak resets.">
        <Slider value={2} min={0} max={5} unit=" days" width={200}/>
      </Row>
    </Group>

    <Group title="Notifications">
      <Row label="Quiz ready" desc="Browser notification when today's quiz lands.">
        <Toggle on={true}/>
      </Row>
      <Row label="Browser sound" desc="Subtle chime — no, really, it's subtle.">
        <Toggle on={false}/>
      </Row>
      <Row label="Daily recap email" desc="Optional. Yesterday's quiz score + any open trades.">
        <Toggle on={false}/>
      </Row>
    </Group>
  </>
);

// ============================================
// Watchlist
// ============================================
const WatchlistPanel = () => {
  const [showImport, setShowImport] = React.useState(false);

  // Each ticker has 1+ HTF→LTF pairs. HTF identifies the point of interest;
  // LTF is where the entry trigger forms.
  const tickers = [
    {sym: 'BTC',    name: 'Bitcoin',         pairs: [['4H','15m'], ['D','1H']],  priority: 'high', active: true},
    {sym: 'ETH',    name: 'Ethereum',        pairs: [['4H','15m'], ['D','1H']],  priority: 'high', active: true},
    {sym: 'ES',     name: 'S&P 500 futures', pairs: [['D','1H'],   ['4H','15m']],priority: 'high', active: true},
    {sym: 'NQ',     name: 'Nasdaq futures',  pairs: [['D','1H']],                priority: 'med',  active: true},
    {sym: 'TSLA',   name: 'Tesla',           pairs: [['D','1H'],   ['4H','15m']],priority: 'med',  active: true},
    {sym: 'AAPL',   name: 'Apple',           pairs: [['D','1H']],                priority: 'med',  active: true},
    {sym: 'GOLD',   name: 'Gold (XAUUSD)',   pairs: [['D','1H']],                priority: 'low',  active: true},
    {sym: 'EURUSD', name: 'EUR/USD',         pairs: [['4H','15m']],              priority: 'low',  active: true},
    {sym: 'GBPUSD', name: 'GBP/USD',         pairs: [['4H','15m']],              priority: 'low',  active: true},
    {sym: 'USDJPY', name: 'USD/JPY',         pairs: [['4H','15m']],              priority: 'low',  active: false},
    {sym: 'OIL',    name: 'Crude oil',       pairs: [['D','1H']],                priority: 'low',  active: false},
    {sym: 'DXY',    name: 'Dollar index',    pairs: [['W','4H']],                priority: 'low',  active: false},
  ];

  return (
    <>
      <SectionHeader title="Watchlist"
        subtitle="The tickers your Scanner sweeps. Per-ticker HTF→LTF pairs and priority. Inactive tickers stay in the list but are not scanned."/>

      {/* Column-meaning explainer */}
      <div style={{padding: '14px 32px 0'}}>
        <div className="tv-card" style={{padding: 14, background: TV.panel2, borderColor: TV.lineSoft}}>
          <div style={{display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 18}}>
            <div>
              <div style={{display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4}}>
                <span style={{
                  width: 18, height: 18, borderRadius: 4, background: TV.accent, color: '#0d1018',
                  fontSize: 11, fontWeight: 700,
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                }}>P</span>
                <div className="tv-uppercase">Priority</div>
              </div>
              <div style={{fontSize: 13, color: TV.text2, lineHeight: 1.55}}>
                Controls <span style={{color: TV.text, fontWeight: 500}}>scan frequency</span>, <span style={{color: TV.text, fontWeight: 500}}>default ranking</span> in the Scanner, and whether the ticker shows on the Dashboard pulse.
              </div>
              <div style={{display: 'grid', gridTemplateColumns: 'auto 1fr', gap: '4px 12px', marginTop: 8, fontSize: 12}}>
                <span style={{color: TV.accent, fontWeight: 600}}>high</span>
                <span style={{color: TV.text2}}>fastest scan · always on Dashboard · alerts enabled</span>
                <span style={{color: TV.text, fontWeight: 600}}>med</span>
                <span style={{color: TV.text2}}>normal scan · in Scanner list · no alerts</span>
                <span style={{color: TV.text3, fontWeight: 600}}>low</span>
                <span style={{color: TV.text2}}>slow scan · de-emphasized in Scanner</span>
              </div>
            </div>

            <div>
              <div style={{display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4}}>
                <span style={{
                  width: 22, height: 18, borderRadius: 4, background: TV.adapt, color: '#0d1018',
                  fontSize: 10, fontWeight: 700,
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                }}>HTF→LTF</span>
                <div className="tv-uppercase">TF pairs</div>
              </div>
              <div style={{fontSize: 13, color: TV.text2, lineHeight: 1.55}}>
                Each setup uses a pair of timeframes: <span style={{color: TV.text, fontWeight: 500}}>HTF identifies the point of interest</span> (bias, dealing range, OB / FVG / liquidity pool), <span style={{color: TV.text, fontWeight: 500}}>LTF is where the entry trigger forms</span> (sweep, CHoCH, FVG return).
              </div>
              <div style={{display: 'grid', gridTemplateColumns: 'auto 1fr', gap: '4px 12px', marginTop: 8, fontSize: 12}}>
                <PairBadge htf="W"  ltf="4H"  compact/>
                <span style={{color: TV.text2}}>multi-week positional</span>
                <PairBadge htf="D"  ltf="1H"  compact/>
                <span style={{color: TV.text2}}>multi-day swing · default for indices / equities</span>
                <PairBadge htf="4H" ltf="15m" compact/>
                <span style={{color: TV.text2}}>intraday swing · default for crypto / 24h markets</span>
                <PairBadge htf="1H" ltf="5m"  compact/>
                <span style={{color: TV.text2}}>intraday scalp / LTF refinement</span>
              </div>
              <div style={{fontSize: 11, color: TV.text4, marginTop: 10, fontStyle: 'italic',
                  paddingTop: 8, borderTop: `1px dashed ${TV.lineSoft}`}}>
                ↳ Mayne's specific recommended pairs per market will be refined once more transcripts are ingested.
              </div>
            </div>
          </div>
        </div>
      </div>

      <div style={{padding: '20px 32px 4px', display: 'flex', alignItems: 'center', gap: 12}}>
        <div className="tv-uppercase">Tickers · {tickers.length}</div>
        <span className="tv-chip ok">{tickers.filter(t => t.active).length} active</span>
        <span className="tv-chip" style={{color: TV.text3}}>{tickers.filter(t => !t.active).length} paused</span>
        <div style={{flex: 1}}/>
        <span style={{fontSize: 12, color: TV.text3}}>scan frequency</span>
        <Segmented options={['1m', '5m', '15m', 'hourly']} value="5m"/>
        <button className="tv-btn" style={{padding: '6px 12px', fontSize: 12}}
            onClick={() => setShowImport(!showImport)}>
          {showImport ? '× Close import' : '↓ Bulk import'}
        </button>
        <button className="tv-btn primary" style={{padding: '6px 12px', fontSize: 12}}>+ Add ticker</button>
      </div>

      {showImport && <BulkImportPanel/>}

      <div style={{padding: '14px 32px'}}>
        <div className="tv-card" style={{padding: 0, overflow: 'hidden'}}>
          <div style={{display: 'grid', gridTemplateColumns: '40px 90px 1fr 140px 140px 110px 28px',
              padding: '10px 16px', borderBottom: `1px solid ${TV.line}`, background: TV.panel2,
              fontSize: 11, fontWeight: 600, color: TV.text3, letterSpacing: '.06em', textTransform: 'uppercase',
              alignItems: 'center', gap: 14}}>
            <span></span>
            <span>Ticker</span>
            <span>Name</span>
            <span style={{display: 'inline-flex', alignItems: 'center', gap: 4}}>
              HTF
              <span style={{
                width: 16, height: 12, borderRadius: 2, background: TV.adapt, color: '#0d1018',
                fontSize: 8, fontWeight: 700,
                display: 'inline-flex', alignItems: 'center', justifyContent: 'center', letterSpacing: 0,
              }}>POI</span>
            </span>
            <span style={{display: 'inline-flex', alignItems: 'center', gap: 4}}>
              LTF
              <span style={{
                width: 24, height: 12, borderRadius: 2, background: TV.ok, color: '#0d1018',
                fontSize: 8, fontWeight: 700,
                display: 'inline-flex', alignItems: 'center', justifyContent: 'center', letterSpacing: 0,
              }}>TRIGGER</span>
            </span>
            <span style={{display: 'inline-flex', alignItems: 'center', gap: 4}}>
              Priority
              <span style={{
                width: 12, height: 12, borderRadius: 2, background: TV.accent, color: '#0d1018',
                fontSize: 8, fontWeight: 700,
                display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
              }}>P</span>
            </span>
            <span></span>
          </div>
          {tickers.map((t,i) => (
            <div key={t.sym} style={{display: 'grid', gridTemplateColumns: '40px 90px 1fr 140px 140px 110px 28px',
                padding: '11px 16px', alignItems: 'center', gap: 14,
                borderBottom: i < tickers.length - 1 ? `1px solid ${TV.lineSoft}` : 'none',
                opacity: t.active ? 1 : 0.55}}>
              <Toggle on={t.active}/>
              <span className="tv-num" style={{fontSize: 14, fontWeight: 600, color: TV.text}}>{t.sym}</span>
              <span style={{fontSize: 13, color: TV.text2}}>{t.name}</span>
              <div style={{display: 'flex', flexDirection: 'column', gap: 3}}>
                {t.pairs.map(([htf], pi) => (
                  <TfTag key={pi} value={htf} kind="htf"/>
                ))}
                {t.pairs.length < 3 && (
                  <span style={{
                    padding: '1px 6px', borderRadius: 3, fontSize: 10,
                    color: TV.text4, border: `1px dashed ${TV.line}`, cursor: 'pointer',
                    alignSelf: 'flex-start',
                  }}>+ HTF</span>
                )}
              </div>
              <div style={{display: 'flex', flexDirection: 'column', gap: 3}}>
                {t.pairs.map(([,ltf], pi) => (
                  <TfTag key={pi} value={ltf} kind="ltf"/>
                ))}
                {t.pairs.length < 3 && (
                  <span style={{
                    padding: '1px 6px', borderRadius: 3, fontSize: 10,
                    color: TV.text4, border: `1px dashed ${TV.line}`, cursor: 'pointer',
                    alignSelf: 'flex-start',
                  }}>+ LTF</span>
                )}
              </div>
              <SelectField value={t.priority}/>
              <span style={{color: TV.text4, fontSize: 14, cursor: 'pointer'}}>×</span>
            </div>
          ))}
        </div>
      </div>

      <Group title="Defaults for new tickers">
        <Row label="Default HTF"
            desc="Higher timeframe pre-loaded for new tickers — where the point of interest is identified.">
          <div style={{display: 'flex', gap: 6, alignItems: 'center'}}>
            {['W','D','4H','1H'].map(t => (
              <span key={t} style={{
                padding: '4px 10px', borderRadius: 4,
                fontSize: 12, fontWeight: 600, fontVariantNumeric: 'tabular-nums',
                color: t === 'D' ? TV.adapt : TV.text3,
                border: `1px solid ${t === 'D' ? TV.adapt : TV.line}`,
                background: t === 'D' ? TV.adaptSoft : 'transparent',
                cursor: 'pointer',
              }}>{t}</span>
            ))}
          </div>
        </Row>
        <Row label="Default LTF"
            desc="Lower timeframe pre-loaded for new tickers — where the entry trigger forms.">
          <div style={{display: 'flex', gap: 6, alignItems: 'center'}}>
            {['1H','15m','5m','1m'].map(t => (
              <span key={t} style={{
                padding: '4px 10px', borderRadius: 4,
                fontSize: 12, fontWeight: 600, fontVariantNumeric: 'tabular-nums',
                color: t === '1H' ? TV.ok : TV.text3,
                border: `1px solid ${t === '1H' ? TV.ok : TV.line}`,
                background: t === '1H' ? TV.okSoft : 'transparent',
                cursor: 'pointer',
              }}>{t}</span>
            ))}
          </div>
        </Row>
        <Row label="Default priority" desc="Affects ranking inside the Scanner detail.">
          <SelectField value="med"/>
        </Row>
        <Row label="Restrict invalid pairs"
            desc="Block pair creation where the LTF isn't strictly lower than the HTF (e.g. 1H paired with 4H).">
          <Toggle on={true}/>
        </Row>
      </Group>
    </>
  );
};

// ---------- HTF → LTF pair badge (still used in explainer + preview) ----------
const PairBadge = ({htf, ltf, compact}) => (
  <span style={{
    display: 'inline-flex', alignItems: 'center', gap: 4,
    padding: compact ? '1px 6px' : '2px 8px', borderRadius: 4,
    border: `1px solid ${TV.line}`, background: TV.panel3,
    fontSize: compact ? 10 : 11, fontWeight: 600,
    color: TV.text, fontVariantNumeric: 'tabular-nums', letterSpacing: '-.1px',
  }}>
    <span style={{color: TV.adapt}}>{htf}</span>
    <span style={{color: TV.text4}}>→</span>
    <span style={{color: TV.ok}}>{ltf}</span>
  </span>
);

// ---------- single-TF tag (used in HTF and LTF columns) ----------
const TfTag = ({value, kind}) => {
  const color = kind === 'htf' ? TV.adapt : TV.ok;
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
      padding: '2px 8px', borderRadius: 3,
      border: `1px solid ${color}`, background: kind === 'htf' ? TV.adaptSoft : TV.okSoft,
      fontSize: 11, fontWeight: 600,
      color, fontVariantNumeric: 'tabular-nums', letterSpacing: '-.1px',
      alignSelf: 'flex-start', minWidth: 38, textAlign: 'center',
    }}>{value}</span>
  );
};

// ---------- bulk import inline panel ----------
const BulkImportPanel = () => {
  const presets = [
    {id: 'crypto', label: 'Crypto majors',  count: 8,  example: 'BTC, ETH, SOL, ...', pair: '4H→15m'},
    {id: 'fx',     label: 'FX majors',      count: 7,  example: 'EURUSD, GBPUSD, ...', pair: '4H→15m'},
    {id: 'idx',    label: 'US index futures', count: 4, example: 'ES, NQ, RTY, YM',    pair: 'D→1H'},
    {id: 'mag7',   label: 'Mag 7 equities', count: 7,  example: 'AAPL, MSFT, GOOGL, ...', pair: 'D→1H'},
    {id: 'comm',   label: 'Commodities',    count: 5,  example: 'GOLD, SILVER, OIL, NG, COPPER', pair: 'D→1H'},
  ];

  const previewRows = [
    {sym: 'SOL',    name: 'Solana',     pairs: [['4H','15m'],['D','1H']], priority: 'med',  status: 'new'},
    {sym: 'AVAX',   name: 'Avalanche',  pairs: [['4H','15m']],            priority: 'low',  status: 'new'},
    {sym: 'BTC',    name: 'Bitcoin',    pairs: [['4H','15m'],['D','1H']], priority: 'high', status: 'dup'},
    {sym: 'MATIC',  name: 'Polygon',    pairs: [['4H','15m']],            priority: 'low',  status: 'new'},
    {sym: 'XRP',    name: 'Ripple',     pairs: [['4H','15m']],            priority: 'low',  status: 'new'},
    {sym: 'LINK',   name: 'Chainlink',  pairs: [['4H','15m']],            priority: 'low',  status: 'new'},
    {sym: 'DOGE',   name: 'Dogecoin',   pairs: [['D','1H']],              priority: 'low',  status: 'new'},
    {sym: 'ETH',    name: 'Ethereum',   pairs: [['4H','15m'],['D','1H']], priority: 'high', status: 'dup'},
  ];

  return (
    <div style={{padding: '0 32px 8px'}}>
      <div className="tv-card" style={{padding: 16, borderColor: TV.accentLine,
          background: 'rgba(234,124,58,0.04)'}}>
        <div style={{display: 'flex', alignItems: 'baseline', gap: 10, marginBottom: 6}}>
          <div className="tv-uppercase" style={{color: TV.accent}}>Bulk import</div>
          <div style={{fontSize: 13, color: TV.text2}}>
            Paste a list, pick a preset, or upload a CSV. Map columns to fields, preview, commit.
          </div>
        </div>

        {/* presets */}
        <div style={{display: 'flex', alignItems: 'center', gap: 8, marginBottom: 14, marginTop: 8, flexWrap: 'wrap'}}>
          <span style={{fontSize: 11, color: TV.text3, fontWeight: 600, letterSpacing: '.06em', textTransform: 'uppercase', marginRight: 4}}>Preset</span>
          {presets.map(p => (
            <button key={p.id} className="tv-btn" style={{padding: '6px 10px', fontSize: 12, display: 'flex', flexDirection: 'column', alignItems: 'flex-start', textAlign: 'left', gap: 1}}>
              <span style={{fontWeight: 600}}>{p.label} <span style={{color: TV.text3, fontWeight: 400}}>· {p.count}</span></span>
              <span style={{color: TV.text3, fontSize: 10, fontWeight: 400}}>{p.example}</span>
              <span style={{color: TV.adapt, fontSize: 10, fontWeight: 500}}>default pair · {p.pair}</span>
            </button>
          ))}
          <div style={{flex: 1}}/>
          <span style={{fontSize: 12, color: TV.text3}}>or</span>
          <button className="tv-btn" style={{padding: '6px 10px', fontSize: 12}}>↑ Upload CSV</button>
        </div>

        {/* paste + map */}
        <div style={{display: 'grid', gridTemplateColumns: '1.2fr 1fr', gap: 14}}>
          {/* paste area */}
          <div>
            <div style={{display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6}}>
              <div className="tv-uppercase">Paste · CSV / one per line</div>
              <span className="tv-chip" style={{fontSize: 11}}><span className="tv-num">8</span> rows detected</span>
            </div>
            <div className="tv-card" style={{padding: 12, background: TV.panel2, minHeight: 180,
                fontFamily: TV.font, fontSize: 13, color: TV.text, lineHeight: 1.6,
                fontVariantNumeric: 'tabular-nums', whiteSpace: 'pre'}}>
{`SOL,Solana,4H→15m+D→1H,med
AVAX,Avalanche,4H→15m,low
BTC,Bitcoin,4H→15m+D→1H,high
MATIC,Polygon,4H→15m,low
XRP,Ripple,4H→15m,low
LINK,Chainlink,4H→15m,low
DOGE,Dogecoin,D→1H,low
ETH,Ethereum,4H→15m+D→1H,high`}
            </div>
          </div>

          {/* mapping */}
          <div>
            <div className="tv-uppercase" style={{marginBottom: 6}}>Column mapping</div>
            <div className="tv-card" style={{padding: 12, background: TV.panel2}}>
              <div style={{display: 'grid', gridTemplateColumns: 'auto 1fr', gap: '8px 12px', fontSize: 13, alignItems: 'center'}}>
                <span style={{color: TV.text3, fontWeight: 600,
                    background: TV.panel3, padding: '2px 8px', borderRadius: 3,
                    border: `1px solid ${TV.line}`, fontFamily: TV.font,
                    fontVariantNumeric: 'tabular-nums', fontSize: 11, textAlign: 'center'}}>col 1</span>
                <SelectField value="Ticker symbol"/>

                <span style={{color: TV.text3, fontWeight: 600,
                    background: TV.panel3, padding: '2px 8px', borderRadius: 3,
                    border: `1px solid ${TV.line}`, fontFamily: TV.font,
                    fontVariantNumeric: 'tabular-nums', fontSize: 11, textAlign: 'center'}}>col 2</span>
                <SelectField value="Display name"/>

                <span style={{color: TV.text3, fontWeight: 600,
                    background: TV.panel3, padding: '2px 8px', borderRadius: 3,
                    border: `1px solid ${TV.line}`, fontFamily: TV.font,
                    fontVariantNumeric: 'tabular-nums', fontSize: 11, textAlign: 'center'}}>col 3</span>
                <SelectField value="TF pairs (HTF→LTF, + separated)"/>

                <span style={{color: TV.text3, fontWeight: 600,
                    background: TV.panel3, padding: '2px 8px', borderRadius: 3,
                    border: `1px solid ${TV.line}`, fontFamily: TV.font,
                    fontVariantNumeric: 'tabular-nums', fontSize: 11, textAlign: 'center'}}>col 4</span>
                <SelectField value="Priority"/>
              </div>
              <div style={{borderTop: `1px solid ${TV.lineSoft}`, paddingTop: 10, marginTop: 10,
                  display: 'flex', flexDirection: 'column', gap: 8, fontSize: 12, color: TV.text2}}>
                <div style={{display: 'flex', justifyContent: 'space-between'}}>
                  <span>Skip header row</span>
                  <Toggle on={false}/>
                </div>
                <div style={{display: 'flex', justifyContent: 'space-between'}}>
                  <span>Activate on import</span>
                  <Toggle on={true}/>
                </div>
                <div style={{display: 'flex', justifyContent: 'space-between'}}>
                  <span>Skip duplicates (vs overwrite)</span>
                  <Toggle on={true}/>
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* preview */}
        <div style={{marginTop: 14}}>
          <div style={{display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6}}>
            <div className="tv-uppercase">Preview</div>
            <span className="tv-chip ok"><span className="tv-num">6</span> new</span>
            <span className="tv-chip warn"><span className="tv-num">2</span> duplicates · skip</span>
            <span className="tv-chip" style={{color: TV.text3}}><span className="tv-num">0</span> errors</span>
            <div style={{flex: 1}}/>
            <span style={{fontSize: 11, color: TV.text3}}>resolution → on commit</span>
          </div>
          <div className="tv-card" style={{padding: 0, overflow: 'hidden', background: TV.panel2}}>
            <div style={{display: 'grid', gridTemplateColumns: '80px 1fr 220px 100px 90px',
                padding: '8px 14px', borderBottom: `1px solid ${TV.line}`, background: TV.panel,
                fontSize: 10, fontWeight: 600, color: TV.text3, letterSpacing: '.06em',
                textTransform: 'uppercase', alignItems: 'center', gap: 12}}>
              <span>Ticker</span>
              <span>Name</span>
              <span>TF pairs</span>
              <span>Priority</span>
              <span style={{textAlign: 'right'}}>Status</span>
            </div>
            {previewRows.map((r,i) => (
              <div key={r.sym} style={{display: 'grid', gridTemplateColumns: '80px 1fr 220px 100px 90px',
                  padding: '8px 14px', alignItems: 'center', gap: 12,
                  borderBottom: i < previewRows.length - 1 ? `1px solid ${TV.lineSoft}` : 'none',
                  opacity: r.status === 'dup' ? 0.55 : 1}}>
                <span className="tv-num" style={{fontSize: 13, fontWeight: 600, color: TV.text}}>{r.sym}</span>
                <span style={{fontSize: 13, color: TV.text2}}>{r.name}</span>
                <div style={{display: 'flex', gap: 4, flexWrap: 'wrap'}}>
                  {r.pairs.map(([htf,ltf], pi) => (
                    <PairBadge key={pi} htf={htf} ltf={ltf} compact/>
                  ))}
                </div>
                <span style={{fontSize: 12, color: TV.text2, textTransform: 'capitalize'}}>{r.priority}</span>
                <span style={{textAlign: 'right'}}>
                  {r.status === 'new'
                    ? <span className="tv-chip ok" style={{fontSize: 10, padding: '1px 6px'}}>NEW</span>
                    : <span className="tv-chip warn" style={{fontSize: 10, padding: '1px 6px'}}>DUP · skip</span>}
                </span>
              </div>
            ))}
          </div>
        </div>

        {/* commit */}
        <div style={{display: 'flex', alignItems: 'center', gap: 10, marginTop: 14}}>
          <button className="tv-btn ghost">Clear</button>
          <div style={{flex: 1}}/>
          <span style={{fontSize: 12, color: TV.text3}}>6 tickers will be added · 2 skipped</span>
          <button className="tv-btn primary">Import 6 tickers →</button>
        </div>
      </div>
    </div>
  );
};

// ============================================
// Validator
// ============================================
const ValidatorPanel = () => (
  <>
    <SectionHeader title="Validator"
      subtitle="Defaults for the Trade Setup Validator and how its results are saved."/>

    <Group title="Readiness verdict thresholds">
      <Row label="READY threshold"
          desc="Number of pass criteria (out of 6) to count as READY.">
        <Slider value={5} min={3} max={6} unit=" of 6" width={260}/>
      </Row>
      <Row label="CONDITIONAL threshold"
          desc="Below READY, above this counts as CONDITIONAL. Else NOT READY.">
        <Slider value={4} min={2} max={5} unit=" of 6" width={260}/>
      </Row>
      <Row label="Block trade entry"
          desc="Prevent 'Mark as taken' on NOT READY trades (force a confirm dialog).">
        <Toggle on={true}/>
      </Row>
    </Group>

    <Group title="Risk / R:R">
      <Row label="Target R:R" desc="Default minimum acceptable risk:reward.">
        <Segmented options={['1:1.5','1:2','1:3','1:4']} value="1:3"/>
      </Row>
      <Row label="Warn below R:R" desc="Validator flags trades whose R:R is below this.">
        <Segmented options={['1:1','1:1.5','1:2','1:2.5']} value="1:2"/>
      </Row>
      <Row label="Per-trade risk size" desc="Default % of account risked per trade.">
        <Slider value={1.2} min={0.25} max={3} unit="%" width={240}/>
      </Row>
    </Group>

    <Group title="Save behavior">
      <Row label="Auto-save to journal"
          desc="Every validator session creates a Journal entry, even if NOT READY.">
        <Toggle on={true}/>
      </Row>
      <Row label="Draft Claude thesis"
          desc="Claude composes a thesis paragraph from your structured answers.">
        <Toggle on={true}/>
      </Row>
      <Row label="Default direction"
          desc="The pre-selected long/short in the validator flow.">
        <Segmented options={['long','short','auto']} value="auto"/>
      </Row>
    </Group>
  </>
);

// ============================================
// Quiz preferences
// ============================================
const QuizPanel = () => (
  <>
    <SectionHeader title="Quiz preferences"
      subtitle="What kinds of questions you see, and how strongly the system weights your weak spots."/>

    <Group title="Question types">
      <Row label="Multiple choice"
          desc="Standard 4-option select.">
        <Toggle on={true}/>
      </Row>
      <Row label="True / false"
          desc="Binary judgment questions.">
        <Toggle on={true}/>
      </Row>
      <Row label="Short answer (Claude-graded)"
          desc="Type a free-text answer; Claude grades against transcript definition.">
        <Toggle on={true}/>
      </Row>
      <Row label="Identify pattern on chart"
          desc="Chart-based questions that ask you to mark a candle / zone.">
        <Toggle on={true}/>
      </Row>
      <Row label="Annotate chart (mark FVG, OB, sweep)"
          desc="Drag/click to draw on a candlestick chart.">
        <Toggle on={false}/>
      </Row>
    </Group>

    <Group title="Concept weighting">
      <Row label="Weak-concept emphasis"
          desc="How aggressively to weight tomorrow's quiz toward concepts you're weak on.">
        <Slider value={60} min={20} max={100} unit="%" width={260}/>
      </Row>
      <Row label="Look-back window"
          desc="Number of recent questions used to compute mastery per concept.">
        <Segmented options={['10','20','30','60']} value="30"/>
      </Row>
      <Row label="Include strong concepts"
          desc="Keep a small sample of 80%+ concepts to prevent regression.">
        <Toggle on={true}/>
      </Row>
    </Group>

    <Group title="Sources">
      <Row label="Pull from episodes"
          desc="Which transcripts the question generator draws from.">
        <SelectField value="All 23 episodes"/>
      </Row>
      <Row label="Newer episodes weighted higher"
          desc="More recent uploads contribute more questions.">
        <Toggle on={false}/>
      </Row>
    </Group>
  </>
);

// ============================================
// Concepts
// ============================================
const ConceptsPanel = () => (
  <>
    <SectionHeader title="Concepts"
      subtitle="How the system decides what counts as weak vs strong, and which concepts the validator and quiz can reference."/>

    <Group title="Mastery thresholds">
      <Row label="WEAK below"
          desc="A concept is treated as weak when % correct over the look-back window is below this.">
        <Slider value={50} min={30} max={70} unit="%" width={260}/>
      </Row>
      <Row label="STRONG above"
          desc="Concept moves to strong (lowest priority for quiz weighting).">
        <Slider value={75} min={60} max={90} unit="%" width={260}/>
      </Row>
      <Row label="Minimum sample size"
          desc="Don't classify a concept until it has at least this many tested questions.">
        <Segmented options={['3','5','10','15']} value="5"/>
      </Row>
    </Group>

    <Group title="Active concept families">
      <Row label="Structure (Bias, BOS / CHoCH, Dealing Range)" desc=""><Toggle on={true}/></Row>
      <Row label="Liquidity (Sweep, Equal H/L, Sessions)" desc=""><Toggle on={true}/></Row>
      <Row label="Imbalance (FVG, Mitigation)" desc=""><Toggle on={true}/></Row>
      <Row label="Entries (OB, OTE, Trade Entries)" desc=""><Toggle on={true}/></Row>
      <Row label="Risk (Invalidation, R:R)" desc=""><Toggle on={true}/></Row>
      <Row label="Sessions / Killzones" desc=""><Toggle on={true}/></Row>
    </Group>

    <Group title="Extraction">
      <Row label="Auto-extract on transcript save"
          desc="Claude reads new transcripts and proposes new concepts. You approve before they go live.">
        <Toggle on={true}/>
      </Row>
      <Row label="Pending concept proposals" desc="Concepts Claude suggested but you haven't approved yet.">
        <button className="tv-btn" style={{fontSize: 13, padding: '6px 12px'}}>Review (3) →</button>
      </Row>
    </Group>
  </>
);

// ============================================
// Documents (admin section — lives inside Settings)
// ============================================
const TranscriptsPanel = () => (
  <>
    <SectionHeader title="Documents"
      subtitle="Upload and manage the source documents — summaries or transcripts. Concepts and quiz questions are generated from everything you add here."/>

    <Group>
      <div className="tv-card" style={{padding: 16, display: 'grid',
          gridTemplateColumns: 'repeat(4, 1fr)', gap: 14}}>
        <div>
          <div className="tv-uppercase">Documents</div>
          <div className="tv-num" style={{fontSize: 24, fontWeight: 700, color: TV.text, marginTop: 2}}>6</div>
        </div>
        <div>
          <div className="tv-uppercase">Concepts extracted</div>
          <div className="tv-num" style={{fontSize: 24, fontWeight: 700, color: TV.text, marginTop: 2}}>16</div>
        </div>
        <div>
          <div className="tv-uppercase">Pending approval</div>
          <div className="tv-num" style={{fontSize: 24, fontWeight: 700, color: TV.warn, marginTop: 2}}>3</div>
        </div>
        <div>
          <div className="tv-uppercase">Last added</div>
          <div style={{fontSize: 14, color: TV.text, marginTop: 6}}>2d ago</div>
        </div>
      </div>
    </Group>

    <Group title="Quick actions">
      <Row label="Add a document"
          desc="Open the upload screen — paste a summary or transcript, give it a topic, and extract concepts.">
        <button className="tv-btn primary" style={{padding: '7px 14px'}}>Add document →</button>
      </Row>
      <Row label="Re-extract all concepts"
          desc="Re-run concept extraction against every document. Takes ~2–3 min.">
        <button className="tv-btn" style={{padding: '7px 14px'}}>Re-extract</button>
      </Row>
      <Row label="Export corpus"
          desc="Download all documents + extracted concepts as a single JSON archive.">
        <button className="tv-btn">↓ Export</button>
      </Row>
    </Group>

    <Group title="Recent documents">
      <div className="tv-card" style={{padding: 0, overflow: 'hidden'}}>
        {[
          ['Consolidated Trading Plan', 'eps 1–4', '2d ago', 16],
          ['Buy-side / Sell-side Liquidity', 'standalone', '3d ago', 9],
          ['Optimal Trade Entry', 'standalone', '5d ago', 8],
          ['BOS vs CHoCH revisited', 'standalone', '1w ago', 11],
        ].map((row, i) => (
          <div key={row[0]} style={{display: 'grid', gridTemplateColumns: '1fr 110px 120px 100px 30px',
              padding: '10px 16px', alignItems: 'center', gap: 12,
              borderBottom: i < 3 ? `1px solid ${TV.lineSoft}` : 'none'}}>
            <span style={{fontSize: 14, color: TV.text}}>{row[0]}</span>
            <span className="tv-chip" style={{fontSize: 10, justifySelf: 'start'}}>{row[1]}</span>
            <span style={{fontSize: 12, color: TV.text3}}>{row[2]}</span>
            <span className="tv-num" style={{fontSize: 12, color: TV.text2}}>{row[3]} concepts</span>
            <span style={{color: TV.text3, cursor: 'pointer', textAlign: 'right'}}>›</span>
          </div>
        ))}
      </div>
    </Group>
  </>
);

// ============================================
// Account
// ============================================
const AccountPanel = () => (
  <>
    <SectionHeader title="Account"
      subtitle="Password protection (single-user app), API keys, integrations."/>

    <Group title="Access">
      <Row label="Site password"
          desc="The shared password that gates the app. Hash stored in Vercel KV.">
        <TextField value="•••••••••••••" width={220} mono/>
        <button className="tv-btn ghost" style={{fontSize: 12, padding: '5px 10px'}}>Change</button>
      </Row>
      <Row label="Session timeout"
          desc="Auto-lock after this many hours of inactivity.">
        <Segmented options={['1h','4h','12h','never']} value="12h"/>
      </Row>
      <Row label="Allowed IPs"
          desc="Optional whitelist. Leave empty to allow any IP.">
        <TextField value="" placeholder="comma-separated · CIDR ok" width={320} mono/>
      </Row>
    </Group>

    <Group title="API keys">
      <Row label="Anthropic API key"
          desc="Powers quiz generation, concept extraction, validator thesis drafting.">
        <TextField value="sk-ant-•••••••••••••••••••••••••rB2k" width={320} mono/>
        <button className="tv-btn ghost" style={{fontSize: 12, padding: '5px 10px'}}>Test</button>
        <button className="tv-btn ghost" style={{fontSize: 12, padding: '5px 10px'}}>Rotate</button>
      </Row>
      <Row label="TradingView (planned)"
          desc="Integration is on the roadmap — not yet wired up.">
        <span className="tv-chip" style={{color: TV.text3}}>not connected</span>
      </Row>
    </Group>

    <Group title="Model preferences">
      <Row label="Quiz generation model" desc=""><SelectField value="claude-haiku-4-5"/></Row>
      <Row label="Concept extraction model" desc=""><SelectField value="claude-sonnet-4-5"/></Row>
      <Row label="Validator thesis model" desc=""><SelectField value="claude-haiku-4-5"/></Row>
    </Group>
  </>
);

// ============================================
// Data
// ============================================
const DataPanel = () => (
  <>
    <SectionHeader title="Data"
      subtitle="Export, backup, and the destructive stuff. All data lives in Vercel KV / Supabase."/>

    <Group title="Storage">
      <div className="tv-card" style={{padding: 16, display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 14}}>
        <div><div className="tv-uppercase">Trades</div><div className="tv-num" style={{fontSize: 22, fontWeight: 700, color: TV.text, marginTop: 2}}>187</div></div>
        <div><div className="tv-uppercase">Quizzes</div><div className="tv-num" style={{fontSize: 22, fontWeight: 700, color: TV.text, marginTop: 2}}>48</div></div>
        <div><div className="tv-uppercase">Transcripts</div><div className="tv-num" style={{fontSize: 22, fontWeight: 700, color: TV.text, marginTop: 2}}>23</div></div>
        <div><div className="tv-uppercase">Concepts</div><div className="tv-num" style={{fontSize: 22, fontWeight: 700, color: TV.text, marginTop: 2}}>187</div></div>
      </div>
    </Group>

    <Group title="Export">
      <Row label="Full backup (JSON)"
          desc="Everything — trades, quizzes, transcripts, concepts, settings.">
        <button className="tv-btn primary" style={{padding: '7px 14px'}}>↓ Download backup</button>
      </Row>
      <Row label="Trade journal (CSV)"
          desc="Per-trade row with thesis, outcome, R:R, concepts. Pivot-table friendly.">
        <button className="tv-btn">↓ Download CSV</button>
      </Row>
      <Row label="Quiz history (CSV)" desc="Per-question row with score, time, source episode.">
        <button className="tv-btn">↓ Download CSV</button>
      </Row>
    </Group>

    <Group title="Backups">
      <Row label="Automatic daily backup"
          desc="Snapshot all data to private S3 bucket every 24h.">
        <Toggle on={true}/>
      </Row>
      <Row label="Last backup" desc="">
        <span className="tv-chip ok"><span className="tv-dot"/>2 hours ago · 487 KB</span>
        <button className="tv-btn ghost" style={{fontSize: 12, padding: '5px 10px'}}>Restore from…</button>
      </Row>
    </Group>

    <Group title="Danger zone">
      <Row label="Reset mastery"
          desc="Clear concept mastery percentages. Trades and quizzes are preserved.">
        <button className="tv-btn" style={{fontSize: 13, color: TV.warn, borderColor: 'rgba(224,179,65,.35)'}}>Reset mastery</button>
      </Row>
      <Row label="Clear quiz history"
          desc="Delete all quiz attempts. Mastery resets along with this.">
        <button className="tv-btn" style={{fontSize: 13, color: TV.warn, borderColor: 'rgba(224,179,65,.35)'}}>Clear quizzes</button>
      </Row>
      <Row label="Wipe everything"
          desc="Delete all data. Backups remain in S3 for 30 days. Cannot be undone via UI.">
        <button className="tv-btn" style={{fontSize: 13, color: TV.fail, borderColor: 'rgba(217,83,79,.4)', background: TV.failSoft}}>Wipe all data</button>
      </Row>
    </Group>
  </>
);

Object.assign(window, {SettingsHF});
