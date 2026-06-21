// spotpnl.jsx — Spot P&L tab (Live Holdings / Trade History / Transactions)
// Loads after portfolio.jsx — reuses PF_CARD, PF_TITLE, PF_SUB, PF_METRIC,
// PFSeg, TokenIcon, ChainBadge and the TV.* tokens / .tv-* utility classes.

// visibility toggle switch (Hide values)
const ToggleSwitch = ({on, label}) => (
  <div style={{display: 'flex', alignItems: 'center', gap: 9}}>
    <span style={{fontSize: 13, color: TV.text2}}>{label}</span>
    <span style={{width: 38, height: 22, borderRadius: 11, flexShrink: 0,
        background: on ? TV.accent : TV.panel3, border: `1px solid ${on ? TV.accent : TV.line}`,
        position: 'relative', display: 'inline-block'}}>
      <span style={{position: 'absolute', top: 2, left: on ? 17 : 2, width: 16, height: 16,
          borderRadius: '50%', background: on ? '#231905' : TV.text2}}/>
    </span>
  </div>
);

// reusable table shell
const PnlTable = ({cols, head, children}) => (
  <div style={{border: `1px solid ${TV.line}`, borderRadius: 10, overflow: 'hidden'}}>
    <div style={{display: 'grid', gridTemplateColumns: cols, gap: 12, padding: '10px 16px',
        background: TV.panel, borderBottom: `1px solid ${TV.line}`,
        fontSize: 11, fontWeight: 600, color: TV.text3, letterSpacing: '.05em', textTransform: 'uppercase'}}>
      {head.map((h, i) => <span key={i} style={{textAlign: h.r ? 'right' : 'left'}}>{h.t}</span>)}
    </div>
    {children}
  </div>
);
const pnlRow = (cols, last) => ({display: 'grid', gridTemplateColumns: cols, gap: 12,
  padding: '11px 16px', alignItems: 'center', fontSize: 13,
  borderBottom: last ? 'none' : `1px solid ${TV.lineSoft}`});

const Money = ({v, color, bold}) => (
  <span className="tv-num" style={{color: color || TV.text, fontWeight: bold ? 700 : 500}}>{v}</span>
);

// ===================== LIVE HOLDINGS =====================
const LIVE_COLS = 'minmax(150px,1.3fr) 92px 104px 110px 110px 118px 132px 78px 86px';
const LIVE_ROWS = [
  // sym, chain, units, avgCost, price, costBasis, mktValue, pnl, up, pctAll, pctEx
  ['ETH',  'ETH', '6.4210',   '$2,180',  '$3,420.10', '$14,000', '$21,963', '+$7,963', true,  '53.7%', '77.4%'],
  ['WBTC', 'ETH', '0.0420',   '$58,200', '$71,840',   '$2,444',  '$3,017',  '+$573',   true,  '7.4%',  '10.6%'],
  ['SOL',  'SOL', '18.40',    '$98.50',  '$168.20',   '$1,812',  '$3,094',  '+$1,282', true,  '7.6%',  '10.9%'],
  ['LINK', 'ETH', '78.50',    '$11.20',  '$14.80',    '$879',    '$1,162',  '+$283',   true,  '2.8%',  '4.1%'],
  ['ARB',  'ARB', '2,140.0',  '$1.32',   '$0.92',     '$2,825',  '$1,969',  '-$856',   false, '4.8%',  '6.9%'],
];

const LiveHoldings = ({hidden}) => {
  const m = v => hidden ? '••••' : v;
  return (
    <div style={{display: 'flex', flexDirection: 'column', gap: 22}}>
      {/* dry powder */}
      <div style={{...PF_CARD, padding: 20, display: 'flex', alignItems: 'center', gap: 24,
          border: `1px solid rgba(79,221,142,.4)`, background: TV.okSoft}}>
        <div>
          <div style={{...PF_TITLE, color: TV.ok}}>Dry Powder</div>
          <div className="tv-num" style={{fontSize: 30, fontWeight: 700, color: TV.text, letterSpacing: '-.5px', marginTop: 4}}>{m('$9,180')}</div>
          <div style={PF_SUB}>total stablecoin value · 3 wallets</div>
        </div>
        <div style={{width: 1, alignSelf: 'stretch', background: 'rgba(79,221,142,.3)'}}/>
        <div style={{display: 'flex', gap: 28}}>
          {[['USDC', '$8,180'], ['USDT', '$1,000']].map(([s, v]) => (
            <div key={s} style={{display: 'flex', alignItems: 'center', gap: 10}}>
              <TokenIcon sym={s}/>
              <div>
                <div style={{fontSize: 13, fontWeight: 600, color: TV.text}}>{s}</div>
                <div className="tv-num" style={{fontSize: 13, color: TV.text2}}>{m(v)}</div>
              </div>
            </div>
          ))}
        </div>
        <div style={{flex: 1}}/>
        <span style={{fontSize: 12.5, color: TV.text3, maxWidth: 200, textAlign: 'right'}}>22.5% of portfolio held in stables — ready to deploy</span>
      </div>

      {/* holdings table */}
      <div style={PF_CARD}>
        <div style={{display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16}}>
          <div style={PF_TITLE}>Live Holdings</div>
          <span className="tv-chip" style={{fontSize: 12}}>5 assets</span>
          <div style={{flex: 1}}/>
          <span style={PF_SUB}>unrealized <Money v={m('+$9,245')} color={TV.ok} bold/> · <span className="tv-num" style={{color: TV.ok}}>+29.7%</span></span>
        </div>
        <PnlTable cols={LIVE_COLS} head={[{t: 'Token'}, {t: 'Units', r: 1}, {t: 'Avg Cost', r: 1}, {t: 'Price', r: 1},
            {t: 'Cost Basis', r: 1}, {t: 'Mkt Value', r: 1}, {t: 'Unreal. P&L', r: 1}, {t: '% all', r: 1}, {t: '% ex-stbl', r: 1}]}>
          {LIVE_ROWS.map((r, i) => (
            <div key={r[0]} style={pnlRow(LIVE_COLS, false)}>
              <span style={{display: 'flex', alignItems: 'center', gap: 9}}>
                <TokenIcon sym={r[0]} size={22}/>
                <span className="tv-num" style={{fontWeight: 700, color: TV.text}}>{r[0]}</span>
                <ChainBadge chain={r[1]}/>
              </span>
              <Money v={m(r[2])} color={TV.text2} /><span style={{display: 'none'}}/>
              <span style={{textAlign: 'right'}}><Money v={m(r[3])} color={TV.text3}/></span>
              <span style={{textAlign: 'right'}}><Money v={m(r[4])} color={TV.text2}/></span>
              <span style={{textAlign: 'right'}}><Money v={m(r[5])} color={TV.text3}/></span>
              <span style={{textAlign: 'right'}}><Money v={m(r[6])} bold/></span>
              <span style={{textAlign: 'right'}}><Money v={m(r[7])} color={r[8] ? TV.ok : TV.fail} bold/></span>
              <span style={{textAlign: 'right'}}><Money v={r[9]} color={TV.text3}/></span>
              <span style={{textAlign: 'right'}}><Money v={r[10]} color={TV.text3}/></span>
            </div>
          ))}
          {/* stablecoins aggregate */}
          <div style={pnlRow(LIVE_COLS, true)}>
            <span style={{display: 'flex', alignItems: 'center', gap: 9}}>
              <TokenIcon sym="USDC" size={22}/>
              <span className="tv-num" style={{fontWeight: 700, color: TV.text}}>Stablecoins</span>
              <span className="tv-chip" style={{fontSize: 10, padding: '1px 6px'}}>2</span>
            </span>
            <span/>
            <span style={{textAlign: 'right'}}><Money v="—" color={TV.text4}/></span>
            <span style={{textAlign: 'right'}}><Money v={m('$1.00')} color={TV.text2}/></span>
            <span style={{textAlign: 'right'}}><Money v={m('$9,180')} color={TV.text3}/></span>
            <span style={{textAlign: 'right'}}><Money v={m('$9,180')} bold/></span>
            <span style={{textAlign: 'right'}}><Money v={m('$0')} color={TV.text3}/></span>
            <span style={{textAlign: 'right'}}><Money v="22.5%" color={TV.text3}/></span>
            <span style={{textAlign: 'right'}}><Money v="—" color={TV.text4}/></span>
          </div>
        </PnlTable>
        <div style={{fontSize: 12, color: TV.text4, marginTop: 12}}>
          % all = share of full portfolio · % ex-stbl = share excluding stablecoins
        </div>
      </div>
    </div>
  );
};

// ===================== TRADE HISTORY =====================
const HIST_COLS = 'minmax(140px,1.2fr) 116px 116px 92px 116px 116px 130px 110px';
const HIST_ROWS = [
  // sym, chain, buy, sell, units, avgBuy, avgSell, realized, up, hold
  ['ETH',  'ETH', '2025-11-02', '2026-01-15', '3.0',        '$2,050',     '$3,180',     '+$3,390', true,  '74d'],
  ['SOL',  'SOL', '2025-12-10', '2026-02-01', '40',         '$135.00',    '$190.00',    '+$2,200', true,  '53d'],
  ['WBTC', 'ETH', '2025-09-15', '2026-02-20', '0.05',       '$52,000',    '$69,000',    '+$850',   true,  '158d'],
  ['PEPE', 'ETH', '2026-01-05', '2026-01-20', '12,000,000', '$0.0000085', '$0.0000071', '-$168',   false, '15d'],
  ['ARB',  'ARB', '2025-10-01', '2026-03-01', '1,000',      '$1.65',      '$0.95',      '-$700',   false, '151d'],
];

const TradeHistory = ({hidden}) => {
  const m = v => hidden ? '••••' : v;
  return (
    <div style={PF_CARD}>
      <div style={{display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16}}>
        <div style={PF_TITLE}>Trade History</div>
        <span className="tv-chip" style={{fontSize: 12}}>5 closed</span>
        <span className="tv-chip" style={{fontSize: 12, color: TV.adapt, borderColor: 'rgba(47,180,232,.4)', background: TV.adaptSoft}}>FIFO cost basis</span>
        <div style={{flex: 1}}/>
        <span style={PF_SUB}>realized <Money v={m('+$5,572')} color={TV.ok} bold/></span>
      </div>
      <PnlTable cols={HIST_COLS} head={[{t: 'Token'}, {t: 'Buy Date'}, {t: 'Sell Date'}, {t: 'Units', r: 1},
          {t: 'Avg Buy', r: 1}, {t: 'Avg Sell', r: 1}, {t: 'Realized P&L', r: 1}, {t: 'Holding', r: 1}]}>
        {HIST_ROWS.map((r, i) => (
          <div key={r[0] + i} style={pnlRow(HIST_COLS, i === HIST_ROWS.length - 1)}>
            <span style={{display: 'flex', alignItems: 'center', gap: 9}}>
              <TokenIcon sym={r[0]} size={22}/>
              <span className="tv-num" style={{fontWeight: 700, color: TV.text}}>{r[0]}</span>
              <ChainBadge chain={r[1]}/>
            </span>
            <span className="tv-num" style={{color: TV.text3}}>{r[2]}</span>
            <span className="tv-num" style={{color: TV.text3}}>{r[3]}</span>
            <span style={{textAlign: 'right'}}><Money v={m(r[4])} color={TV.text2}/></span>
            <span style={{textAlign: 'right'}}><Money v={m(r[5])} color={TV.text3}/></span>
            <span style={{textAlign: 'right'}}><Money v={m(r[6])} color={TV.text2}/></span>
            <span style={{textAlign: 'right'}}><Money v={m(r[7])} color={r[8] ? TV.ok : TV.fail} bold/></span>
            <span style={{textAlign: 'right'}}><Money v={r[9]} color={TV.text3}/></span>
          </div>
        ))}
      </PnlTable>
      <div style={{fontSize: 12, color: TV.text4, marginTop: 12}}>
        Realized P&L computed FIFO — earliest buys matched against each sell.
      </div>
    </div>
  );
};

// ===================== TRANSACTIONS =====================
const TX_COLS = 'minmax(108px,1fr) minmax(110px,1fr) 68px 86px 108px 108px 110px minmax(160px,2fr) 104px';
const TX_ROWS = [
  // date, type, sym, chain, units, price, total, platform, notes
  ['2026-04-14', 'buy',  'cbBTC', 'BASE', '0.15',        '$73,804',     '$11,071', 'Manual',   'BTC-backed collateral via Moonwell'],
  ['2026-04-10', 'sell', 'XRP',   'BNB',  '1,000',       '$1.34',       '$1,340',  'Zerion',   'Partial exit — Venus short'],
  ['2026-03-22', 'buy',  'ETH',   'ETH',  '2.0',         '$3,100',      '$6,200',  'Coinbase', ''],
  ['2026-03-01', 'buy',  'SOL',   'SOL',  '18.40',       '$98.50',      '$1,812',  'Zerion',   ''],
  ['2026-02-20', 'sell', 'WBTC',  'ETH',  '0.05',        '$69,000',     '$3,450',  'Manual',   'Closed WBTC — locked in gains'],
  ['2026-02-01', 'sell', 'SOL',   'SOL',  '40',          '$190.00',     '$7,600',  'Zerion',   ''],
  ['2026-01-20', 'sell', 'PEPE',  'ETH',  '12,000,000',  '$0.0000071',  '$85.20',  'Manual',   ''],
  ['2026-01-15', 'sell', 'ETH',   'ETH',  '3.0',         '$3,180',      '$9,540',  'Kraken',   'ETH peak exit — planned trade'],
];

// add-transaction inline form
const AddTxForm = () => {
  const fInput = {background: TV.panel2, border: `1px solid ${TV.line}`, borderRadius: 7,
      padding: '8px 11px', fontSize: 13, color: TV.text, fontFamily: TV.font};
  const fLabel = {fontSize: 11, fontWeight: 600, color: TV.text3, letterSpacing: '.05em',
      textTransform: 'uppercase', marginBottom: 5, display: 'block'};
  const FField = ({label, children}) => (
    <div style={{display: 'flex', flexDirection: 'column'}}>
      <span style={fLabel}>{label}</span>
      {children}
    </div>
  );
  return (
    <div style={{borderRadius: 10, border: `1px solid ${TV.accentLine}`, background: TV.panel,
        padding: '18px 20px', marginBottom: 18, display: 'flex', flexDirection: 'column', gap: 14}}>
      <div style={{display: 'grid', gridTemplateColumns: '144px 104px 118px 96px 124px 132px 1fr', gap: 12, alignItems: 'start'}}>
        <FField label="Date"><div style={fInput}>05/30/2026</div></FField>
        <FField label="Symbol"><div style={fInput}>BTC</div></FField>
        <FField label="Side">
          <div style={{...fInput, display: 'flex', alignItems: 'center', justifyContent: 'space-between'}}>
            <span style={{color: TV.ok, fontWeight: 600}}>Buy</span>
            <span style={{color: TV.text3, fontSize: 11}}>▾</span>
          </div>
        </FField>
        <FField label="Units"><div style={fInput}>1.0</div></FField>
        <FField label="Price USD"><div style={fInput}>50,000</div></FField>
        <FField label="Platform"><div style={fInput}>Binance</div></FField>
        <FField label="Notes">
          <div style={{...fInput, height: 66, display: 'flex', alignItems: 'flex-start'}}>
            <span style={{color: TV.text4, fontSize: 12, fontStyle: 'italic', opacity: .7}}>Optional note…</span>
          </div>
        </FField>
      </div>
      <div style={{display: 'flex', alignItems: 'center', gap: 10}}>
        <button className="tv-btn primary" style={{padding: '8px 20px'}}>Save</button>
        <button className="tv-btn ghost" style={{padding: '8px 16px'}}>Cancel</button>
      </div>
    </div>
  );
};

const Transactions = ({hidden, showForm = false}) => {
  const m = v => hidden ? '••••' : v;
  return (
    <div style={PF_CARD}>
      <div style={{display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16}}>
        <div style={PF_TITLE}>Transactions</div>
        <span className="tv-chip" style={{fontSize: 12}}>8 of 412</span>
        <div style={{flex: 1}}/>
        <button className="tv-btn primary" style={{padding: '7px 12px', fontSize: 13}}>+ Add transaction</button>
        <button className="tv-btn" style={{padding: '7px 12px', fontSize: 13}}>⬆ Import CSV</button>
      </div>
      {showForm && <AddTxForm/>}
      <PnlTable cols={TX_COLS} head={[{t: 'Date'}, {t: 'Token'}, {t: 'Side'}, {t: 'Units', r: 1},
          {t: 'Price USD', r: 1}, {t: 'Total USD', r: 1}, {t: 'Platform'}, {t: 'Notes'}, {t: 'Actions', r: 1}]}>
        {TX_ROWS.map((r, i) => {
          const buy = r[1] === 'buy';
          return (
            <div key={i} style={pnlRow(TX_COLS, i === TX_ROWS.length - 1)}>
              <span className="tv-num" style={{color: TV.text2}}>{r[0]}</span>
              <span style={{display: 'flex', alignItems: 'center', gap: 9, minWidth: 0}}>
                <TokenIcon sym={r[2]} size={22}/>
                <span className="tv-num" style={{fontWeight: 700, color: TV.text}}>{r[2]}</span>
                <ChainBadge chain={r[3]}/>
              </span>
              <span>
                <span className="tv-chip" style={{fontSize: 11, padding: '1px 8px',
                    color: buy ? TV.ok : TV.fail,
                    borderColor: buy ? 'rgba(79,221,142,.4)' : 'rgba(255,138,138,.4)',
                    background: buy ? TV.okSoft : TV.failSoft}}>{buy ? 'buy' : 'sell'}</span>
              </span>
              <span style={{textAlign: 'right'}}><Money v={m(r[4])} color={TV.text2}/></span>
              <span style={{textAlign: 'right'}}><Money v={m(r[5])} color={TV.text3}/></span>
              <span style={{textAlign: 'right'}}><Money v={m(r[6])} bold/></span>
              <span style={{color: TV.text2, fontSize: 12.5}}>{r[7] || <span style={{color: TV.text4}}>—</span>}</span>
              <span style={{color: TV.text3, fontSize: 12.5, lineHeight: 1.4}}>{r[8] || ''}</span>
              <span style={{display: 'flex', gap: 6, justifyContent: 'flex-end'}}>
                <button className="tv-btn ghost" style={{padding: '3px 10px', fontSize: 12}}>Edit</button>
                <button style={{padding: '3px 9px', fontSize: 12, borderRadius: 5, cursor: 'pointer',
                    border: `1px solid ${TV.fail}`, background: 'transparent', color: TV.fail, fontWeight: 600}}>Del</button>
              </span>
            </div>
          );
        })}
      </PnlTable>
      <div style={{display: 'flex', alignItems: 'center', marginTop: 12}}>
        <span style={{fontSize: 12, color: TV.text4}}>Showing 8 of 412 transactions · sources: Manual · Zerion · CSV import</span>
        <div style={{flex: 1}}/>
        <button className="tv-btn ghost" style={{fontSize: 13}}>Load more →</button>
      </div>
    </div>
  );
};

// ===================== SCREEN =====================
const SpotPnlHF = ({view = 'live', hidden = false, showForm = false}) => {
  const subTab = view === 'history' ? 'Trade History' : view === 'tx' ? 'Transactions' : 'Live Holdings';
  return (
    <div className="tv-frame" style={{display: 'flex', flexDirection: 'column'}}>
      <TVNav active="Spot P&L"/>

      <div style={{flex: 1, padding: '28px 36px 36px', display: 'flex', flexDirection: 'column', gap: 22,
          overflowY: 'auto', minHeight: 0}}>

        {/* header */}
        <div style={{display: 'flex', alignItems: 'flex-end', gap: 16, flexShrink: 0}}>
          <div>
            <div style={{fontSize: 30, fontWeight: 800, color: TV.text, letterSpacing: '-.5px', lineHeight: 1.1}}>Spot P&amp;L</div>
            <div style={{fontSize: 13.5, color: TV.text3, marginTop: 4}}>FIFO cost basis · 3 wallets · spot positions only</div>
          </div>
          <div style={{flex: 1}}/>
          <ToggleSwitch on={hidden} label="Hide values"/>
        </div>

        {/* metric strip */}
        <div style={{display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 16, flexShrink: 0}}>
          {[
            ['Market value', hidden ? '••••' : '$28,348', 'spot holdings', TV.text],
            ['Cost basis', hidden ? '••••' : '$21,910', 'FIFO', TV.text],
            ['Unrealized P&L', hidden ? '••••' : '+$9,245', '+29.7%', TV.ok],
            ['Realized P&L · YTD', hidden ? '••••' : '+$5,572', '5 closed trades', TV.ok],
            ['Dry powder', hidden ? '••••' : '$9,180', '22.5% in stables', TV.text],
          ].map(([label, val, sub, col]) => (
            <div key={label} style={{...PF_METRIC, display: 'flex', flexDirection: 'column', gap: 6}}>
              <div style={{...PF_TITLE, fontSize: 14.5}}>{label}</div>
              <div className="tv-num" style={{fontSize: 26, fontWeight: 700, color: col, letterSpacing: '-.4px', lineHeight: 1}}>{val}</div>
              <div style={{flex: 1}}/>
              <div style={{fontSize: 12.5, color: TV.text3}}>{sub}</div>
            </div>
          ))}
        </div>

        {/* sub-tab switcher */}
        <div style={{flexShrink: 0}}>
          <PFSeg options={['Live Holdings', 'Trade History', 'Transactions']} active={subTab} size="lg"/>
        </div>

        {/* content */}
        {view === 'history' ? <TradeHistory hidden={hidden}/>
          : view === 'tx' ? <Transactions hidden={hidden} showForm={showForm}/>
          : <LiveHoldings hidden={hidden}/>}
      </div>
    </div>
  );
};
