// app.jsx — mounts the design canvas with all 4 screens × 3 variations
const ROOT = ReactDOM.createRoot(document.getElementById('root'));

// Screen frame sizes — 16:10-ish desktop tool
const W = 880, H = 560;

function Sheet() {
  return (
    <DesignCanvas>
      <DCSection
        id="portfolio"
        title="Portfolio · token holdings + DeFi positions (new tab)"
        subtitle="Multi-wallet / multi-chain portfolio. Two sub-views shown as separate frames; segmented switcher drawn in each."
      >
        <DCArtboard id="pf-tokens" label="Portfolio · Token Holdings" width={1400} height={1410}>
          <PortfolioHF view="tokens" />
        </DCArtboard>
        <DCArtboard id="pf-defi" label="Portfolio · DeFi Positions" width={1400} height={3790}>
          <PortfolioHF view="defi" />
        </DCArtboard>
        <DCArtboard id="pf-lend-edit"    label="Portfolio · Lend/Borrow · Edit modal"    width={1400} height={3790}><LendEditScreen/></DCArtboard>
        <DCArtboard id="pf-lend-history" label="Portfolio · Lend/Borrow · History modal" width={1400} height={3790}><LendHistoryScreen/></DCArtboard>
        <DCArtboard id="pf-lend-archive" label="Portfolio · Lend/Borrow · Archive confirm" width={1400} height={3790}><LendArchiveScreen/></DCArtboard>
        <DCArtboard id="pf-lp-opt"   label="Portfolio · LP Tools · LP Optimizer"    width={1400} height={820}><LPToolsHF tool="optimizer"/></DCArtboard>
        <DCArtboard id="pf-lp-il"    label="Portfolio · LP Tools · IL Calculator"    width={1400} height={1060}><LPToolsHF tool="ilcalc"/></DCArtboard>
        <DCArtboard id="pf-lp-hedge" label="Portfolio · LP Tools · Hedge Calculator" width={1400} height={1200}><LPToolsHF tool="hedge"/></DCArtboard>
      </DCSection>

      <DCSection
        id="spotpnl"
        title="Spot P&L · live holdings · trade history · transactions (new tab)"
        subtitle="Three sub-views shown as separate frames; segmented switcher drawn in each. FIFO cost basis."
      >
        <DCArtboard id="sp-live" label="Spot P&L · Live Holdings" width={1400} height={1040}>
          <SpotPnlHF view="live" />
        </DCArtboard>
        <DCArtboard id="sp-history" label="Spot P&L · Trade History" width={1400} height={840}>
          <SpotPnlHF view="history" />
        </DCArtboard>
        <DCArtboard id="sp-tx" label="Spot P&L · Transactions" width={1400} height={1060}>
          <SpotPnlHF view="tx" />
        </DCArtboard>
        <DCArtboard id="sp-hidden" label="Spot P&L · Live Holdings · values hidden" width={1400} height={1040}>
          <SpotPnlHF view="live" hidden={true} />
        </DCArtboard>
        <DCArtboard id="sp-tx-form" label="Spot P&L · Transactions · add form open" width={1400} height={1220}>
          <SpotPnlHF view="tx" showForm={true} />
        </DCArtboard>
      </DCSection>

      <DCSection
        id="settings-new"
        title="Settings · Display · Wallets · API Config · AI Config · Spot P&L Token Config"
        subtitle="One artboard per section — sidebar nav is interactive (click to switch)."
      >
        <DCArtboard id="st-display"   label="Settings · Display Preferences" width={1280} height={820}><SettingsNewHF defaultSection="display"/></DCArtboard>
        <DCArtboard id="st-wallets"   label="Settings · Wallets"             width={1280} height={820}><SettingsNewHF defaultSection="wallets"/></DCArtboard>
        <DCArtboard id="st-integrations" label="Settings · Integrations (RPC + AI keys + other APIs)" width={1280} height={1100}><SettingsNewHF defaultSection="integrations"/></DCArtboard>
        <DCArtboard id="st-ai"        label="Settings · AI Config"          width={1280} height={820}><SettingsNewHF defaultSection="ai"/></DCArtboard>
        <DCArtboard id="st-docs"       label="Settings · Document Uploads"   width={1280} height={980}><SettingsNewHF defaultSection="docs"/></DCArtboard>
        <DCArtboard id="st-pnlconfig" label="Settings · Spot P&L Config"     width={1280} height={900}><SettingsNewHF defaultSection="pnlconfig"/></DCArtboard>
        <DCArtboard id="st-backup"     label="Settings · Backup &amp; Security"  width={1280} height={820}><SettingsNewHF defaultSection="backup"/></DCArtboard>
        <DCArtboard id="st-messaging"  label="Settings · Messaging"              width={1280} height={820}><SettingsNewHF defaultSection="messaging"/></DCArtboard>
      </DCSection>

      <DCSection
        id="performance"
        title="Performance · portfolio value over time · active positions · closed LP + hedges"
        subtitle="Range picker (24H/7D/30D/1Y/All/Custom) · dual-chart layout · matches reference screenshot"
      >
        <DCArtboard id="perf-main" label="Performance" width={1440} height={920}>
          <PerformanceHF />
        </DCArtboard>
      </DCSection>

      <DCSection
        id="marketdata"
        title="Market Data · BTC/ETH prices · Fear&Greed · Macro Cycle Dashboard · LP Pools · Lend/Borrow"
        subtitle="Scrollable single artboard — all market data sections stacked"
      >
        <DCArtboard id="mkt-main" label="Market Data" width={1440} height={2840}>
          <MarketDataHF />
        </DCArtboard>
      </DCSection>

      <DCSection
        id="aibrief"
        title="AI Brief · recommendations-first redesign · market regime · risk alerts · housekeeping"
        subtitle="Concise, action-oriented layout. Recommendations promoted to top."
      >
        <DCArtboard id="ai-brief" label="AI Brief" width={1440} height={1480}>
          <AIBriefHF />
        </DCArtboard>
      </DCSection>

      <DCSection
        id="hifi"
        title="Hi-fi · Blue theme (ocean-navy · gold accent)"
        subtitle="1A · Dashboard, 2A · Quiz, 3A · Transcripts, 4A · Scanner — converted from lo-fi winners to match 5C"
      >
        <DCArtboard id="hf-dash" label="1A · Dashboard · portfolio hub · screener · trades · AI brief · performance" width={1280} height={1200}>
          <DashHF />
        </DCArtboard>
        <DCArtboard id="hf-quiz" label="2A · Quiz" width={1280} height={820}>
          <QuizHF />
        </DCArtboard>
        <DCArtboard id="hf-quiz-complete" label="2A · Quiz complete · score + mastery delta + recap" width={1280} height={1500}>
          <QuizCompleteHF />
        </DCArtboard>
        <DCArtboard id="hf-trans" label="3A · Transcript admin" width={1280} height={760}>
          <TransHF />
        </DCArtboard>
        <DCArtboard id="hf-ingest" label="Ingest · extraction review — what the app pulls from a real summary doc (eps 1–4)" width={1280} height={3000}>
          <IngestReviewHF />
        </DCArtboard>
        <DCArtboard id="hf-scan" label="4A · Setup Scanner" width={1280} height={900}>
          <ScanHF />
        </DCArtboard>
        <DCArtboard id="hf-journal" label="Journal · history (new — depends on 5C save flow)" width={1400} height={820}>
          <JournalHF />
        </DCArtboard>
        <DCArtboard id="hf-journal-entry" label="Journal · single trade entry · full page (multi-screenshot, infinite scroll)" width={1280} height={4200}>
          <JournalEntryFull />
        </DCArtboard>
        <DCArtboard id="hf-reports" label="Reports · analytics (lifetime trade data + breakdowns)" width={1500} height={1900}>
          <ReportsHF />
        </DCArtboard>
        <DCArtboard id="hf-concepts" label="Concept library (browse every concept · mastery · sources · trades)" width={1400} height={1300}>
          <ConceptsHF />
        </DCArtboard>
        <DCArtboard id="hf-settings" label="Trading Settings · schedule · watchlist · validator · quiz · concepts · transcripts · account · data" width={1400} height={1500}>
          <SettingsHF />
        </DCArtboard>
        <DCArtboard id="hf-states" label="States · empty / loading / error mocks across screens" width={1500} height={1400}>
          <StatesHF />
        </DCArtboard>
        <DCArtboard id="hf-screen-map" label="Screen map · IA flow diagram (handoff reference)" width={1500} height={1100}>
          <ScreenMapHF />
        </DCArtboard>
      </DCSection>

      <DCSection
        id="validator"
        title="Screen 5 · Trade Setup Validator (dark hi-fi)"
        subtitle="Adaptive step-by-step flow · path changes based on answers · culminates in a pre-trade reasoning record"
      >
        <DCArtboard id="val-a" label="A · Mid-flow (step 4 / 7) — at the branching question" width={1100} height={700}>
          <ValidatorA />
        </DCArtboard>
        <DCArtboard id="val-b" label="B · Adaptive branch — path just adapted (step 5)" width={1100} height={700}>
          <ValidatorB />
        </DCArtboard>
        <DCArtboard id="val-c" label="C · Summary — pre-trade reasoning record (screenshot-ready) · WINNER" width={1100} height={900}>
          <ValidatorC />
        </DCArtboard>
        <DCArtboard id="val-d" label="D · C-style question screen (hybrid: A/B question + C polish)" width={1100} height={780}>
          <ValidatorD />
        </DCArtboard>
      </DCSection>

      <DCSection
        id="dashboard"
        title="Lo-fi explorations · Screen 1 · Dashboard"
        subtitle="Winner: A · Quiz-Hero (promoted to hi-fi above)"
      >
        <DCArtboard id="dash-a" label="A · Quiz-Hero · sidebar nav" width={W} height={H}>
          <DashA />
        </DCArtboard>
        <DCArtboard id="dash-b" label="B · Split · quiz + scanner 50/50" width={W} height={H}>
          <DashB />
        </DCArtboard>
        <DCArtboard id="dash-c" label="C · Feed · timeline + weak ring" width={W} height={H}>
          <DashC />
        </DCArtboard>
      </DCSection>

      <DCSection
        id="quiz"
        title="Lo-fi explorations · Screen 2 · Quiz"
        subtitle="Winner: A · Chart-Forward (promoted to hi-fi above)"
      >
        <DCArtboard id="quiz-a" label="A · Chart-Forward · vertical stack" width={W} height={720}>
          <QuizA />
        </DCArtboard>
        <DCArtboard id="quiz-b" label="B · Split-Pane · chart ↔ question" width={W} height={H}>
          <QuizB />
        </DCArtboard>
        <DCArtboard id="quiz-c" label="C · Stepper · minimal centered" width={W} height={H}>
          <QuizC />
        </DCArtboard>
      </DCSection>

      <DCSection
        id="transcripts"
        title="Lo-fi explorations · Screen 3 · Transcript admin"
        subtitle="Winner: A · Single form (promoted to hi-fi above)"
      >
        <DCArtboard id="trans-a" label="A · Single form · meta + textarea" width={W} height={H}>
          <TransA />
        </DCArtboard>
        <DCArtboard id="trans-b" label="B · Two-column · list + editor" width={W} height={H}>
          <TransB />
        </DCArtboard>
        <DCArtboard id="trans-c" label="C · Centered form + compact table" width={W} height={H}>
          <TransC />
        </DCArtboard>
      </DCSection>

      <DCSection
        id="scanner"
        title="Lo-fi explorations · Screen 4 · Setup Scanner"
        subtitle="Winner: A · Table + drawer (promoted to hi-fi above)"
      >
        <DCArtboard id="scan-a" label="A · Dense table + drawer" width={W} height={H}>
          <ScanA />
        </DCArtboard>
        <DCArtboard id="scan-b" label="B · Card grid · 3 cols" width={W} height={H}>
          <ScanB />
        </DCArtboard>
        <DCArtboard id="scan-c" label="C · Ranked list + big detail" width={W} height={H}>
          <ScanC />
        </DCArtboard>
      </DCSection>
    </DesignCanvas>
  );
}

ROOT.render(<Sheet />);
