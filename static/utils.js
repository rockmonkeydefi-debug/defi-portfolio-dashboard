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
window.mask = mask;
window.pnlClass = pnlClass;
window.formatDate = formatDate;
window.formatDateShort = formatDateShort;
window.daysAgo = daysAgo;
window.api = api;
window.escHtml = escHtml;
