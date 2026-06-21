// portfolio.jsx — Portfolio tab (Token Holdings + DeFi Positions)
// Extends the existing dark-blue design system: same TV.* tokens, .tv-* utility
// classes, card/typography/spacing vocabulary as DashHF / ScanHF.
// One component, two sub-views via the `view` prop ('tokens' | 'defi').

// ---- shared style constants (mirror the dashboard system) ----
const PF_CARD   = {background: TV.panel, border: `1px solid ${TV.line}`, borderRadius: 14, padding: 24};
const PF_TITLE  = {fontSize: 17, fontWeight: 700, color: TV.accent, letterSpacing: '-.1px'};
const PF_SUB    = {fontSize: 13.5, color: TV.text3};
const PF_METRIC = {background: TV.panel, border: `1px solid ${TV.line}`, borderRadius: 12, padding: 18};

// ---- chain badge (small colored tag, no external logos) ----
const CHAIN_META = {
  ETH:  {label: 'ETH',  color: '#627eea'},
  BASE: {label: 'BASE', color: '#1763ff'},
  ARB:  {label: 'ARB',  color: '#2e9bd6'},
  OP:   {label: 'OP',   color: '#e0524d'},
  SOL:  {label: 'SOL',  color: '#9945ff'},
  POLY: {label: 'POLY', color: '#8247e5'},
  BNB:  {label: 'BNB',  color: '#e3a91a'},
};
const ChainBadge = ({chain}) => {
  const c = CHAIN_META[chain] || {label: chain, color: TV.text4};
  return (
    <span className="tv-num" style={{fontSize: 9.5, fontWeight: 700, color: '#fff',
        background: c.color, borderRadius: 4, padding: '2px 5px', letterSpacing: '.03em',
        flexShrink: 0, lineHeight: 1.3}}>{c.label}</span>
  );
};

// ---- segmented control (matches nav-active treatment: panel3 + accent underline) ----
const PFSeg = ({options, active, size = 'sm'}) => (
  <div style={{display: 'inline-flex', gap: 3, padding: 3, borderRadius: 8,
      background: TV.panel2, border: `1px solid ${TV.line}`}}>
    {options.map(o => {
      const on = o === active;
      return (
        <span key={o} style={{
          padding: size === 'lg' ? '9px 18px' : '6px 13px',
          borderRadius: 6, fontSize: size === 'lg' ? 14 : 13, fontWeight: on ? 600 : 500,
          color: on ? TV.text : TV.text3, background: on ? TV.panel3 : 'transparent',
          boxShadow: on ? `inset 0 -2px 0 ${TV.accent}` : 'none', cursor: 'pointer',
          whiteSpace: 'nowrap',
        }}>{o}</span>
      );
    })}
  </div>
);

// eye / eye-off glyph for wallet visibility
const EyeIcon = ({off}) => (
  <svg width="15" height="15" viewBox="0 0 16 16" fill="none" style={{flexShrink: 0}}>
    <path d="M1 8s2.5-4.5 7-4.5S15 8 15 8s-2.5 4.5-7 4.5S1 8 1 8Z"
        stroke={off ? TV.text4 : TV.text2} strokeWidth="1.3"/>
    <circle cx="8" cy="8" r="1.9" stroke={off ? TV.text4 : TV.text2} strokeWidth="1.3"/>
    {off && <line x1="2.5" y1="13.5" x2="13.5" y2="2.5" stroke={TV.text4} strokeWidth="1.3"/>}
  </svg>
);

const WALLETS = [
  {id: 'hot',    label: 'Desktop Hot',  addr: '0xaB7A…6743', value: '$18,420.55', dot: TV.accent, selected: true,  hidden: false},
  {id: 'spare',  label: 'Spare Change', addr: '0x79c0…c4d9', value: '$6,240.18',  dot: TV.adapt,  selected: true,  hidden: false},
  {id: 'fusion', label: 'Fusion1',      addr: '0xCb27…E805', value: '$13,180.92', dot: TV.ok,     selected: true,  hidden: false},
  {id: 'hype',   label: 'Hype',         addr: '0x0c55…d55E', value: '$2,996.09',  dot: '#c98bdb', selected: true,  hidden: true},
];

const CHAIN_FILTERS = ['All chains', 'Ethereum', 'Base', 'Arbitrum', 'Solana'];

// =============================================================
// Health-factor gauge (full-width, zoned, with scale ticks) — on-system
// =============================================================
const HealthBar = ({value}) => {
  const col = value >= 2 ? TV.ok : value >= 1.3 ? TV.warn : TV.fail;
  const map = v => Math.max(0, Math.min(100, ((v - 1) / 2) * 100)); // 1.0→0%, 3.0→100%
  const pos = map(value);
  const ticks = [1.0, 1.2, 1.5, 2.0, 3.0];
  return (
    <div style={{display: 'flex', flexDirection: 'column', gap: 7}}>
      <div style={{display: 'flex', alignItems: 'center', justifyContent: 'space-between'}}>
        <span className="tv-uppercase">Health factor gauge</span>
        <span className="tv-num" style={{fontSize: 16, fontWeight: 700, color: col}}>{value.toFixed(2)}</span>
      </div>
      <div style={{position: 'relative', height: 9, borderRadius: 5, overflow: 'hidden', display: 'flex'}}>
        <div style={{width: '12%', background: TV.fail}}/>
        <div style={{width: '13%', background: '#e08a42'}}/>
        <div style={{width: '15%', background: TV.warn}}/>
        <div style={{flex: 1, background: TV.ok}}/>
        <div style={{position: 'absolute', left: `${pos}%`, top: '50%', width: 14, height: 14, borderRadius: '50%',
            background: TV.panel, border: `3px solid ${col}`, transform: 'translate(-50%,-50%)',
            boxShadow: '0 1px 4px rgba(0,0,0,.45)'}}/>
      </div>
      <div style={{position: 'relative', height: 13}}>
        {ticks.map(t => {
          const p = map(t);
          return <span key={t} className="tv-num" style={{position: 'absolute', left: `${p}%`,
            transform: p === 0 ? 'none' : p >= 100 ? 'translateX(-100%)' : 'translateX(-50%)',
            fontSize: 10.5, color: TV.text4}}>{t.toFixed(1)}</span>;
        })}
      </div>
    </div>
  );
};

// =============================================================
// TOKEN HOLDINGS table
// =============================================================
const TOKEN_GROUPS = [
  ['Majors', '$24,910', [
    ['ETH',  'Ethereum',     'ETH',  '6.4210',  '$3,420.10', '$21,963', 'Desktop Hot', 54],
    ['WBTC', 'Wrapped BTC',  'ETH',  '0.0420',  '$71,840',   '$3,017',  'Fusion1',     7],
  ]],
  ['Stablecoins', '$9,180', [
    ['USDC', 'USD Coin',     'BASE', '5,240.00', '$1.00',     '$5,240',  '3 wallets',  13],
    ['USDC', 'USD Coin',     'ARB',  '2,940.00', '$1.00',     '$2,940',  'Spare Change', 7],
    ['USDT', 'Tether',       'ETH',  '1,000.00', '$1.00',     '$1,000',  'Desktop Hot', 2],
  ]],
  ['Altcoins', '$6,748', [
    ['SOL',  'Solana',       'SOL',  '18.40',    '$168.20',   '$3,094',  'Hype',        8],
    ['ARB',  'Arbitrum',     'ARB',  '2,140.0',  '$0.92',     '$1,969',  'Spare Change', 5],
    ['LINK', 'Chainlink',    'ETH',  '78.50',    '$14.80',    '$1,162',  'Fusion1',     3],
    ['AERO', 'Aerodrome',    'BASE', '1,310.0',  '$0.40',     '$523',    'Fusion1',     1],
  ]],
];

const TokenHoldings = ({grouping}) => {
  const COLS = 'minmax(190px,1.5fr) 130px 110px 130px 150px 1fr';
  return (
    <div style={PF_CARD}>
      {/* controls */}
      <div style={{display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16, flexWrap: 'wrap'}}>
        <div style={PF_TITLE}>Token Holdings</div>
        <span className="tv-chip" style={{fontSize: 12}}>9 tokens</span>
        <div style={{flex: 1}}/>
        <PFSeg options={['By Type', 'By Wallet']} active={grouping}/>
        <span className="tv-chip" style={{fontSize: 12, color: TV.text3, cursor: 'pointer'}}>
          <span className="tv-dot" style={{color: TV.text4}}/>Dust hidden · &lt; $1 · 8 tokens ($3.21) ✕
        </span>
      </div>

      {/* table */}
      <div style={{border: `1px solid ${TV.line}`, borderRadius: 10, overflow: 'hidden'}}>
        {/* header */}
        <div style={{display: 'grid', gridTemplateColumns: COLS, gap: 14, padding: '10px 16px',
            background: TV.panel2, borderBottom: `1px solid ${TV.line}`,
            fontSize: 11, fontWeight: 600, color: TV.text3, letterSpacing: '.06em', textTransform: 'uppercase'}}>
          <span>Token</span>
          <span style={{textAlign: 'right'}}>Balance</span>
          <span style={{textAlign: 'right'}}>Price</span>
          <span style={{textAlign: 'right'}}>Value</span>
          <span>Wallet</span>
          <span>Allocation</span>
        </div>

        {TOKEN_GROUPS.map(([group, subtotal, rows], gi) => (
          <React.Fragment key={group}>
            <div style={{display: 'flex', alignItems: 'center', gap: 10, padding: '8px 16px',
                background: TV.bg, borderBottom: `1px solid ${TV.lineSoft}`,
                borderTop: gi === 0 ? 'none' : `1px solid ${TV.line}`}}>
              <span style={{fontSize: 11, fontWeight: 700, color: TV.text2, letterSpacing: '.06em', textTransform: 'uppercase'}}>{group}</span>
              <div style={{flex: 1}}/>
              <span className="tv-num" style={{fontSize: 12.5, color: TV.text3}}>{subtotal}</span>
            </div>
            {rows.map(([sym, name, chain, bal, price, value, wallet, alloc], i) => (
              <div key={sym + i} style={{display: 'grid', gridTemplateColumns: COLS, gap: 14,
                  padding: '12px 16px', alignItems: 'center',
                  borderBottom: `1px solid ${TV.lineSoft}`}}>
                <div style={{display: 'flex', alignItems: 'center', gap: 9, minWidth: 0}}>
                  <ChainBadge chain={chain}/>
                  <span className="tv-num" style={{fontSize: 14, fontWeight: 700, color: TV.text}}>{sym}</span>
                  <span style={{fontSize: 12.5, color: TV.text3, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap'}}>{name}</span>
                </div>
                <span className="tv-num" style={{fontSize: 13, color: TV.text2, textAlign: 'right'}}>{bal}</span>
                <span className="tv-num" style={{fontSize: 13, color: TV.text3, textAlign: 'right'}}>{price}</span>
                <span className="tv-num" style={{fontSize: 14, fontWeight: 600, color: TV.text, textAlign: 'right'}}>{value}</span>
                <span style={{fontSize: 12.5, color: TV.text2, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap'}}>{wallet}</span>
                <div style={{display: 'flex', alignItems: 'center', gap: 8}}>
                  <div style={{flex: 1, height: 6, background: TV.panel3, borderRadius: 3, overflow: 'hidden', maxWidth: 130}}>
                    <div style={{height: '100%', width: `${alloc * 1.6}%`, background: TV.accent, opacity: 0.85}}/>
                  </div>
                  <span className="tv-num" style={{fontSize: 12, color: TV.text3, width: 30, textAlign: 'right'}}>{alloc}%</span>
                </div>
              </div>
            ))}
          </React.Fragment>
        ))}
      </div>

      <div style={{display: 'flex', alignItems: 'center', marginTop: 14}}>
        <span style={PF_SUB}>Grouped {grouping === 'By Type' ? 'by asset type' : 'by wallet'} · 8 dust tokens hidden ($3.21)</span>
        <div style={{flex: 1}}/>
        <span className="tv-num" style={{fontSize: 13, color: TV.text2}}>Total <span style={{color: TV.text, fontWeight: 700, fontSize: 15}}>$40,837.74</span></span>
      </div>
    </div>
  );
};

// =============================================================
// DEFI POSITIONS — LP cards + lending cards
// =============================================================
// token icon (small colored disc + glyph; no external logos)
const TOKEN_META = {
  WETH: {c: '#627eea', ab: 'Ξ'}, ETH: {c: '#627eea', ab: 'Ξ'}, WBTC: {c: '#f09242', ab: '₿'},
  cbBTC: {c: '#f09242', ab: '₿'}, USDC: {c: '#2775ca', ab: '$'}, USDT: {c: '#26a17b', ab: '$'},
  AERO: {c: '#1763ff', ab: 'A'}, ARB: {c: '#2e9bd6', ab: 'A'}, SOL: {c: '#9945ff', ab: 'S'},
  LINK: {c: '#2a5ada', ab: 'L'}, XRP: {c: '#5b6b7a', ab: 'X'},
};
const TokenIcon = ({sym, size = 24}) => {
  const m = TOKEN_META[sym] || {c: TV.text4, ab: sym[0]};
  return (
    <span style={{width: size, height: size, borderRadius: '50%', background: m.c, color: '#fff',
        display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
        fontSize: size * 0.5, fontWeight: 700, flexShrink: 0}}>{m.ab}</span>
  );
};

const SectionLabel = ({children}) => (
  <div style={{fontSize: 11.5, fontWeight: 700, color: TV.accent, letterSpacing: '.07em',
      textTransform: 'uppercase', marginBottom: 8}}>{children}</div>
);

const TokenAmountTile = ({sym, amount, usd}) => (
  <div style={{flex: 1, minWidth: 0, padding: '11px 14px', borderRadius: 10,
      border: `1px solid ${TV.line}`, background: TV.panel, display: 'flex', alignItems: 'center', gap: 11}}>
    <TokenIcon sym={sym} size={26}/>
    <span style={{fontSize: 13.5, fontWeight: 600, color: TV.text}}>{sym}</span>
    <div style={{flex: 1}}/>
    <div style={{textAlign: 'right'}}>
      <div className="tv-num" style={{fontSize: 18, fontWeight: 700, color: TV.text, letterSpacing: '-.3px'}}>{amount}</div>
      <div className="tv-num" style={{fontSize: 12, color: TV.text3, marginTop: 1}}>{usd}</div>
    </div>
  </div>
);

// concentrated-liquidity price-range bar
const RangeBar = ({minP, curP, maxP, width, inRange}) => {
  const lo = 14, hi = 70;          // colored band (min→max)
  const cur = inRange ? 44 : 90;   // current-price marker
  return (
    <div>
      <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 9}}>
        <span style={{fontSize: 12, color: TV.text3}}>Price Range</span>
        <span style={{fontSize: 12, fontWeight: 600, color: inRange ? TV.ok : TV.warn}}>
          {inRange ? 'Position Active' : 'Position Inactive'}
        </span>
      </div>
      <div style={{position: 'relative', height: 8, borderRadius: 4, background: TV.panel3, marginBottom: 12}}>
        <div style={{position: 'absolute', left: `${lo}%`, width: `${hi - lo}%`, top: 0, bottom: 0,
            borderRadius: 4, background: 'linear-gradient(90deg,#a855f7,#3b82f6,#22d3ee)'}}/>
        <div style={{position: 'absolute', left: `${cur}%`, top: -3, bottom: -3, width: 3,
            background: inRange ? TV.ok : TV.warn, transform: 'translateX(-50%)', borderRadius: 2}}/>
      </div>
      <div style={{display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 10, textAlign: 'center'}}>
        {[['Min Price', minP, TV.text], ['Current Price', curP, inRange ? TV.text : TV.warn], ['Max Price', maxP, TV.text]].map(([l, v, col]) => (
          <div key={l}>
            <div style={{fontSize: 11, color: TV.text4}}>{l}</div>
            <div className="tv-num" style={{fontSize: 16, fontWeight: 700, color: col, marginTop: 2}}>{v}</div>
          </div>
        ))}
      </div>
      <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 13,
          paddingTop: 12, borderTop: `1px solid ${TV.lineSoft}`}}>
        <span style={{fontSize: 12.5, color: TV.text3}}>Range Width</span>
        <span className="tv-num" style={{fontSize: 14, fontWeight: 700, color: TV.text}}>{width}</span>
      </div>
    </div>
  );
};

const LpCard = ({pair, chain, protocol, fee, wallet, nft, age, inRange, totalValue, uncollectedTotal,
    liquidity, fees, range, perf, apr, pool}) => (
  <div style={{padding: 20, borderRadius: 12, border: `1.5px solid ${TV.accent}`, background: TV.panel2,
      display: 'flex', flexDirection: 'column', gap: 14}}>
    {/* header */}
    <div style={{display: 'flex', alignItems: 'flex-start', gap: 12, flexWrap: 'wrap'}}>
      <div style={{display: 'flex'}}>
        <TokenIcon sym={liquidity[0].sym} size={32}/>
        <span style={{marginLeft: -11}}><TokenIcon sym={liquidity[1].sym} size={32}/></span>
      </div>
      <div style={{minWidth: 0}}>
        <div style={{display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginBottom: 6}}>
          <span style={{fontSize: 17, fontWeight: 700, color: TV.text}}>{pair}</span>
          <span className="tv-chip" style={{fontSize: 11}}>Liquidity Position</span>
          <span className="tv-chip" style={{fontSize: 11}}>{protocol}</span>
          <span className="tv-chip" style={{fontSize: 11}}>{fee} Fee</span>
          <span className="tv-chip" style={{fontSize: 11, color: inRange ? TV.ok : TV.warn,
              borderColor: inRange ? 'rgba(79,221,142,.4)' : 'rgba(255,210,63,.4)',
              background: inRange ? TV.okSoft : TV.warnSoft}}>
            <span className="tv-dot"/>{inRange ? 'In Range' : 'Out of Range'}
          </span>
        </div>
        <div style={{display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', fontSize: 12.5, color: TV.text3}}>
          <ChainBadge chain={chain}/>
          <span>{wallet}</span><span style={{color: TV.text4}}>·</span>
          <span>{protocol}</span><span style={{color: TV.text4}}>·</span>
          <span className="tv-num">NFT #{nft}</span><span style={{color: TV.text4}}>·</span>
          <span className="tv-num">{age}</span>
        </div>
      </div>
      <div style={{flex: 1}}/>
      <div style={{textAlign: 'right'}}>
        <div className="tv-num" style={{fontSize: 26, fontWeight: 700, color: TV.text, letterSpacing: '-.4px'}}>{totalValue}</div>
        <div className="tv-num" style={{fontSize: 12.5, color: TV.ok, marginTop: 2}}>+{uncollectedTotal} Uncollected Fees</div>
      </div>
    </div>

    {/* current liquidity */}
    <div>
      <SectionLabel>Current Liquidity</SectionLabel>
      <div style={{display: 'flex', gap: 14}}>
        {liquidity.map(t => <TokenAmountTile key={t.sym} {...t}/>)}
      </div>
    </div>

    {/* uncollected fees */}
    <div>
      <SectionLabel>Uncollected Fees</SectionLabel>
      <div style={{display: 'flex', gap: 14}}>
        {fees.map(t => <TokenAmountTile key={t.sym} {...t}/>)}
      </div>
      <div style={{display: 'flex', alignItems: 'center', marginTop: 12}}>
        <span style={{fontSize: 13, color: TV.text3}}>Total Uncollected</span>
        <div style={{flex: 1}}/>
        <div style={{textAlign: 'right'}}>
          <div className="tv-num" style={{fontSize: 16, fontWeight: 700, color: TV.ok}}>{uncollectedTotal}</div>
          <div style={{fontSize: 11, color: TV.text3}}>Ready to collect</div>
        </div>
      </div>
    </div>

    {/* concentrated liquidity range */}
    <div>
      <SectionLabel>Concentrated Liquidity Range</SectionLabel>
      <RangeBar {...range} inRange={inRange}/>
    </div>

    {/* performance metrics */}
    <div>
      <SectionLabel>Performance Metrics</SectionLabel>
      <div style={{padding: 16, borderRadius: 10, border: `1px solid rgba(79,221,142,.35)`, background: TV.okSoft}}>
        <div style={{fontSize: 12, color: TV.text3, marginBottom: 4}}>Total Fees</div>
        <div className="tv-num" style={{fontSize: 24, fontWeight: 700, color: TV.ok}}>{perf.total}</div>
        <div style={{marginTop: 7, display: 'flex', flexDirection: 'column', gap: 3}}>
          {perf.collected.map((l, i) => (
            <span key={i} className="tv-num" style={{fontSize: 12.5, color: TV.text2}}>Collected: {l}</span>
          ))}
          <span className="tv-num" style={{fontSize: 12.5, color: TV.ok}}>{perf.uncollected}</span>
        </div>
      </div>
    </div>

    {/* yield & APR */}
    <div>
      <SectionLabel>Yield &amp; APR Projections</SectionLabel>
      <div style={{display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 12}}>
        {apr.map(([lbl, pct, sub]) => (
          <div key={lbl} style={{padding: 14, borderRadius: 10, border: `1px solid ${TV.line}`, background: TV.panel}}>
            <div style={{fontSize: 11.5, color: TV.text3, marginBottom: 5}}>{lbl} APR</div>
            <div className="tv-num" style={{fontSize: 20, fontWeight: 700, color: TV.ok}}>{pct}</div>
            <div className="tv-num" style={{fontSize: 11.5, color: TV.text3, marginTop: 2}}>{sub}</div>
          </div>
        ))}
      </div>
    </div>

    {/* pool statistics */}
    <div>
      <SectionLabel>Pool Statistics</SectionLabel>
      <div style={{display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 12}}>
        {pool.map(([lbl, val, accent]) => (
          <div key={lbl} style={{padding: 14, borderRadius: 10, border: `1px solid ${TV.line}`, background: TV.panel}}>
            <div style={{fontSize: 11.5, color: TV.text3, marginBottom: 5}}>{lbl}</div>
            <div className="tv-num" style={{fontSize: 18, fontWeight: 700, color: accent ? TV.accent : TV.text}}>{val}</div>
          </div>
        ))}
      </div>
    </div>
  </div>
);

// =============================================================
// LEND CARD MODALS — Edit · History · Archive
// =============================================================
const Overlay = ({onClose, children}) => (
  <div style={{position: 'fixed', inset: 0, zIndex: 9999, display: 'flex', alignItems: 'center', justifyContent: 'center',
      background: 'rgba(5,18,35,0.82)'}} onClick={onClose}>
    <div style={{background: TV.panel, border: `1px solid ${TV.line}`, borderRadius: 14,
        boxShadow: '0 24px 80px rgba(0,0,0,.7)', minWidth: 560, maxWidth: 720, width: '90vw', maxHeight: '90vh',
        overflowY: 'auto', position: 'relative'}} onClick={e => e.stopPropagation()}>
      {children}
    </div>
  </div>
);
const MHead = ({title, onClose}) => (
  <div style={{display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      padding: '18px 22px 14px', borderBottom: `1px solid ${TV.line}`}}>
    <span style={{fontSize: 16, fontWeight: 700, color: TV.text}}>{title}</span>
    <span onClick={onClose} style={{fontSize: 20, color: TV.text3, cursor: 'pointer', lineHeight: 1, padding: '0 4px'}}>×</span>
  </div>
);
const MField = ({label, value, placeholder, wide, half}) => (
  <div style={{display: 'flex', flexDirection: 'column', gap: 5, gridColumn: wide ? '1 / -1' : half ? 'span 1' : undefined}}>
    <div style={{fontSize: 11, fontWeight: 700, color: TV.text3, textTransform: 'uppercase', letterSpacing: '.05em'}}>{label}</div>
    <div style={{background: TV.panel2, border: `1px solid ${TV.line}`, borderRadius: 8, padding: '9px 13px',
        fontSize: 13.5, color: value ? TV.text : TV.text4}}>{value || <span style={{opacity:.55}}>{placeholder}</span>}</div>
  </div>
);

const EditModal = ({protocol, chain, opened, maxLtv, lending, borrowing, note, onClose}) => (
  <Overlay onClose={onClose}>
    <MHead title="Edit Position" onClose={onClose}/>
    <div style={{padding: '20px 22px', display: 'flex', flexDirection: 'column', gap: 16}}>
      {/* top fields */}
      <div style={{display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14}}>
        <MField label="Protocol" value={protocol}/>
        <MField label="Network / Chain" value={chain}/>
        <MField label="Date Opened" value={opened}/>
        <div style={{display: 'flex', flexDirection: 'column', gap: 5}}>
          <MField label="Max Borrow LTV %" value={maxLtv ? maxLtv.replace('%','') : ''}/>
          <div style={{fontSize: 11.5, color: TV.text4}}>Protocol’s max borrowing % (e.g. 75 for 75%)</div>
        </div>
      </div>
      {/* lending assets */}
      <div>
        <div style={{fontSize: 12, fontWeight: 700, color: TV.ok, textTransform: 'uppercase', letterSpacing: '.06em', marginBottom: 10}}>Lending Assets</div>
        {lending.map(([sym, qty, , , liqThr, apy], i) => (
          <div key={i} style={{display: 'grid', gridTemplateColumns: '1fr 1fr 1fr 1fr 1fr 32px', gap: 10, marginBottom: 10, alignItems: 'end'}}>
            {[['Token', sym], ['Quantity', qty], ['Liq Thr %', liqThr ? liqThr.replace('%','') : ''], ['APY %', apy ? apy.replace('%','') : ''], ['Manual Price $', '']].map(([l, v]) => (
              <MField key={l} label={l} value={v} placeholder="optional"/>
            ))}
            <button className="tv-btn ghost" style={{padding: '7px 10px', color: TV.fail, borderColor: `${TV.fail}44`}}>×</button>
          </div>
        ))}
        <button className="tv-btn ghost" style={{fontSize: 12.5, padding: '6px 14px', marginTop: 2}}>+ Add Lent Asset</button>
      </div>
      {/* borrowing assets */}
      <div>
        <div style={{fontSize: 12, fontWeight: 700, color: TV.fail, textTransform: 'uppercase', letterSpacing: '.06em', marginBottom: 10}}>Borrowing Assets</div>
        {borrowing.map(([sym, qty, , , apr], i) => (
          <div key={i} style={{display: 'grid', gridTemplateColumns: '1fr 1fr 1fr 1fr 32px', gap: 10, marginBottom: 10, alignItems: 'end'}}>
            {[['Token', sym], ['Quantity', qty], ['Borrow APR %', apr ? apr.replace('%','') : ''], ['Manual Price $', '']].map(([l, v]) => (
              <MField key={l} label={l} value={v} placeholder="optional"/>
            ))}
            <button className="tv-btn ghost" style={{padding: '7px 10px', color: TV.fail, borderColor: `${TV.fail}44`}}>×</button>
          </div>
        ))}
        <button className="tv-btn ghost" style={{fontSize: 12.5, padding: '6px 14px', marginTop: 2}}>+ Add Borrowed Asset</button>
      </div>
      {/* notes */}
      <div style={{display: 'flex', flexDirection: 'column', gap: 6}}>
        <div style={{fontSize: 11, fontWeight: 700, color: TV.text3, textTransform: 'uppercase', letterSpacing: '.05em'}}>Notes</div>
        <div style={{background: TV.panel2, border: `1px solid ${TV.line}`, borderRadius: 8, padding: '10px 13px',
            fontSize: 13.5, color: TV.text3, minHeight: 72, lineHeight: 1.6}}>{note || <span style={{opacity:.5}}>Add a note…</span>}</div>
      </div>
      {/* actions */}
      <div style={{display: 'flex', justifyContent: 'flex-end', gap: 10, paddingTop: 4}}>
        <button className="tv-btn ghost" style={{padding: '9px 20px'}} onClick={onClose}>Cancel</button>
        <button className="tv-btn primary" style={{padding: '9px 22px'}}>Save Position</button>
      </div>
    </div>
  </Overlay>
);

const HISTORY_ACTIONS = ['Note', 'Deposit', 'Withdrawal', 'Borrow', 'Repay', 'Rebalance'];
const HistoryModal = ({protocol, chain, history = 1, onClose}) => {
  const historyEntries = [
    {date: '2026-04-14', type: 'OPENED', desc: 'Opened — lent 0.15 cbBTC, borrowed 3,500 USDC', dot: TV.ok},
    ...(history > 1 ? [
      {date: '2026-04-28', type: 'NOTE', desc: 'BTC held above $70K. Position healthy.', dot: TV.adapt},
      {date: '2026-05-10', type: 'REPAY', desc: 'Repaid 500 USDC partial. LTV reduced to 28%.', dot: TV.warn},
    ] : []).slice(0, history - 1),
  ];
  return (
    <Overlay onClose={onClose}>
      <MHead title={`${protocol} · ${chain} — History`} onClose={onClose}/>
      <div style={{padding: '20px 22px', display: 'flex', flexDirection: 'column', gap: 16}}>
        {/* timeline */}
        <div style={{display: 'flex', flexDirection: 'column', gap: 0}}>
          {historyEntries.map((e, i) => (
            <div key={i} style={{display: 'flex', gap: 14, paddingBottom: 16, position: 'relative'}}>
              <div style={{display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 0, width: 14, flexShrink: 0}}>
                <span style={{width: 10, height: 10, borderRadius: '50%', background: e.dot, flexShrink: 0, marginTop: 4}}/>
                {i < historyEntries.length - 1 && <div style={{width: 1, flex: 1, background: TV.lineSoft, marginTop: 4}}/>}
              </div>
              <div>
                <div className="tv-num" style={{fontSize: 12.5, color: TV.text4, marginBottom: 2}}>{e.date}</div>
                <div style={{fontSize: 12, fontWeight: 700, color: TV.text3, textTransform: 'uppercase', letterSpacing: '.05em', marginBottom: 3}}>{e.type}</div>
                <div style={{fontSize: 13.5, color: TV.text}}>{e.desc}</div>
              </div>
            </div>
          ))}
        </div>
        {/* add entry */}
        <div style={{borderTop: `1px solid ${TV.line}`, paddingTop: 16, display: 'flex', flexDirection: 'column', gap: 12}}>
          <div style={{textAlign: 'center', fontSize: 12, fontWeight: 700, color: TV.text3, letterSpacing: '.06em', textTransform: 'uppercase'}}>Add Entry</div>
          <div style={{display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12}}>
            <div style={{display: 'flex', flexDirection: 'column', gap: 5}}>
              <div style={{fontSize: 11, fontWeight: 700, color: TV.text3, textTransform: 'uppercase', letterSpacing: '.05em'}}>Action</div>
              <div style={{background: TV.panel2, border: `1px solid ${TV.line}`, borderRadius: 8, padding: '9px 13px',
                  fontSize: 13.5, color: TV.text, display: 'flex', justifyContent: 'space-between'}}>
                <span>Note</span><span style={{color: TV.text3}}>▾</span>
              </div>
            </div>
            <MField label="Date" value="05/31/2026"/>
          </div>
          <div style={{display: 'flex', flexDirection: 'column', gap: 5}}>
            <div style={{fontSize: 11, fontWeight: 700, color: TV.text3, textTransform: 'uppercase', letterSpacing: '.05em'}}>Details</div>
            <div style={{background: TV.panel2, border: `1px solid ${TV.line}`, borderRadius: 8, padding: '10px 13px',
                minHeight: 56, fontSize: 13.5, color: TV.text4}}><span style={{opacity:.5}}>Describe the action…</span></div>
          </div>
          <div style={{display: 'flex', justifyContent: 'flex-end', gap: 10}}>
            <button className="tv-btn primary" style={{padding: '9px 22px'}}>Add Entry</button>
          </div>
        </div>
        <div style={{display: 'flex', justifyContent: 'flex-end'}}>
          <button className="tv-btn ghost" style={{padding: '9px 20px'}} onClick={onClose}>Close</button>
        </div>
      </div>
    </Overlay>
  );
};

const ArchiveModal = ({protocol, onClose}) => (
  <Overlay onClose={onClose}>
    <MHead title="Confirm" onClose={onClose}/>
    <div style={{padding: '22px 24px 20px', display: 'flex', flexDirection: 'column', gap: 20}}>
      <div style={{fontSize: 14.5, color: TV.text, lineHeight: 1.6}}>Archive the <strong>{protocol}</strong> position? You can restore it later.</div>
      <div style={{display: 'flex', justifyContent: 'flex-end', gap: 10}}>
        <button className="tv-btn ghost" style={{padding: '9px 20px'}} onClick={onClose}>Cancel</button>
        <button className="tv-btn" style={{padding: '9px 22px', color: TV.fail, borderColor: `${TV.fail}66`,
            background: TV.failSoft}}>Archive</button>
      </div>
    </div>
  </Overlay>
);

const LendCard = ({protocol, chain, dir, tags = [], opened, wallet, history, health, status,
    ltv, maxLtv, netEquity, lendTotal, borrowRemaining, netApy, lendApy, borrowApy,
    lending, borrowing, note, last, liqPrices = []}) => {
  const [modal, setModal] = React.useState(null); // 'edit' | 'history' | 'archive' | null
  const hcol = health >= 2 ? TV.ok : health >= 1.3 ? TV.warn : TV.fail;
  const L_COLS = 'minmax(78px,1fr) 62px 88px 92px 60px 64px';
  const B_COLS = 'minmax(78px,1fr) 76px 88px 92px 66px';
  const headStyle = {fontSize: 10.5, fontWeight: 600, color: TV.text3, letterSpacing: '.05em', textTransform: 'uppercase'};
  return (
    <div style={{padding: 20, borderRadius: 12, border: `1.5px solid ${TV.accent}`, background: TV.panel2,
        display: 'flex', flexDirection: 'column', gap: 16}}>
      {/* header */}
      <div style={{display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap'}}>
        <span style={{fontSize: 15, fontWeight: 700, color: TV.text}}>{protocol}</span>
        <ChainBadge chain={chain}/>
        <span className="tv-chip" style={{fontSize: 11, padding: '1px 7px',
            color: dir === 'long' ? TV.ok : TV.fail,
            borderColor: dir === 'long' ? 'rgba(79,221,142,.4)' : 'rgba(255,138,138,.4)',
            background: dir === 'long' ? TV.okSoft : TV.failSoft}}>
          {dir === 'long' ? '▲ LONG' : '▼ SHORT'}
        </span>
        {tags.map(t => (
          <span key={t} className="tv-chip" style={{fontSize: 11, padding: '1px 7px', color: TV.adapt,
              borderColor: 'rgba(47,180,232,.4)', background: TV.adaptSoft}}>{t}</span>
        ))}
        <span style={{fontSize: 12.5, color: TV.text3}}>Opened {opened} · {wallet}</span>
        <div style={{flex: 1}}/>
        <button className="tv-btn ghost" style={{padding: '5px 10px', fontSize: 12}} onClick={()=>setModal('edit')}>Edit</button>
        <button className="tv-btn ghost" style={{padding: '5px 10px', fontSize: 12}} onClick={()=>setModal('history')}>History ({history})</button>
        <button className="tv-btn ghost" style={{padding: '5px 10px', fontSize: 12}} onClick={()=>setModal('archive')}>Archive</button>
        <span style={{fontSize: 16, color: TV.text3, cursor: 'pointer', padding: '0 4px'}} onClick={()=>setModal('archive')}>×</span>
      </div>
      {modal === 'edit'    && <EditModal    protocol={protocol} chain={chain} opened={opened} maxLtv={maxLtv} lending={lending} borrowing={borrowing} note={note} onClose={()=>setModal(null)}/>}
      {modal === 'history' && <HistoryModal protocol={protocol} chain={chain} history={history} onClose={()=>setModal(null)}/>}
      {modal === 'archive' && <ArchiveModal protocol={protocol} onClose={()=>setModal(null)}/>}

      {/* 5-metric row */}
      <div style={{display: 'grid', gridTemplateColumns: 'repeat(5,1fr)',
          borderTop: `1px solid ${TV.lineSoft}`, borderBottom: `1px solid ${TV.lineSoft}`, padding: '13px 0'}}>
        {[
          ['Health factor', health.toFixed(2), status, hcol],
          ['Current LTV', ltv, `Max ${maxLtv}`, TV.text],
          ['Net equity', netEquity, `Lend ${lendTotal}`, TV.ok],
          ['Borrow remaining', borrowRemaining, `at ${maxLtv} max LTV`, TV.text],
          ['Net APY', netApy, `Lend ${lendApy} / Borrow ${borrowApy}`, netApy.trim().startsWith('-') ? TV.fail : TV.ok],
        ].map(([lbl, val, sub, col], i) => (
          <div key={lbl} style={{display: 'flex', flexDirection: 'column', gap: 3, padding: '0 16px',
              borderLeft: i === 0 ? 'none' : `1px solid ${TV.lineSoft}`}}>
            <span className="tv-uppercase" style={{fontSize: 10}}>{lbl}</span>
            <span className="tv-num" style={{fontSize: 18, fontWeight: 700, color: col, letterSpacing: '-.2px'}}>{val}</span>
            <span style={{fontSize: 11.5, color: TV.text3}}>{sub}</span>
          </div>
        ))}
      </div>

      {/* gauge */}
      <HealthBar value={health}/>

      {/* liquidation prices */}
      {liqPrices && liqPrices.length > 0 && (
        <div style={{display:'flex', gap:10, flexWrap:'wrap'}}>
          <div style={{fontSize:10.5, fontWeight:700, color:TV.fail, textTransform:'uppercase',
              letterSpacing:'.06em', alignSelf:'center', whiteSpace:'nowrap'}}>Liquidates if price falls below</div>
          {liqPrices.map(([sym, liqPx, currPx, pctBelow]) => (
            <div key={sym} style={{padding:'7px 14px', borderRadius:8,
                border:`1px solid ${TV.fail}55`, background:TV.failSoft,
                display:'flex', flexDirection:'column', gap:2, minWidth:130}}>
              <div style={{fontSize:11.5, fontWeight:600, color:TV.text3}}>{sym}</div>
              <div className="tv-num" style={{fontSize:22, fontWeight:800, color:TV.fail, letterSpacing:'-.5px'}}>{liqPx}</div>
              <div style={{fontSize:11.5, color:TV.text4}}>↓ {pctBelow} below current ({currPx})</div>
            </div>
          ))}
        </div>
      )}
      <div style={{display: 'grid', gridTemplateColumns: '1.5fr 30px 1fr', alignItems: 'start'}}>
        {/* lending */}
        <div>
          <div style={{display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8}}>
            <span className="tv-uppercase" style={{color: TV.accent}}>Lending</span>
            <span style={{fontSize: 11, color: TV.text4}}>collateral supplied</span>
          </div>
          <div style={{display: 'grid', gridTemplateColumns: L_COLS, gap: 8, ...headStyle, paddingBottom: 6, borderBottom: `1px solid ${TV.lineSoft}`}}>
            <span>Asset</span><span style={{textAlign: 'right'}}>Qty</span><span style={{textAlign: 'right'}}>Price</span>
            <span style={{textAlign: 'right'}}>Value</span><span style={{textAlign: 'right'}}>LiqThr</span><span style={{textAlign: 'right'}}>APY</span>
          </div>
          {lending.map((r, i) => (
            <div key={i} style={{display: 'grid', gridTemplateColumns: L_COLS, gap: 8, alignItems: 'center',
                padding: '9px 0', borderBottom: i < lending.length - 1 ? `1px solid ${TV.lineSoft}` : 'none', fontSize: 13}}>
              <span style={{display: 'flex', alignItems: 'center', gap: 7}}>
                <span style={{width: 7, height: 7, borderRadius: '50%', background: TV.ok, flexShrink: 0}}/>
                <span className="tv-num" style={{fontWeight: 600, color: TV.text}}>{r[0]}</span>
              </span>
              <span className="tv-num" style={{textAlign: 'right', color: TV.text2}}>{r[1]}</span>
              <span className="tv-num" style={{textAlign: 'right', color: TV.text3}}>{r[2]}</span>
              <span className="tv-num" style={{textAlign: 'right', color: TV.text, fontWeight: 600}}>{r[3]}</span>
              <span className="tv-num" style={{textAlign: 'right', color: TV.text3}}>{r[4]}</span>
              <span className="tv-num" style={{textAlign: 'right', color: TV.ok}}>{r[5]}</span>
            </div>
          ))}
        </div>
        {/* arrow */}
        <div style={{display: 'flex', alignItems: 'center', justifyContent: 'center', alignSelf: 'center',
            color: TV.text4, fontSize: 18}}>→</div>
        {/* borrowing */}
        <div>
          <div style={{display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8}}>
            <span className="tv-uppercase" style={{color: TV.fail}}>Borrowing</span>
          </div>
          <div style={{display: 'grid', gridTemplateColumns: B_COLS, gap: 8, ...headStyle, paddingBottom: 6, borderBottom: `1px solid ${TV.lineSoft}`}}>
            <span>Asset</span><span style={{textAlign: 'right'}}>Qty</span><span style={{textAlign: 'right'}}>Price</span>
            <span style={{textAlign: 'right'}}>Value</span><span style={{textAlign: 'right'}}>APR</span>
          </div>
          {borrowing.map((r, i) => (
            <div key={i} style={{display: 'grid', gridTemplateColumns: B_COLS, gap: 8, alignItems: 'center',
                padding: '9px 0', borderBottom: i < borrowing.length - 1 ? `1px solid ${TV.lineSoft}` : 'none', fontSize: 13}}>
              <span style={{display: 'flex', alignItems: 'center', gap: 7}}>
                <span style={{width: 7, height: 7, borderRadius: '50%', background: TV.fail, flexShrink: 0}}/>
                <span className="tv-num" style={{fontWeight: 600, color: TV.text}}>{r[0]}</span>
              </span>
              <span className="tv-num" style={{textAlign: 'right', color: TV.text2}}>{r[1]}</span>
              <span className="tv-num" style={{textAlign: 'right', color: TV.text3}}>{r[2]}</span>
              <span className="tv-num" style={{textAlign: 'right', color: TV.text, fontWeight: 600}}>{r[3]}</span>
              <span className="tv-num" style={{textAlign: 'right', color: TV.fail}}>{r[4]}</span>
            </div>
          ))}
        </div>
      </div>

      {/* footer */}
      <div style={{display: 'flex', alignItems: 'center', gap: 12, borderTop: `1px solid ${TV.lineSoft}`, paddingTop: 12}}>
        <span style={{fontSize: 12.5, color: TV.text3, fontStyle: 'italic'}}>{note}</span>
        <div style={{flex: 1}}/>
        <span style={{fontSize: 11.5, color: TV.text4}}>Last: {last}</span>
      </div>
    </div>
  );
};

const DefiPositions = () => (
  <div style={{display: 'flex', flexDirection: 'column', gap: 22}}>
    {/* Liquidity positions */}
    <div style={PF_CARD}>
      <div style={{display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16}}>
        <div style={PF_TITLE}>Liquidity Positions</div>
        <span className="tv-chip" style={{fontSize: 12}}>2 LPs</span>
        <div style={{flex: 1}}/>
        <span style={PF_SUB}>total <span className="tv-num" style={{color: TV.text, fontWeight: 700}}>$12,681</span></span>
      </div>
      <div style={{display: 'grid', gridTemplateColumns: '1fr', gap: 16}}>
        <LpCard pair="WETH / USDC" chain="BASE" protocol="Uniswap V3" fee="0.30%" wallet="Sentinel"
            nft="4752944" age="66d 21h" inRange={false} totalValue="$4,441.01" uncollectedTotal="$64.88"
            liquidity={[{sym: 'WETH', amount: '<0.0001', usd: '$0.00'}, {sym: 'USDC', amount: '4,441.0124', usd: '$4,441.01'}]}
            fees={[{sym: 'WETH', amount: '0.013537', usd: '$31.54'}, {sym: 'USDC', amount: '33.332966', usd: '$33.33'}]}
            range={{minP: '1,844.62', curP: '2,333.48', maxP: '2,289.33', width: '19.06%'}}
            perf={{total: '$306.58', collected: ['0.0544 WETH ($126.85)', '114.8558 USDC ($114.86)'], uncollected: '+$64.88 uncollected'}}
            apr={[['Daily', '0.10%', '~$4.58/day'], ['Weekly', '0.72%', '~$32.08/week'], ['Monthly', '3.10%', '~$137.48/month'], ['Yearly', '37.66%', '~$1,672.67/year']]}
            pool={[['Pool TVL', '$135,123,677'], ['24h Volume', '$270,247,355'], ['24h Vol / TVL', '2.00x', true], ['24h Fees', '$949,100']]}/>
        <LpCard pair="ETH / USDC" chain="BASE" protocol="Uniswap V3" fee="0.05%" wallet="Fusion1"
            nft="5012233" age="23d 4h" inRange={true} totalValue="$8,240.00" uncollectedTotal="$124.30"
            liquidity={[{sym: 'WETH', amount: '2.1042', usd: '$7,196.00'}, {sym: 'USDC', amount: '1,044.00', usd: '$1,044.00'}]}
            fees={[{sym: 'WETH', amount: '0.038100', usd: '$88.90'}, {sym: 'USDC', amount: '35.400000', usd: '$35.40'}]}
            range={{minP: '2,050.00', curP: '2,333.48', maxP: '2,620.00', width: '24.80%'}}
            perf={{total: '$512.40', collected: ['0.0920 WETH ($214.60)', '190.2000 USDC ($190.20)'], uncollected: '+$124.30 uncollected'}}
            apr={[['Daily', '0.14%', '~$11.50/day'], ['Weekly', '0.98%', '~$80.55/week'], ['Monthly', '4.20%', '~$345.00/month'], ['Yearly', '51.20%', '~$4,219.00/year']]}
            pool={[['Pool TVL', '$210,480,000'], ['24h Volume', '$402,910,000'], ['24h Vol / TVL', '1.91x', true], ['24h Fees', '$1,240,500']]}/>
      </div>
    </div>

    {/* Lending / borrowing */}
    <div style={PF_CARD}>
      <div style={{display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16}}>
        <div style={PF_TITLE}>Lending / Borrowing</div>
        <span className="tv-chip" style={{fontSize: 12}}>2 positions</span>
        <div style={{flex: 1}}/>
        <span style={PF_SUB}>net equity <span className="tv-num" style={{color: TV.text, fontWeight: 700}}>$19,190</span></span>
      </div>
      <div style={{display: 'grid', gridTemplateColumns: '1fr', gap: 16}}>
        <LendCard protocol="Moonwell" chain="BASE" dir="long" tags={[]} opened="2026-04-14" wallet="Fusion1" history={1}
            health={2.69} status="Safe" ltv="31.60%" maxLtv="85%" netEquity="$7,572" lendTotal="$11,071"
            borrowRemaining="$5,911" netApy="-1.41%" lendApy="0.20%" borrowApy="5.10%"
            lending={[['cbBTC', '0.15', '$73,804', '$11,071', '85%', '0.20%']]}
            borrowing={[['USDC', '3,500', '$0.9996', '$3,499', '5.10%']]}
            note="Simple BTC-backed position. Monitor if BTC drops toward $70K."
            liqPrices={[['cbBTC', '$27,441', '$74,042', '62.9%']]}
            last="2026-04-14 — Opened"/>
        <LendCard protocol="Venus" chain="BNB" dir="short" tags={['Multi-asset']} opened="2026-03-01" wallet="Desktop Hot" history={3}
            health={3.17} status="Safe" ltv="25.7%" maxLtv="65%" netEquity="$11,618" lendTotal="$15,638"
            borrowRemaining="$6,145" netApy="-1.32%" lendApy="0.85%" borrowApy="8.47%"
            lending={[['USDC', '12,000', '$0.9996', '$11,996', '82%', '0.75%'], ['ETH', '1.8', '$2,023', '$3,642', '80%', '1.20%']]}
            borrowing={[['XRP', '3,000', '$1.34', '$4,020', '8.47%']]}
            note="Short XRP. Betting XRP declines. Liquidated if XRP rises above threshold. Unwind target: XRP ~$0.80."
            liqPrices={[['USDC', '$1.52', '$0.9996', '+52.1% rise liquidates'], ['ETH', '$4,180', '$2,023', '+106.6% rise liquidates']]}
            last="2026-04-10 — Repay Borrow"/>
      </div>
    </div>
  </div>
);

// Standalone artboard wrappers — show modal open over the DeFi view
const LendEditScreen = () => (
  <div style={{position:'relative', width:'100%', height:'100%'}}>
    <PortfolioHF view="defi"/>
    <div style={{position:'absolute', inset:0, background:'rgba(5,18,35,0.82)', display:'flex',
        alignItems:'center', justifyContent:'center', zIndex:10}}>
      <div style={{background:TV.panel, border:`1px solid ${TV.line}`, borderRadius:14,
          boxShadow:'0 24px 80px rgba(0,0,0,.7)', width:720, maxHeight:'90%', overflowY:'auto'}}>
        <div style={{display:'flex', alignItems:'center', justifyContent:'space-between',
            padding:'18px 22px 14px', borderBottom:`1px solid ${TV.line}`}}>
          <span style={{fontSize:16, fontWeight:700, color:TV.text}}>Edit Position</span>
          <span style={{fontSize:20, color:TV.text3, cursor:'pointer', lineHeight:1, padding:'0 4px'}}>×</span>
        </div>
        <div style={{padding:'20px 22px', display:'flex', flexDirection:'column', gap:16}}>
          <div style={{display:'grid', gridTemplateColumns:'1fr 1fr', gap:14}}>
            {[['Protocol','Moonwell'],['Network / Chain','Base'],['Date Opened','2026-04-14'],['Max Borrow LTV %','85']].map(([l,v])=>(
              <div key={l} style={{display:'flex', flexDirection:'column', gap:5}}>
                <div style={{fontSize:11, fontWeight:700, color:TV.text3, textTransform:'uppercase', letterSpacing:'.05em'}}>{l}</div>
                <div style={{background:TV.panel2, border:`1px solid ${TV.line}`, borderRadius:8, padding:'9px 13px', fontSize:13.5, color:TV.text}}>{v}</div>
              </div>
            ))}
          </div>
          <div>
            <div style={{fontSize:12, fontWeight:700, color:TV.ok, textTransform:'uppercase', letterSpacing:'.06em', marginBottom:10}}>Lending Assets</div>
            <div style={{display:'grid', gridTemplateColumns:'1fr 1fr 1fr 1fr 1fr 32px', gap:10, marginBottom:10, alignItems:'end'}}>
              {[['Token','cbBTC'],['Quantity','0.15'],['Liq Thr %','85'],['APY %','0.2'],['Manual Price $','']].map(([l,v])=>(
                <div key={l} style={{display:'flex', flexDirection:'column', gap:5}}>
                  <div style={{fontSize:10.5, fontWeight:700, color:TV.text3, textTransform:'uppercase', letterSpacing:'.05em'}}>{l}</div>
                  <div style={{background:TV.panel2, border:`1px solid ${TV.line}`, borderRadius:7, padding:'8px 11px', fontSize:13, color:v?TV.text:TV.text4}}>{v||<span style={{opacity:.5}}>optional</span>}</div>
                </div>
              ))}
              <button className="tv-btn ghost" style={{padding:'7px 10px', color:TV.fail, borderColor:`${TV.fail}44`}}>×</button>
            </div>
            <button className="tv-btn ghost" style={{fontSize:12.5, padding:'6px 14px'}}>+ Add Lent Asset</button>
          </div>
          <div>
            <div style={{fontSize:12, fontWeight:700, color:TV.fail, textTransform:'uppercase', letterSpacing:'.06em', marginBottom:10}}>Borrowing Assets</div>
            <div style={{display:'grid', gridTemplateColumns:'1fr 1fr 1fr 1fr 32px', gap:10, marginBottom:10, alignItems:'end'}}>
              {[['Token','USDC'],['Quantity','3500'],['Borrow APR %','5.1'],['Manual Price $','']].map(([l,v])=>(
                <div key={l} style={{display:'flex', flexDirection:'column', gap:5}}>
                  <div style={{fontSize:10.5, fontWeight:700, color:TV.text3, textTransform:'uppercase', letterSpacing:'.05em'}}>{l}</div>
                  <div style={{background:TV.panel2, border:`1px solid ${TV.line}`, borderRadius:7, padding:'8px 11px', fontSize:13, color:v?TV.text:TV.text4}}>{v||<span style={{opacity:.5}}>optional</span>}</div>
                </div>
              ))}
              <button className="tv-btn ghost" style={{padding:'7px 10px', color:TV.fail, borderColor:`${TV.fail}44`}}>×</button>
            </div>
            <button className="tv-btn ghost" style={{fontSize:12.5, padding:'6px 14px'}}>+ Add Borrowed Asset</button>
          </div>
          <div style={{display:'flex', flexDirection:'column', gap:5}}>
            <div style={{fontSize:11, fontWeight:700, color:TV.text3, textTransform:'uppercase', letterSpacing:'.05em'}}>Notes</div>
            <div style={{background:TV.panel2, border:`1px solid ${TV.line}`, borderRadius:8, padding:'10px 13px',
                minHeight:72, fontSize:13.5, color:TV.text3, lineHeight:1.6}}>Simple BTC-backed position. Monitor if BTC drops toward $70K.</div>
          </div>
          <div style={{display:'flex', justifyContent:'flex-end', gap:10, paddingTop:4}}>
            <button className="tv-btn ghost" style={{padding:'9px 20px'}}>Cancel</button>
            <button className="tv-btn primary" style={{padding:'9px 22px'}}>Save Position</button>
          </div>
        </div>
      </div>
    </div>
  </div>
);

const LendHistoryScreen = () => (
  <div style={{position:'relative', width:'100%', height:'100%'}}>
    <PortfolioHF view="defi"/>
    <div style={{position:'absolute', inset:0, background:'rgba(5,18,35,0.82)', display:'flex',
        alignItems:'center', justifyContent:'center', zIndex:10}}>
      <div style={{background:TV.panel, border:`1px solid ${TV.line}`, borderRadius:14,
          boxShadow:'0 24px 80px rgba(0,0,0,.7)', width:660, maxHeight:'90%', overflowY:'auto'}}>
        <div style={{display:'flex', alignItems:'center', justifyContent:'space-between',
            padding:'18px 22px 14px', borderBottom:`1px solid ${TV.line}`}}>
          <span style={{fontSize:16, fontWeight:700, color:TV.text}}>Moonwell · Base — History</span>
          <span style={{fontSize:20, color:TV.text3, cursor:'pointer', lineHeight:1, padding:'0 4px'}}>×</span>
        </div>
        <div style={{padding:'20px 22px', display:'flex', flexDirection:'column', gap:16}}>
          <div style={{display:'flex', gap:14}}>
            <div style={{display:'flex', flexDirection:'column', alignItems:'center', width:14, flexShrink:0}}>
              <span style={{width:10, height:10, borderRadius:'50%', background:TV.ok, marginTop:4}}/>
            </div>
            <div>
              <div className="tv-num" style={{fontSize:12.5, color:TV.text4, marginBottom:2}}>2026-04-14</div>
              <div style={{fontSize:12, fontWeight:700, color:TV.text3, textTransform:'uppercase', letterSpacing:'.05em', marginBottom:3}}>OPENED</div>
              <div style={{fontSize:13.5, color:TV.text}}>Opened — lent 0.15 cbBTC, borrowed 3,500 USDC</div>
            </div>
          </div>
          <div style={{borderTop:`1px solid ${TV.line}`, paddingTop:16, display:'flex', flexDirection:'column', gap:12}}>
            <div style={{textAlign:'center', fontSize:12, fontWeight:700, color:TV.text3, letterSpacing:'.06em', textTransform:'uppercase'}}>Add Entry</div>
            <div style={{display:'grid', gridTemplateColumns:'1fr 1fr', gap:12}}>
              <div style={{display:'flex', flexDirection:'column', gap:5}}>
                <div style={{fontSize:11, fontWeight:700, color:TV.text3, textTransform:'uppercase', letterSpacing:'.05em'}}>Action</div>
                <div style={{background:TV.panel2, border:`1px solid ${TV.line}`, borderRadius:8, padding:'9px 13px',
                    fontSize:13.5, color:TV.text, display:'flex', justifyContent:'space-between'}}>
                  <span>Note</span><span style={{color:TV.text3}}>▾</span>
                </div>
              </div>
              <div style={{display:'flex', flexDirection:'column', gap:5}}>
                <div style={{fontSize:11, fontWeight:700, color:TV.text3, textTransform:'uppercase', letterSpacing:'.05em'}}>Date</div>
                <div style={{background:TV.panel2, border:`1px solid ${TV.line}`, borderRadius:8, padding:'9px 13px', fontSize:13.5, color:TV.text}}>05/31/2026</div>
              </div>
            </div>
            <div style={{display:'flex', flexDirection:'column', gap:5}}>
              <div style={{fontSize:11, fontWeight:700, color:TV.text3, textTransform:'uppercase', letterSpacing:'.05em'}}>Details</div>
              <div style={{background:TV.panel2, border:`1px solid ${TV.line}`, borderRadius:8, padding:'10px 13px',
                  minHeight:56, fontSize:13.5, color:TV.text4}}><span style={{opacity:.5}}>Describe the action…</span></div>
            </div>
            <div style={{display:'flex', justifyContent:'flex-end'}}>
              <button className="tv-btn primary" style={{padding:'9px 22px'}}>Add Entry</button>
            </div>
          </div>
          <div style={{display:'flex', justifyContent:'flex-end'}}>
            <button className="tv-btn ghost" style={{padding:'9px 20px'}}>Close</button>
          </div>
        </div>
      </div>
    </div>
  </div>
);

const LendArchiveScreen = () => (
  <div style={{position:'relative', width:'100%', height:'100%'}}>
    <PortfolioHF view="defi"/>
    <div style={{position:'absolute', inset:0, background:'rgba(5,18,35,0.82)', display:'flex',
        alignItems:'center', justifyContent:'center', zIndex:10}}>
      <div style={{background:TV.panel, border:`1px solid ${TV.line}`, borderRadius:14,
          boxShadow:'0 24px 80px rgba(0,0,0,.7)', width:460}}>
        <div style={{display:'flex', alignItems:'center', justifyContent:'space-between',
            padding:'18px 22px 14px', borderBottom:`1px solid ${TV.line}`}}>
          <span style={{fontSize:16, fontWeight:700, color:TV.text}}>Confirm</span>
          <span style={{fontSize:20, color:TV.text3, cursor:'pointer', lineHeight:1, padding:'0 4px'}}>×</span>
        </div>
        <div style={{padding:'22px 24px 20px', display:'flex', flexDirection:'column', gap:20}}>
          <div style={{fontSize:14.5, color:TV.text, lineHeight:1.6}}>Archive the <strong>Moonwell</strong> position? You can restore it later.</div>
          <div style={{display:'flex', justifyContent:'flex-end', gap:10}}>
            <button className="tv-btn ghost" style={{padding:'9px 20px'}}>Cancel</button>
            <button className="tv-btn" style={{padding:'9px 22px', color:TV.fail, borderColor:`${TV.fail}66`, background:TV.failSoft}}>Archive</button>
          </div>
        </div>
      </div>
    </div>
  </div>
);

// =============================================================
// PORTFOLIO screen
// =============================================================
const PortfolioHF = ({view = 'tokens'}) => {
  const subTab = view === 'defi' ? 'DeFi Positions' : 'Token Holdings';
  return (
    <div className="tv-frame" style={{display: 'flex', flexDirection: 'column'}}>
      <TVNav active="Portfolio"/>

      <div style={{flex: 1, padding: '28px 36px 36px', display: 'flex', flexDirection: 'column', gap: 22,
          overflowY: 'auto', minHeight: 0}}>

        {/* ===== HEADER ===== */}
        <div style={{display: 'flex', alignItems: 'flex-end', gap: 16, flexShrink: 0}}>
          <div>
            <div style={{fontSize: 30, fontWeight: 800, color: TV.text, letterSpacing: '-.5px', lineHeight: 1.1}}>Portfolio</div>
            <div style={{fontSize: 13.5, color: TV.text3, marginTop: 4}}>Updated 2m ago · 3 of 4 wallets · 3 chains</div>
          </div>
          <div style={{flex: 1}}/>
          <button className="tv-btn" style={{padding: '9px 15px'}}>↻ Refresh</button>
        </div>

        {/* ===== METRIC STRIP ===== */}
        <div style={{display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 16, flexShrink: 0}}>
          {[
            ['Total value', '$40,837.74', '343 tokens · 3 wallets', TV.text],
            ['24h change', '+$612.40', '+1.52%', TV.ok],
            ['Token holdings', '$28,348', '9 shown · 8 dust', TV.text],
            ['DeFi value', '$12,489', '2 LP · 2 lending', TV.text],
          ].map(([label, val, sub, col]) => (
            <div key={label} style={{...PF_METRIC, display: 'flex', flexDirection: 'column', gap: 6}}>
              <div style={{...PF_TITLE, fontSize: 14.5}}>{label}</div>
              <div className="tv-num" style={{fontSize: 27, fontWeight: 700, color: col, letterSpacing: '-.4px', lineHeight: 1}}>{val}</div>
              <div style={{flex: 1}}/>
              <div style={{fontSize: 12.5, color: TV.text3}}>{sub}</div>
            </div>
          ))}
        </div>

        {/* ===== DEFI SUMMARY STRIP — LP + lend/borrow totals ===== */}
        <div style={{display: 'grid', gridTemplateColumns: 'repeat(6, 1fr)', gap: 14, flexShrink: 0}}>
          {[
            ['LP value', '$12,681', '2 positions', TV.text],
            ['LP uncollected', '$189.18', 'ready to collect', TV.ok],
            ['Total lent', '$26,709', 'all active positions', TV.ok],
            ['Total borrowed', '$7,519', '28.2% of collateral', TV.fail],
            ['Net equity', '$19,190', 'lend − borrow', TV.ok],
            ['Portfolio HF', '2.95', 'weighted by debt', TV.ok],
          ].map(([label, val, sub, col]) => (
            <div key={label} style={{...PF_METRIC, padding: 16, display: 'flex', flexDirection: 'column', gap: 5}}>
              <div style={{...PF_TITLE, fontSize: 12.5}}>{label}</div>
              <div className="tv-num" style={{fontSize: 22, fontWeight: 700, color: col, letterSpacing: '-.3px', lineHeight: 1}}>{val}</div>
              <div style={{flex: 1}}/>
              <div style={{fontSize: 11.5, color: TV.text3}}>{sub}</div>
            </div>
          ))}
        </div>

        {/* ===== FILTER BAR ===== */}
        <div style={{...PF_CARD, padding: 18, display: 'flex', flexDirection: 'column', gap: 14, flexShrink: 0}}>
          {/* wallets */}
          <div style={{display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap'}}>
            <span style={{fontSize: 11, fontWeight: 600, color: TV.text3, letterSpacing: '.06em',
                textTransform: 'uppercase', width: 58, flexShrink: 0}}>Wallets</span>
            {WALLETS.map(w => (
              <div key={w.id} style={{display: 'flex', alignItems: 'center', gap: 9, padding: '7px 11px',
                  borderRadius: 8, cursor: 'pointer', opacity: w.hidden ? 0.45 : 1,
                  border: `1px solid ${w.selected && !w.hidden ? TV.accentLine : TV.line}`,
                  background: w.selected && !w.hidden ? TV.accentSoft : TV.panel2}}>
                <span style={{width: 8, height: 8, borderRadius: '50%', background: w.dot, flexShrink: 0}}/>
                <div style={{display: 'flex', flexDirection: 'column', lineHeight: 1.25}}>
                  <span style={{fontSize: 13, fontWeight: 600, color: TV.text}}>{w.label}</span>
                  <span className="tv-num" style={{fontSize: 11, color: TV.text3}}>{w.addr} · {w.value}</span>
                </div>
                <span style={{marginLeft: 4, display: 'flex'}} title={w.hidden ? 'hidden' : 'visible'}><EyeIcon off={w.hidden}/></span>
              </div>
            ))}
            <button className="tv-btn ghost" style={{padding: '6px 10px', fontSize: 12.5}}>+ Add wallet</button>
          </div>

          <div style={{height: 1, background: TV.lineSoft}}/>

          {/* chains */}
          <div style={{display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap'}}>
            <span style={{fontSize: 11, fontWeight: 600, color: TV.text3, letterSpacing: '.06em',
                textTransform: 'uppercase', width: 58, flexShrink: 0}}>Chains</span>
            {CHAIN_FILTERS.map((c, i) => {
              const on = i === 0;
              return (
                <span key={c} style={{padding: '6px 13px', borderRadius: 7, fontSize: 13, fontWeight: 500,
                    cursor: 'pointer', color: on ? TV.text : TV.text2,
                    border: `1px solid ${on ? TV.accentLine : TV.line}`,
                    background: on ? TV.accentSoft : TV.panel2}}>{c}</span>
              );
            })}
          </div>
        </div>

        {/* ===== SUB-TAB SWITCHER ===== */}
        <div style={{flexShrink: 0}}>
          <PFSeg options={['Token Holdings', 'DeFi Positions', 'LP Tools']} active={subTab} size="lg"/>
        </div>

        {/* ===== CONTENT ===== */}
        {view === 'defi' ? <DefiPositions/> : <TokenHoldings grouping="By Type"/>}
      </div>
    </div>
  );
};
