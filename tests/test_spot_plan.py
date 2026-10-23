"""Landing 59 (Oct 23): the spot plan and Doc's band states at a spot trade's open.

Glenn ruled ("A, A, A", Oct 23 04:13-04:17 PDT; replaces the Oct 16 "D1-D10 as
checklist fields"): a short plan per spot trade for tracking, discipline and
thinking it through. Basis (own chart setup / analyst call / other; generic,
no names); a setup from his list for an own chart setup, a one-line thesis for an analyst
call; for every trade the exit plan, an optional invalidation price,
conviction and horizon. No affordability tick. Open Trading-book spot trades
without a plan show "plan missing" (a reminder only). Doc's Daily and Weekly
band states are saved automatically at a spot trade's open (Hyperliquid-listed
tokens), with the two-close rule.

Covers doc_trend.compute_band_state, the spot_plans table and route, the
trades route's plan / plan_missing / doc_bands_at_open, and _trade_doc_pass
(the doc_bands part of the trade-open snapshot). Real init_db() on a tmp_path
SQLite file; Hyperliquid candles from a fake candleSnapshot (made-up prices).
No network. Fake addresses only, built in code.

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
from src.engines import doc_trend
from src.engines.noodle_bands import ema

TF_MS = wp.TRADE_SNAPSHOT_TF_MS
CURRENT = {}


# -- compute_band_state ----------------------------------------------------

def _bars(closes, step=3600):
    return [{'time': 1_000_000 + i * step, 'open': c, 'high': c, 'low': c, 'close': c, 'volume': 1.0}
            for i, c in enumerate(closes)]


def _edges(closes, fast, slow):
    ef, es = ema(closes, fast), ema(closes, slow)
    return [(max(a, b), min(a, b)) if a is not None and b is not None else (None, None) for a, b in zip(ef, es)]


def _inside(prefix, fast=10, slow=20):
    """A next close that lands inside the zone: the midpoint of the last
    bar's two EMAs (each new EMA moves toward it but stays on its side)."""
    up, lo = _edges(prefix, fast, slow)[-1]
    return (up + lo) / 2


def _below(prefix, f=0.9, fast=10, slow=20):
    return _edges(prefix, fast, slow)[-1][1] * f        # under both EMAs, so under the new lower edge


def _above(prefix, f=1.1, fast=10, slow=20):
    return _edges(prefix, fast, slow)[-1][0] * f


def _state(closes):
    return doc_trend.compute_band_state(_bars(closes), fast=10, slow=20)


def test_band_state_needs_slow_bars():
    out = doc_trend.compute_band_state(_bars([100.0] * 19), fast=10, slow=20)
    assert out['state'] is None and out['position'] is None and out['upper'] is None and out['bars'] == 19


def test_two_closes_beyond_the_edge_set_the_state_and_one_does_not():
    base = [100.0 + i * 0.5 for i in range(60)]                      # a steady climb: closes above the zone
    assert _state(base)['state'] == 'BULLISH'
    one = base + [_below(base)]
    one.append(_inside(one))                                          # one close below, then back inside: no loss
    out = _state(one)
    assert out['state'] == 'BULLISH' and out['position'] == 'inside'
    two = base + [_below(base)]
    two.append(_below(two))                                           # two in a row below: lost on the second
    out = _state(two)
    edges = _edges(two, 10, 20)
    assert two[-2] < edges[-2][1] and two[-1] < edges[-1][1]
    assert out['state'] == 'BEARISH' and out['position'] == 'below'
    assert out['state_ts'] == _bars(two)[-1]['time']


def test_a_close_inside_resets_the_count():
    base = [100.0 + i * 0.5 for i in range(60)]
    closes = base + [_below(base)]
    closes.append(_inside(closes))
    closes.append(_below(closes))
    assert _state(closes)['state'] == 'BULLISH'                       # below, inside, below: never two in a row
    closes.append(_below(closes))
    assert _state(closes)['state'] == 'BEARISH'


def test_state_is_none_until_the_first_two_close_run():
    flat = [100.0] * 30                                               # both EMAs at 100: zero-width zone
    out = _state(flat + [101.0])
    assert out['state'] is None and out['position'] == 'above'        # a single close above
    out = _state(flat + [101.0, 101.5])
    assert out['state'] == 'BULLISH' and out['state_ts'] == _bars(flat + [101.0, 101.5])[-1]['time']


def test_band_state_is_the_mirror_for_a_downtrend():
    base = [200.0 - i * 0.5 for i in range(60)]
    assert _state(base)['state'] == 'BEARISH'
    one = base + [_above(base)]
    out = _state(one)
    assert out['state'] == 'BEARISH' and out['position'] == 'above'
    two = one + [_above(one)]
    assert _state(two)['state'] == 'BULLISH'


def test_state_ts_stays_on_the_confirming_bar_while_the_state_holds():
    base = [100.0 + i * 0.5 for i in range(60)]
    closes = base + [_below(base)]
    closes.append(_below(closes))
    ts = _state(closes)['state_ts']
    closes += [_below(closes, 0.99)]                                  # a third close below: same state, same time
    assert _state(closes)['state_ts'] == ts


def test_band_state_keeps_the_cross_fields_and_defaults_to_100_200():
    closes = [100.0 + math.sin(i / 20) * 5 + i * 0.05 for i in range(400)]
    out = doc_trend.compute_band_state(_bars(closes))
    cross = doc_trend.compute_ema_cross(_bars(closes))
    for k in ('ema_fast', 'ema_slow', 'cross_state', 'cross_ts', 'cross_unbounded'):
        assert out[k] == cross[k], k
    assert out['upper'] == max(cross['ema_fast'], cross['ema_slow'])
    assert out['lower'] == min(cross['ema_fast'], cross['ema_slow'])
    assert doc_trend.DOC_BAND_CLOSES == 2


# -- fixtures ----------------------------------------------------------------

def price_at(t_s, coin="AAA"):
    base = {"AAA": 2.0, "BBB": 50.0}.get(coin, 10.0)
    return base * (1 + 0.15 * math.sin(t_s / 86400 / 11) + 0.03 * math.sin(t_s / 3600 / 9) + t_s / 2e11)


class FakeHL:
    """candleSnapshot like Hyperliquid's (every bar whose open falls in the
    window, the forming one included). `after` triples every bar that opens
    at or after that time (proves no lookahead)."""

    def __init__(self, fail=(), after=None):
        self.calls, self.fail, self.after = [], set(fail), after

    def __call__(self, payload):
        assert payload["type"] == "candleSnapshot", payload
        req = payload["req"]
        self.calls.append((req["coin"], req["interval"], req["startTime"], req["endTime"]))
        if req["coin"] in self.fail:
            raise ConnectionError("venue down")
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


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = str(tmp_path / "portfolio.db")
    monkeypatch.setattr(portfolio_db, "get_db_path", lambda: path)
    portfolio_db.init_db()
    monkeypatch.delenv("TXFLOW_WALLETS", raising=False)
    monkeypatch.setattr(wp, "load_wallet_config", lambda: {})
    monkeypatch.setattr(wp, "_txflow_post", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no TxFlow call")))
    monkeypatch.setattr(wp, "_hl_accounts_cache_copy", lambda: {"fetched_at": None, "wallets": {}})
    monkeypatch.setattr(wp, "_TXFLOW_CACHE", {"fetched_at": None, "wallets": {}, "error": None})
    monkeypatch.setitem(wp._HL_UNIVERSE_CACHE, "crypto", {"AAA": "AAA", "BBB": "BBB"})
    monkeypatch.setitem(wp._HL_UNIVERSE_CACHE, "xyz", {})
    monkeypatch.setitem(wp._HL_UNIVERSE_CACHE, "fetched_at", time.time())
    monkeypatch.setattr(wp, "_hl_refresh_universes", lambda force=False: None)
    fake = FakeHL()
    monkeypatch.setattr(wp, "_hl_post", fake)
    CURRENT["fake"] = fake
    conn = portfolio_db.get_connection()
    yield conn
    conn.close()


def addr(n):
    return "0x" + str(n) * 40


def seed(db):
    """Spot, Trading book: AAA open (Oct 10), BBB closed (Oct 1-8), NOTHL open
    (not on Hyperliquid). Long-term book: HOLD open. One manual perp trade."""
    rows = [("2026-10-10", "AAA", "buy", 100, 200.0, 1), ("2026-10-01", "BBB", "buy", 10, 500.0, 2),
            ("2026-10-08", "BBB", "sell", 10, 600.0, 2), ("2026-10-12", "NOTHL", "buy", 50, 150.0, 3),
            ("2026-10-05", "HOLD", "buy", 5, 50.0, 4)]
    for day, sym, side, units, total, n in rows:
        db.execute("INSERT INTO spot_transactions (trade_date, symbol, side, units, price_usd, total_usd, chain, "
                   "contract_address) VALUES (?, ?, ?, ?, ?, ?, 'base', ?)", (day, sym, side, units, total, total, addr(n)))
    db.execute("INSERT INTO spot_position_books (position_key, book, updated_at) VALUES (?, 'long_term', ?)",
               ("base " + addr(4), "2026-10-05T00:00:00+00:00"))
    db.execute("INSERT INTO spot_trade_log (ticker, direction, source, entry_price, stop_price, qty, entered_at, market) "
               "VALUES ('SOL', 'long', 'manual', 100, 95, 1, '2026-10-09T10:00:00+00:00', 'perp')")
    db.commit()


def trades_by(db):
    trades, _ = wp._trades_build(db)
    return {(t["market"], t["symbol"]): t for t in trades}


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


OWN = {"basis": "own_setup", "setup": "trend_retest_poi", "thesis": None, "exit_plan": "weekly_flip",
       "invalidation_px": None, "conviction": "high", "horizon": "positional"}
CALL = {"basis": "analyst_call", "setup": None, "thesis": "Narrative rotation into AI agents",
        "exit_plan": "analyst_exit", "invalidation_px": None, "conviction": "normal", "horizon": "narrative"}


def put(client, tid, body):
    return client.put("/api/trading/trades/" + tid + "/spot-plan", data=json.dumps(body), content_type="application/json")


def plan_rows(db):
    return [dict(r) for r in db.execute("SELECT * FROM spot_plans ORDER BY id").fetchall()]


# -- table and route ---------------------------------------------------------

def test_init_db_creates_spot_plans(db):
    cols = [r[1] for r in db.execute("PRAGMA table_info(spot_plans)")]
    assert cols == ['id', 'trade_id', 'basis', 'setup', 'thesis', 'exit_plan', 'invalidation_px',
                    'conviction', 'horizon', 'created_at']
    assert db.execute("SELECT name FROM sqlite_master WHERE name = 'idx_spot_plans_trade'").fetchone()


def test_put_saves_an_own_setup_plan_and_the_trades_route_shows_it(db, client):
    seed(db)
    aaa = trades_by(db)[("spot", "AAA")]
    r = put(client, aaa["trade_id"], OWN)
    assert r.status_code == 200
    plan = r.get_json()["plan"]
    assert {k: plan[k] for k in OWN} == OWN and plan["saved_at"]
    rows = plan_rows(db)
    assert len(rows) == 1 and rows[0]["trade_id"] == aaa["trade_id"] and rows[0]["basis"] == "own_setup"
    trades = {(t["market"], t["symbol"]): t for t in client.get("/api/trading/trades").get_json()["trades"]}
    got = trades[("spot", "AAA")]
    assert {k: got["plan"][k] for k in OWN} == OWN and got["plan_missing"] is False


def test_plan_missing_only_on_open_trading_spot_trades(db, client):
    seed(db)
    trades = {(t["market"], t["symbol"]): t for t in client.get("/api/trading/trades").get_json()["trades"]}
    assert trades[("spot", "AAA")]["plan_missing"] is True
    assert trades[("spot", "NOTHL")]["plan_missing"] is True
    assert trades[("spot", "BBB")]["status"] == "closed" and trades[("spot", "BBB")]["plan_missing"] is False
    assert trades[("spot", "HOLD")]["book"] != "trading" and trades[("spot", "HOLD")]["plan_missing"] is False
    perp = trades[("perp", "SOL")]
    assert perp["plan"] is None and perp["plan_missing"] is False and perp["doc_bands_at_open"] is None


def test_a_closed_trade_takes_a_plan_too(db, client):
    seed(db)
    bbb = trades_by(db)[("spot", "BBB")]
    assert put(client, bbb["trade_id"], CALL).status_code == 200
    got = {(t["market"], t["symbol"]): t for t in client.get("/api/trading/trades").get_json()["trades"]}
    assert got[("spot", "BBB")]["plan"]["thesis"] == CALL["thesis"]


def test_unchanged_plan_writes_nothing_and_a_change_appends(db, client):
    seed(db)
    tid = trades_by(db)[("spot", "AAA")]["trade_id"]
    put(client, tid, OWN)
    put(client, tid, dict(OWN))
    assert len(plan_rows(db)) == 1
    put(client, tid, dict(OWN, conviction="low"))
    rows = plan_rows(db)
    assert len(rows) == 2 and rows[-1]["conviction"] == "low" and rows[0]["conviction"] == "high"


def test_clear_appends_a_null_row_and_plan_missing_returns(db, client):
    seed(db)
    tid = trades_by(db)[("spot", "AAA")]["trade_id"]
    put(client, tid, OWN)
    r = put(client, tid, {"basis": None})
    assert r.status_code == 200 and r.get_json()["plan"] is None
    rows = plan_rows(db)
    assert len(rows) == 2 and all(rows[-1][k] is None for k in wp._SPOT_PLAN_FIELDS)
    got = {(t["market"], t["symbol"]): t for t in client.get("/api/trading/trades").get_json()["trades"]}
    assert got[("spot", "AAA")]["plan"] is None and got[("spot", "AAA")]["plan_missing"] is True
    put(client, tid, {"basis": None})                                  # clearing again: nothing new
    assert len(plan_rows(db)) == 2


def test_clearing_a_trade_with_no_plan_writes_nothing(db, client):
    seed(db)
    tid = trades_by(db)[("spot", "NOTHL")]["trade_id"]
    assert put(client, tid, {"basis": None}).status_code == 200
    assert plan_rows(db) == []


@pytest.mark.parametrize("body, fragment", [
    ([], "JSON object"),
    ({}, "basis is required"),
    (dict(OWN, extra=1), "unknown field: extra"),
    (dict(OWN, basis="hunch"), "basis must be"),
    (dict(OWN, setup=None), "needs setup"),
    (dict(OWN, setup="breaker"), "needs setup"),
    (dict(CALL, thesis=None), "needs a one-line thesis"),
    (dict(CALL, thesis="   "), "needs a one-line thesis"),
    (dict(CALL, setup="compression"), "only for an own chart setup"),
    (dict(CALL, basis="other", setup="range_deviation"), "only for an own chart setup"),
    (dict(CALL, thesis="x" * 201), "up to 200"),
    (dict(CALL, thesis=5), "up to 200"),
    (dict(OWN, exit_plan=None), "exit_plan must be"),
    (dict(OWN, exit_plan="stop"), "exit_plan must be"),
    (dict(OWN, exit_plan="price_level"), "needs invalidation_px"),
    (dict(OWN, invalidation_px=0), "positive number"),
    (dict(OWN, invalidation_px="-2"), "positive number"),
    (dict(OWN, invalidation_px="abc"), "positive number"),
    (dict(OWN, invalidation_px=True), "positive number"),
    (dict(OWN, invalidation_px="nan"), "positive number"),
    (dict(OWN, invalidation_px="1e16"), "positive number"),
    (dict(OWN, invalidation_px="1e-31"), "positive number"),
    (dict(OWN, invalidation_px="1" * 41), "positive number"),
    (dict(OWN, conviction="max"), "conviction must be"),
    (dict(OWN, horizon=None), "horizon must be"),
    ({"basis": None, "conviction": "high"}, "basis null and nothing else"),
])
def test_bad_bodies_are_refused(db, client, body, fragment):
    seed(db)
    tid = trades_by(db)[("spot", "AAA")]["trade_id"]
    r = put(client, tid, body)
    assert r.status_code == 400 and fragment in r.get_json()["error"]
    assert plan_rows(db) == []


def test_thesis_is_trimmed_and_the_price_normalised(db, client):
    seed(db)
    tid = trades_by(db)[("spot", "AAA")]["trade_id"]
    body = dict(OWN, basis="other", setup=None, thesis="  two   spaces" + chr(10) + "and a line  ",
                exit_plan="price_level", invalidation_px="1.2500")
    plan = put(client, tid, body).get_json()["plan"]
    assert plan["thesis"] == "two spaces and a line"
    assert plan["invalidation_px"] == wp.hl_trades._qp(__import__("decimal").Decimal("1.25"))
    assert plan["setup"] is None


def test_a_tiny_price_keeps_every_digit(db, client):
    seed(db)
    tid = trades_by(db)[("spot", "AAA")]["trade_id"]
    plan = put(client, tid, dict(OWN, invalidation_px="0.00000000012340")).get_json()["plan"]
    assert plan["invalidation_px"] == "0.0000000001234"
    plan = put(client, tid, dict(OWN, invalidation_px=125000)).get_json()["plan"]
    assert plan["invalidation_px"] == "125000"


def test_only_spot_trades_take_a_plan(db, client):
    seed(db)
    perp = trades_by(db)[("perp", "SOL")]
    assert put(client, perp["trade_id"], OWN).status_code == 404
    assert put(client, "not-a-trade", OWN).status_code == 404
    assert plan_rows(db) == []


def test_the_restore_report_reads_the_newest_plan():
    from src.storage import db_restore
    assert ('spot_plans', 'created_at', 'Spot plans') in db_restore.NEWEST_COLUMNS


def test_no_table_means_no_plans(db):
    db.execute("DROP TABLE spot_plans")
    assert wp._spot_plans_latest(db) == {}


def test_the_value_lists_match_the_rulings():
    assert wp.SPOT_PLAN_BASES == ('own_setup', 'analyst_call', 'other')
    assert wp.SPOT_PLAN_EXITS == ('weekly_flip', 'target', 'analyst_exit', 'price_level')
    assert wp.SPOT_PLAN_CONVICTIONS == ('high', 'normal', 'low')
    assert wp.SPOT_PLAN_HORIZONS == ('cyclical', 'positional', 'narrative')
    assert wp.SPOT_PLAN_SETUPS == ('trend_retest_poi', 'trend_retest_sfp', 'range_deviation', 'range_3_drives_msb',
                                   'expansion_candle', 'compression', 'vwap_trend_continuation', 'vwap_range_reversion',
                                   'spot_cyclical', 'other')                     # Landing 60 added the last two


def test_spot_cyclical_and_other_are_setups(db, client):
    seed(db)
    tid = trades_by(db)[("spot", "AAA")]["trade_id"]
    for setup in ("spot_cyclical", "other"):
        r = put(client, tid, dict(OWN, setup=setup))
        assert r.status_code == 200 and r.get_json()["plan"]["setup"] == setup


# -- Doc's band states at a spot trade's open ---------------------------------

def snap_of(db, tid):
    row = db.execute("SELECT scanner_snapshot_json FROM trade_annotations WHERE trade_id = ?", (tid,)).fetchone()
    return json.loads(row[0]) if row and row[0] else {}


def test_doc_pass_writes_bands_from_bars_before_the_trade_day(db):
    seed(db)
    wp._trade_snapshot_pass(db)                                        # trend parts first
    fake = CURRENT["fake"]
    fake.calls.clear()
    stats = wp._trade_doc_pass(db)
    t = trades_by(db)
    aaa, nothl, bbb = t[("spot", "AAA")], t[("spot", "NOTHL")], t[("spot", "BBB")]
    assert stats == {"done": 2, "unavailable": 1, "failed": 0, "pending": 0}
    doc = snap_of(db, aaa["trade_id"])["doc_bands"]
    as_of = int(datetime(2026, 10, 10, tzinfo=timezone.utc).timestamp() * 1000)
    assert doc["v"] == 1 and doc["reason"] is None and doc["market"] == "AAA" and doc["scale"] == 1
    assert doc["as_of"] == datetime(2026, 10, 10, tzinfo=timezone.utc).isoformat()
    for part in (doc["daily"], doc["weekly"]):
        assert part["state"] in ("BULLISH", "BEARISH") and part["position"] in ("above", "inside", "below")
        assert float(part["upper"]) >= float(part["lower"])
    assert doc["weekly"]["bars"] == 700
    assert 690 <= doc["daily"]["bars"] <= 700                          # 2,800 hourlies into whole 4H buckets
    aaa_calls = [c for c in fake.calls if c[0] == "AAA"]
    assert sorted((c[1], c[3]) for c in aaa_calls) == [("1d", as_of), ("1h", as_of)]
    assert ("1h", as_of - 3600000 * 2801) in [(c[1], c[2]) for c in aaa_calls]
    nd = snap_of(db, nothl["trade_id"])["doc_bands"]
    assert nd["reason"] == "not_on_hyperliquid" and nd["daily"] is None and nd["weekly"] is None
    assert not [c for c in fake.calls if c[0] == "NOTHL"]
    assert snap_of(db, bbb["trade_id"])["doc_bands"]["reason"] is None
    hold = t[("spot", "HOLD")]
    assert "doc_bands" not in snap_of(db, hold["trade_id"])            # not the Trading book: no snapshot at all


def test_doc_bands_do_not_look_past_the_trade_day(db, monkeypatch):
    seed(db)
    wp._trade_snapshot_pass(db)
    wp._trade_doc_pass(db)
    tid = trades_by(db)[("spot", "AAA")]["trade_id"]
    first = snap_of(db, tid)["doc_bands"]
    as_of = int(datetime(2026, 10, 10, tzinfo=timezone.utc).timestamp() * 1000)
    monkeypatch.setattr(wp, "_hl_post", FakeHL(after=as_of))
    again = wp._trade_open_doc_bands("AAA", as_of)
    assert again == {"daily": first["daily"], "weekly": first["weekly"]}


def test_a_4h_bucket_still_forming_at_as_of_is_left_out(db):
    seed(db)
    day = int(datetime(2026, 10, 10, tzinfo=timezone.utc).timestamp() * 1000)
    at_midnight = wp._trade_open_doc_bands("AAA", day)
    two_am = wp._trade_open_doc_bands("AAA", day + 2 * 3600000)      # 00:00-02:00 is half a 4H bucket
    assert two_am["daily"] == at_midnight["daily"]


def test_a_trade_moved_out_of_the_trading_book_shows_no_bands(db, client):
    seed(db)
    wp._trade_snapshot_pass(db)
    wp._trade_doc_pass(db)
    db.execute("INSERT INTO spot_position_books (position_key, book, updated_at) VALUES (?, 'long_term', ?)",
               ("base " + addr(1), "2026-10-20T00:00:00+00:00"))
    db.commit()
    got = {(t["market"], t["symbol"]): t for t in client.get("/api/trading/trades").get_json()["trades"]}
    aaa = got[("spot", "AAA")]
    assert aaa["book"] == "long_term" and aaa["doc_bands_at_open"] is None and aaa["plan_missing"] is False


def test_doc_pass_is_idempotent_and_capped(db):
    seed(db)
    wp._trade_snapshot_pass(db)
    fake = CURRENT["fake"]
    fake.calls.clear()
    assert wp._trade_doc_pass(db, cap=1) == {"done": 0, "unavailable": 1, "failed": 0, "pending": 2}   # newest first: NOTHL
    assert wp._trade_doc_pass(db, cap=0)["pending"] == 2
    wp._trade_doc_pass(db)
    fake.calls.clear()
    assert wp._trade_doc_pass(db) == {"done": 0, "unavailable": 0, "failed": 0, "pending": 0}
    assert fake.calls == []


def test_a_failed_fetch_writes_nothing_and_is_retried(db, monkeypatch):
    seed(db)
    wp._trade_snapshot_pass(db)
    monkeypatch.setattr(wp, "_hl_post", FakeHL(fail={"AAA"}))
    stats = wp._trade_doc_pass(db)
    tid = trades_by(db)[("spot", "AAA")]["trade_id"]
    assert stats["failed"] == 1 and "doc_bands" not in snap_of(db, tid)
    monkeypatch.setattr(wp, "_hl_post", FakeHL())
    wp._trade_doc_pass(db)
    assert snap_of(db, tid)["doc_bands"]["reason"] is None


def test_doc_pass_waits_for_the_trend_part(db):
    seed(db)
    assert wp._trade_doc_pass(db) == {"done": 0, "unavailable": 0, "failed": 0, "pending": 0}


def test_a_price_mismatch_carries_over_as_the_reason(db, monkeypatch):
    seed(db)
    wp._trade_snapshot_pass(db)
    tid = trades_by(db)[("spot", "AAA")]["trade_id"]
    snap = snap_of(db, tid)
    snap["trend"]["reason"] = "price_mismatch"
    db.execute("UPDATE trade_annotations SET scanner_snapshot_json = ? WHERE trade_id = ?", (json.dumps(snap), tid))
    db.commit()
    fake = CURRENT["fake"]
    fake.calls.clear()
    wp._trade_doc_pass(db)
    assert snap_of(db, tid)["doc_bands"]["reason"] == "price_mismatch"
    assert not [c for c in fake.calls if c[0] == "AAA"]


def test_doc_pass_keeps_user_fields_and_updated_at(db, client):
    seed(db)
    tid = trades_by(db)[("spot", "AAA")]["trade_id"]
    client.put("/api/trading/trades/" + tid + "/annotation", data=json.dumps({"notes": "keep me"}),
               content_type="application/json")
    before = dict(db.execute("SELECT notes, updated_at FROM trade_annotations WHERE trade_id = ?", (tid,)).fetchone())
    wp._trade_snapshot_pass(db)
    wp._trade_doc_pass(db)
    after = dict(db.execute("SELECT notes, updated_at FROM trade_annotations WHERE trade_id = ?", (tid,)).fetchone())
    assert after == before and snap_of(db, tid)["doc_bands"]["v"] == 1


def test_trades_route_carries_doc_bands_at_open(db, client):
    seed(db)
    wp._trade_snapshot_pass(db)
    wp._trade_doc_pass(db)
    got = {(t["market"], t["symbol"]): t for t in client.get("/api/trading/trades").get_json()["trades"]}
    doc = got[("spot", "AAA")]["doc_bands_at_open"]
    assert doc["v"] == 1 and doc["daily"]["state"] in ("BULLISH", "BEARISH")
    assert got[("spot", "NOTHL")]["doc_bands_at_open"]["reason"] == "not_on_hyperliquid"
    assert got[("spot", "HOLD")]["doc_bands_at_open"] is None
    assert "doc_bands" not in (got[("spot", "AAA")]["open_snapshot"] or {})


def test_worker_runs_the_doc_pass_and_logs_it(db, monkeypatch, capsys):
    seed(db)
    monkeypatch.setattr(wp, "_trade_exit_pass_safe", lambda conn: None)
    wp._trade_snapshot_worker()                                         # trend parts, then the doc pass
    out = capsys.readouterr().out
    assert "[trade-doc] done+=2 unavailable+=1 failed=0 pending=0" in out


def test_a_doc_pass_exception_never_stops_the_worker(db, monkeypatch, capsys):
    seed(db)
    monkeypatch.setattr(wp, "_trade_exit_pass_safe", lambda conn: None)
    monkeypatch.setattr(wp, "_trade_doc_pass", lambda conn: (_ for _ in ()).throw(RuntimeError("boom")))
    assert wp._trade_snapshot_worker() is not None
    assert "[trade-doc] pass exception RuntimeError" in capsys.readouterr().out


def test_a_quiet_doc_pass_logs_nothing(db, monkeypatch, capsys):
    seed(db)
    monkeypatch.setattr(wp, "_trade_exit_pass_safe", lambda conn: None)
    wp._trade_snapshot_worker()
    capsys.readouterr()
    wp._trade_snapshot_worker()                                         # everything already has its part
    assert "[trade-doc]" not in capsys.readouterr().out
