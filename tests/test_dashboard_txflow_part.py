"""Landing 38: the Dashboard shows the TxFlow part of the complete total
(static/dashboard.js), in step with portfolio_total.compose_total and the
portfolio_total_snapshots columns.

Reads the source files and calls the pure composer; no app or database.
"""
import os
import re
from datetime import datetime, timezone

import portfolio_total as pt
import src.engines.snapshot_service as ss
import src.storage.portfolio_db as portfolio_db

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _src():
    with open(os.path.join(ROOT, "static", "dashboard.js"), encoding="utf-8") as f:
        return f.read()


# No backslashes in this file (the landing's patch travels as a shell heredoc):
# plain string slicing and simple patterns instead of escapes.
def _between(src, head, tail):
    start = src.find(head)
    assert start >= 0, head + " not found"
    end = src.find(tail, start)
    assert end > start, head + " has no end"
    return src[start + len(head):end]


def _part_rows(src):
    body = _between(src, "const DASH_PART_ROWS = [", "];")
    return re.findall(r"'([a-z0-9_]+)', '([^']*)'", body)        # each ['key', 'Label'] pair


def _seam_versions(src):
    body = _between(src, "const DASH_SEAM_TEXT = {", "};")
    return {int(v) for v in re.findall(r"([0-9]+): *'", body)}


def _every_component_key():
    """The keys compose_total returns with every optional part present."""
    tx = {"fetched_at": None, "error": None, "wallets": []}
    r = pt.compose_total({}, [], set(), True, {}, {}, datetime(2026, 10, 14, tzinfo=timezone.utc), txflow_state=tx)
    return [c["key"] for c in r["components"]]


def test_txflow_row_follows_hyperliquid():
    rows = _part_rows(_src())
    keys = [k for k, _ in rows]
    assert ("txflow", "TxFlow") in rows
    assert keys.index("txflow") == keys.index("hyperliquid") + 1


def test_every_counted_part_has_a_dashboard_row_and_a_history_column():
    keys = {k for k, _ in _part_rows(_src())}
    comps = set(_every_component_key()) - {"zerion_staking"}          # shown as a NOT COUNTED extra
    assert comps <= keys
    assert {k + "_usd" for k in keys} <= set(portfolio_db.PORTFOLIO_TOTAL_SNAPSHOT_COLUMNS)
    assert set(ss._PORTFOLIO_TOTAL_PART_KEYS) == set(_every_component_key())


def test_current_definition_version_has_seam_text():
    versions = _seam_versions(_src())
    assert ss.PORTFOLIO_TOTAL_DEFINITION_VERSION in versions
    assert "3: 'TxFlow not counted'" in _src()


def test_txflow_loading_is_handled_like_hyperliquid():
    src = _src()
    r = pt.compose_total({}, [], set(), True, {}, {}, datetime(2026, 10, 14, tzinfo=timezone.utc),
                         txflow_state={"fetched_at": None, "error": None, "wallets": []})
    tx = next(c for c in r["components"] if c["key"] == "txflow")
    assert tx["warnings"] == ["TxFlow loading"]                         # the text the hero hides while pending
    assert "key === 'txflow' ? 'TxFlow loading' : 'Hyperliquid loading'" in src
    assert "(key === 'txflow' && txLoading)" in src
    assert "if ((!hl || hl.counted) && (!tx || tx.counted)) return;" in src      # the re-check waits for TxFlow too
    assert "TxFlow loading — not in the total yet." in src
    assert "else if (key === 'txflow') sub = _dashTxSub(c, subMoney);" in src
    assert "txflow: 30 * 60000" in src
