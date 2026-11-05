"""Landing 95: the Telegram Perps Summary and Watch List messages.

Perps: open positions from the Open Perps card's data (_perps_open_payload),
R and closed trades from the Trade Log (_trades_build); both replaced here.
Watch List: the page's view (_watch_view) and prices replaced; the respected
label is a port of the page's rule (pinned to the page's constants below);
"what changed" compares with the state the last scheduled message stored.

web_portfolio spawns a background scheduler on non-__main__ import; we
neutralize threading.Thread.start during import (established pattern).
"""
import json
import os
import re
import threading
from datetime import datetime, timedelta, timezone

import pytest

_orig_start = threading.Thread.start
threading.Thread.start = lambda self, *a, **k: None
try:
    import web_portfolio as wp
finally:
    threading.Thread.start = _orig_start

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UTC = timezone.utc
NOW = datetime(2026, 11, 10, 15, 0, tzinfo=UTC)


def _js(name):
    with open(os.path.join(ROOT, "static", name), encoding="utf-8") as f:
        return f.read()


# -- The port stays in step with the page --------------------------------------

def test_the_respected_rule_constants_match_the_page():
    trends = _js("trends.js")
    assert f"const TRENDS_RESPECT_MIN_TAGS = {wp.WATCH_MSG_RESPECT_MIN_TAGS};" in trends
    assert f"const TRENDS_RESPECT_WINDOW_BARS = {wp.WATCH_MSG_RESPECT_WINDOW_BARS};" in trends
    assert f"const TRENDS_RESPECT_MAX_LOSSES = {wp.WATCH_MSG_RESPECT_MAX_LOSSES};" in trends
    assert "const TRENDS_RESPECT_TFS = ['1d', '12h', '4h', '1h'];" in trends and wp.WATCH_MSG_RESPECT_TFS == ('1d', '12h', '4h', '1h')
    assert "const TRENDS_RESPECT_TF_SECONDS = { '1d': 86400, '12h': 43200, '4h': 14400, '1h': 3600 };" in trends
    assert wp.WATCH_MSG_RESPECT_TF_SECONDS == {'1d': 86400, '12h': 43200, '4h': 14400, '1h': 3600}
    # the rule's own lines, so a change to how the page judges a timeframe fails here too
    cell = trends.split("function _trendsRespectCell(r, tfKey, nowMs) {", 1)[1].split("\n}\n", 1)[0]
    for line in ("const lastClosedOpen = Math.floor(computedSec / tfSec) * tfSec - tfSec;",
                 "if (flatBars >= TRENDS_RESPECT_WINDOW_BARS) return null;",
                 "if (typeof r.respect_tags !== 'number' || r.respect_tags < TRENDS_RESPECT_MIN_TAGS) return null;",
                 "if (typeof r.respect_losses !== 'number' || r.respect_losses > TRENDS_RESPECT_MAX_LOSSES) return null;",
                 "const barsAgo = Math.max(0, Math.round((lastClosedOpen - r.respect_last_ts) / tfSec));",
                 "status: barsAgo < TRENDS_RESPECT_WINDOW_BARS ? 'pass' : 'stale',"):
        assert line in cell, line
    wl = _js("watchlist.js")
    assert "const WL_RESPECT_TFS = ['1d', '12h', '4h', '1h'];" in wl
    assert "const WL_ROW_TFS = ['1w', '1d', '12h', '4h', '1h'];" in wl and wp.WATCH_MSG_ROW_TFS == ('1w', '1d', '12h', '4h', '1h')
    assert "if (cell && cell.status === 'pass' && (!best || cell.tags > best.cell.tags)) best = { tf, cell };" in wl
    assert "const SPOT_TREND_TFS = [['4h', '4H'], ['12h', '12H'], ['1d', '1D'], ['1w', '1W']];" in _js("spotpnl.js")
    assert wp.WATCH_MSG_DOT_TFS == (('4h', '4H'), ('12h', '12H'), ('1d', '1D'), ('1w', '1W'))


# -- The respected label ---------------------------------------------------------

def row(tf, *, bars_ago=2, tags=3, losses=0, dir="BULLISH", **kw):
    """A noodle row for timeframe tf computed at NOW whose latest tag is bars_ago closed bars back."""
    sec = wp.WATCH_MSG_RESPECT_TF_SECONDS[tf]
    last_closed_open = (int(NOW.timestamp()) // sec) * sec - sec
    r = {"computed_at": NOW.isoformat(), "respect_dir": dir, "respect_since": last_closed_open - 50 * sec,
         "respect_tags": tags, "respect_losses": losses, "respect_last_ts": last_closed_open - bars_ago * sec}
    r.update(kw)
    return r


def test_the_cell_follows_the_pages_rule():
    assert wp._watch_respect_cell(None, "1d") is None
    assert wp._watch_respect_cell(row("1d"), "1d") == {"status": "pass", "dir": "BULLISH", "tags": 3}
    assert wp._watch_respect_cell(row("1d", bars_ago=29), "1d")["status"] == "pass"
    assert wp._watch_respect_cell(row("1d", bars_ago=30), "1d")["status"] == "stale"
    assert wp._watch_respect_cell(row("4h", tags=1), "4h") is None
    assert wp._watch_respect_cell(row("4h", losses=2), "4h") is None
    assert wp._watch_respect_cell(row("4h", dir="SIDEWAYS"), "4h") is None
    assert wp._watch_respect_cell(row("4h", respect_last_ts=None), "4h") is None
    assert wp._watch_respect_cell(row("4h", computed_at=None), "4h") is None
    sec = 14400
    lco = (int(NOW.timestamp()) // sec) * sec - sec
    assert wp._watch_respect_cell(row("4h", respect_dir=None, respect_ranging_since=lco - 5 * sec), "4h") == {"status": "ranging"}
    assert wp._watch_respect_cell(row("4h", respect_dir=None, respect_ranging_since=lco - 30 * sec), "4h") is None
    assert wp._watch_respect_cell(row("4h", respect_dir=None), "4h") is None


def test_the_label_takes_the_most_tags_then_the_longer_timeframe():
    assert wp._watch_respected_label(None) == "No respected trend"
    assert wp._watch_respected_label({"4h": row("4h", tags=5), "1d": row("1d", tags=3)}) == "Respected 4H Bullish (5 tags)"
    assert wp._watch_respected_label({"4h": row("4h", tags=3), "1d": row("1d", tags=3, dir="BEARISH")}) == "Respected 1D Bearish (3 tags)"
    assert wp._watch_respected_label({"1d": row("1d", bars_ago=40)}) == "No respected trend"     # stale never counts
    assert wp._watch_respected_label({"1w": row("1d")}) == "No respected trend"                  # 1W is not a respect timeframe


def test_the_trend_source_is_the_newer_of_scanner_and_check():
    sc = {"scanner_symbol": "WIF", "as_of": "2026-11-10T10:00:00", "timeframes": {"1d": {"position": "above"}}}
    ck = {"computed_at": "2026-11-10T12:00:00", "price": 1.5, "timeframes": {"1d": {"position": "below"}}}
    assert wp._watch_trend_source({"scanner": sc, "check": ck})["1d"]["position"] == "below"
    assert wp._watch_trend_source({"scanner": dict(sc, as_of="2026-11-10T13:00:00"), "check": ck})["1d"]["position"] == "above"
    assert wp._watch_trend_source({"scanner": sc, "check": None})["1d"]["position"] == "above"
    assert wp._watch_trend_source({"scanner": {"timeframes": {}}, "check": {"timeframes": {}}}) is None


def test_the_price_falls_back_like_the_page():
    sc = {"scanner_symbol": "WIF", "timeframes": {"4h": {"price": 2.0}, "1h": {"price": 2.1}}}
    it = {"name": "WIF", "scanner": sc, "check": {"price": 1.5}}
    assert wp._watch_item_price(it, 2.5) == (2.5, "live")
    assert wp._watch_item_price(it, None) == (2.1, "scanner")                      # the 1h row first
    assert wp._watch_item_price(dict(it, scanner=dict(sc, scanner_symbol="KWIF")), None) == (1.5, "check")   # a kilo market's price is not the token's
    assert wp._watch_item_price({"name": "X", "scanner": None, "check": None}, None) == (None, None)


# -- The Watch List message ------------------------------------------------------

@pytest.fixture
def watch(tmp_path, monkeypatch):
    monkeypatch.setattr(wp, "TELEGRAM_WATCH_STATE_PATH", str(tmp_path / "data" / "telegram_watch_state.json"))
    state = {"items": [], "prices": {}}
    monkeypatch.setattr(wp, "_watch_view", lambda conn: {"items": state["items"]})
    monkeypatch.setattr(wp, "_watch_live_prices", lambda active: {i["key"]: state["prices"].get(i["key"]) for i in active})
    monkeypatch.setattr(wp, "_TELEGRAM_PENDING_STATE", {})
    return state


def sent_watch(now):
    """A scheduled Watch List message that went out: build, then keep its state (as the scheduler does)."""
    text = wp._telegram_watch_list_text(now)
    wp._telegram_after_send("watch_list")
    return text


def item(key, name, *, active=True, pos=None, tfs_extra=None, chain="Solana"):
    tfs = {tf: {"position": p} for tf, p in (pos or {}).items()}
    for tf, r in (tfs_extra or {}).items():
        tfs.setdefault(tf, {}).update(r)
    return {"key": key, "name": name, "chain_label": chain, "active": active,
            "scanner": {"scanner_symbol": name, "as_of": NOW.isoformat(), "timeframes": tfs} if tfs else None, "check": None}


def test_the_first_message_lists_the_active_tokens_and_stores_the_baseline(watch):
    watch["items"] = [item("notes-w1", "WIF", pos={"4h": "above", "12h": "touch", "1d": "below", "1w": "above"},
                           tfs_extra={"1d": row("1d", tags=4)}),
                      item("notes-w2", "Parked", active=False),
                      item("notes-w3", "A<B&C")]
    watch["prices"] = {"notes-w1": 1.84}
    lines = sent_watch(NOW).split("\n")
    assert lines[0] == "<b>Watch List</b>" and lines[1] == "First Watch List message: nothing to compare yet."
    assert lines[2] == "<b>Active (2)</b>"
    assert lines[3] == "  <b>WIF</b> \u00b7 Solana \u00b7 $1.84"
    assert lines[4] == "    4H above 12H touching 1D below 1W above \u00b7 Respected 1D Bullish (4 tags)"
    assert lines[5] == "  <b>A&lt;B&amp;C</b> \u00b7 Solana \u00b7 no price"
    assert lines[6] == "    4H n/a 12H n/a 1D n/a 1W n/a \u00b7 No respected trend"
    assert "Parked" not in "\n".join(lines)
    stored = json.load(open(wp.TELEGRAM_WATCH_STATE_PATH))
    assert set(stored["items"]) == {"notes-w1", "notes-w3"} and stored["items"]["notes-w1"]["price"] == 1.84


def test_the_next_message_says_what_changed(watch):
    watch["items"] = [item("notes-w1", "WIF", pos={"4h": "above", "1d": "above"}),
                      item("notes-w2", "BONK", pos={"4h": "below"})]
    watch["prices"] = {"notes-w1": 2.0, "notes-w2": 0.00002}
    sent_watch(NOW)
    watch["items"] = [item("notes-w1", "WIF", pos={"4h": "above", "1d": "below"}, tfs_extra={"4h": row("4h", tags=2)}),
                      item("notes-w2", "BONK", pos={"4h": "below"}),
                      item("notes-w4", "NEW")]
    watch["prices"] = {"notes-w1": 2.2, "notes-w2": 0.0000204}
    text = sent_watch(NOW + timedelta(days=1))
    changed = text.split("<b>Changed since the last message</b>\n", 1)[1].split("\n<b>Active", 1)[0].split("\n")
    assert changed == ["  WIF: 1D above \u2192 below",
                       "  WIF: Respected 4H Bullish (2 tags) (was No respected trend)",
                       "  WIF: price +10.0%",
                       "  NEW: new on the list"]                          # BONK moved 2%: under the 5% bar
    assert "  <b>BONK</b> \u00b7 Solana \u00b7 $0.00002040" in text


def test_prices_read_well_for_large_and_tiny_coins():
    assert [wp._telegram_price(v) for v in (98765.4, 1.0, 0.5, 0.012345, 0.0000123456, 0)] == \
        ["$98,765.40", "$1.00", "$0.5000", "$0.01235", "$0.00001235", "$0"]


def test_nothing_changed_says_so(watch):
    watch["items"] = [item("notes-w1", "WIF", pos={"4h": "above"})]
    watch["prices"] = {"notes-w1": 2.0}
    sent_watch(NOW)
    assert "<b>Changed since the last message</b>\n  Nothing.\n" in sent_watch(NOW)


def test_a_send_test_leaves_the_baseline_alone(watch):
    watch["items"] = [item("notes-w1", "WIF", pos={"4h": "above"})]
    watch["prices"] = {"notes-w1": 2.0}
    wp._telegram_build_message("watch_list", NOW, test=True)
    wp._telegram_after_send("watch_list")
    assert not os.path.exists(wp.TELEGRAM_WATCH_STATE_PATH)
    wp._telegram_build_message("watch_list", NOW)
    wp._telegram_after_send("watch_list")
    watch["prices"] = {"notes-w1": 3.0}
    assert "price +50.0%" in wp._telegram_build_message("watch_list", NOW, test=True)
    assert json.load(open(wp.TELEGRAM_WATCH_STATE_PATH))["items"]["notes-w1"]["price"] == 2.0


def test_a_failed_send_keeps_the_previous_baseline(watch, tmp_path, monkeypatch):
    from src.engines import telegram_service as tg
    monkeypatch.setattr(tg, "TELEGRAM_CONFIG_PATH", str(tmp_path / "data" / "telegram_config.json"))
    monkeypatch.setattr(tg, "TELEGRAM_SENT_PATH", str(tmp_path / "data" / "telegram_sent.json"))
    m = tg.default_messages()
    m["watch_list"] = {"enabled": True, "time": "07:00"}
    tg.save_telegram_config({"bot_token": "123456789:AAH" + "x" * 32, "chat_id": "42", "enabled": True, "messages": m})
    watch["items"] = [item("notes-w1", "WIF", pos={"4h": "above"})]
    watch["prices"] = {"notes-w1": 2.0}
    sent_log = []
    monkeypatch.setattr(tg, "send_telegram_message", lambda *a, **k: sent_log.append(a) or {"ok": True})
    at = datetime(2026, 11, 10, 7, 0, tzinfo=tg.pacific_tz()).astimezone(UTC)
    assert tg.run_scheduled_tick(at, wp._telegram_build_message, wp._telegram_after_send) == [("watch_list", "send", None)]
    assert json.load(open(wp.TELEGRAM_WATCH_STATE_PATH))["items"]["notes-w1"]["price"] == 2.0
    watch["prices"] = {"notes-w1": 3.0}
    monkeypatch.setattr(tg, "send_telegram_message", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("Telegram API error: Bad Gateway")))
    out = tg.run_scheduled_tick(at + timedelta(days=1), wp._telegram_build_message, wp._telegram_after_send)
    assert out == [("watch_list", "failed", "Telegram API error: Bad Gateway")]
    assert json.load(open(wp.TELEGRAM_WATCH_STATE_PATH))["items"]["notes-w1"]["price"] == 2.0     # not the unsent 3.0
    assert "WIF: price +50.0%" in wp._telegram_watch_list_text(at + timedelta(days=2))             # still reported next time


def test_a_gap_day_keeps_the_last_value_seen(watch):
    watch["items"] = [item("notes-w1", "WIF", pos={"1d": "above"})]
    watch["prices"] = {"notes-w1": 2.0}
    sent_watch(NOW)
    watch["items"] = [item("notes-w1", "WIF")]                          # no scanner row, no price today
    watch["prices"] = {}
    assert "Nothing." in sent_watch(NOW + timedelta(days=1))
    watch["items"] = [item("notes-w1", "WIF", pos={"1d": "below"})]
    watch["prices"] = {"notes-w1": 3.0}
    text = sent_watch(NOW + timedelta(days=2))
    assert "WIF: 1D above \u2192 below" in text and "WIF: price +50.0%" in text


def test_prices_from_different_sources_are_not_compared(watch):
    it = item("notes-w1", "WIF", pos={"1h": "above"}, tfs_extra={"1h": {"price": 1.0}})
    watch["items"] = [it]
    watch["prices"] = {"notes-w1": 2.0}                                # live
    sent_watch(NOW)
    watch["prices"] = {}                                               # DexScreener did not answer: the scanner's price
    assert "price" not in sent_watch(NOW + timedelta(days=1)).split("<b>Active")[0]


def test_exactly_five_percent_counts_and_names_are_escaped_in_changes(watch):
    watch["items"] = [item("notes-w1", "A<B", pos={"4h": "above"})]
    watch["prices"] = {"notes-w1": 2.0}
    sent_watch(NOW)
    watch["prices"] = {"notes-w1": 2.1}
    assert "  A&lt;B: price +5.0%" in sent_watch(NOW + timedelta(days=1))


def test_no_active_tokens(watch):
    assert "<b>Active (0)</b>\n  No Active tokens." in wp._telegram_watch_list_text(NOW)


# -- The Perps Summary -----------------------------------------------------------

@pytest.fixture
def perps(monkeypatch):
    data = {"positions": [], "venues": [{"venue": "Hyperliquid", "status": "ok"}], "trades": []}
    monkeypatch.setattr(wp, "_perps_open_payload", lambda: {"positions": data["positions"], "venues": data["venues"]})
    monkeypatch.setattr(wp, "_trades_build", lambda conn: (data["trades"], {}))
    monkeypatch.setattr(wp, "get_connection", lambda: None, raising=False)
    import src.storage.portfolio_db as pdb

    class _C:
        def close(self):
            pass
    monkeypatch.setattr(pdb, "get_connection", lambda: _C())
    return data


def pos(coin="BTC", direction="long", venue="Hyperliquid", label="Desktop Hot", upnl="412", margin="5000",
        dist="-3.1", flags=(), stale=False):
    return {"coin": coin, "direction": direction, "venue": venue, "wallet_label": label, "unrealized_pnl": upnl,
            "margin_used": margin, "stop_distance_pct": dist, "flags": list(flags), "stale": stale}


def trade(coin="BTC", direction="long", venue="Hyperliquid", label="Desktop Hot", status="open", stop="95000",
          entry="100000", peak="0.14", net=None, r=None, close_ms=None):
    return {"market": "perp", "status": status, "symbol": coin, "direction": direction, "venue": venue,
            "wallet_label": label, "stop": {"px": stop} if stop else None, "avg_entry": entry, "size_peak": peak,
            "net_pnl": net, "r_multiple": r, "_close_ms": close_ms}


def test_an_open_position_shows_pnl_margin_r_and_stop(perps):
    perps["positions"] = [pos()]
    perps["trades"] = [trade()]
    lines = wp._telegram_perps_summary_text(NOW).split("\n")
    assert lines[:4] == ["<b>Perps Summary</b>",
                         "<b>BTC long \u00b7 Hyperliquid (Desktop Hot)</b>",
                         "  P&amp;L: +$412 (+8.2% on margin) \u00b7 +0.59R",        # 412 / (5000 x 0.14 = 700)
                         "  Stop: 3.1% away"]
    assert lines[4:] == ["<b>Closed in the last 24h</b>", "  None."]


def test_no_stop_untracked_unreadable_and_stale(perps):
    perps["positions"] = [pos(coin="ETH", direction="short", label="Plazm", flags=("no_stop",), dist=None),
                          pos(coin="SOL", venue="TxFlow", label="TX", flags=("open_orders_unavailable",), dist=None, stale=True),
                          pos(coin="DOGE", upnl=None, margin=None, dist="2.0", flags=("stop_partial",))]
    perps["trades"] = [trade(coin="ETH", direction="short", label="Plazm", stop=None)]
    text = wp._telegram_perps_summary_text(NOW)
    assert "<b>ETH short \u00b7 Hyperliquid (Plazm)</b>\n  P&amp;L: +$412 (+8.2% on margin) \u00b7 no stop set\n  Stop: none on the venue" in text
    assert "<b>SOL long \u00b7 TxFlow (TX) [stale]</b>\n  P&amp;L: +$412 (+8.2% on margin) \u00b7 not in the Trade Log yet\n  Stop: couldn't read the venue's orders" in text
    assert "<b>DOGE long \u00b7 Hyperliquid (Desktop Hot)</b>\n  P&amp;L: n/a \u00b7 not in the Trade Log yet\n  Stop: 2.0% away (covers part of the position)" in text


def test_a_trade_matches_only_its_own_venue_wallet_coin_and_side(perps):
    perps["positions"] = [pos()]
    perps["trades"] = [trade(direction="short"), trade(label="Other"), trade(venue="TxFlow"), trade(status="closed")]
    assert "not in the Trade Log yet" in wp._telegram_perps_summary_text(NOW)


def test_venues_not_loaded(perps):
    perps["venues"] = [{"venue": "Hyperliquid", "status": "loading"}, {"venue": "TxFlow", "status": "ok"}]
    assert "No open positions read yet (Hyperliquid not loaded)." in wp._telegram_perps_summary_text(NOW)
    perps["positions"] = [pos()]
    assert "Hyperliquid not loaded yet: its positions may be missing." in wp._telegram_perps_summary_text(NOW)
    perps["venues"] = [{"venue": "Hyperliquid", "status": "ok"}]
    perps["positions"] = []
    assert "\nNo open positions.\n" in wp._telegram_perps_summary_text(NOW)


def test_trades_closed_in_the_last_24_hours(perps):
    ms = lambda dt: int(dt.timestamp() * 1000)
    perps["trades"] = [trade(coin="SOL", status="closed", net="230.5", r="1.4", close_ms=ms(NOW - timedelta(hours=3))),
                       trade(coin="ARB", direction="short", status="closed", net="-80", r=None, close_ms=ms(NOW - timedelta(hours=20))),
                       trade(coin="OLD", status="closed", net="10", r="0.1", close_ms=ms(NOW - timedelta(hours=25))),
                       dict(trade(coin="SPOT", status="closed", net="5", close_ms=ms(NOW)), market="spot")]
    closed = wp._telegram_perps_summary_text(NOW).split("<b>Closed in the last 24h</b>\n", 1)[1].split("\n")
    assert closed == ["  ARB short: -$80", "  SOL long: +$230 (+1.40R)"]


def test_build_message_routes_the_new_types(perps, watch):
    assert wp._telegram_build_message("perps_summary", NOW).startswith("<b>Perps Summary</b>")
    assert wp._telegram_build_message("watch_list", NOW).startswith("<b>Watch List</b>")


def test_the_open_perps_route_still_answers_from_the_extracted_body(monkeypatch):
    monkeypatch.setattr(wp, "_perps_open_payload", lambda: {"positions": [], "totals": {}, "venues": []})
    monkeypatch.setattr(wp, "get_password_hash", lambda: "x")
    c = wp.app.test_client()
    with c.session_transaction() as s:
        s["authenticated"] = True
    assert c.get("/api/trading/perps/open").get_json() == {"positions": [], "totals": {}, "venues": []}
    monkeypatch.setattr(wp, "_perps_open_payload", lambda: 1 / 0)
    assert c.get("/api/trading/perps/open").status_code == 500


def test_the_prices_route_uses_the_shared_lookup(monkeypatch):
    src = open(wp.__file__, encoding="utf-8").read()
    route = src.split("def api_watchlist_prices():", 1)[1].split("\n@app.route", 1)[0]
    assert "prices = _watch_live_prices(active)" in route and "ThreadPoolExecutor" not in route
