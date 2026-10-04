"""Trade-open snapshot (Landing 4, HANDOFF_spot_perps_rebuild.md 3.5 and 14):
_hl_candles_before (closed bars only), _trade_open_trend (the scanner's
engine and settings on bars that closed before the open; 1w from dailies,
4h from hourlies, forming buckets dropped), _trade_snapshot_pass (leverage
at first sight, trend for perps on 7 timeframes and Trading-book spot on
1D / 1W, kilo markets x1000, reasons - an entry far from Hyperliquid's
price included - failures write nothing, cap, newest first, idempotent),
the worker (single-flight, skipped during a scanner
scan), the fill-sync thread running sync then snapshot, and the trades
route's "open_snapshot", the leverage of a closed perp trade from the
snapshot, and the unattached list ignoring snapshot-only rows.

Real init_db() on a tmp_path SQLite file (portfolio_db.get_db_path
monkeypatched). Hyperliquid trades come from synthetic fills written
straight into hl_fills; candles from a fake candleSnapshot (made-up
prices). The Hyperliquid universe cache is set in memory. No network.
Fake wallet addresses only, built in code.

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
from src.engines.noodle_bands import compute_noodle_state

W = "0x" + "d" * 40
TF_MS = wp.TRADE_SNAPSHOT_TF_MS
ETH_OPEN = int(datetime(2026, 10, 2, 9, 37, tzinfo=timezone.utc).timestamp() * 1000)   # mid 4h bucket, mid week
BTC_OPEN = int(datetime(2026, 9, 27, 14, 5, tzinfo=timezone.utc).timestamp() * 1000)
BTC_CLOSE = BTC_OPEN + 20 * 3600000
CURRENT = {}                         # the fixture's fake candleSnapshot (a sqlite connection takes no attributes)
SETTINGS = {'fast': 12, 'medium': 21, 'slow': 25, 'atr_length': 20, 'band_multiplier': 0.01, 'use_atr': True}


def price_at(t_s, coin="ETH"):
    """A made-up price path: a slow wave plus a trend, per coin."""
    base = {"ETH": 4000.0, "BTC": 110000.0, "kBONK": 0.02}.get(coin, 50.0)
    return base * (1 + 0.08 * math.sin(t_s / 86400 / 9) + 0.02 * math.sin(t_s / 3600 / 7) + t_s / 1e12)


class FakeHL:
    """candleSnapshot like Hyperliquid's: every bar whose open time falls in
    [startTime, endTime], the still-forming one included. `after` shifts
    every bar that opens at or after that time (to prove no lookahead)."""

    def __init__(self, fail=(), after=None):
        self.calls = []
        self.fail = set(fail)
        self.after = after

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
    monkeypatch.setitem(wp._HL_UNIVERSE_CACHE, "crypto", {"ETH": "ETH", "BTC": "BTC", "KBONK": "kBONK"})
    monkeypatch.setitem(wp._HL_UNIVERSE_CACHE, "xyz", {})
    monkeypatch.setitem(wp._HL_UNIVERSE_CACHE, "fetched_at", time.time())
    fake = FakeHL()
    monkeypatch.setattr(wp, "_hl_post", fake)
    conn = portfolio_db.get_connection()
    CURRENT["fake"] = fake
    yield conn
    conn.close()


def seed(db):
    """HL: open ETH long (Oct 2), closed BTC long (Sep 27-28). Spot: BONK
    (kilo market) and NOTHL (not on Hyperliquid) in the Trading book, AAA in
    long-term. One manual perp trade."""
    db.execute("INSERT INTO hl_sync_state (wallet, first_seen_at, last_sync_at, last_ok_at) VALUES (?, ?, ?, ?)",
               (W, "2026-09-01T00:00:00+00:00", "2026-10-03T00:00:00+00:00", "2026-10-03T00:00:00+00:00"))
    for f in (fill("ETH", 1, ETH_OPEN, "B", "1", "4100", "0"),
              fill("BTC", 2, BTC_OPEN, "B", "0.01", "111000", "0"),
              fill("BTC", 3, BTC_CLOSE, "A", "0.01", "112000", "0.01", pnl="10")):
        db.execute("INSERT INTO hl_fills (wallet, tid, coin, time_ms, raw_json, fetched_at) VALUES (?, ?, ?, ?, ?, ?)",
                   (W, f["tid"], f["coin"], f["time"], json.dumps(f), "2026-10-03T00:00:00+00:00"))
    for sym, addr, price in (("BONK", "0x" + "1" * 40, 0.000025), ("NOTHL", "0x" + "2" * 40, 3.0),
                             ("AAA", "0x" + "3" * 40, 1.0)):
        # price_usd holds the row's TOTAL (spot_trades.build), so avg_entry = price.
        db.execute("INSERT INTO spot_transactions (trade_date, symbol, side, units, price_usd, total_usd, chain, "
                   "contract_address) VALUES ('2026-09-20', ?, 'buy', 100, ?, ?, 'base', ?)", (sym, price * 100, price * 100, addr))
    db.execute("INSERT INTO spot_position_books (position_key, book, updated_at) VALUES (?, 'long_term', ?)",
               ("base " + "0x" + "3" * 40, "2026-09-01T00:00:00+00:00"))
    db.execute("INSERT INTO spot_trade_log (ticker, direction, source, entry_price, stop_price, qty, entered_at, market) "
               "VALUES ('SOL', 'long', 'manual', 100, 95, 1, '2026-09-25T10:00:00+00:00', 'perp')")
    db.commit()


def trades_by(db):
    trades, _ = wp._trades_build(db)
    return {(t["source"], t["symbol"]): t for t in trades}


def snapshot(db, trade_id):
    row = db.execute("SELECT scanner_snapshot_json, scanner_captured_at FROM trade_annotations WHERE trade_id = ?",
                     (trade_id,)).fetchone()
    return (json.loads(row[0]) if row and row[0] else None), (row[1] if row else None)


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


# ── candles before a time ────────────────────────────────────────────────

def test_candles_before_keeps_only_bars_closed_by_the_end(db):
    out = wp._hl_candles_before("ETH", "1h", ETH_OPEN, 10)
    assert len(out) == 10
    assert all(c["time"] * 1000 + 3600000 <= ETH_OPEN for c in out)
    assert [c["time"] for c in out] == sorted(c["time"] for c in out)
    assert out[-1]["time"] * 1000 == ETH_OPEN - ETH_OPEN % 3600000 - 3600000          # the forming 09:00 bar is gone
    coin, interval, start, end = CURRENT["fake"].calls[-1]
    assert (coin, interval, end, start) == ("ETH", "1h", ETH_OPEN, ETH_OPEN - 3600000 * 11)


def test_candles_before_rejects_an_odd_answer(db, monkeypatch):
    monkeypatch.setattr(wp, "_hl_post", lambda payload: {"error": "x"})
    with pytest.raises(ValueError):
        wp._hl_candles_before("ETH", "1d", ETH_OPEN, 5)


# ── trend at open ────────────────────────────────────────────────────────

def test_trend_matches_the_engine_on_closed_bars(db):
    view = wp._trade_open_trend("ETH", ETH_OPEN, "4100", 1, wp.TRADE_SNAPSHOT_PERP_TFS, SETTINGS)
    assert list(view) == list(wp.TRADE_SNAPSHOT_PERP_TFS)
    for tf in ("15m", "30m", "1h", "12h", "1d"):
        closed = wp._hl_candles_before("ETH", tf, ETH_OPEN, wp.TRADE_SNAPSHOT_DEPTH[tf])
        r = compute_noodle_state(closed, **SETTINGS)
        assert view[tf]["state"] == r["state"] and view[tf]["bars"] == len(closed)
        assert view[tf]["upper_band"] == wp._snapshot_num(r["upper_band"])
        assert view[tf]["position"] == wp._noodle_band_position(4100.0, r["upper_band"], r["lower_band"])
    assert all(view[tf]["position"] in ("above", "touch", "below") for tf in view)


def test_weekly_and_4h_drop_the_bucket_still_forming(db):
    view = wp._trade_open_trend("ETH", ETH_OPEN, "4100", 1, ("4h", "1w"), SETTINGS)
    dailies = wp._hl_candles_before("ETH", "1d", ETH_OPEN, 300)
    weeks = [w for w in wp._weekly_from_dailies(dailies, limit=10 ** 6) if w["time"] + 7 * 86400 <= ETH_OPEN // 1000]
    hourlies = wp._hl_candles_before("ETH", "1h", ETH_OPEN, 1440)
    h4 = [b for b in wp._h4_from_h1(hourlies, limit=10 ** 6) if b["time"] + 14400 <= ETH_OPEN // 1000]
    assert view["1w"]["bars"] == len(weeks) and view["4h"]["bars"] == len(h4)
    assert weeks[-1]["time"] + 7 * 86400 <= ETH_OPEN // 1000 < weeks[-1]["time"] + 14 * 86400   # last full week only
    assert h4[-1]["time"] == (ETH_OPEN // 1000 // 14400) * 14400 - 14400                     # 04:00 bucket, not 08:00
    assert view["1w"]["state"] == compute_noodle_state(weeks, **SETTINGS)["state"]


def test_no_lookahead(db, monkeypatch):
    first = wp._trade_open_trend("ETH", ETH_OPEN, "4100", 1, wp.TRADE_SNAPSHOT_PERP_TFS, SETTINGS)
    monkeypatch.setattr(wp, "_hl_post", FakeHL(after=ETH_OPEN - ETH_OPEN % 900000))        # prices change from the open's bar on
    second = wp._trade_open_trend("ETH", ETH_OPEN, "4100", 1, wp.TRADE_SNAPSHOT_PERP_TFS, SETTINGS)
    assert first == second


def test_an_entry_far_from_hyperliquid_raises(db):
    closes = wp._hl_candles_before("ETH", "15m", ETH_OPEN, wp.TRADE_SNAPSHOT_DEPTH["15m"])
    with pytest.raises(wp.TradeSnapshotPriceMismatch) as e:
        wp._trade_open_trend("ETH", ETH_OPEN, "40", 1, wp.TRADE_SNAPSHOT_PERP_TFS, SETTINGS)
    assert e.value.ref_close == closes[-1]["close"]                                       # the latest close before the open
    with pytest.raises(wp.TradeSnapshotPriceMismatch):
        wp._trade_open_trend("ETH", ETH_OPEN, str(closes[-1]["close"] * 3.2), 1, ("1d",), SETTINGS)
    assert wp._trade_open_trend("ETH", ETH_OPEN, str(closes[-1]["close"] * 2.9), 1, ("15m",), SETTINGS)["15m"]["position"] == "above"
    assert wp._trade_open_trend("ETH", ETH_OPEN, None, 1, ("15m",), SETTINGS)["15m"]["position"] is None   # no price: no check


def test_too_few_bars_leaves_the_position_empty(db, monkeypatch):
    monkeypatch.setitem(wp.TRADE_SNAPSHOT_DEPTH, "1d", 10)
    view = wp._trade_open_trend("ETH", ETH_OPEN, "4100", 1, ("1d",), SETTINGS)
    assert view["1d"]["state"] == "WARMUP" and view["1d"]["position"] is None and view["1d"]["upper_band"] is None


def test_the_scanner_settings_are_used(db, monkeypatch):
    monkeypatch.setattr(wp, "_scanner_settings", lambda: {"noodle_ema_fast": 8, "noodle_ema_medium": 13,
                                                          "noodle_ema_slow": 30, "noodle_atr_length": 14,
                                                          "noodle_band_multiplier": 0.02, "noodle_use_atr": False})
    assert wp._trade_snapshot_settings() == {"fast": 8, "medium": 13, "slow": 30, "atr_length": 14,
                                             "band_multiplier": 0.02, "use_atr": False}
    seen = []
    real = wp.compute_noodle_state
    monkeypatch.setattr(wp, "compute_noodle_state", lambda c, **k: seen.append(k) or real(c, **k))
    seed(db)
    wp._trade_snapshot_pass(db, cap=1)
    assert seen and all(k["slow"] == 30 and k["use_atr"] is False for k in seen)


# ── the pass ─────────────────────────────────────────────────────────────

def test_pass_covers_perps_and_trading_spot(db):
    seed(db)
    stats = wp._trade_snapshot_pass(db, cap=10)
    assert stats == {"leverage": 0, "targets": 0, "trend": 3, "unavailable": 1, "failed": 0, "pending": 0}
    t = trades_by(db)
    eth, _ = snapshot(db, t[("hyperliquid", "ETH")]["trade_id"])
    tr = eth["trend"]
    assert (tr["v"], tr["market"], tr["scale"], tr["precision"], tr["reason"], tr["price"]) == (1, "ETH", 1, "time", None, "4100")
    assert tr["as_of"] == datetime.fromtimestamp(ETH_OPEN / 1000, timezone.utc).isoformat()
    # Keys are stored sorted (json.dumps sort_keys); the page orders them itself.
    assert sorted(tr["timeframes"]) == sorted(wp.TRADE_SNAPSHOT_PERP_TFS) and tr["weekly_state"] == tr["timeframes"]["1w"]["state"]
    btc, captured = snapshot(db, t[("hyperliquid", "BTC")]["trade_id"])
    assert btc["trend"]["market"] == "BTC" and captured == btc["trend"]["computed_at"]
    bonk, _ = snapshot(db, t[("spot_tx", "BONK")]["trade_id"])
    assert (bonk["trend"]["market"], bonk["trend"]["scale"], bonk["trend"]["precision"]) == ("kBONK", 1000, "day")
    assert bonk["trend"]["as_of"] == "2026-09-20T00:00:00+00:00" and sorted(bonk["trend"]["timeframes"]) == ["1d", "1w"]
    nothl, _ = snapshot(db, t[("spot_tx", "NOTHL")]["trade_id"])
    assert nothl["trend"]["reason"] == "not_on_hyperliquid" and nothl["trend"]["timeframes"] == {}
    assert snapshot(db, t[("spot_tx", "AAA")]["trade_id"]) == (None, None)                 # long-term book
    assert snapshot(db, t[("manual", "SOL")]["trade_id"]) == (None, None)                  # manual trade
    rows = {r["trade_id"]: dict(r) for r in db.execute("SELECT * FROM trade_annotations")}
    row = rows[t[("hyperliquid", "ETH")]["trade_id"]]
    assert row["market"] == "perp" and row["stop_px"] is None and row["notes"] is None and row["followed_rules"] is None
    assert rows[t[("spot_tx", "BONK")]["trade_id"]]["market"] == "spot"


def test_kilo_markets_scale_the_price(db):
    seed(db)
    wp._trade_snapshot_pass(db, cap=10)
    t = trades_by(db)[("spot_tx", "BONK")]
    trend = snapshot(db, t["trade_id"])[0]["trend"]
    closed = wp._hl_candles_before("kBONK", "1d", trend and int(datetime(2026, 9, 20, tzinfo=timezone.utc).timestamp() * 1000), 300)
    r = compute_noodle_state(closed, **SETTINGS)
    assert t["avg_entry"] is not None and float(t["avg_entry"]) == pytest.approx(0.000025)
    assert trend["price"] == t["avg_entry"]
    assert trend["timeframes"]["1d"]["position"] == wp._noodle_band_position(0.000025 * 1000, r["upper_band"], r["lower_band"]) == "above"
    assert wp._noodle_band_position(0.000025, r["upper_band"], r["lower_band"]) == "below"   # unscaled would be wrong


def test_a_same_ticker_token_is_not_read(db):
    """A Base token called ETH bought at $3 is not Hyperliquid's ETH: no reading, kept as price_mismatch."""
    seed(db)
    db.execute("INSERT INTO spot_transactions (trade_date, symbol, side, units, price_usd, total_usd, chain, "
               "contract_address) VALUES ('2026-09-22', 'ETH', 'buy', 100, 300, 300, 'base', ?)", ("0x" + "4" * 40,))
    db.commit()
    stats = wp._trade_snapshot_pass(db, cap=10)
    assert stats == {"leverage": 0, "targets": 0, "trend": 3, "unavailable": 2, "failed": 0, "pending": 0}
    fake_eth = trades_by(db)[("spot_tx", "ETH")]
    tr = snapshot(db, fake_eth["trade_id"])[0]["trend"]
    assert (tr["reason"], tr["market"], tr["timeframes"], tr["weekly_state"]) == ("price_mismatch", "ETH", {}, None)
    assert float(tr["ref_close"]) > 1000 and tr["price"] == fake_eth["avg_entry"]
    assert wp._trade_snapshot_pass(db, cap=10)["unavailable"] == 0                       # kept: not retried


def test_failure_writes_nothing_and_the_next_pass_retries(db, monkeypatch):
    seed(db)
    monkeypatch.setattr(wp, "_hl_post", FakeHL(fail={"ETH"}))
    stats = wp._trade_snapshot_pass(db, cap=10)
    assert stats["failed"] == 1 and stats["trend"] == 2
    eth_id = trades_by(db)[("hyperliquid", "ETH")]["trade_id"]
    assert snapshot(db, eth_id) == (None, None)
    monkeypatch.setattr(wp, "_hl_post", FakeHL())
    assert wp._trade_snapshot_pass(db, cap=10)["trend"] == 1
    assert snapshot(db, eth_id)[0]["trend"]["market"] == "ETH"


def test_universe_unavailable_skips_the_trend_step(db, monkeypatch):
    seed(db)
    monkeypatch.setitem(wp._HL_UNIVERSE_CACHE, "crypto", None)
    monkeypatch.setattr(wp, "_hl_refresh_universes", lambda force=False: None)
    stats = wp._trade_snapshot_pass(db, cap=10)
    assert stats == {"leverage": 0, "targets": 0, "trend": 0, "unavailable": 0, "failed": 0, "pending": 4}
    assert db.execute("SELECT COUNT(*) FROM trade_annotations").fetchone()[0] == 0


def test_cap_newest_first_and_idempotent(db):
    seed(db)
    stats = wp._trade_snapshot_pass(db, cap=1)
    assert stats["trend"] == 1 and stats["pending"] == 3
    t = trades_by(db)
    assert snapshot(db, t[("hyperliquid", "ETH")]["trade_id"])[0] is not None              # newest opened first
    assert snapshot(db, t[("hyperliquid", "BTC")]["trade_id"])[0] is None
    for _ in range(4):
        wp._trade_snapshot_pass(db, cap=1)
    calls = len(CURRENT["fake"].calls)
    before = [tuple(r) for r in db.execute("SELECT * FROM trade_annotations ORDER BY trade_id")]
    assert wp._trade_snapshot_pass(db, cap=1) == {"leverage": 0, "targets": 0, "trend": 0, "unavailable": 0, "failed": 0, "pending": 0}
    assert len(CURRENT["fake"].calls) == calls
    assert [tuple(r) for r in db.execute("SELECT * FROM trade_annotations ORDER BY trade_id")] == before


def test_an_older_version_is_recomputed(db):
    seed(db)
    wp._trade_snapshot_pass(db, cap=10)
    eth_id = trades_by(db)[("hyperliquid", "ETH")]["trade_id"]
    snap = snapshot(db, eth_id)[0]
    snap["trend"]["v"] = 0
    db.execute("UPDATE trade_annotations SET scanner_snapshot_json = ? WHERE trade_id = ?", (json.dumps(snap), eth_id))
    db.commit()
    assert wp._trade_snapshot_pass(db, cap=10)["trend"] == 1
    assert snapshot(db, eth_id)[0]["trend"]["v"] == 1


def test_an_existing_annotation_keeps_its_fields_and_updated_at(db):
    seed(db)
    eth_id = trades_by(db)[("hyperliquid", "ETH")]["trade_id"]
    db.execute("INSERT INTO trade_annotations (trade_id, market, stop_px, stop_set_at, stop_source, notes, created_at, "
               "updated_at) VALUES (?, 'perp', '4000', '2026-10-02T10:00:00+00:00', 'manual', 'my plan', "
               "'2026-10-02T10:00:00+00:00', '2026-10-02T10:00:00+00:00')", (eth_id,))
    db.commit()
    wp._trade_snapshot_pass(db, cap=10)
    row = dict(db.execute("SELECT * FROM trade_annotations WHERE trade_id = ?", (eth_id,)).fetchone())
    assert (row["stop_px"], row["notes"], row["updated_at"], row["created_at"]) == (
        "4000", "my plan", "2026-10-02T10:00:00+00:00", "2026-10-02T10:00:00+00:00")
    assert json.loads(row["scanner_snapshot_json"])["trend"]["market"] == "ETH" and row["scanner_captured_at"]


def test_leverage_is_captured_once_while_open(db, monkeypatch):
    seed(db)

    def cache(lev, lev_type):
        pos = {"coin": "ETH", "szi": "1", "entry_px": "4100", "unrealized_pnl": "5", "cum_funding_since_open": "0",
               "position_value": "4105", "liquidation_px": "3000", "margin_used": "400", "return_on_equity": "0.1",
               "leverage": lev, "leverage_type": lev_type}
        return {"fetched_at": "2026-10-03T00:00:00+00:00", "wallets": {W: {"positions": [pos], "open_orders": []}}}

    monkeypatch.setattr(wp, "_hl_accounts_cache_copy", lambda: cache(10, "isolated"))
    assert wp._trade_snapshot_pass(db, cap=0)["leverage"] == 1
    eth_id = trades_by(db)[("hyperliquid", "ETH")]["trade_id"]
    lev = snapshot(db, eth_id)[0]["leverage"]
    assert (lev["value"], lev["type"]) == ("10", "isolated") and wp._trades_dt(lev["seen_at"]) is not None
    monkeypatch.setattr(wp, "_hl_accounts_cache_copy", lambda: cache(20, "cross"))
    assert wp._trade_snapshot_pass(db, cap=0)["leverage"] == 0
    assert snapshot(db, eth_id)[0]["leverage"]["value"] == "10"                           # the first value seen stays
    btc_id = trades_by(db)[("hyperliquid", "BTC")]["trade_id"]
    assert snapshot(db, btc_id) == (None, None)                                           # closed: never live


def test_a_closed_trade_takes_its_leverage_from_the_snapshot(db, client):
    seed(db)
    btc_id = trades_by(db)[("hyperliquid", "BTC")]["trade_id"]
    db.execute("INSERT INTO trade_annotations (trade_id, market, scanner_snapshot_json, created_at, updated_at) "
               "VALUES (?, 'perp', ?, 'x', 'x')",
               (btc_id, json.dumps({"leverage": {"value": "5", "type": "cross", "seen_at": "2026-09-27T14:10:00+00:00"}})))
    db.commit()
    body = client.get('/api/trading/trades').get_json()
    btc = next(t for t in body["trades"] if t["trade_id"] == btc_id)
    assert (btc["status"], btc["leverage"], btc["leverage_type"]) == ("closed", "5", "cross")
    assert btc["open_snapshot"] == {"trend": None, "leverage": {"value": "5", "type": "cross",
                                                                "seen_at": "2026-09-27T14:10:00+00:00"}}


# ── the route ────────────────────────────────────────────────────────────

def test_route_exposes_the_snapshot_and_stays_read_only(db, client):
    seed(db)
    wp._trade_snapshot_pass(db, cap=10)
    calls = len(CURRENT["fake"].calls)
    before = [tuple(r) for r in db.execute("SELECT * FROM trade_annotations ORDER BY trade_id")]
    r = client.get('/api/trading/trades')
    text = r.get_data(as_text=True)
    assert W not in text and W[2:] not in text
    body = r.get_json()
    by = {(t["source"], t["symbol"]): t for t in body["trades"]}
    eth = by[("hyperliquid", "ETH")]["open_snapshot"]
    assert sorted(eth["trend"]["timeframes"]) == sorted(wp.TRADE_SNAPSHOT_PERP_TFS) and eth["leverage"] is None
    assert by[("spot_tx", "NOTHL")]["open_snapshot"]["trend"]["reason"] == "not_on_hyperliquid"
    assert by[("manual", "SOL")]["open_snapshot"] is None and by[("spot_tx", "AAA")]["open_snapshot"] is None
    assert body["unattached_annotations"] == []
    client.get('/api/trading/trades')
    assert [tuple(r) for r in db.execute("SELECT * FROM trade_annotations ORDER BY trade_id")] == before
    assert len(CURRENT["fake"].calls) == calls                                                    # no candle fetch on a read


def test_unattached_ignores_snapshot_only_rows(db, client):
    db.execute("INSERT INTO trade_annotations (trade_id, market, scanner_snapshot_json, created_at, updated_at) "
               "VALUES (?, 'perp', '{}', 'x', 'x')", ("t" + "4" * 20,))
    db.execute("INSERT INTO trade_annotations (trade_id, market, notes, created_at, updated_at) "
               "VALUES (?, 'perp', 'kept', 'x', 'x')", ("t" + "5" * 20,))
    db.commit()
    unattached = client.get('/api/trading/trades').get_json()["unattached_annotations"]
    assert [u["trade_id"] for u in unattached] == ["t" + "5" * 20]


def test_no_wallet_address_in_stored_snapshots(db):
    seed(db)
    wp._trade_snapshot_pass(db, cap=10)
    for (raw,) in db.execute("SELECT scanner_snapshot_json FROM trade_annotations"):
        assert W not in raw and W[2:] not in raw


# ── worker and thread ────────────────────────────────────────────────────

def test_the_fill_sync_thread_runs_sync_then_snapshot(monkeypatch):
    order = []
    monkeypatch.setattr(wp, "_hl_trades_refresh_worker", lambda *a, **k: order.append("sync"))
    monkeypatch.setattr(wp, "_trade_snapshot_worker", lambda: order.append("snapshot"))
    wp._hl_trades_refresh_then_snapshots()
    assert order == ["sync", "snapshot"]


def test_worker_runs_a_pass_and_logs(db, capsys):
    seed(db)
    stats = wp._trade_snapshot_worker()
    assert stats["trend"] + stats["unavailable"] == 4
    assert "[trade-snapshot] leverage+=0 targets+=0 trend+=3 unavailable+=1 failed=0 pending=0" in capsys.readouterr().out


def test_worker_skips_during_a_scan_and_is_single_flight(db):
    seed(db)
    assert wp._NOODLE_SCAN_LOCK.acquire(blocking=False)
    try:
        assert wp._trade_snapshot_worker() is None
    finally:
        wp._NOODLE_SCAN_LOCK.release()
    assert wp._TRADE_SNAPSHOT_LOCK.acquire(blocking=False)
    try:
        assert wp._trade_snapshot_worker() is None
    finally:
        wp._TRADE_SNAPSHOT_LOCK.release()
    assert db.execute("SELECT COUNT(*) FROM trade_annotations").fetchone()[0] == 0


def test_worker_never_raises(db, monkeypatch, capsys):
    monkeypatch.setattr(wp, "_trade_snapshot_pass", lambda conn: 1 / 0)
    assert wp._trade_snapshot_worker() is None
    assert "[trade-snapshot] pass exception ZeroDivisionError" in capsys.readouterr().out
    assert wp._TRADE_SNAPSHOT_LOCK.acquire(blocking=False)                                 # released after the error
    wp._TRADE_SNAPSHOT_LOCK.release()
