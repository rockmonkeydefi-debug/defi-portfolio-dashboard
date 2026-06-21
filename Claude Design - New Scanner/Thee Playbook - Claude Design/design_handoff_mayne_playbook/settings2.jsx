// settings2.jsx — Settings (new spec): Display · Wallets · API Config · AI Config · Spot P&L Config
// Loads after spotpnl.jsx — reuses TV.*, .tv-*, PF_CARD/TITLE/SUB, PFSeg, ToggleSwitch,
// TokenIcon, ChainBadge, WALLETS (from portfolio.jsx).

const SETT_SECTIONS = [
  {id: 'display',      label: 'Display Preferences'},
  {id: 'wallets',      label: 'Wallets'},
  {id: 'integrations', label: 'Integrations'},
  {id: 'ai',           label: 'AI Config'},
  {id: 'docs',         label: 'Document Uploads'},
  {id: 'pnlconfig',    label: 'Spot P&L Config'},
  {id: 'backup',       label: 'Backup & Security'},
  {id: 'messaging',    label: 'Messaging'},
];

// plain text input look
const SInput = ({value, placeholder, mono, type = 'text'}) => (
  <div style={{background: TV.panel2, border: `1px solid ${TV.line}`, borderRadius: 8,
      padding: '9px 13px', fontSize: 13.5, color: type === 'password' ? TV.text4 : TV.text,
      fontFamily: mono ? "'Fira Code', monospace" : TV.font, wordBreak: 'break-all', lineHeight: 1.4}}>
    {type === 'password' ? '••••••••••••••••••••' : (value || <span style={{color: TV.text4}}>{placeholder}</span>)}
  </div>
);

const SLabel = ({children, sub}) => (
  <div style={{marginBottom: sub ? 4 : 6}}>
    <div style={{fontSize: 14, fontWeight: 600, color: TV.text}}>{children}</div>
    {sub && <div style={{fontSize: 12.5, color: TV.text3, marginTop: 2}}>{sub}</div>}
  </div>
);

const SField = ({label, sub, children}) => (
  <div style={{display: 'flex', flexDirection: 'column', gap: 0}}>
    <SLabel sub={sub}>{label}</SLabel>
    {children}
  </div>
);

// ── section: Display Preferences ──────────────────────────────
const DisplaySection = () => (
  <div style={{display: 'flex', flexDirection: 'column', gap: 20}}>
    <div style={PF_CARD}>
      <div style={{...PF_TITLE, marginBottom: 18}}>Display Preferences</div>

      {/* Hide all values toggle — full-width, prominent */}
      <div style={{display:'flex', alignItems:'center', justifyContent:'space-between',
          padding:'14px 18px', borderRadius:10, border:`1.5px solid ${TV.accentLine}`,
          background:TV.accentSoft, marginBottom:20}}>
        <div style={{display:'flex', flexDirection:'column', gap:3}}>
          <div style={{fontSize:15, fontWeight:700, color:TV.text}}>Hide all portfolio values</div>
          <div style={{fontSize:12.5, color:TV.text3}}>Masks all personal balances, P&amp;L, and position values site-wide. Market data, quiz scores, and public data are unaffected.</div>
        </div>
        <div style={{display:'flex', alignItems:'center', gap:10, flexShrink:0, marginLeft:24}}>
          <span style={{fontSize:12.5, color:TV.text3}}>Off</span>
          <div style={{width:44, height:24, borderRadius:12, background:TV.panel3,
              border:`1.5px solid ${TV.line}`, position:'relative', cursor:'pointer', flexShrink:0}}>
            <div style={{position:'absolute', top:2, left:2, width:16, height:16, borderRadius:'50%',
                background:TV.text4, transition:'left .2s'}}/>
          </div>
          <span style={{fontSize:12.5, color:TV.text3}}>On</span>
        </div>
      </div>

      <div style={{display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20}}>
        <SField label="Dust Threshold" sub="Tokens below this value are hidden from Token Holdings">
          <div style={{display: 'flex', gap: 10, alignItems: 'center', marginTop: 6}}>
            <div style={{fontSize: 13, color: TV.text2, alignSelf: 'center'}}>$</div>
            <SInput value="1.00"/>
            <span style={{fontSize: 13, color: TV.text3}}>USD</span>
          </div>
        </SField>
        <SField label="Lending Threshold" sub="Lending/borrowing positions below this value are hidden">
          <div style={{display: 'flex', gap: 10, alignItems: 'center', marginTop: 6}}>
            <div style={{fontSize: 13, color: TV.text2, alignSelf: 'center'}}>$</div>
            <SInput value="10.00"/>
            <span style={{fontSize: 13, color: TV.text3}}>USD</span>
          </div>
        </SField>
      </div>
    </div>
  </div>
);

// ── section: Wallets ───────────────────────────────────────────
const WalletsSection = () => (
  <div style={{display: 'flex', flexDirection: 'column', gap: 20}}>
    <div style={PF_CARD}>
      <div style={{...PF_TITLE, marginBottom: 18}}>Connected Wallets</div>
      <div style={{display: 'flex', flexDirection: 'column', gap: 0, borderRadius: 10, border: `1px solid ${TV.line}`, overflow: 'hidden'}}>
        {WALLETS.map((w, i) => (
          <div key={w.id} style={{display: 'flex', alignItems: 'center', gap: 14, padding: '14px 16px',
              borderBottom: i < WALLETS.length - 1 ? `1px solid ${TV.lineSoft}` : 'none',
              opacity: w.hidden ? 0.5 : 1}}>
            <span style={{width: 9, height: 9, borderRadius: '50%', background: w.dot, flexShrink: 0}}/>
            <div style={{minWidth: 120}}>
              <div style={{fontSize: 14, fontWeight: 600, color: TV.text}}>{w.label}</div>
              <div className="tv-num" style={{fontSize: 12, color: TV.text3, marginTop: 1}}>{w.addr}</div>
            </div>
            <span style={{fontSize: 12.5, color: TV.text3}}>{w.value}</span>
            <div style={{flex: 1}}/>
            <ToggleSwitch on={!w.hidden} label={w.hidden ? 'Hidden' : 'Visible'}/>
            <button className="tv-btn ghost" style={{padding: '4px 10px', fontSize: 12, color: TV.fail,
                borderColor: `rgba(255,138,138,.35)`}}>Remove</button>
          </div>
        ))}
      </div>
      <div style={{display: 'flex', gap: 10, alignItems: 'stretch', marginTop: 16}}>
        <div style={{flex: 1}}><SInput placeholder="Paste wallet address (0x…) or ENS name"/></div>
        <button className="tv-btn primary" style={{padding: '9px 18px'}}>+ Add wallet</button>
      </div>
    </div>
  </div>
);

// ── section: Integrations (RPC + AI keys + other APIs) ───────
const SaveBtn = () => <button className="tv-btn" style={{padding:'7px 14px',fontSize:13}}>Save</button>;
const KeyRow = ({label, badge, sub, value, placeholder}) => (
  <div style={{display:'flex', flexDirection:'column', gap:6}}>
    <div style={{display:'flex', alignItems:'center', gap:8}}>
      <span style={{fontSize:12.5, fontWeight:700, color:TV.text3, letterSpacing:'.05em', textTransform:'uppercase'}}>{label}</span>
      {badge && <span className="tv-chip" style={{fontSize:10.5, padding:'1px 7px',
          color: badge==='REQUIRED'?TV.fail: badge==='RECOMMENDED'?TV.warn: TV.text3,
          borderColor: badge==='REQUIRED'?'rgba(255,138,138,.4)': badge==='RECOMMENDED'?'rgba(255,210,63,.4)': TV.line,
          background: badge==='REQUIRED'?TV.failSoft: badge==='RECOMMENDED'?TV.warnSoft:'transparent'}}>{badge}</span>}
    </div>
    <div style={{display:'flex', gap:8, alignItems:'center'}}>
      <div style={{flex:1}}><SInput value={value} placeholder={placeholder} type={value?'password':'text'} mono/></div>
      <SaveBtn/>
    </div>
    {sub && <div style={{fontSize:12, color:TV.text3, lineHeight:1.45}}>{sub}</div>}
  </div>
);
const RpcRow = ({chain, defaultProvider, hasKey}) => (
  <div style={{display:'flex', alignItems:'flex-start', gap:12, padding:'12px 0', borderBottom:`1px solid ${TV.lineSoft}`}}>
    <div style={{width:100}}>
      <div style={{fontSize:11.5, fontWeight:700, color:TV.text3, textTransform:'uppercase', letterSpacing:'.05em', marginBottom:6}}>{chain}</div>
      <div style={{background:TV.panel2, border:`1px solid ${TV.line}`, borderRadius:7, padding:'7px 10px',
          fontSize:12.5, color:TV.text, display:'flex', justifyContent:'space-between'}}>
        <span>{defaultProvider}</span><span style={{color:TV.text3}}>▾</span>
      </div>
    </div>
    <div style={{flex:1}}>
      <div style={{fontSize:11.5, fontWeight:700, color:TV.text3, textTransform:'uppercase', letterSpacing:'.05em', marginBottom:6}}>{hasKey?'Full RPC URL':'API Key'}</div>
      <div style={{display:'flex', gap:8}}>
        <div style={{flex:1}}><SInput value={hasKey?'6dmS••••••••••••civK':''} placeholder="Paste your API key" type={hasKey?'password':'text'} mono/></div>
        <SaveBtn/>
      </div>
    </div>
  </div>
);
const SectionHead = ({icon, title, desc}) => (
  <div style={{marginBottom:14}}>
    <div style={{fontSize:15, fontWeight:700, color:TV.ok, marginBottom:5}}>{icon} {title}</div>
    {desc && <div style={{fontSize:12.5, color:TV.text3, lineHeight:1.5}}>{desc}</div>}
  </div>
);
const IntegrationsSection = () => (
  <div style={{display:'flex', flexDirection:'column', gap:22}}>
    <div style={PF_CARD}>
      <SectionHead icon="⚡" title="RPC Endpoints" desc="Required for on-chain LP analytics, health factors, and gas data. Free tiers from Alchemy or Infura are sufficient — one key reused across chains."/>
      <RpcRow chain="Ethereum" defaultProvider="Custom URL" hasKey={true}/>
      <RpcRow chain="Arbitrum" defaultProvider="Alchemy" hasKey={false}/>
      <RpcRow chain="Base"     defaultProvider="Alchemy" hasKey={false}/>
    </div>
    <div style={PF_CARD}>
      <SectionHead icon="🤖" title="AI Provider Keys" desc="Powers AI analysis and the Daily Brief. Configure exactly one — you don't need all three. Without an AI key the dashboard still works."/>
      <div style={{display:'flex', flexDirection:'column', gap:16}}>
        <KeyRow label="OpenAI API Key" placeholder="Enter key…" sub="GPT-4o and other OpenAI models. Sign up at platform.openai.com"/>
        <KeyRow label="Anthropic API Key" value="sk-a••••••••••••••••••••••••••AQAA" sub="Claude (Sonnet, Opus, Haiku) via the Anthropic API. Sign up at console.anthropic.com"/>
        <KeyRow label="AWS Bedrock Bearer Token" placeholder="Enter key…" sub="Claude models via your AWS account. Get the bearer token from AWS Console → Bedrock"/>
      </div>
    </div>
    <div style={PF_CARD}>
      <SectionHead icon="🔗" title="Other APIs"/>
      <div style={{display:'flex', flexDirection:'column', gap:16}}>
        <KeyRow label="Zerion API Key" badge="REQUIRED" value="zk_7••••••••••••••••••••••••eaa0" sub="Unified EVM portfolio discovery — tokens, DeFi positions, and lending across chains. Free dev tier at developers.zerion.io"/>
        <KeyRow label="Etherscan API Key" badge="RECOMMENDED" value="98HG••••••••••••••••••••M73S" sub="Position age and historical collected-fees lookup for Ethereum and Arbitrum LPs. Free at etherscan.io/apis"/>
        <KeyRow label="FRED API Key" badge="OPTIONAL" value="a261••••••••••••••••••••••206" sub="Macro indicators (US10Y, DXY, M2, Fed Funds) used in the AI Daily Brief. Free at fred.stlouisfed.org"/>
      </div>
    </div>
  </div>
);

// ── section: AI Config ─────────────────────────────────────────
const CLAUDE_MODELS = ['claude-opus-4-5', 'claude-sonnet-4-5', 'claude-haiku-3-5'];

const AiSection = () => (
  <div style={{display: 'flex', flexDirection: 'column', gap: 20}}>
    {/* provider + model */}
    <div style={PF_CARD}>
      <div style={{...PF_TITLE, marginBottom: 18}}>AI Config</div>
      <div style={{display: 'flex', flexDirection: 'column', gap: 16}}>
        <SField label="Provider"><PFSeg options={['Anthropic', 'OpenAI']} active="Anthropic" size="sm"/></SField>
        <SField label="Model" sub="Model list updates based on selected provider">
          <div style={{display: 'flex', gap: 10, alignItems: 'center', marginTop: 6}}>
            <div style={{flex: 1, background: TV.panel2, border: `1px solid ${TV.line}`, borderRadius: 8,
                padding: '9px 13px', fontSize: 13.5, color: TV.text, display: 'flex', justifyContent: 'space-between'}}>
              <span>claude-sonnet-4-5</span>
              <span style={{color: TV.text3}}>▾</span>
            </div>
          </div>
          <div style={{display: 'flex', gap: 7, marginTop: 8}}>
            {CLAUDE_MODELS.map(m => (
              <span key={m} className="tv-chip" style={{fontSize: 11,
                  ...(m === 'claude-sonnet-4-5' ? {color: TV.accent, borderColor: TV.accentLine, background: TV.accentSoft} : {})}}>{m}</span>
            ))}
          </div>
        </SField>
      </div>
    </div>
  </div>
);

// ── section: Document Uploads ─────────────────────────────────
const REGIME_COLORS = {bear: TV.fail, bull: TV.ok, stablecoin: TV.adapt, cashflow_other: TV.warn};
const REGIME_LABELS = {bear: 'Bear', bull: 'Bull', stablecoin: 'Stablecoin', cashflow_other: 'Cashflow/Other'};
const TOPIC_COLORS  = {setups: TV.accent, concepts: TV.adapt, validation: TV.ok, general: TV.text3};
const TOPIC_LABELS  = {setups: 'Setups', concepts: 'Concepts', validation: 'Validation', general: 'General'};
const DEFI_DOCS = [
  {name:'BTC_Strategy_Q1_2026.md',       date:'2026-01-15', tag:'bear',          size:'4.2 KB'},
  {name:'ETH_Yield_Framework.pdf',        date:'2026-02-10', tag:'bull',          size:'18.7 KB'},
  {name:'Stablecoin_Rotation_Rules.xlsx', date:'2026-03-05', tag:'stablecoin',    size:'11.1 KB'},
];
const TRADING_DOCS = [
  {name:'OrderBlock_Framework.pdf',       date:'2026-02-12', tag:'setups',     size:'9.4 KB'},
  {name:'ICT_Concepts_Reference.md',      date:'2026-01-08', tag:'concepts',   size:'6.1 KB'},
  {name:'Trade_Validation_Criteria.docx', date:'2026-03-20', tag:'validation', size:'14.3 KB'},
];
const DocTable = ({docs, tagColors, tagLabels}) => (
  <div style={{borderRadius:10, border:`1px solid ${TV.line}`, overflow:'hidden', marginTop:12}}>
    <div style={{display:'grid', gridTemplateColumns:'minmax(180px,1fr) 110px 1fr 90px', gap:12,
        padding:'9px 14px', background:TV.panel, fontSize:11, fontWeight:600, color:TV.text3, letterSpacing:'.05em', textTransform:'uppercase'}}>
      <span>File</span><span>Uploaded</span><span>Tag</span><span style={{textAlign:'right'}}>Size</span>
    </div>
    {docs.map(d => {
      const tc = tagColors[d.tag] || TV.text3;
      return (
        <div key={d.name} style={{display:'grid', gridTemplateColumns:'minmax(180px,1fr) 110px 1fr 90px', gap:12,
            padding:'12px 14px', alignItems:'center', borderTop:`1px solid ${TV.lineSoft}`, fontSize:13}}>
          <span className="tv-num" style={{color:TV.text, fontWeight:600, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap'}}>{d.name}</span>
          <span className="tv-num" style={{color:TV.text3}}>{d.date}</span>
          <span style={{display:'flex', alignItems:'center', gap:8}}>
            <span className="tv-chip" style={{fontSize:11, color:tc, borderColor:`${tc}55`, background:`${tc}18`}}>{tagLabels[d.tag]}</span>
            <span style={{color:TV.text4, fontSize:11}}>▾</span>
          </span>
          <span style={{display:'flex', gap:6, justifyContent:'flex-end', alignItems:'center'}}>
            <span className="tv-num" style={{fontSize:12, color:TV.text4}}>{d.size}</span>
            <button className="tv-btn ghost" style={{padding:'2px 8px', fontSize:12, color:TV.fail}}>✕</button>
          </span>
        </div>
      );
    })}
  </div>
);
const DropZone = () => (
  <div style={{padding:'20px', borderRadius:10, border:`2px dashed ${TV.line}`, background:TV.panel2,
      display:'flex', flexDirection:'column', alignItems:'center', gap:7, marginTop:12, cursor:'pointer'}}>
    <div style={{fontSize:26, color:TV.text3}}>⬆</div>
    <div style={{fontSize:13.5, fontWeight:600, color:TV.text}}>Drag files here or click to upload</div>
    <div style={{fontSize:12, color:TV.text3}}>.md · .pdf · .docx · .xlsx · .csv</div>
  </div>
);
const DocsSection = () => (
  <div style={{display:'flex', flexDirection:'column', gap:22}}>
    <div style={PF_CARD}>
      <div style={{...PF_TITLE, marginBottom:4}}>DeFi Strategy</div>
      <div style={PF_SUB}>Used by the AI when analyzing your portfolio, DeFi positions, and lending health. Tag each document with the market regime it applies to.</div>
      <DropZone/>
      <DocTable docs={DEFI_DOCS} tagColors={REGIME_COLORS} tagLabels={REGIME_LABELS}/>
    </div>
    <div style={PF_CARD}>
      <div style={{...PF_TITLE, marginBottom:4}}>Trading Strategy</div>
      <div style={PF_SUB}>Used for quiz generation, trade validation criteria, and chart-scanning setup identification. Tag each by topic area.</div>
      <DropZone/>
      <DocTable docs={TRADING_DOCS} tagColors={TOPIC_COLORS} tagLabels={TOPIC_LABELS}/>
    </div>
  </div>
);

// ── section: Spot P&L Token Config ────────────────────────────
const PNL_TOKEN_ROWS = [
  // sym, chain, contract, priceSource, dexFallback
  ['ETH',   'ETH',  '',                                             'CoinGecko'],
  ['WBTC',  'ETH',  '0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599', 'CoinGecko'],
  ['SOL',   'SOL',  '',                                             'CoinGecko'],
  ['ARB',   'ARB',  '0x912CE59144191C1204E64559FE8253a0e49E6548', 'DexScreener'],
  ['LINK',  'ETH',  '0x514910771AF9Ca656af840dff83E8264EcF986CA', 'CoinGecko'],
  ['PEPE',  'ETH',  '0x6982508145454Ce325dDBe47a25d4ec3d2311933', 'DexScreener'],
  ['cbBTC', 'BASE', '0xcbb7c0000Ab88B473b1f5aFd9ef808440eed33Bf', 'DexScreener'],
];
const TOK_COLS = 'minmax(130px,1fr) minmax(260px,2fr) 150px 100px';

const PnlConfigSection = () => (
  <div style={PF_CARD}>
    <div style={{...PF_TITLE, marginBottom: 4}}>Spot P&amp;L Token Config</div>
    <div style={{...PF_SUB, marginBottom: 18}}>Override contract addresses, set price sources, and enable DexScreener fallback per token.</div>

    <div style={{borderRadius: 10, border: `1px solid ${TV.line}`, overflow: 'hidden'}}>
      <div style={{display: 'grid', gridTemplateColumns: TOK_COLS, gap: 12, padding: '9px 14px',
          background: TV.panel, fontSize: 11, fontWeight: 600, color: TV.text3, letterSpacing: '.05em', textTransform: 'uppercase'}}>
        <span>Token</span><span>Contract Override</span><span>Price Source</span><span style={{textAlign:'right'}}>Test</span>
      </div>
      {PNL_TOKEN_ROWS.map(([sym, chain, contract, source, dex], i) => (
        <div key={sym} style={{display: 'grid', gridTemplateColumns: TOK_COLS, gap: 12, padding: '11px 14px',
            alignItems: 'center', borderTop: `1px solid ${TV.lineSoft}`, fontSize: 13}}>
          <span style={{display: 'flex', alignItems: 'center', gap: 8}}>
            <TokenIcon sym={sym} size={22}/>
            <span className="tv-num" style={{fontWeight: 700, color: TV.text}}>{sym}</span>
            <ChainBadge chain={chain}/>
          </span>
          <div style={{background: TV.panel2, border: `1px solid ${TV.line}`, borderRadius: 7, padding: '6px 10px',
              fontSize: 11.5, color: contract ? TV.text3 : TV.text4, fontFamily: "'Fira Code', monospace",
              overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap'}}>
            {contract || <span style={{fontStyle: 'italic', opacity: .6}}>auto-detected</span>}
          </div>
          <div style={{background: TV.panel2, border: `1px solid ${TV.line}`, borderRadius: 7, padding: '7px 10px',
              fontSize: 12.5, color: TV.text, display: 'flex', justifyContent: 'space-between'}}>
            <span>{source}</span><span style={{color: TV.text3}}>▾</span>
          </div>
          <div style={{display: 'flex', justifyContent: 'flex-end'}}>
            <button className="tv-btn" style={{padding: '5px 12px', fontSize: 12.5}}>Test ↗</button>
          </div>
        </div>
      ))}
    </div>
  </div>
);

// ── main component ─────────────────────────────────────────────
// ── section: Backup & Security ─────────────────────────────
const BackupSection = () => (
  <div style={{display:'flex', flexDirection:'column', gap:20}}>
    {/* Backup & Restore */}
    <div style={PF_CARD}>
      <SectionHead icon="💾" title="Backup & Restore"/>
      <div style={{display:'grid', gridTemplateColumns:'1fr 1fr', gap:24}}>
        <div style={{display:'flex', flexDirection:'column', gap:10}}>
          <SLabel sub="Full SQLite snapshot of all portfolio data, transactions, and history.">Snapshot Database</SLabel>
          <div style={{display:'flex', gap:10}}>
            <button className="tv-btn" style={{padding:'9px 18px', fontSize:13}}>Export DB</button>
            <button className="tv-btn primary" style={{padding:'9px 18px', fontSize:13}}>Import DB</button>
          </div>
        </div>
        <div style={{display:'flex', flexDirection:'column', gap:10}}>
          <SLabel sub="API keys, wallets, AI config, display preferences, and profile.">All Settings</SLabel>
          <div style={{display:'flex', gap:10}}>
            <button className="tv-btn" style={{padding:'9px 18px', fontSize:13}}>Export Settings</button>
            <button className="tv-btn primary" style={{padding:'9px 18px', fontSize:13}}>Import Settings</button>
          </div>
        </div>
      </div>
      <div style={{marginTop:14, padding:'10px 14px', borderRadius:8, background:TV.panel2,
          border:`1px solid ${TV.line}`, fontSize:12.5, color:TV.text3, lineHeight:1.5}}>
        ⚠ Importing will overwrite existing data. Export a backup first. Database imports restart the app.
      </div>
    </div>
    {/* Password */}
    <div style={PF_CARD}>
      <SectionHead icon="🔒" title="Password"/>
      <div style={{display:'grid', gridTemplateColumns:'1fr 1fr 1fr auto', gap:12, alignItems:'end'}}>
        {[['Current Password','Current','password'],['New Password','Min 6 chars','password'],['Confirm New','Repeat','password']].map(([lbl,ph,type])=>(
          <div key={lbl}>
            <div style={{fontSize:11, fontWeight:700, color:TV.text3, textTransform:'uppercase',
                letterSpacing:'.05em', marginBottom:6}}>{lbl}</div>
            <SInput placeholder={ph} type={type}/>
          </div>
        ))}
        <button className="tv-btn primary" style={{padding:'9px 20px', fontSize:13, whiteSpace:'nowrap'}}>Update Password</button>
      </div>
    </div>
  </div>
);

// ── section: Messaging ───────────────────────────────────
const MessagingSection = () => (
  <div style={{display:'flex', flexDirection:'column', gap:20}}>
    <div style={PF_CARD}>
      <SectionHead icon="✉" title="Telegram Notifications"
          desc="Receive daily portfolio digests and market regime assessments via Telegram. Create a bot with @BotFather to get your bot token."/>
      {/* config row */}
      <div style={{display:'grid', gridTemplateColumns:'1fr 1fr 160px 140px', gap:12, alignItems:'end', marginBottom:18}}>
        {[['Bot Token','••••','password'],['Chat ID','','text'],['Schedule (UTC Hour)','9','text']].map(([lbl,val,type])=>(
          <div key={lbl}>
            <div style={{fontSize:11, fontWeight:700, color:TV.text3, textTransform:'uppercase', letterSpacing:'.05em', marginBottom:6}}>{lbl}</div>
            <SInput value={val} placeholder="Paste value" type={type} mono={lbl==='Bot Token'}/>
          </div>
        ))}
        <div>
          <div style={{fontSize:11, fontWeight:700, color:TV.text3, textTransform:'uppercase', letterSpacing:'.05em', marginBottom:6}}>Enabled</div>
          <div style={{background:TV.panel2, border:`1px solid ${TV.line}`, borderRadius:8, padding:'9px 13px',
              fontSize:13, color:TV.text, display:'flex', justifyContent:'space-between'}}>
            <span>Disabled</span><span style={{color:TV.text3}}>▾</span>
          </div>
        </div>
      </div>
      {/* notification content */}
      <div style={{borderTop:`1px solid ${TV.lineSoft}`, paddingTop:16}}>
        <div style={{fontSize:14, fontWeight:700, color:TV.accent, marginBottom:12}}>Notification Content</div>
        <div style={{display:'flex', gap:20, marginBottom:18}}>
          {['Daily Digest','Market Regime Assessment'].map(lbl=>(
            <label key={lbl} style={{display:'flex', alignItems:'center', gap:8, cursor:'pointer'}}>
              <span style={{width:16, height:16, borderRadius:3, background:TV.adapt,
                  display:'flex', alignItems:'center', justifyContent:'center', flexShrink:0}}>
                <span style={{color:'#fff', fontSize:11, fontWeight:700}}>✓</span>
              </span>
              <span style={{fontSize:13.5, color:TV.text}}>{lbl}</span>
            </label>
          ))}
        </div>
        <div style={{display:'flex', gap:10}}>
          <button className="tv-btn" style={{padding:'9px 20px', fontSize:13}}>Save</button>
          <button className="tv-btn primary" style={{padding:'9px 20px', fontSize:13}}>Send Test Message</button>
        </div>
      </div>
    </div>
  </div>
);

const SettingsNewHF = ({defaultSection = 'display'}) => {
  const [section, setSection] = React.useState(defaultSection);
  const CONTENT = {
    display:      <DisplaySection/>,
    wallets:      <WalletsSection/>,
    integrations: <IntegrationsSection/>,
    ai:           <AiSection/>,
    docs:         <DocsSection/>,
    pnlconfig:    <PnlConfigSection/>,
    backup:       <BackupSection/>,
    messaging:    <MessagingSection/>,
  };
  return (
    <div className="tv-frame" style={{display: 'flex', flexDirection: 'column'}}>
      <TVNav active="Settings"/>
      <div style={{flex: 1, display: 'flex', minHeight: 0, overflow: 'hidden'}}>
        {/* sidebar */}
        <div style={{width: 220, borderRight: `1px solid ${TV.line}`, background: TV.panel,
            padding: '24px 12px', display: 'flex', flexDirection: 'column', gap: 4, flexShrink: 0}}>
          <div style={{fontSize: 11, fontWeight: 600, color: TV.text4, letterSpacing: '.07em',
              textTransform: 'uppercase', padding: '0 8px', marginBottom: 10}}>Settings</div>
          {SETT_SECTIONS.map(s => (
            <div key={s.id} onClick={() => setSection(s.id)} style={{padding: '9px 12px', borderRadius: 8,
                cursor: 'pointer', fontSize: 13.5, fontWeight: section === s.id ? 600 : 400,
                color: section === s.id ? TV.text : TV.text2,
                background: section === s.id ? TV.panel3 : 'transparent',
                borderLeft: section === s.id ? `3px solid ${TV.accent}` : '3px solid transparent'}}>
              {s.label}
            </div>
          ))}
        </div>
        {/* content panel */}
        <div style={{flex: 1, padding: '28px 32px', overflowY: 'auto', minHeight: 0}}>
          {CONTENT[section]}
        </div>
      </div>
    </div>
  );
};
