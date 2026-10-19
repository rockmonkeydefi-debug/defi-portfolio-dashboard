"""Shared test setup.

Importing web_portfolio spawns a background scheduler on non-__main__ import.
We neutralize threading.Thread.start for the duration of that import (the
established pattern) so no thread starts during the test session, then restore
it. Test modules can then `import web_portfolio` normally (Python caches the
module, so this import-safe load wins).

Repo root is put on sys.path so `import web_portfolio` and
`from src.engines... import ...` resolve regardless of the invocation cwd.
"""
import os
import sys
import threading

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

_orig_start = threading.Thread.start
threading.Thread.start = lambda self, *a, **k: None
try:
    import web_portfolio  # noqa: F401  (import-safe warm load; scheduler suppressed)
finally:
    threading.Thread.start = _orig_start


import pytest  # noqa: E402  (after the import-safe warm load above)


@pytest.fixture(autouse=True)
def _no_ledger_auto_backfill(monkeypatch):
    """Ledger-as-source commit 2: GET /api/maxfi/advisor now starts a REAL
    ledger backfill thread when a chain is due. Every existing advisor-route
    test meets both triggers - its open positions are not in
    maxfi_ledger_positions, and a clean checkout has no last-run file (data/
    is gitignored) - so without this guard each of them would start a real
    backfill (network, DB writes).
    The spawner becomes a no-op and the last-kick map starts empty in every
    test, so one test's cooldown never leaks into the next. Tests that need
    to see a spawn install their own recorder over this no-op."""
    monkeypatch.setattr(web_portfolio, "_spawn_ledger_backfill_thread", lambda chains: None)
    monkeypatch.setattr(web_portfolio, "_LEDGER_AUTO_BACKFILL_LAST_KICK", {})
    # Ledger-as-source commit 3: the same guard for the token-daily auto-refresh.
    monkeypatch.setattr(web_portfolio, "_spawn_token_daily_refresh_thread", lambda chains: None)
    monkeypatch.setattr(web_portfolio, "_TOKEN_DAILY_AUTO_LAST_KICK", {})
    # Total portfolio value (commit B): GET /api/portfolio/total starts a REAL
    # Hyperliquid accounts refresh thread when its cache is cold - the same
    # guard: a no-op spawner and fresh cache/in-flight/last-kick state per test.
    monkeypatch.setattr(web_portfolio, "_spawn_hl_accounts_refresh_thread", lambda wallets: None)
    monkeypatch.setattr(web_portfolio, "_HL_ACCOUNTS_CACHE", {"fetched_at": None, "wallets": {}, "error": None})
    monkeypatch.setattr(web_portfolio, "_HL_ACCOUNTS_IN_FLIGHT", False)
    monkeypatch.setattr(web_portfolio, "_HL_ACCOUNTS_LAST_KICK", {"at": None})
    # DexFi bonds (level-shift step 3): the same guard for the DexFi bonds
    # cache. A snapshot run freshens it INLINE (_dexfi_bonds_state_for_snapshot),
    # so the fetch itself is also stubbed to a clean failure - no test reaches
    # DexFi's real API. tests/test_dexfi_bonds_cache.py restores the real
    # fetch and fakes requests.get instead.
    # The no-op spawner also clears the in-flight flag (as a refresh that ended
    # at once would); otherwise a later snapshot freshen in the same test would
    # wait HL_SNAPSHOT_WAIT_SECONDS for a thread that never ran.
    monkeypatch.setattr(web_portfolio, "_spawn_dexfi_bonds_refresh_thread",
                        lambda wallets: setattr(web_portfolio, "_DEXFI_BONDS_IN_FLIGHT", False))
    monkeypatch.setattr(web_portfolio, "_dexfi_fetch_bonds", lambda wallets: {
        "info": None, "info_error": "DexFi disabled in tests", "wallets": {}, "checked": [], "errors": {}})
    monkeypatch.setattr(web_portfolio, "_DEXFI_BONDS_CACHE",
                        {"fetched_at": None, "info": None, "wallets": {}, "error": None})
    monkeypatch.setattr(web_portfolio, "_DEXFI_BONDS_IN_FLIGHT", False)
    monkeypatch.setattr(web_portfolio, "_DEXFI_BONDS_LAST_KICK", {"at": None})
    # TxFlow in the total (Landing 38): GET /api/portfolio/total kicks a TxFlow
    # refresh and a snapshot run freshens the TxFlow cache INLINE
    # (_txflow_state_for_snapshot) - the same guard: no TXFLOW_WALLETS from the
    # environment or a .env, a no-op spawner that clears the in-flight flag,
    # TxFlow's info-API call stubbed to a clean failure (tests that read TxFlow
    # stub _txflow_post or _txflow_fetch_states themselves), and fresh
    # cache/in-flight/last-kick state per test.
    monkeypatch.delenv("TXFLOW_WALLETS", raising=False)
    monkeypatch.setattr(web_portfolio, "_spawn_txflow_refresh_thread",
                        lambda wallets: setattr(web_portfolio, "_TXFLOW_IN_FLIGHT", False))

    def _txflow_disabled(body):
        raise RuntimeError("TxFlow disabled in tests")
    monkeypatch.setattr(web_portfolio, "_txflow_post", _txflow_disabled)
    monkeypatch.setattr(web_portfolio, "_TXFLOW_CACHE", {"fetched_at": None, "wallets": {}, "error": None})
    monkeypatch.setattr(web_portfolio, "_TXFLOW_IN_FLIGHT", False)
    monkeypatch.setattr(web_portfolio, "_TXFLOW_LAST_KICK", {"at": None})
    # TxFlow in the Trends scan (Landing 53): the scan's TxFlow phase calls
    # _txflow_post (blocked above, so it ends at once with one log line), paces
    # its calls, and keeps a match table in memory and in a JSON file beside
    # scanner_settings.json. No pause between calls or before a retry, and a
    # fresh table per test that never reads a stray file (file_loaded True);
    # tests/test_noodle_txflow_scan.py sets its own state.
    monkeypatch.setattr(web_portfolio, "TXFLOW_SCAN_PACE_SECONDS", 0.0)
    monkeypatch.setattr(web_portfolio, "TXFLOW_SCAN_RETRY_SLEEP_SECONDS", 0.0)
    monkeypatch.setattr(web_portfolio, "_TXFLOW_MARKETS",
                        {"tokens": None, "tokens_at": 0.0, "match": None, "file_loaded": True})
    monkeypatch.setattr(web_portfolio, "_TXFLOW_PACE", {"next": 0.0})
