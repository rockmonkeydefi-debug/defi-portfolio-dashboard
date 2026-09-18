/* ===== SPOT TRADE LOG SCREEN (HANDOFF_trade_log.md) =====
   Standard house theme (navy tv-* classes), JSX + Babel-standalone like
   archive.js/aibrief.js - the "React.createElement only" convention in
   trends.js is specific to that file's page-scoped Bullmania palette
   override, not the house default. No new palette here (not requested by
   ruling 6).

   Data comes from two existing GETs, zero new routes:
     GET /api/spot/trade-log            -> { trades: [...], summary: {...} }
     GET /api/trading/scanner/noodle-state -> { symbols: [{symbol, price,
       timeframes}, ...], meta }
   The ticker dropdown is sourced from noodle-state's symbols[].symbol list
   (exact casing, e.g. 'kBONK') - never free text (ruling B). */
const { useState, useEffect } = React;

function _nowLocalDatetimeValue() {
  const d = new Date();
  d.setMinutes(d.getMinutes() - d.getTimezoneOffset());
  return d.toISOString().slice(0, 16);
}

function _localDatetimeToIso(value) {
  if (!value) return null;
  const d = new Date(value);
  return isNaN(d) ? null : d.toISOString();
}

const TRADE_LOG_EMPTY_FORM = {
  ticker: '', direction: 'long', source: 'MHC', venue: '',
  entry_price: '', stop_price: '', qty: '', target_price: '',
  entered_at: _nowLocalDatetimeValue(), notes: '',
};

function TradeLogFollowedBadge({ value }) {
  if (value === 1) return <span className="tv-chip ok">Followed</span>;
  if (value === 0) return <span className="tv-chip fail">Deviated</span>;
  return <span style={{ color: 'var(--text4)', fontSize: 12 }}>—</span>;
}

function TradeLogSnapshotDetail({ trade }) {
  let snapshot = null;
  try { snapshot = JSON.parse(trade.scanner_snapshot_json || 'null'); } catch (e) { snapshot = null; }
  if (!snapshot) return <div style={{ fontSize: 12, color: 'var(--text4)' }}>No snapshot recorded.</div>;
  return <div style={{ padding: '10px 12px', background: 'var(--bg)', border: '1px solid var(--line)', borderRadius: 8 }}>
    <div style={{ fontSize: 11, color: 'var(--text4)', marginBottom: 8 }}>
      Scanner snapshot captured at entry — {formatDate(snapshot.captured_at)}, never recomputed.
    </div>
    {snapshot.reason
      ? <div style={{ fontSize: 12, color: 'var(--text3)' }}>Reason: {snapshot.reason}</div>
      : <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
          <thead>
            <tr>
              {['TF', 'State', 'Alignment', 'To Flip %', 'Flips', 'Last Close'].map((h) =>
                <th key={h} style={{ textAlign: 'left', padding: '4px 8px', color: 'var(--text4)', fontSize: 12, fontWeight: 600, borderBottom: '1px solid var(--line)' }}>{h}</th>)}
            </tr>
          </thead>
          <tbody>
            {(snapshot.timeframes || []).map((tf) =>
              <tr key={tf.timeframe} style={{ borderBottom: '1px solid var(--line)' }}>
                <td style={{ padding: '4px 8px', color: 'var(--text2)' }}>{tf.timeframe}</td>
                <td style={{ padding: '4px 8px', color: 'var(--text2)' }}>{tf.state || '—'}</td>
                <td style={{ padding: '4px 8px', color: 'var(--text2)' }}>{tf.alignment_state || '—'}</td>
                <td style={{ padding: '4px 8px', color: 'var(--text2)' }}>
                  {typeof tf.dist_to_flip_pct === 'number' ? tf.dist_to_flip_pct.toFixed(1) + '%' : '—'}
                </td>
                <td style={{ padding: '4px 8px', color: 'var(--text2)' }}>
                  {typeof tf.flip_count_window === 'number' ? tf.flip_count_window : '—'}
                </td>
                <td style={{ padding: '4px 8px', color: 'var(--text2)' }}>
                  {typeof tf.last_close === 'number' ? tf.last_close : '—'}
                </td>
              </tr>)}
          </tbody>
        </table>}
  </div>;
}

function TradeLogCloseForm({ trade, onSubmit, onCancel }) {
  const [exitPrice, setExitPrice] = useState('');
  const [exitedAt, setExitedAt] = useState(_nowLocalDatetimeValue());
  const [followed, setFollowed] = useState('');   // '' | '1' | '0' - required
  const [deviationNote, setDeviationNote] = useState('');

  const canSubmit = exitPrice !== '' && !isNaN(Number(exitPrice)) && (followed === '1' || followed === '0');

  return <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center', padding: '10px 12px', background: 'var(--bg)', border: '1px solid var(--line)', borderRadius: 8 }}>
    <input className="tv-input" style={{ width: 110 }} type="number" step="any" placeholder="Exit price"
      value={exitPrice} onChange={(e) => setExitPrice(e.target.value)} />
    <input className="tv-input" style={{ width: 190 }} type="datetime-local"
      value={exitedAt} onChange={(e) => setExitedAt(e.target.value)} />
    <select className="tv-select" value={followed} onChange={(e) => setFollowed(e.target.value)}>
      <option value="" disabled>Followed rules?</option>
      <option value="1">Yes — followed</option>
      <option value="0">No — deviated</option>
    </select>
    <input className="tv-input" style={{ width: 200 }} type="text" placeholder="Deviation note (optional)"
      value={deviationNote} onChange={(e) => setDeviationNote(e.target.value)} />
    <button className="tv-btn primary" disabled={!canSubmit}
      style={{ opacity: canSubmit ? 1 : 0.5, cursor: canSubmit ? 'pointer' : 'default' }}
      onClick={() => onSubmit({
        exit_price: Number(exitPrice),
        exited_at: _localDatetimeToIso(exitedAt),
        followed_rules: Number(followed),
        deviation_note: deviationNote || null,
      })}>Close trade</button>
    <button className="tv-btn" onClick={onCancel}>Cancel</button>
    {!canSubmit && <span style={{ fontSize: 13, color: 'var(--fail)' }}>Exit price and Followed rules? are both required.</span>}
  </div>;
}

function TradeLogEntryForm({ tickers, onCreate }) {
  const [form, setForm] = useState(TRADE_LOG_EMPTY_FORM);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);

  function set(field, value) { setForm((prev) => Object.assign({}, prev, { [field]: value })); }

  const entryNum = Number(form.entry_price);
  const stopNum = Number(form.stop_price);
  const zeroRisk = form.entry_price !== '' && form.stop_price !== '' && entryNum === stopNum;
  const canSubmit = form.ticker && form.entry_price !== '' && form.stop_price !== '' &&
    form.qty !== '' && !zeroRisk && !submitting;

  async function submit() {
    setSubmitting(true);
    setError(null);
    try {
      await api('/api/spot/trade-log', {
        method: 'POST',
        body: JSON.stringify({
          ticker: form.ticker, direction: form.direction, source: form.source || 'MHC',
          venue: form.venue || null, entry_price: entryNum, stop_price: stopNum,
          qty: Number(form.qty),
          target_price: form.target_price !== '' ? Number(form.target_price) : null,
          entered_at: _localDatetimeToIso(form.entered_at),
          notes: form.notes || null,
        }),
      });
      setForm(Object.assign({}, TRADE_LOG_EMPTY_FORM, { entered_at: _nowLocalDatetimeValue() }));
      onCreate();
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      setSubmitting(false);
    }
  }

  return <div className="tv-card" style={{ marginBottom: 20 }}>
    <div className="tv-section-title">New trade</div>
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10 }}>
      <select className="tv-select" style={{ minWidth: 120 }} value={form.ticker} onChange={(e) => set('ticker', e.target.value)}>
        <option value="" disabled>Ticker…</option>
        {tickers.map((t) => <option key={t} value={t}>{t}</option>)}
      </select>
      <select className="tv-select" value={form.direction} onChange={(e) => set('direction', e.target.value)}>
        <option value="long">Long</option>
        <option value="short">Short</option>
      </select>
      <input className="tv-input" style={{ width: 90 }} type="text" placeholder="Source"
        value={form.source} onChange={(e) => set('source', e.target.value)} />
      <input className="tv-input" style={{ width: 110 }} type="text" placeholder="Venue (optional)"
        value={form.venue} onChange={(e) => set('venue', e.target.value)} />
      <input className="tv-input" style={{ width: 110 }} type="number" step="any" placeholder="Entry price"
        value={form.entry_price} onChange={(e) => set('entry_price', e.target.value)} />
      <input className="tv-input" style={{ width: 110 }} type="number" step="any" placeholder="Stop price"
        value={form.stop_price} onChange={(e) => set('stop_price', e.target.value)} />
      <input className="tv-input" style={{ width: 100 }} type="number" step="any" placeholder="Qty"
        value={form.qty} onChange={(e) => set('qty', e.target.value)} />
      <input className="tv-input" style={{ width: 110 }} type="number" step="any" placeholder="Target (optional)"
        value={form.target_price} onChange={(e) => set('target_price', e.target.value)} />
      <input className="tv-input" style={{ width: 190 }} type="datetime-local"
        value={form.entered_at} onChange={(e) => set('entered_at', e.target.value)} />
      <textarea className="tv-input" style={{ width: 220, minHeight: 36 }} placeholder="Notes (optional)"
        value={form.notes} onChange={(e) => set('notes', e.target.value)} />
      <button className="tv-btn primary" disabled={!canSubmit}
        style={{ opacity: canSubmit ? 1 : 0.5, cursor: canSubmit ? 'pointer' : 'default' }}
        onClick={submit}>{submitting ? 'Logging…' : 'Log trade'}</button>
    </div>
    {zeroRisk && <div style={{ fontSize: 13, color: 'var(--fail)', marginTop: 8 }}>
      Entry price and stop price can't be equal — that's a zero-risk trade and can't be logged.
    </div>}
    {error && <div style={{ fontSize: 13, color: 'var(--fail)', marginTop: 8 }}>{error}</div>}
  </div>;
}

function TradeLogRow({ trade, open, onClose, onDelete, onCloseSubmit }) {
  const [showClose, setShowClose] = useState(false);
  const [showSnapshot, setShowSnapshot] = useState(false);

  async function handleDelete() {
    if (!confirm(`Delete the ${trade.ticker} trade logged ${formatDate(trade.entered_at)}? This can't be undone.`)) return;
    await onDelete(trade.id);
  }

  const rResultColor = typeof trade.r_result === 'number' ? (trade.r_result >= 0 ? 'var(--ok)' : 'var(--fail)') : 'var(--text4)';

  return <React.Fragment>
    <tr>
      <td style={{ padding: '10px 12px', color: 'var(--text2)', fontWeight: 700 }}>{trade.ticker}</td>
      <td style={{ padding: '10px 12px', color: 'var(--text2)', textTransform: 'capitalize' }}>{trade.direction}</td>
      <td className="num" style={{ padding: '10px 12px', color: 'var(--text2)' }}>{trade.entry_price}</td>
      <td className="num" style={{ padding: '10px 12px', color: 'var(--text2)' }}>{trade.stop_price}</td>
      {open
        ? <React.Fragment>
            <td className="num" style={{ padding: '10px 12px', color: 'var(--text2)' }}>{trade.qty}</td>
            <td className="num" style={{ padding: '10px 12px', color: 'var(--text2)' }}>
              {typeof trade.target_price === 'number' ? trade.target_price : '—'}
            </td>
            <td className="num" style={{ padding: '10px 12px', color: 'var(--text2)' }}>
              {typeof trade.planned_rr === 'number' ? trade.planned_rr.toFixed(2) + 'R' : '—'}
            </td>
            <td className="num" style={{ padding: '10px 12px', color: 'var(--text2)' }}>{fmt(trade.risk_usd)}</td>
            <td className="num" style={{ padding: '10px 12px', color: 'var(--text2)' }}>{fmt(trade.notional_usd)}</td>
          </React.Fragment>
        : <React.Fragment>
            <td className="num" style={{ padding: '10px 12px', color: 'var(--text2)' }}>{trade.exit_price}</td>
            <td className="num" style={{ padding: '10px 12px', fontWeight: 700, color: rResultColor }}>
              {typeof trade.r_result === 'number' ? (trade.r_result >= 0 ? '+' : '') + trade.r_result.toFixed(2) + 'R' : '—'}
            </td>
            <td style={{ padding: '10px 12px', color: 'var(--text2)' }}>{formatDateShort(trade.exited_at)}</td>
            <td style={{ padding: '10px 12px' }}><TradeLogFollowedBadge value={trade.followed_rules} /></td>
            <td style={{ padding: '10px 12px', color: 'var(--text4)', fontSize: 12 }}>{trade.deviation_note || '—'}</td>
          </React.Fragment>}
      <td style={{ padding: '10px 12px', color: 'var(--text2)' }}>{formatDateShort(trade.entered_at)}</td>
      <td style={{ padding: '10px 12px', color: 'var(--text4)', fontSize: 12 }}>{trade.notes || '—'}</td>
      <td style={{ padding: '10px 12px', whiteSpace: 'nowrap' }}>
        {open && <button className="tv-btn" style={{ fontSize: 11, padding: '3px 10px', marginRight: 6 }}
          onClick={() => setShowClose((v) => !v)}>{showClose ? 'Cancel' : 'Close'}</button>}
        <button className="tv-btn" style={{ fontSize: 11, padding: '3px 10px', marginRight: 6 }}
          onClick={() => setShowSnapshot((v) => !v)}>{showSnapshot ? 'Hide snapshot' : 'Snapshot'}</button>
        <button className="tv-btn danger" style={{ fontSize: 11, padding: '3px 10px' }} onClick={handleDelete}>Delete</button>
      </td>
    </tr>
    {showClose && <tr><td colSpan={12} style={{ padding: '0 12px 10px' }}>
      <TradeLogCloseForm trade={trade} onCancel={() => setShowClose(false)}
        onSubmit={async (payload) => { await onCloseSubmit(trade.id, payload); setShowClose(false); }} />
    </td></tr>}
    {showSnapshot && <tr><td colSpan={12} style={{ padding: '0 12px 10px' }}>
      <TradeLogSnapshotDetail trade={trade} />
    </td></tr>}
  </React.Fragment>;
}

function TradeLogTable({ trades, open, onDelete, onCloseSubmit }) {
  if (trades.length === 0) return <div style={{ color: 'var(--text4)', fontSize: 13, padding: '16px 0' }}>
    No {open ? 'open' : 'closed'} trades.
  </div>;
  const openCols = ['TICKER', 'DIR', 'ENTRY', 'STOP', 'QTY', 'TARGET', 'PLANNED RR', 'RISK $', 'NOTIONAL $', 'ENTERED', 'NOTES', ''];
  const closedCols = ['TICKER', 'DIR', 'ENTRY', 'STOP', 'EXIT', 'R RESULT', 'EXITED', 'FOLLOWED', 'DEVIATION', 'ENTERED', 'NOTES', ''];
  const cols = open ? openCols : closedCols;
  return <table className="tv-table">
    <thead><tr>{cols.map((c) => <th key={c}>{c}</th>)}</tr></thead>
    <tbody>
      {trades.map((t) => <TradeLogRow key={t.id} trade={t} open={open} onDelete={onDelete} onCloseSubmit={onCloseSubmit} />)}
    </tbody>
  </table>;
}

function TradeLogScreen() {
  const [trades, setTrades] = useState([]);
  const [summary, setSummary] = useState(null);
  const [tickers, setTickers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  function load() {
    setLoading(true);
    setError(null);
    Promise.all([
      api('/api/spot/trade-log'),
      api('/api/trading/scanner/noodle-state'),
    ]).then(([tradeLogResp, noodleResp]) => {
      setTrades(tradeLogResp.trades || []);
      setSummary(tradeLogResp.summary || null);
      // Ticker list is sourced from noodle-state's own symbols[].symbol
      // (exact noodle_state casing, e.g. 'kBONK') - never free text
      // (ruling B). Note: noodle-state returns {symbols: [...], meta} -
      // an ARRAY of per-symbol objects, not an object keyed by symbol.
      setTickers((noodleResp.symbols || []).map((s) => s.symbol).sort());
    }).catch((e) => {
      setError(String(e.message || e));
    }).finally(() => setLoading(false));
  }
  useEffect(load, []);

  async function handleCloseSubmit(id, payload) {
    await api(`/api/spot/trade-log/${id}`, { method: 'PUT', body: JSON.stringify(payload) });
    load();
  }
  async function handleDelete(id) {
    await api(`/api/spot/trade-log/${id}`, { method: 'DELETE' });
    load();
  }

  if (loading) return <div style={{ padding: 40, textAlign: 'center', color: 'var(--text4)' }}>
    <div className="spin" style={{ display: 'inline-block', width: 24, height: 24, border: '2px solid var(--line)', borderTopColor: 'var(--accent)', borderRadius: '50%' }} />
  </div>;
  if (error) return <div style={{ padding: 40, textAlign: 'center', color: 'var(--fail)' }}>Failed to load trade log: {error}</div>;

  const openTrades = trades.filter((t) => t.status === 'open');
  const closedTrades = trades.filter((t) => t.status === 'closed');

  return <div className="tv-content">
    <div className="tv-page-title">Trade Log</div>
    <TradeLogEntryForm tickers={tickers} onCreate={load} />
    {summary && <div className="tv-card" style={{ marginBottom: 20, fontSize: 14, color: 'var(--text2)' }}>
      <strong style={{ color: 'var(--text)' }}>{summary.mhc_followed_closed_count} / {summary.gate_target}</strong> MHC
      rule-followed trades &middot; expectancy{' '}
      <span className={typeof summary.expectancy_r === 'number' ? pnlClass(summary.expectancy_r) : ''}>
        {typeof summary.expectancy_r === 'number' ? summary.expectancy_r.toFixed(2) + 'R' : '—'}
      </span>
    </div>}

    <div className="tv-section-title">Open trades ({openTrades.length})</div>
    <div className="tv-card" style={{ marginBottom: 24, padding: 0, overflowX: 'auto' }}>
      <TradeLogTable trades={openTrades} open={true} onDelete={handleDelete} onCloseSubmit={handleCloseSubmit} />
    </div>

    <div className="tv-section-title">Closed trades ({closedTrades.length})</div>
    <div className="tv-card" style={{ padding: 0, overflowX: 'auto' }}>
      <TradeLogTable trades={closedTrades} open={false} onDelete={handleDelete} onCloseSubmit={handleCloseSubmit} />
    </div>
  </div>;
}

window.TradeLogScreen = TradeLogScreen;
