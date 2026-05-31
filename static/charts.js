/* ===== CHART COMPONENTS (React.createElement — no JSX) ===== */

function Sparkline(props) {
  var data = props.data, color = props.color || 'var(--ok)', width = props.width || 80, height = props.height || 32;
  if (!data || data.length < 2) return null;
  var min = Math.min.apply(null, data), max = Math.max.apply(null, data), range = max - min || 1;
  var pts = data.map(function(v, i) {
    return ((i / (data.length - 1)) * width) + ',' + (height - ((v - min) / range) * (height - 4) - 2);
  }).join(' ');
  return React.createElement('svg', { width: width, height: height, style: { display: 'block' } },
    React.createElement('polyline', { points: pts, fill: 'none', stroke: color, strokeWidth: 1.5, strokeLinejoin: 'round', strokeLinecap: 'round' })
  );
}

function HealthBar(props) {
  var value = props.value || 0, max = props.max || 5;
  var pct = Math.max(0, Math.min(100, ((Math.min(value, max) - 1) / (max - 1)) * 100));
  return React.createElement('div', { style: { position: 'relative', height: 8, borderRadius: 4 } },
    React.createElement('div', { style: { position: 'absolute', inset: 0, background: 'linear-gradient(to right,var(--fail),var(--warn) 30%,var(--ok))', borderRadius: 4 } }),
    React.createElement('div', { style: { position: 'absolute', top: -3, width: 3, height: 14, background: '#fff', borderRadius: 2, left: pct + '%', transform: 'translateX(-50%)', boxShadow: '0 0 4px rgba(0,0,0,0.6)' } })
  );
}

function PriceRangeBar(props) {
  var lower = props.lower, upper = props.upper, current = props.current;
  if (!lower && !upper) return null;
  var pct = (upper > lower) ? Math.max(0, Math.min(100, ((current - lower) / (upper - lower)) * 100)) : 50;
  var inRange = current >= lower && current <= upper;
  var mc = inRange ? 'var(--ok)' : 'var(--fail)';
  return React.createElement('div', null,
    React.createElement('div', { style: { display: 'flex', justifyContent: 'space-between', fontSize: 11, color: 'var(--text4)', marginBottom: 4 } },
      React.createElement('span', null, 'Min: ' + (window.fmtNum ? fmtNum(lower, 4) : lower.toFixed(4))),
      React.createElement('span', { style: { color: 'var(--text)' } }, 'Current: ' + (window.fmtNum ? fmtNum(current, 4) : current.toFixed(4))),
      React.createElement('span', null, 'Max: ' + (window.fmtNum ? fmtNum(upper, 4) : upper.toFixed(4)))
    ),
    React.createElement('div', { style: { position: 'relative', height: 6, background: 'var(--panel3)', borderRadius: 3 } },
      inRange && React.createElement('div', { style: { position: 'absolute', inset: 0, background: 'var(--ok-soft)', borderRadius: 3 } }),
      React.createElement('div', { style: { position: 'absolute', top: -3, width: 3, height: 12, background: mc, borderRadius: 2, left: pct + '%', transform: 'translateX(-50%)' } })
    )
  );
}

function SimpleLineChart(props) {
  var data = props.data, width = props.width || 400, height = props.height || 180, color = props.color || 'var(--accent)';
  if (!data || data.length < 2) {
    return React.createElement('div', { style: { width: width, height: height, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text4)', fontSize: 12 } }, 'No data');
  }
  var values = data.map(function(d) { return typeof d === 'object' ? (d.y != null ? d.y : d) : d; });
  var min = Math.min.apply(null, values), max = Math.max.apply(null, values), range = max - min || 1;
  var pad = 12;
  var pts = values.map(function(v, i) {
    var x = pad + (i / (values.length - 1)) * (width - pad * 2);
    var y = pad + ((max - v) / range) * (height - pad * 2);
    return x + ',' + y;
  }).join(' ');
  return React.createElement('svg', { width: width, height: height, style: { display: 'block' } },
    React.createElement('polyline', { points: pts, fill: 'none', stroke: color, strokeWidth: 2, strokeLinejoin: 'round', strokeLinecap: 'round' })
  );
}

window.Sparkline = Sparkline;
window.HealthBar = HealthBar;
window.PriceRangeBar = PriceRangeBar;
window.SimpleLineChart = SimpleLineChart;
