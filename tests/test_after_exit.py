"""After exit (Landing 7, HANDOFF_spot_perps_rebuild.md 18 and 19): for
every closed Hyperliquid / TxFlow perp trade, the noodle at the close
("exit_trend"), the best and worst prices while it was open ("excursion",
R on every read against the trade's stop) and had you held the plan
("held": the settled stop and the nearest planned take-profit, walked from
the open to 14 days after the exit; one candle touching both is "both";
"watching" until the horizon, re-checked at most hourly; recomputed when
the trade's stop or target changes).

Covers _hl_candles_range (paging, the bar containing the start, the end),
_trade_exit_intervals (finest candles whose history reaches the open),
_trade_excursion and _trade_first_touch (pure), _trade_exit_pass (parts,
reasons, cap, newest close first, idempotent, failures write nothing,
re-checks), the worker's "[trade-exit]" line, and the trades route's
"after_exit" (read-only, no address).

Real init_db() on a tmp_path SQLite file (portfolio_db.get_db_path
monkeypatched). Hyperliquid trades come from synthetic fills and order
records written straight into hl_fills / hl_orders; candles from a fake
candleSnapshot that, like Hyperliquid, serves only bars up to "now" and only
the most recent 5,000 per interval (made-up prices). The Hyperliquid
universe cache is set in memory. No network. Fake wallet addresses only,
built in code.

web_portfolio spawns a background scheduler on non-__main__ import; we
neutralize threading.Thread.start during import (established pattern).
"""
import json
import math
import threading
import time
from datetime import datetime, timezone

import pytest

_orig_start = threading.Thread.start
threading.Thread.start = lambda self, *a, **k: None
try:
    import web_portfolio as wp
finally:
    threading.Thread.start = _orig_start

import src.storage.portfolio_db as portfolio_db

W = "0x" + "e" * 40
MIN = 60000
HOUR = 3600000
DAY = 86400000
TF_MS = wp.TRADE_SNAPSHOT_TF_MS
OPEN = int(datetime(2026, 9, 27, 14, 5, tzinfo=timezone.utc).timestamp() * 1000)
CLOSE = OPEN + 6 * HOUR
LATER = CLOSE + 20 * DAY          # the 14-day horizon is over; only 15m candles reach the open
BASES = {"BTC": 100.0, "SOL": 100.0, "ETH": 4000.0}


def iso(ms):
    return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat()


class FakeHL:
    """candleSnapshot like Hyperliquid's: bars whose open time falls in
    [startTime, endTime] and is no later than `now`, only the most recent
    5,000 per interval, at most `cap` per answer (oldest first). Prices sit
    within 0.1% of the coin's base; `spikes` (start_ms, end_ms, "high" /
    "low", px) push the high / low of every bar overlapping that window."""

    def __init__(self, now, spikes=(), cap=5000, fail=(), missing=()):
        self.now = now
        self.spikes = list(spikes)
        self.cap = cap
        self.fail = set(fail)
        self.missing = set(missing)
        self.calls = []

    def bar(self, coin, t, ms):
        mid = BASES.get(coin, 50.0) * (1 + 0.0005 * math.sin(t / 1000 / 3600 / 5))
        hi, lo = mid * 1.001, mid * 0.999
        for a, b, kind, px in self.spikes:
            if t <= b and t + ms > a:
                if kind == "high":
                    hi = max(hi, px)
                else:
                    lo = min(lo, px)
        return {"t": t, "T": t + ms - 1, "s": coin, "o": str(mid), "h": str(hi), "l": str(lo), "c": str(mid),
                "v": "1", "n": 1}

    def __call__(self, payload):
        assert payload["type"] == "candleSnapshot", payload
        req = payload["req"]
        self.calls.append((req["coin"], req["interval"], req["startTime"], req["endTime"]))
        if req["coin"] in self.fail:
            raise ConnectionError("venue down")
        if req["interval"] in self.missing:
            return []
        ms = TF_MS[req["interval"]]
        oldest = self.now - self.now % ms - 4999 * ms
        t = req["startTime"] - req["startTime"] % ms
        if t < req["startTime"]:
            t += ms
        t = max(t, oldest)
        out = []
        while t <= req["endTime"] and t <= self.now and len(out) < self.cap:
            out.append(self.bar(req["coin"], t, ms))
            t += ms
        return out


def fill(coin, tid, t, side, sz, px, start, pnl="0"):
    return {"coin": coin, "tid": tid, "time": t, "side": side, "sz": sz, "px": px, "startPosition": start,
            "closedPnl": pnl, "fee": "0.01", "builderFee": "0", "dir": "x", "oid": tid, "hash": "0x0"}


def rec(oid, coin, side, px, placed, kind):
    """One historicalOrders placement record (Hyperliquid shape)."""
    return {"status": "open", "statusTimestamp": placed,
            "order": {"coin": coin, "side": side, "oid": oid, "timestamp": placed, "triggerPx": str(px),
                      "isTrigger": True, "reduceOnly": True, "isPositionTpsl": False, "orderType": kind,
                      "children": []}}


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = str(tmp_path / "portfolio.db")
    monkeypatch.setattr(portfolio_db, "get_db_path", lambda: path)
    portfolio_db.init_db()
    monkeypatch.delenv("TXFLOW_WALLETS", raising=False)
    monkeypatch.setattr(wp, "load_wallet_config", lambda: {W: {"label": "HL main"}})
    monkeypatch.setattr(wp, "_txflow_post", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no TxFlow call")))
    monkeypatch.setattr(wp, "_hl_accounts_cache_copy", lambda: {"fetched_at": None, "wallets": {}})
    monkeypatch.setattr(wp, "_TXFLOW_CACHE", {"fetched_at": None, "wallets": {}, "error": None})
    monkeypatch.setitem(wp._HL_UNIVERSE_CACHE, "crypto", {"BTC": "BTC", "SOL": "SOL", "ETH": "ETH"})
    monkeypatch.setitem(wp._HL_UNIVERSE_CACHE, "xyz", {})
    monkeypatch.setitem(wp._HL_UNIVERSE_CACHE, "fetched_at", time.time())
    conn = portfolio_db.get_connection()
    conn.execute("INSERT INTO hl_sync_state (wallet, first_seen_at, last_sync_at, last_ok_at) VALUES (?, ?, ?, ?)",
                 (W, "2026-09-01T00:00:00+00:00", "2026-10-03T00:00:00+00:00", "2026-10-03T00:00:00+00:00"))
    conn.commit()
    yield conn
    conn.close()


def use(monkeypatch, fake):
    monkeypatch.setattr(wp, "_hl_post", fake)
    return fake


def add_trade(db, coin, tid, open_ms=OPEN, close_ms=CLOSE, direction="long", entry="100", exit_px="101",
              stop="95", target="110", stop_at=None, target_at=None):
    """One perp trade (closed unless close_ms is None) with a stop order and a take-profit order placed at the open
    (None leaves either out)."""
    side_in, side_out = ("B", "A") if direction == "long" else ("A", "B")
    start_close = "1" if direction == "long" else "-1"
    fills = [fill(coin, tid, open_ms, side_in, "1", entry, "0")]
    if close_ms is not None:
        fills.append(fill(coin, tid + 1, close_ms, side_out, "1", exit_px, start_close, pnl="1"))
    for f in fills:
        db.execute("INSERT INTO hl_fills (wallet, tid, coin, time_ms, raw_json, fetched_at) VALUES (?, ?, ?, ?, ?, ?)",
                   (W, f["tid"], f["coin"], f["time"], json.dumps(f), "2026-10-03T00:00:00+00:00"))
    orders = []
    if stop is not None:
        orders.append(rec(tid * 10 + 1, coin, side_out, stop, stop_at or open_ms, "Stop Market"))
    if target is not None:
        orders.append(rec(tid * 10 + 2, coin, side_out, target, target_at or open_ms, "Take Profit Market"))
    for r in orders:
        db.execute("INSERT INTO hl_orders (wallet, oid, coin, status, status_ts, order_ts, raw_json, fetched_at) "
                   "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                   (W, r["order"]["oid"], coin, r["status"], r["statusTimestamp"], r["order"]["timestamp"],
                    json.dumps(r), "2026-10-03T00:00:00+00:00"))
    db.commit()


def by_symbol(db):
    trades, _ = wp._trades_build(db)
    return {t["symbol"]: t for t in trades}


def snap(db, trade_id):
    row = db.execute("SELECT scanner_snapshot_json FROM trade_annotations WHERE trade_id = ?", (trade_id,)).fetchone()
    return json.loads(row[0]) if row and row[0] else {}


def parts(db, symbol):
    return snap(db, by_symbol(db)[symbol]["trade_id"])


@pytest.fixture
def client(db, monkeypatch):
    monkeypatch.setattr(wp, "_maybe_kick_hl_trades_refresh", lambda now, force=False: False)
    monkeypatch.setattr(wp, "_maybe_kick_txflow_trades_refresh", lambda now, force=False: False)
    monkeypatch.setattr(wp, "_maybe_kick_hl_accounts_refresh", lambda now: False)
    monkeypatch.setattr(wp, "_maybe_kick_txflow_refresh", lambda now: False)
    monkeypatch.setattr(wp, "get_password_hash", lambda: "x")
    wp.app.config["TESTING"] = True
    c = wp.app.test_client()
    with c.session_transaction() as sess:
        sess["authenticated"] = True
    return c


# ── candles over a range ─────────────────────────────────────────────────

def test_range_pages_through_capped_answers(monkeypatch):
    fake = use(monkeypatch, FakeHL(now=OPEN + 3000 * MIN, cap=500))                 # inside the 5,000-candle 1m history
    out = wp._hl_candles_range("BTC", "1m", OPEN, OPEN + 1999 * MIN)
    start = OPEN - OPEN % MIN
    assert [b["time"] * 1000 for b in out] == [start + i * MIN for i in range(2000)]   # the bar containing the open first
    assert len(fake.calls) == 4 and [c[2] for c in fake.calls] == [start + i * 500 * MIN for i in range(4)]


def test_range_stops_at_now_and_rejects_an_odd_answer(monkeypatch):
    fake = use(monkeypatch, FakeHL(now=OPEN + 30 * MIN))
    out = wp._hl_candles_range("BTC", "15m", OPEN, OPEN + DAY)
    assert out[-1]["time"] * 1000 <= OPEN + 30 * MIN and len(fake.calls) == 2      # the second answer adds nothing
    monkeypatch.setattr(wp, "_hl_post", lambda payload: {"error": "x"})
    with pytest.raises(ValueError):
        wp._hl_candles_range("BTC", "15m", OPEN, OPEN + DAY)


def test_intervals_are_the_finest_whose_history_reaches_the_open():
    assert wp._trade_exit_intervals(OPEN, CLOSE, CLOSE + DAY) == ["1m", "5m", "15m"]
    assert wp._trade_exit_intervals(OPEN, CLOSE, CLOSE + 5 * DAY) == ["5m", "15m"]      # 1m history is ~3.4 days
    assert wp._trade_exit_intervals(OPEN, OPEN + 2 * DAY, OPEN + 2 * DAY + HOUR) == ["5m", "15m"]   # 2,880 1m bars
    assert wp._trade_exit_intervals(OPEN, CLOSE, CLOSE + 20 * DAY) == ["15m"]
    assert wp._trade_exit_intervals(OPEN, CLOSE, CLOSE + 60 * DAY) == []


# ── the pure walks ───────────────────────────────────────────────────────

def bars_of(*hl):
    return [{"time": i * 900, "open": 100, "close": 100, "high": h, "low": l, "volume": 1} for i, (h, l) in enumerate(hl)]


def test_excursion_long_and_short():
    b = bars_of((101, 99), (104, 98), (104, 97), (102, 97))
    assert wp._trade_excursion(b, "long") == {"best_px": 104, "best_ms": 900000, "worst_px": 97, "worst_ms": 1800000}
    assert wp._trade_excursion(b, "short") == {"best_px": 97, "best_ms": 1800000, "worst_px": 104, "worst_ms": 900000}
    assert wp._trade_excursion([], "long") is None


def test_first_touch_long_short_and_both():
    b = bars_of((101, 99), (111, 98), (102, 94))
    assert wp._trade_first_touch(b, "long", 95, 110)[0] == "target"
    assert wp._trade_first_touch(b, "long", 95, 112)[0] == "stop"
    assert wp._trade_first_touch(b, "long", 98.5, 110) == ("both", b[1])
    assert wp._trade_first_touch(b, "long", 90, 120) == (None, None)
    assert wp._trade_first_touch(b, "short", 112, 95)[0] == "target"                  # low 94 reaches a short's 95
    assert wp._trade_first_touch(b, "short", 111, 90)[0] == "stop"                    # high 111 reaches a short's 111


# ── the pass ─────────────────────────────────────────────────────────────

def test_target_after_the_exit(db, monkeypatch):
    add_trade(db, "BTC", 1)
    use(monkeypatch, FakeHL(now=LATER, spikes=[(CLOSE + 2 * DAY, CLOSE + 2 * DAY, "high", 111)]))
    stats = wp._trade_exit_pass(db, now_ms=LATER)
    assert stats == {"done": 1, "unavailable": 0, "rechecked": 0, "failed": 0, "pending": 0}
    p = parts(db, "BTC")
    held = p["held"]
    assert (held["outcome"], held["phase"], held["interval"], held["reason"]) == ("target", "after", "15m", None)
    assert held["at"] == iso(CLOSE + 2 * DAY - (CLOSE + 2 * DAY) % (15 * MIN))
    assert (held["entry_px"], held["stop_px"], held["target_px"]) == ("100", "95", "110")
    assert held["horizon_end"] == iso(CLOSE + 14 * DAY) and held["checked_at"] == iso(LATER)
    tr = p["exit_trend"]
    assert (tr["v"], tr["reason"], tr["market"], tr["price"], tr["as_of"]) == (1, None, "BTC", "101", iso(CLOSE))
    assert sorted(tr["timeframes"]) == sorted(wp.TRADE_SNAPSHOT_PERP_TFS) and tr["weekly_state"] == tr["timeframes"]["1w"]["state"]
    exc = p["excursion"]
    assert (exc["interval"], exc["reason"], exc["market"]) == ("15m", None, "BTC") and exc["bars"] == 25   # 6 h overlaps 25 bars
    assert 100 < float(exc["best_px"]) < 100.2 and 99.8 < float(exc["worst_px"]) < 100


def test_trend_at_exit_uses_candles_closed_before_the_close(db, monkeypatch):
    add_trade(db, "BTC", 1)
    use(monkeypatch, FakeHL(now=LATER))
    wp._trade_exit_pass(db, now_ms=LATER)
    view = wp._trade_open_trend("BTC", CLOSE, "101", 1, wp.TRADE_SNAPSHOT_PERP_TFS, wp._trade_snapshot_settings())
    assert parts(db, "BTC")["exit_trend"]["timeframes"] == json.loads(json.dumps(view))


def test_stop_crossed_during_the_trade(db, monkeypatch):
    add_trade(db, "BTC", 1)
    use(monkeypatch, FakeHL(now=LATER, spikes=[(OPEN + 2 * HOUR, OPEN + 2 * HOUR, "low", 94.5),
                                               (CLOSE + DAY, CLOSE + DAY, "high", 111)]))
    wp._trade_exit_pass(db, now_ms=LATER)
    held = parts(db, "BTC")["held"]
    assert (held["outcome"], held["phase"], held["interval"]) == ("stop", "during", "15m")
    assert held["at"] == iso(OPEN + 2 * HOUR - (OPEN + 2 * HOUR) % (15 * MIN))
    assert float(parts(db, "BTC")["excursion"]["worst_px"]) == 94.5


def test_one_candle_touching_both_is_unclear(db, monkeypatch):
    t = CLOSE + 3 * DAY
    add_trade(db, "BTC", 1)
    use(monkeypatch, FakeHL(now=LATER, spikes=[(t, t, "high", 111), (t + 5 * MIN, t + 5 * MIN, "low", 94)]))
    wp._trade_exit_pass(db, now_ms=LATER)
    held = parts(db, "BTC")["held"]
    assert (held["outcome"], held["phase"], held["at"]) == ("both", "after", iso(t - t % (15 * MIN)))


def test_neither_within_the_horizon(db, monkeypatch):
    add_trade(db, "BTC", 1)
    use(monkeypatch, FakeHL(now=LATER, spikes=[(CLOSE + 15 * DAY, CLOSE + 15 * DAY, "high", 111)]))   # past the horizon
    wp._trade_exit_pass(db, now_ms=LATER)
    held = parts(db, "BTC")["held"]
    assert (held["outcome"], held["phase"], held["at"]) == ("neither", None, None)


def test_watching_is_rechecked_at_most_hourly(db, monkeypatch):
    now = CLOSE + 2 * DAY
    add_trade(db, "BTC", 1)
    fake = use(monkeypatch, FakeHL(now=now))
    assert wp._trade_exit_pass(db, now_ms=now)["done"] == 1
    assert parts(db, "BTC")["held"]["outcome"] == "watching"
    calls = len(fake.calls)
    fake.now = now + 30 * MIN
    assert wp._trade_exit_pass(db, now_ms=now + 30 * MIN) == {"done": 0, "unavailable": 0, "rechecked": 0,
                                                                "failed": 0, "pending": 0}
    assert len(fake.calls) == calls                                                   # too soon: no call
    fake.now = now + 2 * HOUR
    fake.spikes.append((now + HOUR, now + HOUR, "high", 112))
    assert wp._trade_exit_pass(db, now_ms=now + 2 * HOUR)["rechecked"] == 1
    assert len(fake.calls) == calls + 1                                               # one call: the after-exit candles
    held = parts(db, "BTC")["held"]
    assert (held["outcome"], held["phase"], held["checked_at"]) == ("target", "after", iso(now + 2 * HOUR))
    assert wp._trade_exit_pass(db, now_ms=now + 5 * HOUR)["rechecked"] == 0           # final now


def test_recent_trades_use_one_minute_candles(db, monkeypatch):
    now = CLOSE + DAY
    add_trade(db, "BTC", 1)
    spike = OPEN + 2 * HOUR + 7 * MIN
    use(monkeypatch, FakeHL(now=now, spikes=[(spike, spike, "high", 104), (OPEN + HOUR, OPEN + HOUR, "low", 97)]))
    wp._trade_exit_pass(db, now_ms=now)
    exc = parts(db, "BTC")["excursion"]
    assert (exc["interval"], exc["best_px"], exc["best_at"], exc["worst_px"]) == ("1m", "104", iso(spike), "97")
    assert exc["bars"] == 361


def test_falls_back_to_a_coarser_interval(db, monkeypatch):
    now = CLOSE + DAY
    add_trade(db, "BTC", 1)
    use(monkeypatch, FakeHL(now=now, missing={"1m"}))
    wp._trade_exit_pass(db, now_ms=now)
    assert parts(db, "BTC")["excursion"]["interval"] == "5m"


def test_short_trade(db, monkeypatch):
    add_trade(db, "SOL", 1, direction="short", entry="100", exit_px="99", stop="105", target="90")
    use(monkeypatch, FakeHL(now=LATER, spikes=[(OPEN + HOUR, OPEN + HOUR, "low", 96),
                                               (CLOSE + DAY, CLOSE + DAY, "low", 89.5)]))
    wp._trade_exit_pass(db, now_ms=LATER)
    p = parts(db, "SOL")
    assert (p["held"]["outcome"], p["held"]["phase"]) == ("target", "after")
    assert p["excursion"]["best_px"] == "96" and 100 < float(p["excursion"]["worst_px"]) < 100.2


def test_no_target_or_no_stop_is_not_tested(db, monkeypatch):
    add_trade(db, "BTC", 1, target=None)
    add_trade(db, "SOL", 3, stop=None)
    fake = use(monkeypatch, FakeHL(now=LATER))
    assert wp._trade_exit_pass(db, now_ms=LATER)["done"] == 2
    btc, sol = parts(db, "BTC"), parts(db, "SOL")
    assert (btc["held"]["reason"], btc["held"]["outcome"], btc["held"]["target_px"]) == ("no_target", None, None)
    assert (sol["held"]["reason"], sol["held"]["stop_px"]) == ("no_stop", None)
    assert btc["excursion"]["best_px"] and sol["excursion"]["best_px"] and btc["exit_trend"]["timeframes"]
    after = [c for c in fake.calls if c[1] == "15m" and c[2] >= CLOSE - CLOSE % (15 * MIN)]
    assert after == []                                                                # nothing to walk after the exit


def test_a_changed_stop_recomputes_the_verdict(db, monkeypatch):
    add_trade(db, "BTC", 1)
    fake = use(monkeypatch, FakeHL(now=LATER, spikes=[(CLOSE + DAY, CLOSE + DAY, "low", 95.5),
                                                      (CLOSE + 2 * DAY, CLOSE + 2 * DAY, "high", 111)]))
    wp._trade_exit_pass(db, now_ms=LATER)
    assert parts(db, "BTC")["held"]["outcome"] == "target"
    trade_id = by_symbol(db)["BTC"]["trade_id"]
    db.execute("UPDATE trade_annotations SET stop_px = '96', stop_source = 'manual', stop_set_at = ? WHERE trade_id = ?",
               (iso(LATER), trade_id))
    db.commit()
    trend_before = parts(db, "BTC")["exit_trend"]
    calls = len(fake.calls)
    assert wp._trade_exit_pass(db, now_ms=LATER + HOUR)["done"] == 1
    p = parts(db, "BTC")
    assert (p["held"]["outcome"], p["held"]["stop_px"]) == ("stop", "96")
    assert p["exit_trend"] == trend_before                                            # only the verdict is redone
    assert {c[1] for c in fake.calls[calls:]} == {"15m"} and len(fake.calls) - calls == 2


def test_failure_writes_nothing_and_the_next_pass_retries(db, monkeypatch):
    add_trade(db, "BTC", 1)
    use(monkeypatch, FakeHL(now=LATER, fail={"BTC"}))
    assert wp._trade_exit_pass(db, now_ms=LATER)["failed"] == 1
    assert parts(db, "BTC") == {}
    use(monkeypatch, FakeHL(now=LATER))
    assert wp._trade_exit_pass(db, now_ms=LATER)["done"] == 1
    assert parts(db, "BTC")["held"]["outcome"] == "neither"


def test_cap_newest_close_first_and_idempotent(db, monkeypatch):
    add_trade(db, "BTC", 1)
    add_trade(db, "SOL", 3, open_ms=OPEN + DAY, close_ms=CLOSE + DAY)
    fake = use(monkeypatch, FakeHL(now=LATER + DAY))
    stats = wp._trade_exit_pass(db, cap=1, now_ms=LATER + DAY)
    assert stats["done"] == 1 and stats["pending"] == 1
    assert parts(db, "SOL") and parts(db, "BTC") == {}                                # the newer close first
    wp._trade_exit_pass(db, cap=1, now_ms=LATER + DAY)
    calls = len(fake.calls)
    before = [tuple(r) for r in db.execute("SELECT * FROM trade_annotations ORDER BY trade_id")]
    assert wp._trade_exit_pass(db, now_ms=LATER + 2 * DAY) == {"done": 0, "unavailable": 0, "rechecked": 0,
                                                                 "failed": 0, "pending": 0}
    assert len(fake.calls) == calls
    assert [tuple(r) for r in db.execute("SELECT * FROM trade_annotations ORDER BY trade_id")] == before


def test_only_closed_synced_perps_are_covered(db, monkeypatch):
    add_trade(db, "BTC", 1, close_ms=None)                                            # open
    db.execute("INSERT INTO spot_trade_log (ticker, direction, source, entry_price, stop_price, qty, entered_at, "
               "exit_price, exited_at, followed_rules, market) VALUES ('SOL', 'long', 'manual', 100, 95, 1, ?, 105, ?, 1, 'perp')",
               (iso(OPEN), iso(CLOSE)))
    db.execute("INSERT INTO spot_transactions (trade_date, symbol, side, units, price_usd, total_usd, chain, "
               "contract_address) VALUES ('2026-09-20', 'BTC', 'buy', 1, 100, 100, 'base', ?)", ("0x" + "1" * 40,))
    db.commit()
    fake = use(monkeypatch, FakeHL(now=LATER))
    assert wp._trade_exit_pass(db, now_ms=LATER) == {"done": 0, "unavailable": 0, "rechecked": 0, "failed": 0,
                                                      "pending": 0}
    assert fake.calls == [] and db.execute("SELECT COUNT(*) FROM trade_annotations").fetchone()[0] == 0
    trades, _ = wp._trades_build(db)
    assert all(t["after_exit"] is None for t in trades)


def test_not_on_hyperliquid_and_a_different_token(db, monkeypatch):
    add_trade(db, "NOTHL", 1)
    add_trade(db, "ETH", 3)                                                           # entry $100; Hyperliquid's ETH is ~$4,000
    fake = use(monkeypatch, FakeHL(now=LATER))
    stats = wp._trade_exit_pass(db, now_ms=LATER)
    assert stats == {"done": 0, "unavailable": 2, "rechecked": 0, "failed": 0, "pending": 0}
    nothl, eth = parts(db, "NOTHL"), parts(db, "ETH")
    assert (nothl["exit_trend"]["reason"], nothl["excursion"]["reason"], nothl["held"]["reason"]) == ("not_on_hyperliquid",) * 3
    assert (eth["exit_trend"]["reason"], eth["excursion"]["reason"], eth["held"]["reason"]) == ("price_mismatch",) * 3
    assert eth["excursion"]["best_px"] is None and eth["held"]["outcome"] is None
    assert not [c for c in fake.calls if c[0] == "NOTHL"]
    calls = len(fake.calls)
    assert wp._trade_exit_pass(db, now_ms=LATER + HOUR)["unavailable"] == 0 and len(fake.calls) == calls   # kept


def test_the_open_snapshot_and_user_fields_are_kept(db, monkeypatch):
    add_trade(db, "BTC", 1)
    trade_id = by_symbol(db)["BTC"]["trade_id"]
    opened = {"trend": {"v": 1, "market": "BTC"}, "leverage": {"value": "5", "type": "cross", "seen_at": iso(OPEN)}}
    db.execute("INSERT INTO trade_annotations (trade_id, market, notes, followed_rules, scanner_snapshot_json, "
               "scanner_captured_at, created_at, updated_at) VALUES (?, 'perp', 'my plan', 1, ?, 'cap', 'c', 'u')",
               (trade_id, json.dumps(opened)))
    db.commit()
    use(monkeypatch, FakeHL(now=LATER))
    wp._trade_exit_pass(db, now_ms=LATER)
    row = dict(db.execute("SELECT * FROM trade_annotations WHERE trade_id = ?", (trade_id,)).fetchone())
    assert (row["notes"], row["followed_rules"], row["scanner_captured_at"], row["created_at"], row["updated_at"]) == (
        "my plan", 1, "cap", "c", "u")
    stored = json.loads(row["scanner_snapshot_json"])
    assert stored["trend"] == opened["trend"] and stored["leverage"] == opened["leverage"]
    assert {"exit_trend", "excursion", "held"} <= set(stored)


def test_universe_unavailable_computes_nothing(db, monkeypatch):
    add_trade(db, "BTC", 1)
    monkeypatch.setitem(wp._HL_UNIVERSE_CACHE, "crypto", None)
    monkeypatch.setattr(wp, "_hl_refresh_universes", lambda force=False: None)
    fake = use(monkeypatch, FakeHL(now=LATER))
    assert wp._trade_exit_pass(db, now_ms=LATER)["pending"] == 1
    assert fake.calls == [] and parts(db, "BTC") == {}


# ── the route ────────────────────────────────────────────────────────────

def test_route_after_exit_with_r_and_read_only(db, client, monkeypatch):
    add_trade(db, "BTC", 1)
    add_trade(db, "SOL", 3, close_ms=None)
    use(monkeypatch, FakeHL(now=LATER, spikes=[(OPEN + HOUR, OPEN + HOUR, "high", 104),
                                               (OPEN + 2 * HOUR, OPEN + 2 * HOUR, "low", 97),
                                               (CLOSE + 2 * DAY, CLOSE + 2 * DAY, "high", 111)]))
    wp._trade_exit_pass(db, now_ms=LATER)
    calls = len(wp._hl_post.calls)
    before = [tuple(r) for r in db.execute("SELECT * FROM trade_annotations ORDER BY trade_id")]
    r = client.get('/api/trading/trades')
    text = r.get_data(as_text=True)
    assert W not in text and W[2:] not in text
    by = {t["symbol"]: t for t in r.get_json()["trades"]}
    ae = by["BTC"]["after_exit"]
    assert ae["trend"]["as_of"] == iso(CLOSE) and ae["trend"]["reason"] is None
    exc = ae["excursion"]
    assert (exc["best_px"], exc["best_r"], exc["worst_px"], exc["worst_r"], exc["interval"]) == (
        "104", "0.800000", "97", "-0.600000", "15m")
    held = ae["held"]
    assert (held["outcome"], held["phase"], held["plan_r"], held["stale"]) == ("target", "after", "2.000000", False)
    assert by["SOL"]["after_exit"] is None                                            # still open
    client.get('/api/trading/trades')
    assert len(wp._hl_post.calls) == calls                                            # no candle fetch on a read
    assert [tuple(r) for r in db.execute("SELECT * FROM trade_annotations ORDER BY trade_id")] == before


def test_route_marks_a_changed_plan_stale_and_r_follows_the_stop(db, client, monkeypatch):
    add_trade(db, "BTC", 1)
    use(monkeypatch, FakeHL(now=LATER, spikes=[(OPEN + HOUR, OPEN + HOUR, "high", 104)]))
    wp._trade_exit_pass(db, now_ms=LATER)
    trade_id = by_symbol(db)["BTC"]["trade_id"]
    db.execute("UPDATE trade_annotations SET stop_px = '98', stop_source = 'manual', stop_set_at = ? WHERE trade_id = ?",
               (iso(LATER), trade_id))
    db.commit()
    ae = {t["symbol"]: t for t in client.get('/api/trading/trades').get_json()["trades"]}["BTC"]["after_exit"]
    assert ae["held"]["stale"] is True and ae["held"]["stop_px"] == "95"
    assert ae["excursion"]["best_r"] == "2.000000"                                    # (104 - 100) / (100 - 98)


def test_route_before_the_first_pass(db, client):
    add_trade(db, "BTC", 1)
    ae = {t["symbol"]: t for t in client.get('/api/trading/trades').get_json()["trades"]}["BTC"]["after_exit"]
    assert ae == {"trend": None, "excursion": None, "held": None}


# ── the worker ───────────────────────────────────────────────────────────

def test_worker_runs_the_exit_pass_after_the_open_pass(db, monkeypatch, capsys):
    now = int(time.time() * 1000)
    add_trade(db, "BTC", 1, open_ms=now - 3 * DAY, close_ms=now - 3 * DAY + 6 * HOUR)
    use(monkeypatch, FakeHL(now=now + HOUR))
    stats = wp._trade_snapshot_worker()
    out = capsys.readouterr().out
    assert stats["trend"] == 1
    assert "[trade-snapshot] leverage+=0 targets+=0 trend+=1 unavailable+=0 failed=0 pending=0" in out
    assert "[trade-exit] done+=1 unavailable+=0 rechecked=0 failed=0 pending=0" in out
    p = parts(db, "BTC")
    assert {"trend", "exit_trend", "excursion", "held"} <= set(p) and p["held"]["outcome"] == "watching"


def test_worker_survives_an_exit_pass_exception(db, monkeypatch, capsys):
    monkeypatch.setattr(wp, "_trade_exit_pass", lambda conn: 1 / 0)
    use(monkeypatch, FakeHL(now=LATER))
    stats = wp._trade_snapshot_worker()
    out = capsys.readouterr().out
    assert stats is not None and "[trade-snapshot] " in out
    assert "[trade-exit] pass exception ZeroDivisionError" in out and "[trade-exit] done" not in out
    assert wp._TRADE_SNAPSHOT_LOCK.acquire(blocking=False)
    wp._TRADE_SNAPSHOT_LOCK.release()


def test_no_wallet_address_in_stored_parts(db, monkeypatch):
    add_trade(db, "BTC", 1)
    use(monkeypatch, FakeHL(now=LATER))
    wp._trade_exit_pass(db, now_ms=LATER)
    for (raw,) in db.execute("SELECT scanner_snapshot_json FROM trade_annotations"):
        assert W not in raw and W[2:] not in raw
