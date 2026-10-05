"""Advisor v1, Landing 8c-1: guard for the perps page's Hide values masking.

The page rewrites R2 evidence wholesale when Hide values is on and shows every
other rule's evidence, reason and definition as sent. That is only safe while
dollar amounts and "% of capital" appear in R2 evidence and nowhere else in the
evaluator's output. This test fails if a rule change breaks that assumption, so
the page's masking has to be revisited first. Made-up trades; no network.
"""
import re
from datetime import datetime, timezone

from src.engines import perp_rules as pr

MIN = 60000
HOUR = 3600000
DAY = 86400000
T0 = int(datetime(2026, 9, 20, 10, 0, tzinfo=timezone.utc).timestamp() * 1000)
MONEY = re.compile(r"\$|of capital", re.I)


def _iso(ms):
    return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat()


def _trade(**kw):
    tfs = {tf: {"position": "above", "state": "IGNORED"} for tf in ("15m", "30m", "1h", "4h", "12h", "1d", "1w")}
    t = {"trade_id": "t1", "market": "perp", "source": "hyperliquid", "status": "closed", "direction": "long",
         "symbol": "ETH", "opened_at": _iso(T0), "closed_at": _iso(T0 + DAY), "avg_entry": "100",
         "size_peak": "10", "stop": {"px": "95", "source": "hl_order", "set_at": _iso(T0 + 2 * MIN)},
         "planned_target": None, "leverage": None, "net_pnl": "10",
         "annotation": {"followed_rules": None, "notes": None, "deviation_note": None},
         "open_snapshot": {"trend": {"v": 1, "reason": None, "timeframes": tfs}, "leverage": None}}
    t.update(kw)
    return t


def _variants():
    big = _trade(trade_id="big", size_peak="5000")                      # 1R far over 1% of capital
    ok = _trade(trade_id="ok", size_peak="10")                          # within limits
    tiny = _trade(trade_id="tiny", size_peak="0.001")                   # negligible 1R
    nostop = _trade(trade_id="nostop", stop=None)
    live = _trade(trade_id="live", status="open", closed_at=None, size_peak="400")
    planned = _trade(trade_id="planned", planned_target={"prices": ["130"]},
                     annotation={"followed_rules": True, "notes": "took profit early", "deviation_note": None})
    early = _trade(trade_id="early", opened_at=_iso(datetime(2026, 9, 1, tzinfo=timezone.utc).timestamp() * 1000))
    return [big, ok, tiny, nostop, live, planned, early]


def test_dollars_and_capital_percent_only_in_r2_evidence():
    out = pr.evaluate_all(_variants(), {}, now_ms=T0 + 2 * DAY)
    seen_r2_money = False
    for tid, entry in out["trades"].items():
        for r in entry["rules"]:
            for field in ("evidence", "reason"):
                text = r.get(field) or ""
                if r["rule"] == "R2" and field == "evidence":
                    seen_r2_money = seen_r2_money or bool(MONEY.search(text))
                    continue
                assert not MONEY.search(text), (tid, r["rule"], field, text)
            for note in r.get("notes") or []:
                assert not MONEY.search(str(note)), (tid, r["rule"], "notes", note)
    assert seen_r2_money  # the guard is looking at the one place money is expected


def test_definitions_and_tally_carry_no_dollar_amounts():
    # Definitions state the limits as percentages ("1% of capital"), which is
    # fine; a dollar sign is not. The page shows definitions even when hidden.
    out = pr.evaluate_all(_variants(), {}, now_ms=T0 + 2 * DAY)
    for rule in out["rules"]:
        assert "$" not in rule["definition"], rule["id"]
        assert "$" not in rule["title"], rule["id"]
    assert "$" not in out["note"]
    assert "$" not in repr(out["tally"])
