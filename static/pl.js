/* ===== P/L SNAPSHOT SCREEN ===== */
//
// Weekly manual tracking of total capital over the pl_snapshots/pl_flows
// backend (see web_portfolio.py's /api/pl/* routes). One question, two
// stacked charts (Glenn's ruling: no raw wallet-totals line):
//   top:    flow-adjusted profit over time
//   bottom: LP book value over time
// Styling convention follows checklist.js exactly: className for shared
// chrome (tv-card/tv-section-title/tv-page-title/tv-input/tv-select/tv-btn/
// tv-table/tv-label), inline styles for everything bespoke (colors,
// spacing, one-off layout). React.createElement throughout, no JSX -
// checklist.js's own choice, mirrored here rather than performance.js's
// JSX (performance.js is consulted only for its Recharts prop/styling
// conventions, not its authoring style).

/* ── pure helpers ── */

function _plTruncateAddr(addr) {
  if (!addr) return '—';
  if (addr.length <= 12) return addr;
  return addr.slice(0, 6) + '…' + addr.slice(-4);
}

// api() throws Error(<raw response text>) on any non-2xx; every /api/pl/*
// error body is {"error": ...} or {"error": "UnknownWallet", "detail": ...}
// - detail (when present) is the plain-English message, error alone is
// otherwise already plain English (see _pl_valid_date/_pl_is_finite_number
// callers in web_portfolio.py). Mirrors maxfi.js's local mxExtractErr.
function _plExtractErr(e) {
  let msg = (e && e.message) ? e.message : String(e);
  try {
    const j = JSON.parse(msg);
    if (j) msg = j.detail || j.error || msg;
  } catch (e2) {}
  return msg;
}

function _plWalletLabel(wallets, walletAddr) {
  if (!walletAddr) return null;
  const w = (wallets || []).find((x) => x.address === String(walletAddr).toLowerCase());
  return w ? (w.label || _plTruncateAddr(w.address)) : _plTruncateAddr(walletAddr);
}

function _plSigned(v) {
  return (v >= 0 ? '+' : '-') + fmt(Math.abs(v));
}

// ASSUMPTION (per spec, not engineered around): every saved snapshot_date
// contains the same wallet set, because the entry form always submits all
// currently-flagged wallets together. If an older date has fewer wallet
// rows than the latest date (a wallet was flagged/unflagged since), TOTAL/
// LP for that date are still computed from whatever rows are present -
// no backfill, no assumed zero for the missing wallet.
function _plGroupByDate(snapshots) {
  const byDate = {};
  (snapshots || []).forEach((s) => {
    if (!byDate[s.snapshot_date]) {
      byDate[s.snapshot_date] = { date: s.snapshot_date, total: 0, lp: 0, rows: [] };
    }
    const g = byDate[s.snapshot_date];
    g.total += Number(s.wallet_total_usd) || 0;
    g.lp += Number(s.lp_book_value_usd) || 0;
    g.rows.push(s);
  });
  // snapshot_date is 'YYYY-MM-DD' - plain string comparison is chronological.
  return Object.values(byDate).sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : 0));
}

// Flow-window comparison (load-bearing): for each date d (ascending),
// flowsThrough(d) sums amount_usd over flows with baselineDate < flow_date
// <= d. Flows dated ON OR BEFORE the baseline are already embedded inside
// TOTAL(baselineDate) itself (that's what "baseline" means - a snapshot of
// capital as it stood after everything up to that point) and must NOT be
// subtracted again here, or they'd be double-counted. profit(d) = TOTAL(d)
// - TOTAL(baselineDate) - flowsThrough(d); profit(baselineDate) is 0 by
// construction since no flow can satisfy baselineDate < flow_date <=
// baselineDate.
function _plComputeSeries(dateGroups, flows) {
  if (!dateGroups || dateGroups.length === 0) return [];
  const baselineDate = dateGroups[0].date;
  const baselineTotal = dateGroups[0].total;
  const flowList = flows || [];
  return dateGroups.map((g) => {
    const flowsThrough = flowList.reduce((sum, f) => {
      if (f.flow_date > baselineDate && f.flow_date <= g.date) {
        return sum + (Number(f.amount_usd) || 0);
      }
      return sum;
    }, 0);
    const profit = g.total - baselineTotal - flowsThrough;
    return { date: g.date, total: g.total, lp: g.lp, profit, flowsThrough };
  });
}

// Date-only strings parsed as UTC midnight so chart positioning/formatting
// doesn't drift with the viewer's timezone.
function _plDateToTs(dateStr) {
  return Date.parse(dateStr + 'T00:00:00Z');
}

function _plDateTick(ts) {
  return new Date(ts).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

function _plYFmt(v) {
  const sign = v < 0 ? '-' : '';
  const a = Math.abs(v);
  if (a >= 1_000_000) return sign + '$' + (a / 1_000_000).toFixed(2) + 'M';
  if (a >= 1_000) return sign + '$' + (a / 1_000).toFixed(1) + 'K';
  return sign + '$' + a.toFixed(0);
}

function _plTooltipFmt(v) {
  const sign = v < 0 ? '-' : '';
  return sign + '$' + Math.abs(v).toLocaleString(undefined, { maximumFractionDigits: 0 });
}

/* ── headline stat card ── */

function PlStatCard({ label, value, subtitle, color }) {
  return React.createElement('div', { className: 'tv-card', style: { padding: '14px 16px', flex: 1 } },
    React.createElement('div', { style: { fontSize: 12, color: 'var(--text3)', marginBottom: 8 } }, label),
    React.createElement('div', { className: 'tv-num', style: { fontSize: 24, color: color || 'var(--text)' } }, value),
    subtitle && React.createElement('div', { style: { fontSize: 11, color: 'var(--text3)', marginTop: 6 } }, subtitle)
  );
}

/* ── charts (Recharts prop/styling conventions copied from performance.js;
   x-axis is numeric timestamps rather than performance.js's category axis
   so flow-date ReferenceLines can land BETWEEN snapshot points, not only
   on them - a category axis can only place a line on an existing tick) ── */

function PlProfitChart({ series, flows, baselineDate, lastDate }) {
  const R = window.Recharts || {};
  const { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ReferenceLine, ResponsiveContainer } = R;
  if (!LineChart) {
    return React.createElement('div', { style: { color: 'var(--text3)', fontSize: 13, textAlign: 'center', padding: '60px 0' } },
      'Chart library not loaded');
  }

  const chartData = series.map((s) => ({ ts: _plDateToTs(s.date), profit: s.profit }));
  const flowLines = (flows || []).filter((f) => f.flow_date >= baselineDate && f.flow_date <= lastDate);

  return React.createElement(ResponsiveContainer, { width: '100%', height: 300 },
    React.createElement(LineChart, { data: chartData, margin: { top: 4, right: 8, left: 0, bottom: 0 } },
      React.createElement(CartesianGrid, { strokeDasharray: '3 3', stroke: 'var(--line)', strokeOpacity: 0.2 }),
      React.createElement(XAxis, {
        dataKey: 'ts', type: 'number', domain: ['dataMin', 'dataMax'],
        tickFormatter: _plDateTick,
        tick: { fill: 'var(--text3)', fontSize: 11 },
        tickLine: false, axisLine: false,
      }),
      React.createElement(YAxis, {
        domain: ['auto', 'auto'],
        tickFormatter: _plYFmt,
        tick: { fill: 'var(--text3)', fontSize: 11 },
        tickLine: false, axisLine: false, width: 60,
      }),
      React.createElement(Tooltip, {
        contentStyle: { background: 'var(--panel)', border: '1px solid var(--line)', fontSize: 12, borderRadius: 6 },
        labelStyle: { color: 'var(--text)', marginBottom: 4 },
        labelFormatter: _plDateTick,
        formatter: (v) => [_plTooltipFmt(v), 'Profit'],
      }),
      ...flowLines.map((f, i) => React.createElement(ReferenceLine, {
        key: 'flow-' + i,
        x: _plDateToTs(f.flow_date),
        stroke: f.amount_usd >= 0 ? 'var(--ok)' : 'var(--fail)',
        strokeDasharray: '4 4',
        label: {
          value: (f.amount_usd >= 0 ? '+' : '-') + '$' + Math.abs(f.amount_usd).toLocaleString(undefined, { maximumFractionDigits: 0 }),
          position: 'top',
          fill: f.amount_usd >= 0 ? 'var(--ok)' : 'var(--fail)',
          fontSize: 11,
        },
      })),
      React.createElement(Line, {
        type: 'monotone', dataKey: 'profit', name: 'Profit',
        stroke: 'var(--accent)', strokeWidth: 2, dot: { r: 3 }, activeDot: { r: 4 },
      })
    )
  );
}

function PlLpChart({ series }) {
  const R = window.Recharts || {};
  const { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } = R;
  if (!LineChart) {
    return React.createElement('div', { style: { color: 'var(--text3)', fontSize: 13, textAlign: 'center', padding: '60px 0' } },
      'Chart library not loaded');
  }

  const chartData = series.map((s) => ({ ts: _plDateToTs(s.date), lp: s.lp }));

  return React.createElement(ResponsiveContainer, { width: '100%', height: 300 },
    React.createElement(LineChart, { data: chartData, margin: { top: 4, right: 8, left: 0, bottom: 0 } },
      React.createElement(CartesianGrid, { strokeDasharray: '3 3', stroke: 'var(--line)', strokeOpacity: 0.2 }),
      React.createElement(XAxis, {
        dataKey: 'ts', type: 'number', domain: ['dataMin', 'dataMax'],
        tickFormatter: _plDateTick,
        tick: { fill: 'var(--text3)', fontSize: 11 },
        tickLine: false, axisLine: false,
      }),
      React.createElement(YAxis, {
        domain: ['auto', 'auto'],
        tickFormatter: _plYFmt,
        tick: { fill: 'var(--text3)', fontSize: 11 },
        tickLine: false, axisLine: false, width: 60,
      }),
      React.createElement(Tooltip, {
        contentStyle: { background: 'var(--panel)', border: '1px solid var(--line)', fontSize: 12, borderRadius: 6 },
        labelStyle: { color: 'var(--text)', marginBottom: 4 },
        labelFormatter: _plDateTick,
        formatter: (v) => [_plTooltipFmt(v), 'LP book value'],
      }),
      React.createElement(Line, {
        type: 'monotone', dataKey: 'lp', name: 'LP book value',
        stroke: 'var(--ok)', strokeWidth: 2, dot: { r: 3 }, activeDot: { r: 4 },
      })
    )
  );
}

/* ── snapshot entry form ── */

function PlSnapshotForm({ wallets, walletsError, snapshots, onSaved }) {
  const [entryDate, setEntryDate] = React.useState(() => new Date().toISOString().slice(0, 10));
  const [entryAmounts, setEntryAmounts] = React.useState({});
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState(null);
  const [result, setResult] = React.useState(null);

  // Prefill from existing rows for the chosen date (upsert - saving again
  // for the same date corrects it) whenever the date, the wallet list, or
  // the loaded snapshots change.
  React.useEffect(() => {
    const rowsForDate = (snapshots || []).filter((s) => s.snapshot_date === entryDate);
    const next = {};
    (wallets || []).forEach((w) => {
      const match = rowsForDate.find((s) => String(s.wallet).toLowerCase() === w.address);
      next[w.address] = match ? String(match.wallet_total_usd) : '';
    });
    setEntryAmounts(next);
    setResult(null);
    setError(null);
  }, [entryDate, wallets, snapshots]);

  function validate() {
    if (!wallets || wallets.length === 0) return 'No MaxFi-flagged wallets configured.';
    for (const w of wallets) {
      const raw = entryAmounts[w.address];
      if (raw === undefined || raw === '') return `Enter a total for ${w.label || _plTruncateAddr(w.address)}.`;
      const n = Number(raw);
      if (!Number.isFinite(n) || n < 0) return `${w.label || _plTruncateAddr(w.address)}'s total must be a number >= 0.`;
    }
    return null;
  }

  async function save() {
    setError(null);
    const v = validate();
    if (v) { setError(v); return; }
    setSaving(true);
    try {
      const entries = wallets.map((w) => ({ wallet: w.address, wallet_total_usd: Number(entryAmounts[w.address]) }));
      const d = await api('/api/pl/snapshots', {
        method: 'POST',
        body: JSON.stringify({ snapshot_date: entryDate, entries }),
      });
      if (d === undefined || d === null) {
        setError('session expired');
        setSaving(false);
        return;
      }
      setResult(d.snapshots || []);
      setSaving(false);
      onSaved();
    } catch (e) {
      setError(_plExtractErr(e));
      setSaving(false);
    }
  }

  return React.createElement('div', { className: 'tv-card', style: { padding: 20 } },
    React.createElement('div', { className: 'tv-section-title', style: { marginBottom: 14 } }, 'Save a snapshot'),
    walletsError && React.createElement('div', { style: { color: 'var(--fail)', fontSize: 13, marginBottom: 12 } }, walletsError),
    (!walletsError && wallets.length === 0) && React.createElement('div', { style: { color: 'var(--text3)', fontSize: 13, marginBottom: 12 } },
      'No wallets are flagged for MaxFi. Go to Settings → Wallets and enable the MaxFi toggle on a wallet.'),
    wallets.length > 0 && React.createElement('div', { style: { display: 'flex', flexDirection: 'column', gap: 14 } },
      React.createElement('div', { style: { display: 'flex', flexDirection: 'column', gap: 6, maxWidth: 220 } },
        React.createElement('label', { style: { fontSize: 12, color: 'var(--text3)' } }, 'Date'),
        React.createElement('input', {
          type: 'date', className: 'tv-input', value: entryDate,
          onChange: (e) => setEntryDate(e.target.value),
        })
      ),
      React.createElement('div', { style: { display: 'flex', flexDirection: 'column', gap: 10 } },
        wallets.map((w) => React.createElement('div', { key: w.address, style: { display: 'flex', flexDirection: 'column', gap: 6, maxWidth: 320 } },
          React.createElement('label', { style: { fontSize: 13, color: 'var(--text2)' } }, w.label || _plTruncateAddr(w.address)),
          React.createElement('input', {
            type: 'number', min: 0, step: '0.01', className: 'tv-input',
            placeholder: '0.00',
            value: entryAmounts[w.address] === undefined ? '' : entryAmounts[w.address],
            onChange: (e) => setEntryAmounts((prev) => Object.assign({}, prev, { [w.address]: e.target.value })),
          })
        ))
      ),
      React.createElement('div', { style: { fontSize: 11, color: 'var(--text3)' } },
        'LP book value fills in automatically from the last valuation'),
      error && React.createElement('div', { style: { color: 'var(--fail)', fontSize: 13 } }, error),
      React.createElement('button', {
        className: 'tv-btn primary', disabled: saving, onClick: save, style: { alignSelf: 'flex-start' },
      }, saving ? 'Saving…' : 'Save'),
      result && React.createElement('div', {
        style: { padding: 12, background: 'var(--panel2)', border: '1px solid var(--line)', borderRadius: 8, display: 'flex', flexDirection: 'column', gap: 6 },
      },
        React.createElement('div', { style: { fontSize: 13, color: 'var(--ok)', fontWeight: 600 } }, 'Saved.'),
        result.map((row) => {
          const label = _plWalletLabel(wallets, row.wallet);
          const skipped = row.lp_skipped_positions || 0;
          return React.createElement('div', { key: row.wallet, style: { fontSize: 13, color: 'var(--text2)' } },
            label + ': LP ' + fmt(row.lp_book_value_usd || 0)
            + (skipped > 0
              ? ` (${skipped} open position${skipped === 1 ? '' : 's'} had no recorded value and ${skipped === 1 ? 'was' : 'were'} skipped)`
              : ''));
        })
      )
    )
  );
}

/* ── snapshot history table ── */

function PlSnapshotHistoryTable({ dateGroups, wallets, onDeleted }) {
  const [confirmDate, setConfirmDate] = React.useState(null);
  const [error, setError] = React.useState(null);

  // Column set is the UNION of every wallet ever saved, not just the
  // currently-flagged list - an older date recorded under a wallet that
  // was later unflagged must not silently disappear from its own history.
  const walletKeys = React.useMemo(() => {
    const set = new Set();
    dateGroups.forEach((g) => g.rows.forEach((r) => set.add(r.wallet)));
    return Array.from(set).sort();
  }, [dateGroups]);

  async function doDelete(date) {
    setError(null);
    try {
      const d = await api(`/api/pl/snapshots?date=${encodeURIComponent(date)}`, { method: 'DELETE' });
      if (d === undefined || d === null) {
        setError('session expired');
        return;
      }
      setConfirmDate(null);
      onDeleted();
    } catch (e) {
      setError(_plExtractErr(e));
    }
  }

  if (dateGroups.length === 0) {
    return React.createElement('div', { className: 'tv-card', style: { padding: 20 } },
      React.createElement('div', { className: 'tv-section-title', style: { marginBottom: 14 } }, 'Snapshot history'),
      React.createElement('div', { style: { fontSize: 13, color: 'var(--text3)' } }, 'No snapshot dates saved yet.'));
  }

  // Most recent date first, easiest to eyeball/correct.
  const rowsDesc = dateGroups.slice().reverse();

  return React.createElement('div', { className: 'tv-card', style: { padding: 20 } },
    React.createElement('div', { className: 'tv-section-title', style: { marginBottom: 14 } }, 'Snapshot history'),
    error && React.createElement('div', { style: { color: 'var(--fail)', fontSize: 13, marginBottom: 10 } }, error),
    React.createElement('div', { style: { overflowX: 'auto' } },
      React.createElement('table', { className: 'tv-table', style: { width: '100%' } },
        React.createElement('thead', null,
          React.createElement('tr', null,
            React.createElement('th', null, 'DATE'),
            walletKeys.map((wk) => React.createElement('th', { key: wk }, _plWalletLabel(wallets, wk) || _plTruncateAddr(wk))),
            React.createElement('th', null, 'LP SUM'),
            React.createElement('th', null, '')
          )
        ),
        React.createElement('tbody', null,
          rowsDesc.map((g) => {
            const confirming = confirmDate === g.date;
            const byWallet = {};
            g.rows.forEach((r) => { byWallet[r.wallet] = r; });
            return React.createElement('tr', { key: g.date },
              React.createElement('td', null, g.date),
              walletKeys.map((wk) => React.createElement('td', { key: wk },
                byWallet[wk] ? fmt(byWallet[wk].wallet_total_usd) : '—')),
              React.createElement('td', null, fmt(g.lp)),
              React.createElement('td', null,
                !confirming && React.createElement('button', {
                  className: 'tv-btn danger', style: { fontSize: 12 }, onClick: () => setConfirmDate(g.date),
                }, 'Delete'),
                confirming && React.createElement('div', { style: { display: 'flex', gap: 6 } },
                  React.createElement('button', {
                    className: 'tv-btn danger', style: { fontSize: 12 }, onClick: () => doDelete(g.date),
                  }, 'Confirm Delete'),
                  React.createElement('button', {
                    className: 'tv-btn', style: { fontSize: 12 }, onClick: () => setConfirmDate(null),
                  }, 'Cancel')
                )
              )
            );
          })
        )
      )
    )
  );
}

/* ── capital-flows ledger ── */

function PlFlowsLedger({ flows, wallets, onChanged }) {
  const [flowDate, setFlowDate] = React.useState(() => new Date().toISOString().slice(0, 10));
  const [direction, setDirection] = React.useState('in');
  const [amount, setAmount] = React.useState('');
  const [wallet, setWallet] = React.useState('');
  const [note, setNote] = React.useState('');
  const [saving, setSaving] = React.useState(false);
  const [addError, setAddError] = React.useState(null);
  const [confirmId, setConfirmId] = React.useState(null);
  const [rowError, setRowError] = React.useState(null);

  function validate() {
    if (!flowDate) return 'Pick a date.';
    const n = Number(amount);
    if (!Number.isFinite(n) || n === 0) return 'Enter a non-zero amount.';
    return null;
  }

  async function addFlow() {
    setAddError(null);
    const v = validate();
    if (v) { setAddError(v); return; }
    setSaving(true);
    try {
      const signed = direction === 'out' ? -Math.abs(Number(amount)) : Math.abs(Number(amount));
      const body = { flow_date: flowDate, amount_usd: signed };
      if (wallet) body.wallet = wallet;
      if (note) body.note = note;
      const d = await api('/api/pl/flows', { method: 'POST', body: JSON.stringify(body) });
      if (d === undefined || d === null) {
        setAddError('session expired');
        setSaving(false);
        return;
      }
      setAmount('');
      setNote('');
      setSaving(false);
      onChanged();
    } catch (e) {
      setAddError(_plExtractErr(e));
      setSaving(false);
    }
  }

  async function doDelete(id) {
    setRowError(null);
    try {
      const d = await api(`/api/pl/flows/${id}`, { method: 'DELETE' });
      if (d === undefined || d === null) {
        setRowError('session expired');
        return;
      }
      setConfirmId(null);
      onChanged();
    } catch (e) {
      setRowError(_plExtractErr(e));
    }
  }

  const rowsDesc = (flows || []).slice().reverse();

  return React.createElement('div', { className: 'tv-card', style: { padding: 20 } },
    React.createElement('div', { className: 'tv-section-title', style: { marginBottom: 4 } }, 'Capital flows'),
    React.createElement('div', { style: { fontSize: 11, color: 'var(--text3)', marginBottom: 14, lineHeight: 1.5 } },
      "Record only money entering or leaving these wallets from outside. Transfers between them cancel out — don't log those."),

    React.createElement('div', { style: { display: 'flex', flexWrap: 'wrap', gap: 10, alignItems: 'flex-end', marginBottom: 16 } },
      React.createElement('div', { style: { display: 'flex', flexDirection: 'column', gap: 4 } },
        React.createElement('label', { style: { fontSize: 11, color: 'var(--text3)' } }, 'Date'),
        React.createElement('input', {
          type: 'date', className: 'tv-input', style: { width: 150 }, value: flowDate,
          onChange: (e) => setFlowDate(e.target.value),
        })
      ),
      React.createElement('div', { style: { display: 'flex', flexDirection: 'column', gap: 4 } },
        React.createElement('label', { style: { fontSize: 11, color: 'var(--text3)' } }, 'Direction'),
        React.createElement('select', {
          className: 'tv-select', value: direction, onChange: (e) => setDirection(e.target.value),
        },
          React.createElement('option', { value: 'in' }, 'In'),
          React.createElement('option', { value: 'out' }, 'Out')
        )
      ),
      React.createElement('div', { style: { display: 'flex', flexDirection: 'column', gap: 4 } },
        React.createElement('label', { style: { fontSize: 11, color: 'var(--text3)' } }, 'Amount (USD)'),
        React.createElement('input', {
          type: 'number', min: 0, step: '0.01', className: 'tv-input', style: { width: 130 },
          placeholder: '0.00', value: amount, onChange: (e) => setAmount(e.target.value),
        })
      ),
      React.createElement('div', { style: { display: 'flex', flexDirection: 'column', gap: 4 } },
        React.createElement('label', { style: { fontSize: 11, color: 'var(--text3)' } }, 'Wallet (optional)'),
        React.createElement('select', {
          className: 'tv-select', value: wallet, onChange: (e) => setWallet(e.target.value),
        },
          React.createElement('option', { value: '' }, '—'),
          (wallets || []).map((w) => React.createElement('option', { key: w.address, value: w.address },
            w.label || _plTruncateAddr(w.address)))
        )
      ),
      React.createElement('div', { style: { display: 'flex', flexDirection: 'column', gap: 4, flex: 1, minWidth: 160 } },
        React.createElement('label', { style: { fontSize: 11, color: 'var(--text3)' } }, 'Note (optional)'),
        React.createElement('input', {
          type: 'text', className: 'tv-input', value: note, onChange: (e) => setNote(e.target.value),
        })
      ),
      React.createElement('button', {
        className: 'tv-btn primary', disabled: saving, onClick: addFlow,
      }, saving ? 'Adding…' : 'Add')
    ),
    addError && React.createElement('div', { style: { color: 'var(--fail)', fontSize: 13, marginBottom: 12 } }, addError),
    rowError && React.createElement('div', { style: { color: 'var(--fail)', fontSize: 13, marginBottom: 12 } }, rowError),

    rowsDesc.length === 0
      ? React.createElement('div', { style: { fontSize: 13, color: 'var(--text3)' } }, 'No flows recorded yet.')
      : React.createElement('div', { style: { overflowX: 'auto' } },
          React.createElement('table', { className: 'tv-table', style: { width: '100%' } },
            React.createElement('thead', null,
              React.createElement('tr', null,
                React.createElement('th', null, 'DATE'),
                React.createElement('th', null, 'AMOUNT'),
                React.createElement('th', null, 'WALLET'),
                React.createElement('th', null, 'NOTE'),
                React.createElement('th', null, '')
              )
            ),
            React.createElement('tbody', null,
              rowsDesc.map((f) => {
                const confirming = confirmId === f.id;
                return React.createElement('tr', { key: f.id },
                  React.createElement('td', null, f.flow_date),
                  React.createElement('td', { style: { color: f.amount_usd >= 0 ? 'var(--ok)' : 'var(--fail)', fontWeight: 500 } },
                    _plSigned(f.amount_usd)),
                  React.createElement('td', null, _plWalletLabel(wallets, f.wallet) || '—'),
                  React.createElement('td', null, f.note || '—'),
                  React.createElement('td', null,
                    !confirming && React.createElement('button', {
                      className: 'tv-btn danger', style: { fontSize: 12 }, onClick: () => setConfirmId(f.id),
                    }, 'Delete'),
                    confirming && React.createElement('div', { style: { display: 'flex', gap: 6 } },
                      React.createElement('button', {
                        className: 'tv-btn danger', style: { fontSize: 12 }, onClick: () => doDelete(f.id),
                      }, 'Confirm Delete'),
                      React.createElement('button', {
                        className: 'tv-btn', style: { fontSize: 12 }, onClick: () => setConfirmId(null),
                      }, 'Cancel')
                    )
                  )
                );
              })
            )
          )
        )
  );
}

/* ── main screen ── */

function PLScreen() {
  const [data, setData] = React.useState({ snapshots: [], flows: [] });
  const [loading, setLoading] = React.useState(true);
  const [loadError, setLoadError] = React.useState(null);
  const [wallets, setWallets] = React.useState([]);
  const [walletsError, setWalletsError] = React.useState(null);

  async function loadData() {
    setLoadError(null);
    try {
      const d = await api('/api/pl/data');
      if (d === undefined || d === null) {
        setLoadError('session expired');
        setLoading(false);
        return;
      }
      setData({ snapshots: d.snapshots || [], flows: d.flows || [] });
      setLoading(false);
    } catch (e) {
      setLoadError(_plExtractErr(e));
      setLoading(false);
    }
  }

  // Same wallet-list source as maxfi.js: GET /api/wallets, filter the
  // maxfi flag, lowercase the address for lookups (resolve_wallet_casing
  // on the backend is case-insensitive, so the lowercased form still
  // resolves correctly on every write).
  async function loadWallets() {
    setWalletsError(null);
    try {
      const d = await api('/api/wallets');
      if (d === undefined || d === null) {
        setWalletsError('session expired');
        return;
      }
      const list = Array.isArray(d) ? d : (d.wallets || []);
      const flagged = list
        .filter((w) => w.maxfi === true)
        .map((w) => ({ address: String(w.address).toLowerCase(), label: w.label || '' }));
      setWallets(flagged);
    } catch (e) {
      setWalletsError(_plExtractErr(e));
    }
  }

  React.useEffect(() => { loadData(); loadWallets(); }, []);

  const dateGroups = React.useMemo(() => _plGroupByDate(data.snapshots), [data.snapshots]);
  const series = React.useMemo(() => _plComputeSeries(dateGroups, data.flows), [dateGroups, data.flows]);

  if (loading) {
    return React.createElement('div', {
      style: { display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: 320, color: 'var(--text3)', fontSize: 14 },
    }, 'Loading P/L data…');
  }

  const hasAny = dateGroups.length > 0;
  const last = hasAny ? series[series.length - 1] : null;
  const baseline = hasAny ? series[0] : null;

  let headline = null;
  if (hasAny) {
    const rawChange = last.total - baseline.total;
    const netFlows = last.flowsThrough;
    const lpPct = last.total !== 0 ? (last.lp / last.total * 100) : null;
    headline = React.createElement('div', { style: { display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12 } },
      React.createElement(PlStatCard, { label: 'Current Total (latest date)', value: fmt(last.total) }),
      React.createElement(PlStatCard, {
        label: 'Flow-Adjusted Profit Since Baseline',
        value: _plSigned(last.profit),
        color: last.profit >= 0 ? 'var(--ok)' : 'var(--fail)',
        subtitle: 'raw change ' + _plSigned(rawChange) + ' − net flows ' + _plSigned(netFlows),
      }),
      React.createElement(PlStatCard, {
        label: 'Latest LP Book Value',
        value: fmt(last.lp),
        subtitle: lpPct != null ? lpPct.toFixed(1) + '% of total' : '—',
      })
    );
  }

  let charts = null;
  if (dateGroups.length >= 2) {
    charts = React.createElement('div', { style: { display: 'flex', flexDirection: 'column', gap: 16 } },
      React.createElement('div', { className: 'tv-card' },
        React.createElement('div', { className: 'tv-label', style: { color: 'var(--accent)', marginBottom: 14 } },
          'Profit since ' + formatDate(baseline.date) + ' (flow-adjusted)'),
        React.createElement(PlProfitChart, { series, flows: data.flows, baselineDate: baseline.date, lastDate: last.date })
      ),
      React.createElement('div', { className: 'tv-card' },
        React.createElement('div', { className: 'tv-label', style: { color: 'var(--text3)', marginBottom: 14 } }, 'LP book value'),
        React.createElement(PlLpChart, { series })
      )
    );
  } else if (dateGroups.length === 1) {
    charts = React.createElement('div', { className: 'tv-card', style: { padding: '40px 20px', textAlign: 'center' } },
      React.createElement('div', { style: { fontSize: 13, color: 'var(--text3)' } }, 'One more snapshot and the charts appear'));
  }

  return React.createElement('div', { style: { display: 'flex', flexDirection: 'column', gap: 20 } },
    React.createElement('div', null,
      React.createElement('div', { className: 'tv-page-title', style: { marginBottom: 4 } }, 'P/L'),
      React.createElement('div', { style: { fontSize: 12, color: 'var(--text3)' } },
        'Weekly manual capital tracking - flow-adjusted profit and LP book value over time.')
    ),
    loadError && React.createElement('div', { style: { color: 'var(--fail)', fontSize: 13 } }, loadError),
    !hasAny && React.createElement('div', { style: { fontSize: 13, color: 'var(--text3)' } },
      'No snapshots yet — save your first one below'),
    headline,
    charts,
    React.createElement(PlSnapshotForm, { wallets, walletsError, snapshots: data.snapshots, onSaved: loadData }),
    React.createElement(PlSnapshotHistoryTable, { dateGroups, wallets, onDeleted: loadData }),
    React.createElement(PlFlowsLedger, { flows: data.flows, wallets, onChanged: loadData })
  );
}

window.PLScreen = PLScreen;
