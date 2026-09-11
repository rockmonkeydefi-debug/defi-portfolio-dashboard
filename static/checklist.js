/* ===== PLAYBOOK CHECKLIST SCREEN ===== */

// Numbered checkbox rows for one card. State is React.useState only, local
// to this component instance - no localStorage, no backend write, no read
// on mount. It resets to all-unchecked every time this tab is revisited,
// since app.js renders exactly one active screen and unmounts the rest
// (same unmount-driven reset SettingsScreen's own section jump relies on).
function ChecklistCard({ title, caption, items }) {
  const [checked, setChecked] = React.useState({});

  function toggle(idx) {
    setChecked(prev => Object.assign({}, prev, { [idx]: !prev[idx] }));
  }

  return React.createElement('div', { className: 'tv-card', style: { padding: 20 } },
    React.createElement('div', { className: 'tv-section-title', style: { marginBottom: caption ? 4 : 14 } }, title),
    caption && React.createElement('div', { style: { fontSize: 12, color: 'var(--text4)', marginBottom: 14, lineHeight: 1.5 } }, caption),
    React.createElement('div', { style: { display: 'flex', flexDirection: 'column', gap: 10 } },
      items.map((text, idx) =>
        React.createElement('label', {
          key: idx,
          style: { display: 'flex', alignItems: 'flex-start', gap: 10, cursor: 'pointer' },
        },
          React.createElement('input', {
            type: 'checkbox',
            checked: !!checked[idx],
            onChange: () => toggle(idx),
            style: { marginTop: 3, flexShrink: 0, width: 15, height: 15, cursor: 'pointer' },
          }),
          React.createElement('span', {
            style: {
              fontSize: 13, lineHeight: 1.5,
              color: checked[idx] ? 'var(--text4)' : 'var(--text2)',
              textDecoration: checked[idx] ? 'line-through' : 'none',
            },
          }, (idx + 1) + '. ' + text)
        )
      )
    )
  );
}

// Section 1 - prose/bullets, no checkboxes: a strategy summary is read, not
// checked off.
const CHECKLIST_STRATEGY_BULLETS = [
  'Verdicts are reactive and fee-side only: they compare what a position earns against how fast its volatile token is decaying. No predictive or directional TA is used anywhere.',
  'CLOSE rule: 7d run-rate APR < 2.0 x decay. Run-rate = (claims in the trailing 7 days + prorated uncollected fees) / min(7, days open), as a % of current position value. Decay = the token’s 7d price trend in %/day, clamped at 0 - flat or rising tokens have decay 0 and read HOLD.',
  'Trends use the last completed daily candle - verdicts do not flip on today’s partial candle.',
  'The 2.0 multiplier is a judgment-set buffer, tuned over time from the Bucket B flagged-vs-resolved cohort.',
  'Lifetime run-rate APR is shown as context only. It is never a verdict input.',
  'Known blind spots: the rule never sees principal-path damage (rebalance IL crystallization), and uncollected fees are only as fresh as the last valuation refresh.',
  'Book disciplines: autocompound OFF book-wide. New capital enters as $25–50 probes only; full size appears only as scale-up on a measured probe. Russian Doll layering is capped at 2–3 layers and every layer counts fully against sizing caps.',
];

function ChecklistStrategyCard() {
  return React.createElement('div', { className: 'tv-card', style: { padding: 20 } },
    React.createElement('div', { className: 'tv-section-title', style: { marginBottom: 14 } },
      'Strategy summary: how verdicts work'),
    React.createElement('div', { style: { display: 'flex', flexDirection: 'column', gap: 10 } },
      CHECKLIST_STRATEGY_BULLETS.map((text, idx) =>
        React.createElement('div', {
          key: idx,
          style: { display: 'flex', alignItems: 'flex-start', gap: 10, fontSize: 13, lineHeight: 1.5, color: 'var(--text2)' },
        },
          React.createElement('span', { style: { color: 'var(--text4)', flexShrink: 0 } }, '•'),
          React.createElement('span', null, text)
        )
      )
    )
  );
}

function ChecklistScreen() {
  return React.createElement('div', { style: { display: 'flex', flexDirection: 'column', gap: 20 } },
    React.createElement('div', null,
      React.createElement('div', { className: 'tv-page-title', style: { marginBottom: 4 } }, 'MaxFi Checklist'),
      React.createElement('div', { style: { fontSize: 12, color: 'var(--text4)' } },
        'Checkboxes are session-only and reset when you leave this tab.')
    ),
    React.createElement(ChecklistStrategyCard),
    React.createElement(ChecklistCard, {
      title: 'Crash badge fires (≥20% drop vs last completed daily close)',
      caption: 'The badge is display-only and only as fresh as the last valuation refresh - refresh before acting.',
      items: [
        'Cause check first. Protocol failure or exploit? Exit always - stop here.',
        'The badge shows in-range / out-of-range only. On an out-of-range crash badge, confirm below vs above in the Range cell before acting.',
        'Below range: the LP thesis is dead. Close the position. Re-decide spot exposure separately, as its own decision.',
        'In range: hold for crisis-rate fees - but set the second-leg exit line (the price at which you exit regardless) NOW, before doing anything else.',
      ],
    }),
    React.createElement(ChecklistCard, {
      title: 'Daily verdict flips CLOSE',
      items: [
        'Harvest claims first. A claim resets the accrual anchor and clears any rebalance or auto-split artifact.',
        'Pull the advisor once, fresh, and act within one sitting. Never act across stale snapshots.',
        'Artifact check: was the position recently rebalanced or auto-split? If in doubt, claim, then re-check the verdict.',
        'Bucket it. Run-rate below 1x decay (Bucket A): close. Between 1x and 2x (Bucket B): hold, and log it to the flagged-vs-resolved cohort that tunes the 2.0 multiplier.',
        'Before any batch of closes, spot-check one clear-tier CLOSE and one hair-trigger CLOSE against dashboard P/L.',
      ],
    }),
    React.createElement(ChecklistCard, {
      title: 'New-entry checkpoint',
      items: [
        'Entry gates are decision-grade only when token-daily data is current on the pool’s chain. Null gates mean uncleared, not blocked.',
        'Downtrend-gate limitation: both-windows-negative passes pumped-then-dumping tokens. Check the 30d number manually before trusting a pass.',
        'Tiny-liquidity pools inflate entry scores. Eyeball liquidity before sizing (display floor pending Phase E).',
        'Size the entry as a $25–50 probe. Full size only as scale-up on a measured probe.',
        'Sizing caps: [PLACEHOLDER — per-position and book caps to be filled in by Glenn]. Russian Doll layers count fully against caps; 2–3 layer cap.',
      ],
    })
  );
}

window.ChecklistScreen = ChecklistScreen;
