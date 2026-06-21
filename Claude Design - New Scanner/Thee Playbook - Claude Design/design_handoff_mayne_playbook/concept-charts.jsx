// concept-charts.jsx — Small annotated candlestick illustrations for each concept
// Renders 12–16 candles in a fixed-size SVG with concept-specific overlays
// (OB boxes, FVG bands, sweep levels, break lines, entry arrows, etc).
// Used inside ConceptDetail (concepts.jsx).

// ---------- generic renderer ----------
// candles: array of [open, close, low, high]
// overlays: array of overlay descriptors, see types below
const ConceptChart = ({candles, overlays = [], caption, height = 200}) => {
  const W = 420, H = height, padX = 18, padTop = 14, padBottom = 24;
  const n = candles.length;

  // price range with a little headroom
  const allPrices = candles.flatMap(c => [c[2], c[3]]).concat(
    overlays.flatMap(o => [o.y, o.y1, o.y2, o.from, o.to].filter(v => v != null))
  );
  const pMin = Math.min(...allPrices) - 1;
  const pMax = Math.max(...allPrices) + 1;
  const pRange = pMax - pMin;

  const innerW = W - padX * 2;
  const innerH = H - padTop - padBottom;
  const slotW = innerW / n;
  const candleW = Math.max(4, slotW * 0.6);

  const xOf = (i) => padX + i * slotW + slotW / 2;
  const yOf = (p) => padTop + (1 - (p - pMin) / pRange) * innerH;

  return (
    <div style={{display: 'flex', flexDirection: 'column'}}>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H} preserveAspectRatio="none">
        <defs>
          <pattern id="fvgPat" patternUnits="userSpaceOnUse" width="6" height="6" patternTransform="rotate(45)">
            <line x1="0" y1="0" x2="0" y2="6" stroke={TV.accent} strokeWidth="1.5" opacity="0.4"/>
          </pattern>
          <pattern id="sweepPat" patternUnits="userSpaceOnUse" width="5" height="5" patternTransform="rotate(45)">
            <line x1="0" y1="0" x2="0" y2="5" stroke={TV.adapt} strokeWidth="1.2" opacity="0.35"/>
          </pattern>
        </defs>

        {/* faint y gridlines */}
        {[0.25, 0.5, 0.75].map((t, i) => (
          <line key={i} x1={padX} x2={W - padX}
                y1={padTop + t * innerH} y2={padTop + t * innerH}
                stroke={TV.lineSoft} strokeWidth="1"/>
        ))}

        {/* zone overlays (under candles) — premium/discount, killzone */}
        {overlays.filter(o => o.type === 'zone' || o.type === 'killzone' || o.type === 'discount' || o.type === 'premium').map((o, i) => {
          const y1 = yOf(o.y2);
          const y2 = yOf(o.y1);
          const color = o.color || (o.type === 'discount' ? TV.ok : o.type === 'premium' ? TV.fail : TV.adapt);
          const xStart = o.xFrom != null ? padX + o.xFrom * slotW : padX;
          const xEnd   = o.xTo   != null ? padX + o.xTo   * slotW : W - padX;
          return (
            <g key={'z' + i}>
              <rect x={xStart} y={y1} width={xEnd - xStart} height={y2 - y1}
                    fill={color} fillOpacity="0.07" stroke={color} strokeOpacity="0.25" strokeDasharray="3 3" strokeWidth="1"/>
              {o.label && (
                <text x={xStart + 6} y={y1 + 12} fontSize="9" fill={color} fontWeight="600"
                      style={{textTransform: 'uppercase', letterSpacing: '.08em'}}>{o.label}</text>
              )}
            </g>
          );
        })}

        {/* horizontal levels — sweep, invalidation, structure */}
        {overlays.filter(o => o.type === 'level' || o.type === 'invalidation' || o.type === 'sweep-line').map((o, i) => {
          const y = yOf(o.y);
          const color = o.color || (o.type === 'invalidation' ? TV.fail : o.type === 'sweep-line' ? TV.adapt : TV.text2);
          const dash = o.solid ? null : (o.type === 'invalidation' ? '4 3' : '2 3');
          return (
            <g key={'l' + i}>
              <line x1={padX} x2={W - padX} y1={y} y2={y}
                    stroke={color} strokeWidth="1.2" strokeDasharray={dash}/>
              {o.label && (
                <text x={W - padX - 4} y={y - 4} fontSize="9" fill={color}
                      fontWeight="600" textAnchor="end"
                      style={{textTransform: 'uppercase', letterSpacing: '.06em'}}>{o.label}</text>
              )}
            </g>
          );
        })}

        {/* candles */}
        {candles.map((c, i) => {
          const [o, cl, lo, hi] = c;
          const up = cl >= o;
          const color = up ? TV.ok : TV.fail;
          const x = xOf(i);
          const bodyTop = yOf(Math.max(o, cl));
          const bodyBot = yOf(Math.min(o, cl));
          const wickTop = yOf(hi);
          const wickBot = yOf(lo);
          return (
            <g key={i}>
              <line x1={x} x2={x} y1={wickTop} y2={wickBot} stroke={color} strokeWidth="1"/>
              <rect x={x - candleW / 2} y={bodyTop} width={candleW}
                    height={Math.max(1.2, bodyBot - bodyTop)}
                    fill={color} stroke={color}/>
            </g>
          );
        })}

        {/* boxes drawn ON TOP — OB, FVG, mitigation, OTE */}
        {overlays.filter(o => o.type === 'ob' || o.type === 'fvg' || o.type === 'mitigation' || o.type === 'ote' || o.type === 'box').map((o, i) => {
          const y1 = yOf(o.y2);
          const y2 = yOf(o.y1);
          const x1 = padX + o.xFrom * slotW;
          const x2 = o.xTo != null ? padX + o.xTo * slotW : W - padX;
          const color = o.color || (o.type === 'ob' ? TV.accent : o.type === 'fvg' ? TV.accent : o.type === 'ote' ? TV.adapt : TV.warn);
          const fill = o.type === 'fvg' ? 'url(#fvgPat)' : color;
          const fillOpacity = o.type === 'fvg' ? 1 : (o.fillOpacity != null ? o.fillOpacity : 0.18);
          return (
            <g key={'b' + i}>
              <rect x={x1} y={y1} width={x2 - x1} height={y2 - y1}
                    fill={fill} fillOpacity={fillOpacity}
                    stroke={color} strokeWidth="1.2"/>
              {o.label && (
                <g>
                  <rect x={x2 + 3} y={y1 - 1} width={26} height={11}
                        fill={TV.bg} stroke={color} strokeWidth="1" rx="2"/>
                  <text x={x2 + 16} y={y1 + 7} fontSize="9" fill={color} fontWeight="700"
                        textAnchor="middle">{o.label}</text>
                </g>
              )}
            </g>
          );
        })}

        {/* arrows */}
        {overlays.filter(o => o.type === 'arrow').map((o, i) => {
          const x = xOf(o.x);
          const y = yOf(o.y);
          const dy = o.dir === 'up' ? -1 : 1;
          const color = o.color || TV.accent;
          return (
            <g key={'a' + i}>
              <line x1={x} y1={y + dy * 28} x2={x} y2={y + dy * 6}
                    stroke={color} strokeWidth="2"/>
              <polygon points={`${x},${y + dy * 2} ${x - 4},${y + dy * 8} ${x + 4},${y + dy * 8}`}
                       fill={color}/>
              {o.label && (
                <text x={x} y={y + dy * 36} fontSize="10" fill={color}
                      fontWeight="700" textAnchor="middle"
                      style={{textTransform: 'uppercase', letterSpacing: '.06em'}}>{o.label}</text>
              )}
            </g>
          );
        })}

        {/* annotations — small floating labels */}
        {overlays.filter(o => o.type === 'note').map((o, i) => {
          const x = xOf(o.x);
          const y = yOf(o.y);
          return (
            <g key={'n' + i}>
              <circle cx={x} cy={y} r="3" fill={o.color || TV.accent}/>
              <text x={x + 6} y={y + 3} fontSize="10" fill={o.color || TV.text2} fontWeight="500">{o.label}</text>
            </g>
          );
        })}

        {/* x-axis label */}
        <text x={W / 2} y={H - 6} fontSize="9" fill={TV.text4} textAnchor="middle">
          schematic · not real price data
        </text>
      </svg>
      {caption && (
        <div style={{fontSize: 12, color: TV.text2, marginTop: 6, lineHeight: 1.45, paddingLeft: 4}}>
          {caption}
        </div>
      )}
    </div>
  );
};

// ---------- per-concept chart data ----------
// candles: [open, close, low, high]
const CHARTS_BY_CONCEPT = {
  // ─── Order Block ────────────────────────────────────────────────
  'order-block': {
    caption: '↑ Bullish OB at candle 5 — the last down-close before the impulse up. Mayne: it\'s where institutional buys filled; price returns here to rebalance.',
    candles: [
      [155,150,148,156],[150,148,145,151],[148,145,142,149],[145,142,140,146],
      [142,138,136,143],[138,134,132,140], // candle 5: the OB
      [134,142,133,143],[142,148,141,150],[148,154,147,156],[154,160,153,162],
      [160,165,158,166],[165,168,163,170],[168,172,166,173],[172,170,168,174],
    ],
    overlays: [
      {type: 'ob', xFrom: 5, xTo: 14, y1: 132, y2: 140, label: 'OB'},
      {type: 'arrow', x: 6, y: 134, dir: 'up', label: 'impulse'},
    ],
  },

  // ─── Fair Value Gap ────────────────────────────────────────────
  'fvg': {
    caption: '↑ Bullish 3-candle FVG: the high of candle 5 sits below the low of candle 7 — wicks don\'t overlap. Price seeks to return and rebalance.',
    candles: [
      [148,146,144,149],[146,144,142,147],[144,143,141,145],[143,141,140,144],
      [141,142,140,143], // c4
      [142,150,141,151], // c5 — impulse 1
      [150,156,149,157], // c6 — impulse 2 (the gap candle)
      [156,162,155,163], // c7 — impulse 3 (low is above c5 high)
      [162,160,159,164],[160,162,159,164],[162,158,156,163],
      [158,160,156,162],[160,158,156,162],[158,160,156,163],
    ],
    overlays: [
      // FVG region: between c5 high (~151) and c7 low (~155)
      {type: 'fvg', xFrom: 5, xTo: 14, y1: 151, y2: 155, label: 'FVG'},
      {type: 'note', x: 6, y: 153, label: 'imbalance', color: TV.accent},
    ],
  },

  // ─── Liquidity Sweep ───────────────────────────────────────────
  'liquidity-sweep': {
    caption: '↑ Two equal lows at 140 form sell-side liquidity. Price sweeps below, takes the stops, and immediately reclaims — the rejection wick is the signal.',
    candles: [
      [148,144,142,149],[144,141,140,145],[141,143,140,144],[143,142,140,144],
      [142,144,140,145], // c4 — first low at 140
      [144,146,143,147],[146,148,145,149],[148,145,142,149],
      [145,142,140,146],[142,140,140,143], // c9 — second low at 140 (equal)
      [140,138,136,141], // c10 — sweep wick goes below to 136
      [138,144,138,145],[144,150,143,151],[150,156,149,157],
    ],
    overlays: [
      {type: 'sweep-line', y: 140, label: 'equal lows · liquidity'},
      {type: 'box', xFrom: 10, xTo: 11, y1: 136, y2: 140, color: TV.adapt, fillOpacity: 0.15, label: 'sweep'},
      {type: 'arrow', x: 11, y: 140, dir: 'up', label: 'reclaim'},
    ],
  },

  // ─── BOS / CHoCH ──────────────────────────────────────────────
  'bos-choch': {
    caption: '↑ BOS: trend continuation, price takes the most recent same-side swing high. CHoCH: first opposite break, signaling exhaustion. The marked break is a CHoCH after a buy-side sweep.',
    candles: [
      [148,152,147,153],[152,156,151,157],[156,154,152,158],[154,160,153,161],
      [160,163,158,164], // c4 — prior HH
      [163,158,156,164],[158,154,152,159],[154,158,152,159],[158,162,156,163],
      [162,166,160,167], // c9 — slightly higher, then...
      [166,160,158,167],[160,156,154,161],[156,150,148,157], // c12 — break below recent low
      [150,148,146,151],
    ],
    overlays: [
      {type: 'level', y: 158, label: 'recent low (broken)', color: TV.text2},
      {type: 'level', y: 167, label: 'recent high', color: TV.text2},
      {type: 'arrow', x: 12, y: 156, dir: 'down', label: 'CHoCH', color: TV.fail},
    ],
  },

  // ─── Killzones ────────────────────────────────────────────────
  'killzones': {
    caption: '↑ London open killzone (02:00–05:00 NY) — most expansion happens here. The sweep, displacement, and CHoCH all delivered inside the highlighted window.',
    candles: [
      [148,147,146,149],[147,148,146,149],[148,147,146,149], // pre-kz quiet
      [147,150,146,151],[150,144,142,151],[144,140,138,145], // c3-5: sweep in
      [140,148,140,149],[148,156,147,157],[156,162,155,163], // c6-8: displacement
      [162,164,160,165],[164,166,162,167],[166,165,164,168], // c9-11: post-kz drift
      [165,166,164,168],[166,167,164,168],
    ],
    overlays: [
      {type: 'killzone', xFrom: 3, xTo: 9, y1: 138, y2: 167, label: 'London open · KZ', color: TV.adapt},
    ],
  },

  // ─── Bias ────────────────────────────────────────────────────
  'bias': {
    caption: '↑ Bullish bias: most recent decisive break of structure is to the upside; a lower-high has not yet printed.',
    candles: [
      [140,144,138,145],[144,142,140,145],[142,148,141,149],
      [148,152,146,153],[152,150,148,154],[150,156,149,157],
      [156,160,154,161],[160,158,156,162],[158,164,157,165],
      [164,168,162,169],[168,170,166,171],[170,172,168,173],
      [172,174,170,175],[174,178,173,179],
    ],
    overlays: [
      {type: 'level', y: 153, label: 'last decisive BOS', color: TV.ok, solid: true},
      {type: 'note', x: 8, y: 163, label: 'higher highs', color: TV.ok},
      {type: 'note', x: 10, y: 169, label: 'higher lows', color: TV.ok},
    ],
  },

  // ─── Dealing Range ────────────────────────────────────────────
  'dealing-range': {
    caption: '↑ The active 4H dealing range from 138 (low) to 178 (high). Equilibrium at 158; below = discount (long zone in a bullish bias), above = premium.',
    candles: [
      [148,144,142,149],[144,140,138,145],[140,146,138,148],
      [146,150,144,151],[150,154,148,156],[154,160,153,161],
      [160,165,158,166],[165,170,164,172],[170,175,168,176],
      [175,178,173,178],[178,172,170,178],[172,168,166,173],
      [168,162,160,170],[162,158,156,164],
    ],
    overlays: [
      {type: 'level', y: 178, label: 'range high', color: TV.text2, solid: true},
      {type: 'level', y: 138, label: 'range low', color: TV.text2, solid: true},
      {type: 'level', y: 158, label: 'equilibrium · 0.5', color: TV.adapt},
      {type: 'discount', y1: 138, y2: 158, label: 'discount'},
      {type: 'premium',  y1: 158, y2: 178, label: 'premium'},
    ],
  },

  // ─── Premium / Discount ───────────────────────────────────────
  'premium-discount': {
    caption: '↑ Premium (red) vs Discount (green). In a bullish bias, take longs only from discount; in a bearish bias, shorts only from premium.',
    candles: [
      [150,154,148,155],[154,160,153,161],[160,166,159,167],[166,170,164,171],
      [170,172,168,173],[172,168,166,173],[168,162,160,170],[162,158,156,164],
      [158,154,152,160],[154,152,150,156],[152,156,151,158],[156,162,155,164],
      [162,168,160,170],[168,174,166,176],
    ],
    overlays: [
      {type: 'level', y: 175, label: 'range high', color: TV.text2, solid: true},
      {type: 'level', y: 148, label: 'range low',  color: TV.text2, solid: true},
      {type: 'level', y: 161.5, label: 'equilibrium', color: TV.adapt},
      {type: 'premium',  y1: 161.5, y2: 175, label: 'PREMIUM · short here'},
      {type: 'discount', y1: 148, y2: 161.5, label: 'DISCOUNT · long here'},
    ],
  },

  // ─── Mitigation ───────────────────────────────────────────────
  'mitigation': {
    caption: '↑ The bullish FVG left at candles 4–6 is mitigated when price returns and trades through it (candles 10–11). After mitigation, the imbalance is "filled."',
    candles: [
      [140,138,136,141],[138,140,137,141],[140,142,138,143], // pre
      [142,148,141,149],[148,154,147,155],[154,158,153,159], // c3-5 impulse making FVG
      [158,162,156,163],[162,164,160,166], // continuation
      [164,160,158,165],[160,156,154,161], // pullback starts
      [156,152,150,157],[152,150,148,153], // c10-11 enter & fill the FVG
      [150,154,148,156],[154,158,152,160],
    ],
    overlays: [
      {type: 'fvg', xFrom: 4, xTo: 10, y1: 149, y2: 153, label: 'FVG'},
      {type: 'arrow', x: 10, y: 153, dir: 'down', label: 'mitigation', color: TV.warn},
    ],
  },

  // ─── Trade Entries ────────────────────────────────────────────
  'trade-entries': {
    caption: '↑ Three Mayne-approved triggers shown together: (1) OB tap, (2) FVG return, (3) sweep + LTF CHoCH. Entry arrow at the actual fill.',
    candles: [
      [148,144,142,149],[144,140,138,145],
      [140,138,136,141], // c2 — bullish OB
      [138,144,137,145],[144,150,143,151],[150,156,148,157], // impulse w/ FVG
      [156,160,154,162],[160,158,156,162],
      [158,154,152,160],[154,150,148,155],
      [150,148,146,151], // sweep low
      [148,154,146,156], // reclaim
      [154,158,152,160],[158,162,156,164],
    ],
    overlays: [
      {type: 'ob', xFrom: 2, xTo: 14, y1: 136, y2: 141, label: 'OB'},
      {type: 'fvg', xFrom: 4, xTo: 12, y1: 145, y2: 148, label: 'FVG'},
      {type: 'sweep-line', y: 146, label: 'swept'},
      {type: 'arrow', x: 11, y: 148, dir: 'up', label: 'entry'},
    ],
  },

  // ─── Invalidation ─────────────────────────────────────────────
  'invalidation': {
    caption: '↑ Invalidation: a close below 142 says "this long is wrong." Stop is parked below; if hit, don\'t fight it, don\'t move it.',
    candles: [
      [148,150,146,151],[150,154,148,155],[154,152,150,156],[152,156,150,158],
      [156,160,154,161],[160,158,156,162],[158,162,156,164],[162,166,160,167],
      [166,164,162,168],[164,160,158,166],[160,156,154,162],
      [156,154,152,158],[154,150,148,156],[150,148,146,152],
    ],
    overlays: [
      {type: 'invalidation', y: 142, label: 'invalidation · stop'},
      {type: 'arrow', x: 0, y: 149, dir: 'up', label: 'entry'},
      {type: 'note', x: 12, y: 152, label: '↓ approaching stop', color: TV.warn},
    ],
  },

  // ─── Optimal Trade Entry (OTE) ────────────────────────────────
  'optimal-trade-entry': {
    caption: '↑ OTE zone is the 0.62–0.79 fib retracement of the recent leg. Combined with discount + FVG, this is the narrowest, highest-RR LTF entry.',
    candles: [
      [142,146,140,147],[146,152,144,153],[152,158,150,159],[158,164,156,166],
      [164,170,162,172], // swing high at 172
      [170,166,164,172],[166,162,160,168],[162,158,156,164],
      [158,156,154,160], // c8 — into OTE
      [156,154,152,158], // c9 — deep into OTE
      [154,158,152,160],
      [158,162,156,164],[162,168,160,170],[168,172,166,174],
    ],
    overlays: [
      {type: 'level', y: 172, label: 'swing high (1.0)', color: TV.text2},
      {type: 'level', y: 140, label: 'swing low (0)',    color: TV.text2},
      {type: 'ote',   xFrom: 6, xTo: 12, y1: 152, y2: 159, label: 'OTE'},
      {type: 'arrow', x: 9, y: 156, dir: 'up', label: 'entry'},
    ],
  },
};

Object.assign(window, {ConceptChart, CHARTS_BY_CONCEPT});
