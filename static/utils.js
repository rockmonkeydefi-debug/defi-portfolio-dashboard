/* ===== UTILITY FUNCTIONS ===== */

function fmt(value, decimals = 2) {
  if (value == null || isNaN(value)) return '$0.00';
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(value);
}

function fmtNum(value, decimals = 4) {
  if (value == null || isNaN(value)) return '0';
  return new Intl.NumberFormat('en-US', {
    minimumFractionDigits: 0,
    maximumFractionDigits: decimals,
  }).format(value);
}

function fmtPct(value) {
  if (value == null || isNaN(value)) return '0.00%';
  const sign = value >= 0 ? '+' : '';
  return sign + value.toFixed(2) + '%';
}

const _SUBSCRIPT_DIGITS = '₀₁₂₃₄₅₆₇₈₉';

function _toSubscript(n) {
  return String(n).split('').map(c => _SUBSCRIPT_DIGITS[+c]).join('');
}

function fmtPrice(value, decimals = 2) {
  // Price formatter with sub-cent handling. At or above $0.01 delegates to
  // fmt(value, decimals) so existing columns render exactly as before. Below
  // $0.01: 3 significant digits; 3+ leading zeros after the decimal compress
  // DexScreener-style to a subscript zero count.
  //   0.0000036398 -> "$0.0₅364"   0.00044070 -> "$0.0₃441"
  //   0.00446      -> "$0.00446"   0.0005     -> "$0.0₃5"
  if (value == null || isNaN(value)) return '$0.00';
  if (value <= 0 || value >= 0.01) return fmt(value, decimals);
  const rounded = Number(value.toPrecision(3));
  if (rounded >= 0.01) return fmt(rounded, decimals); // 0.00999... rounds up
  const zeros = -Math.floor(Math.log10(rounded)) - 1;
  if (zeros >= 3) {
    const digits = String(Math.round(rounded * Math.pow(10, zeros + 3)))
      .replace(/0+$/, '');
    return '$0.0' + _toSubscript(zeros) + digits;
  }
  return '$' + rounded.toFixed(zeros + 3).replace(/0+$/, '').replace(/\.$/, '');
}

// A token's unit price: 2 decimals from $100 up, else 4; fmtPrice handles
// sub-cent prices. The Spot page's rule (Landing 2a), shared with Token
// Holdings (Landing 18) so the two pages show the same price the same way.
function fmtTokenPrice(value) {
  return fmtPrice(value, Math.abs(Number(value) || 0) >= 100 ? 2 : 4);
}

function mask(value, hidden, formatted = true) {
  if (hidden) return '••••';
  return formatted ? fmt(value) : value;
}

function pnlClass(value) {
  return value >= 0 ? 'ok' : 'fail';
}

function formatDate(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  if (isNaN(d)) return iso;
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}

function formatDateShort(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  if (isNaN(d)) return iso;
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

function daysAgo(iso) {
  if (!iso) return null;
  const d = new Date(iso);
  if (isNaN(d)) return null;
  return Math.floor((Date.now() - d.getTime()) / 86400000);
}

async function api(path, options = {}) {
  const res = await fetch(path, {
    ...options,
    headers: { 'Content-Type': 'application/json', ...options.headers },
  });
  if (res.status === 401) {
    window.location.href = '/login';
    return;
  }
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

function escHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

// Expose to global scope for non-module scripts
window.fmt = fmt;
window.fmtNum = fmtNum;
window.fmtPct = fmtPct;
window.fmtPrice = fmtPrice;
window.fmtTokenPrice = fmtTokenPrice;
window.mask = mask;
window.pnlClass = pnlClass;
window.formatDate = formatDate;
window.formatDateShort = formatDateShort;
window.daysAgo = daysAgo;
window.api = api;
window.escHtml = escHtml;

// The nav's Spot and Perps badges (Landing 8d), from one /api/trading/trades
// response: {spot: open spot exit signals, perpOpen: the rows of the Perps
// Open tab (perp trades not closed, partly closed and opened before the gate
// start included, plus live venue positions with no trade yet), perpNeedsStop:
// open perp trades flagged "needs a stop", perpNotReady (Landing 22): open
// perp trades that could still count toward the risk gate but still miss a
// part (gateMissing)}. null when the response is not a trades response.
// app.js, perps.js and dashboard.js all count through this.
function tradesNavCounts(d) {
  if (!d || !Array.isArray(d.trades) || !d.summary || typeof d.summary !== 'object') return null;
  const perps = d.trades.filter(t => t && t.market === 'perp');
  const untracked = Array.isArray(d.untracked_positions) ? d.untracked_positions.length : 0;
  return {
    spot: Number((d.summary.spot || {}).exit_signal_count) || 0,
    perpOpen: perps.filter(t => t.status !== 'closed').length + untracked,
    perpNeedsStop: perps.filter(t => t.status !== 'closed' && t.attention === 'needs_stop').length,
    perpNotReady: perps.filter(t => t.status !== 'closed' && gateMissing(t).length > 0).length,
  };
}
window.tradesNavCounts = tradesNavCounts;

// Landing 22: what an open perp trade still needs before its close to count
// toward the risk gate, from the trades route's "gate_prep" ({"missing":
// [...]} on a trade that can still count, null otherwise): the known parts
// of GATE_PREP_PARTS in that order ([] when none, or for any other shape).
// The keys match perp_rules.GATE_PREP_PARTS (a test pins them).
const GATE_PREP_PARTS = ['setup', 'poi', 'take_profit'];
const GATE_PREP_LABELS = { setup: 'setup', poi: 'POI', take_profit: 'take-profit' };
function gateMissing(t) {
  const m = t && t.gate_prep && Array.isArray(t.gate_prep.missing) ? t.gate_prep.missing : [];
  return GATE_PREP_PARTS.filter(p => m.indexOf(p) >= 0);
}
window.gateMissing = gateMissing;
window.GATE_PREP_LABELS = GATE_PREP_LABELS;
