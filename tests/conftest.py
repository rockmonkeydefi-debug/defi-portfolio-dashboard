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
