"""BTC context in the trade-open snapshot (Landing 69): _trade_open_btc (BTC's
noodle band and point of interest on the 7 perp timeframes from bars that
closed before the open, no lookahead; the POI path equals the scan's, whatever
the placeholder forming bar holds), _trade_btc_pass (perp trades with a trend
part only, newest first, capped, versioned, failures write nothing, other
parts kept), the worker wiring and log line, and the part staying out of the
trades route's open_snapshot (record only).

Same style as test_trade_open_snapshot.py: real init_db() on a tmp_path
SQLite file, synthetic fills, a fake candleSnapshot with made-up prices, no
network, fake wallet addresses only.
"""
import json
import random
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
from src.engines.noodle_bands import compute_noodle_state

W = "0x" + "d" * 40
TF_MS = wp.TRADE_SNAPSHOT_TF_MS
ETH_OPEN = int(datetime(2026, 10, 2, 9, 37, tzinfo=timezone.utc).timestamp() * 1000)
BTC_OPEN = int(datetime(2026, 9, 27, 14, 5, tzinfo=timezone.utc).timestamp() * 1000)
BTC_CLOSE = BTC_OPEN + 20 * 3600000
SOL_OPEN = int(datetime(2026, 9, 30, 6, 12, tzinfo=timezone.utc).timestamp() * 1000)
SETTINGS = {'fast': 12, 'medium': 21, 'slow': 25, 'atr_length': 20, 'band_multiplier': 0.01, 'use_atr': True}
CURRENT = {}


def price_at(t_s, coin="BTC"):
    import math
    base = {"ETH": 4000.0, "BTC": 110000.0, "SOL": 200.0}.get(coin, 50.0)
    return base * (1 + 0.08 * math.sin(t_s / 86400 / 9) + 0.02 * math.sin(t_s / 3600 / 7) + t_s / 1e12)


class FakeHL:
    """candleSnapshot: every bar whose open time falls in [startTime,
    endTime], the still-forming one included. `after` triples every bar that
    opens at or after that time (proves no lookahead); `fail` coins raise;
    `empty` coins answer []."""

    def __init__(self, fail=(), after=None, empty=()):
        self.calls = []
        self.fail = set(fail)
        self.empty = set(empty)
        self.after = after

    def __call__(self, payload):
        assert payload["type"] == "candleSnapshot", payload
        req = payload["req"]
        self.calls.append((req["coin"], req["interval"], req["startTime"], req["endTime"]))
        if req["coin"] in self.fail:
            raise ConnectionError("venue down")
        if req["coin"] in self.empty:
            return []
        ms = TF_MS[req["interval"]]
        t = req["startTime"] - req["startTime"] % ms
        if t < req["startTime"]:
            t += ms
        out = []
        while t <= req["endTime"]:
            c = price_at(t / 1000, req["coin"])
            if self.after is not None and t >= self.after:
                c *= 3
            out.append({"t": t, "T": t + ms - 1, "s": req["coin"], "i": req["interval"], "o": str(c),
                        "h": str(c * 1.004), "l": str(c * 0.996), "c": str(c), "v": "1", "n": 1})
            t += ms
        return out


def fill(coin, tid, t, side, sz, px, start, pnl="0"):
    return {"coin": coin, "tid": tid, "time": t, "side": side, "sz": sz, "px": px, "startPosition": start,
            "closedPnl": pnl, "fee": "0.1", "builderFee": "0", "dir": "x", "oid": tid, "hash": "0x0"}


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
    monkeypatch.setitem(wp._HL_UNIVERSE_CACHE, "crypto", {"ETH": "ETH", "BTC": "BTC", "SOL": "SOL", "KBONK": "kBONK"})
    monkeypatch.setitem(wp._HL_UNIVERSE_CACHE, "xyz", {})
    monkeypatch.setitem(wp._HL_UNIVERSE_CACHE, "fetched_at", time.time())
    fake = FakeHL()
    monkeypatch.setattr(wp, "_hl_post", fake)
    conn = portfolio_db.get_connection()
    CURRENT["fake"] = fake
    yield conn
    conn.close()


def seed(db):
    """HL: open ETH long (Oct 2), open SOL long (Sep 30), closed BTC long
    (Sep 27-28). Spot: BONK (Trading book). One manual perp trade."""
    db.execute("INSERT INTO hl_sync_state (wallet, first_seen_at, last_sync_at, last_ok_at) VALUES (?, ?, ?, ?)",
               (W, "2026-09-01T00:00:00+00:00", "2026-10-03T00:00:00+00:00", "2026-10-03T00:00:00+00:00"))
    for f in (fill("ETH", 1, ETH_OPEN, "B", "1", "4100", "0"),
              fill("SOL", 4, SOL_OPEN, "B", "1", "200", "0"),
              fill("BTC", 2, BTC_OPEN, "B", "0.01", "111000", "0"),
              fill("BTC", 3, BTC_CLOSE, "A", "0.01", "112000", "0.01", pnl="10")):
        db.execute("INSERT INTO hl_fills (wallet, tid, coin, time_ms, raw_json, fetched_at) VALUES (?, ?, ?, ?, ?, ?)",
                   (W, f["tid"], f["coin"], f["time"], json.dumps(f), "2026-10-03T00:00:00+00:00"))
    db.execute("INSERT INTO spot_transactions (trade_date, symbol, side, units, price_usd, total_usd, chain, "
               "contract_address) VALUES ('2026-09-20', 'BONK', 'buy', 100, 2.5, 2.5, 'base', ?)", ("0x" + "1" * 40,))
    db.execute("INSERT INTO spot_trade_log (ticker, direction, source, entry_price, stop_price, qty, entered_at, market) "
               "VALUES ('SOL', 'long', 'manual', 100, 95, 1, '2026-09-25T10:00:00+00:00', 'perp')")
    db.commit()


def trades_by(db):
    trades, _ = wp._trades_build(db)
    return {(t["source"], t["symbol"]): t for t in trades}


def snap_of(db, tid):
    row = db.execute("SELECT scanner_snapshot_json FROM trade_annotations WHERE trade_id = ?", (tid,)).fetchone()
    return json.loads(row[0]) if row and row[0] else {}


def with_trend_parts(db):
    seed(db)
    wp._trade_snapshot_pass(db, cap=20)
    CURRENT["fake"].calls.clear()


# -- _trade_open_btc ---------------------------------------------------------

def test_every_perp_timeframe_matches_the_engine_on_closed_bars(db):
    out = wp._trade_open_btc(ETH_OPEN, SETTINGS)
    assert list(out["timeframes"]) == list(wp.TRADE_SNAPSHOT_PERP_TFS)
    for tf in ("15m", "30m", "1h", "12h", "1d"):
        closed = wp._hl_candles_before("BTC", tf, ETH_OPEN, wp.TRADE_SNAPSHOT_DEPTH[tf])
        r = compute_noodle_state(closed, **SETTINGS)
        v = out["timeframes"][tf]
        assert (v["state"], v["bars"]) == (r["state"], len(closed))
        assert v["upper_band"] == wp._snapshot_num(r["upper_band"]) and v["lower_band"] == wp._snapshot_num(r["lower_band"])
        assert v["last_close"] == wp._snapshot_num(closed[-1]["close"])
    assert out["timeframes"]["1w"]["bars"] > 90 and out["timeframes"]["4h"]["bars"] > 300


def test_weekly_and_4h_drop_the_bucket_still_forming(db):
    out = wp._trade_open_btc(ETH_OPEN, SETTINGS)["timeframes"]
    dailies = wp._hl_candles_before("BTC", "1d", ETH_OPEN, wp.DOC_TREND_CANDLE_LIMITS["1d"])
    allweeks = wp._weekly_from_dailies(dailies, limit=10 ** 6)
    weeks = [w for w in allweeks if w["time"] + 7 * 86400 <= ETH_OPEN // 1000]
    assert len(allweeks) == len(weeks) + 1                                  # Oct 2 is mid-week: one forming week exists
    assert out["1w"]["bars"] == len(weeks) and out["1w"]["state"] == compute_noodle_state(weeks, **SETTINGS)["state"]
    h4 = [b for b in wp._h4_from_h1(wp._hl_candles_before("BTC", "1h", ETH_OPEN, 1440), limit=10 ** 6)
          if b["time"] + 14400 <= ETH_OPEN // 1000]
    assert out["4h"]["bars"] == len(h4) and out["4h"]["last_close"] == wp._snapshot_num(h4[-1]["close"])


def test_price_is_the_newest_closed_bar_and_its_time(db):
    out = wp._trade_open_btc(ETH_OPEN, SETTINGS)
    last15 = wp._hl_candles_before("BTC", "15m", ETH_OPEN, 1)[0]
    assert out["price"] == wp._snapshot_num(last15["close"])
    assert out["price_ts"] == datetime.fromtimestamp(last15["time"] + 900, timezone.utc).isoformat()
    assert out["price_ts"] == "2026-10-02T09:30:00+00:00"            # the 09:15 bar closed 09:30; the 09:30 bar is forming at 09:37


def test_numbers_are_plain_strings_and_poi_only_on_the_scan_timeframes(db):
    out = wp._trade_open_btc(ETH_OPEN, SETTINGS)
    for tf, v in out["timeframes"].items():
        for k in ("upper_band", "lower_band", "last_close"):
            assert v[k] is None or isinstance(v[k], str)
        if tf not in wp.TREND_POI_TIMEFRAMES:
            assert v["poi"] is None and v["respect_dir"] is None
    pois = [v["poi"] for v in out["timeframes"].values() if v["poi"]]
    assert pois, "the fake series should give at least one POI"
    for p in pois:
        assert p["type"] in ("OB", "FVG") and float(p["top"]) >= float(p["bottom"]) and isinstance(p["at_band"], bool)


def test_no_lookahead(db, monkeypatch):
    first = wp._trade_open_btc(ETH_OPEN, SETTINGS)
    monkeypatch.setattr(wp, "_hl_post", FakeHL(after=ETH_OPEN - ETH_OPEN % 900000))
    assert wp._trade_open_btc(ETH_OPEN, SETTINGS) == first


@pytest.mark.parametrize("open_ms", [ETH_OPEN, BTC_OPEN, BTC_CLOSE, SOL_OPEN])
def test_pois_equal_the_scans_whatever_the_forming_bar_holds(db, open_ms):
    """The scan hands _trend_pois the still-forming bar last; at the open there
    is none, so a placeholder stands in. The result must be the scan's."""
    out = wp._trade_open_btc(open_ms, SETTINGS)
    ps = wp._scanner_settings()
    checked = 0
    for tf in wp.TREND_POI_TIMEFRAMES:
        if tf == "4h":
            bars = [b for b in wp._h4_from_h1(wp._hl_candles_before("BTC", "1h", open_ms, 1440), limit=10 ** 6)
                    if b["time"] + 14400 <= open_ms // 1000]
        else:
            bars = wp._hl_candles_before("BTC", tf, open_ms, wp.TRADE_SNAPSHOT_DEPTH.get(tf, 300))
        r = compute_noodle_state(bars, **SETTINGS)
        rt = wp.compute_respected_trend(bars, slow=SETTINGS["slow"], atr_length=SETTINGS["atr_length"],
                                        band_multiplier=SETTINGS["band_multiplier"], use_atr=SETTINGS["use_atr"])
        assert out["timeframes"][tf]["respect_dir"] == rt.get("dir")
        last = bars[-1]["close"]
        for f in ({"open": last * 1.01, "high": last * 1.08, "low": last * 0.9, "close": last * 1.05, "volume": 7.0},
                  {"open": last, "high": last * 1.001, "low": last * 0.7, "close": last * 0.72, "volume": 1.0}):
            forming = dict(f, time=bars[-1]["time"] + TF_MS[tf] // 1000)
            want = wp._trend_pois(bars + [forming], rt.get("dir"), rt.get("since"), r["upper_band"], r["lower_band"],
                                  settings=ps) if rt.get("dir") else None
            got = out["timeframes"][tf]["poi"]
            if want is None or not want["type"]:
                assert got is None
            else:
                assert got == {"type": want["type"], "top": wp._snapshot_num(want["top"]),
                               "bottom": wp._snapshot_num(want["bottom"]), "ts": want["ts"],
                               "at_band": want["at_band"], "count": want["count"]}
                checked += 1
    assert checked >= 2


def _series(seed_, n=400, step=3600):
    r = random.Random(seed_)
    p, drift, out = 100.0, 0.002, []
    for i in range(n):
        if i % 80 == 0:
            drift = r.choice([-0.003, 0.003, 0.0005])
        o = p
        p = p * (1 + drift + r.gauss(0, 0.01))
        out.append({"open": o, "high": max(o, p) * (1 + abs(r.gauss(0, 0.004))),
                    "low": min(o, p) * (1 - abs(r.gauss(0, 0.004))), "close": p,
                    "volume": 1000 + r.random() * 500, "time": 1700000000 + i * step})
    return out


def test_trend_pois_ignores_the_final_bar_on_random_series():
    """The placeholder is only sound if the detectors never read the final bar."""
    ps = wp._scanner_settings()
    seen = with_poi = 0
    for s in range(60):
        c = _series(s)
        r = compute_noodle_state(c, fast=12, medium=21, slow=28, atr_length=14, band_multiplier=0.011875, use_atr=True)
        rt = wp.compute_respected_trend(c, slow=28, atr_length=14, band_multiplier=0.011875, use_atr=True)
        if not rt.get("dir"):
            continue
        last = c[-1]["close"]
        outs = [wp._trend_pois(c + [dict(f, time=c[-1]["time"] + 3600)], rt["dir"], rt.get("since"),
                               r["upper_band"], r["lower_band"], settings=ps)
                for f in ({"open": last, "high": last, "low": last, "close": last, "volume": 0.0},
                          {"open": last, "high": last * 1.05, "low": last * 0.9, "close": last * 1.04, "volume": 9.0},
                          {"open": last, "high": last * 1.01, "low": last * 0.8, "close": last * 0.82, "volume": 3.0})]
        seen += 1
        with_poi += bool(outs[0]["type"])
        assert outs[0] == outs[1] == outs[2], s
    assert seen >= 30 and with_poi >= 20


def test_only_the_scan_timeframes_get_a_respected_trend_or_poi_on_trending_bars(db, monkeypatch):
    """Strongly trending bars on every interval: 15m / 30m / 1w must still carry no POI."""
    def trending(coin, interval, end_ms, limit):
        step = TF_MS[interval] // 1000
        last = end_ms // 1000 // step * step - step
        base = _series(11, n=limit, step=step)
        shift = last - base[-1]["time"]
        return [dict(b, time=b["time"] + shift) for b in base]
    monkeypatch.setattr(wp, "_hl_candles_before", trending)
    out = wp._trade_open_btc(ETH_OPEN, SETTINGS)
    assert any(out["timeframes"][tf]["respect_dir"] for tf in wp.TREND_POI_TIMEFRAMES)
    for tf in ("15m", "30m", "1w"):
        assert out["timeframes"][tf]["respect_dir"] is None and out["timeframes"][tf]["poi"] is None


def test_a_timeframe_whose_poi_fails_is_marked_and_the_rest_survive(db, monkeypatch, capsys):
    real = wp._trend_pois

    def boom(candles, *a, **k):
        raise RuntimeError("x")
    monkeypatch.setattr(wp, "_trend_pois", boom)
    out = wp._trade_open_btc(ETH_OPEN, SETTINGS)
    failed = [tf for tf, v in out["timeframes"].items() if v.get("poi_failed")]
    assert failed and all(out["timeframes"][tf]["poi"] is None for tf in failed)
    assert all(out["timeframes"][tf]["state"] for tf in wp.TRADE_SNAPSHOT_PERP_TFS)
    monkeypatch.setattr(wp, "_trend_pois", real)
    assert not any(v.get("poi_failed") for v in wp._trade_open_btc(ETH_OPEN, SETTINGS)["timeframes"].values())


def test_no_btc_candles_at_all_raises(db, monkeypatch):
    monkeypatch.setattr(wp, "_hl_post", FakeHL(empty=("BTC",)))
    with pytest.raises(ValueError):
        wp._trade_open_btc(ETH_OPEN, SETTINGS)


# -- the pass ----------------------------------------------------------------

def test_pass_covers_perps_with_a_trend_part_only(db):
    seed(db)
    assert wp._trade_btc_pass(db) == {"done": 0, "unavailable": 0, "failed": 0, "pending": 0}   # no trend parts yet
    assert not CURRENT["fake"].calls
    wp._trade_snapshot_pass(db, cap=20)
    CURRENT["fake"].calls.clear()
    stats = wp._trade_btc_pass(db, cap=10)
    assert stats == {"done": 3, "unavailable": 0, "failed": 0, "pending": 0}
    t = trades_by(db)
    for key in (("hyperliquid", "ETH"), ("hyperliquid", "SOL"), ("hyperliquid", "BTC")):
        part = snap_of(db, t[key]["trade_id"])["btc_context"]
        assert part["v"] == 1 and part["coin"] == "BTC" and part["reason"] is None
        assert sorted(part["timeframes"]) == sorted(wp.TRADE_SNAPSHOT_PERP_TFS)
        assert part["as_of"] == wp._trades_dt(t[key]["opened_at"]).isoformat()
    spot = snap_of(db, t[("spot_tx", "BONK")]["trade_id"])
    assert "btc_context" not in spot                                  # spot: not covered
    assert {c[0] for c in CURRENT["fake"].calls} == {"BTC"}
    assert len(CURRENT["fake"].calls) == 15                           # five calls per trade


def test_each_trade_gets_btc_as_of_its_own_open(db):
    with_trend_parts(db)
    wp._trade_btc_pass(db, cap=10)
    t = trades_by(db)
    eth = snap_of(db, t[("hyperliquid", "ETH")]["trade_id"])["btc_context"]
    sol = snap_of(db, t[("hyperliquid", "SOL")]["trade_id"])["btc_context"]
    assert eth["as_of"] == datetime.fromtimestamp(ETH_OPEN / 1000, timezone.utc).isoformat()
    assert sol["as_of"] == datetime.fromtimestamp(SOL_OPEN / 1000, timezone.utc).isoformat()
    assert eth["price_ts"] == "2026-10-02T09:30:00+00:00" and sol["price_ts"] == "2026-09-30T06:00:00+00:00"
    assert eth["price"] != sol["price"]
    assert eth["timeframes"] == wp._trade_open_btc(ETH_OPEN, wp._trade_snapshot_settings())["timeframes"]


def test_the_other_parts_are_kept_and_updated_at_is_untouched(db):
    with_trend_parts(db)
    t = trades_by(db)[("hyperliquid", "ETH")]
    before = snap_of(db, t["trade_id"])
    row = db.execute("SELECT updated_at, scanner_captured_at FROM trade_annotations WHERE trade_id = ?", (t["trade_id"],)).fetchone()
    wp._trade_btc_pass(db, cap=10)
    after = snap_of(db, t["trade_id"])
    assert {k: v for k, v in after.items() if k != "btc_context"} == before
    assert db.execute("SELECT updated_at, scanner_captured_at FROM trade_annotations WHERE trade_id = ?",
                      (t["trade_id"],)).fetchone() == row


def test_capped_newest_first_and_idempotent(db):
    with_trend_parts(db)
    stats = wp._trade_btc_pass(db, cap=1)
    assert stats == {"done": 1, "unavailable": 0, "failed": 0, "pending": 2}
    t = trades_by(db)
    done = [k for k in (("hyperliquid", "ETH"), ("hyperliquid", "SOL"), ("hyperliquid", "BTC"))
            if "btc_context" in snap_of(db, t[k]["trade_id"])]
    assert done == [("hyperliquid", "ETH")]                           # newest opened first
    assert wp._trade_btc_pass(db, cap=0)["pending"] == 2
    wp._trade_btc_pass(db)
    CURRENT["fake"].calls.clear()
    assert wp._trade_btc_pass(db) == {"done": 0, "unavailable": 0, "failed": 0, "pending": 0}
    assert not CURRENT["fake"].calls
    assert wp.TRADE_SNAPSHOT_BTC_CAP == 3


def test_an_old_version_is_recomputed(db, monkeypatch):
    with_trend_parts(db)
    wp._trade_btc_pass(db)
    monkeypatch.setattr(wp, "TRADE_SNAPSHOT_BTC_VERSION", 2)
    assert wp._trade_btc_pass(db)["done"] == 3
    t = trades_by(db)[("hyperliquid", "ETH")]
    assert snap_of(db, t["trade_id"])["btc_context"]["v"] == 2


def test_a_fetch_error_writes_nothing_and_retries(db, monkeypatch):
    with_trend_parts(db)
    monkeypatch.setattr(wp, "_hl_post", FakeHL(fail=("BTC",)))
    stats = wp._trade_btc_pass(db)
    assert stats == {"done": 0, "unavailable": 0, "failed": 3, "pending": 0}
    assert all("btc_context" not in snap_of(db, t["trade_id"]) for t in trades_by(db).values())
    monkeypatch.setattr(wp, "_hl_post", FakeHL())
    assert wp._trade_btc_pass(db)["done"] == 3


def test_one_failing_trade_does_not_stop_the_others(db, monkeypatch):
    with_trend_parts(db)
    real = wp._trade_open_btc
    state = {"n": 0}

    def flaky(as_of_ms, *a, **k):
        state["n"] += 1
        if state["n"] == 1:
            raise ConnectionError("x")
        return real(as_of_ms, *a, **k)
    monkeypatch.setattr(wp, "_trade_open_btc", flaky)
    assert wp._trade_btc_pass(db) == {"done": 2, "unavailable": 0, "failed": 1, "pending": 0}


def test_a_trade_with_no_open_time_gets_a_reason_and_no_fetch(db, monkeypatch):
    with_trend_parts(db)
    monkeypatch.setattr(wp, "_trades_dt", lambda v: None)
    stats = wp._trade_btc_pass(db)
    assert stats == {"done": 0, "unavailable": 3, "failed": 0, "pending": 0}
    part = snap_of(db, trades_by(db)[("hyperliquid", "ETH")]["trade_id"])["btc_context"]
    assert part["reason"] == "no_open_time" and part["timeframes"] == {} and part["as_of"] is None
    assert not CURRENT["fake"].calls


def test_the_open_time_is_the_trades_own_not_the_trend_parts(db):
    with_trend_parts(db)
    t = trades_by(db)[("hyperliquid", "ETH")]
    snap = snap_of(db, t["trade_id"])
    snap["trend"]["as_of"] = "2020-01-01T00:00:00+00:00"
    wp._trade_snapshot_write(db, t, snap, None, "2026-10-03T00:00:00+00:00")
    wp._trade_btc_pass(db)
    assert snap_of(db, t["trade_id"])["btc_context"]["as_of"] == datetime.fromtimestamp(ETH_OPEN / 1000, timezone.utc).isoformat()


def test_a_btc_trade_gets_its_own_coin_as_btc_context(db):
    with_trend_parts(db)
    wp._trade_btc_pass(db)
    part = snap_of(db, trades_by(db)[("hyperliquid", "BTC")]["trade_id"])["btc_context"]
    assert part["coin"] == "BTC" and part["reason"] is None


def test_the_scope_is_hyperliquid_and_txflow_perps(db):
    assert wp._trade_btc_scope({"source": "hyperliquid"}) and wp._trade_btc_scope({"source": "txflow"})
    assert not wp._trade_btc_scope({"source": "spot_tx", "book": "trading"})
    assert not wp._trade_btc_scope({"source": "manual"})


def test_the_safe_wrapper_never_raises(db, monkeypatch, capsys):
    monkeypatch.setattr(wp, "_trade_btc_pass", lambda conn: (_ for _ in ()).throw(RuntimeError("x")))
    assert wp._trade_btc_pass_safe(db) is None
    assert "[trade-btc] pass exception RuntimeError" in capsys.readouterr().out


# -- the worker and the public shape -----------------------------------------

def test_worker_runs_the_btc_pass_and_logs_it(db, capsys):
    seed(db)
    assert wp._trade_snapshot_worker() is not None
    out = capsys.readouterr().out
    assert "[trade-btc] done+=3 unavailable+=0 failed=0 pending=0" in out
    assert snap_of(db, trades_by(db)[("hyperliquid", "ETH")]["trade_id"])["btc_context"]["v"] == 1


def test_a_quiet_btc_pass_logs_nothing(db, capsys):
    seed(db)
    wp._trade_snapshot_worker()
    capsys.readouterr()
    wp._trade_snapshot_worker()
    assert "[trade-btc]" not in capsys.readouterr().out


def test_a_btc_pass_exception_never_stops_the_worker(db, monkeypatch, capsys):
    seed(db)
    monkeypatch.setattr(wp, "_trade_btc_pass", lambda conn: 1 / 0)
    assert wp._trade_snapshot_worker() is not None
    assert "[trade-btc] pass exception ZeroDivisionError" in capsys.readouterr().out


def test_the_part_stays_out_of_the_public_snapshot(db):
    with_trend_parts(db)
    wp._trade_btc_pass(db)
    trades, annotations = wp._trades_build(db)
    t = next(x for x in trades if x["symbol"] == "ETH")
    assert "btc_context" in snap_of(db, t["trade_id"])
    pub = wp._trade_snapshot_public(t, annotations.get(t["trade_id"]))
    assert "btc_context" not in json.dumps(pub)
