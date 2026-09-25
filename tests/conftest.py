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
