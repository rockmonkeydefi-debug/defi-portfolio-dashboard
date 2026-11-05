"""Landing 94: the Messaging settings' scheduled Telegram messages - one entry
per message type (telegram_service.MESSAGE_TYPES) with its own checkbox and
Pacific send time, the settings routes, the per-type test route, the
scheduler's decisions (due_messages / run_scheduled_tick: 3-hour late grace,
sent state recorded before the send, daylight saving) and the two message
builders (Portfolio Value, Risk Gate).

Real init_db() on a tmp_path SQLite file; the settings and sent-state files
point into tmp_path. No network: Telegram's sendMessage is replaced.

web_portfolio spawns a background scheduler on non-__main__ import; we
neutralize threading.Thread.start during import (established pattern).
"""
import json
import threading
from datetime import datetime, timedelta, timezone

import pytest

_orig_start = threading.Thread.start
threading.Thread.start = lambda self, *a, **k: None
try:
    import web_portfolio as wp
finally:
    threading.Thread.start = _orig_start

import src.storage.portfolio_db as portfolio_db
from src.engines import telegram_service as tg

TOKEN = "123456789:AAH" + "x" * 32
UTC = timezone.utc


@pytest.fixture
def files(tmp_path, monkeypatch):
    monkeypatch.setattr(tg, "TELEGRAM_CONFIG_PATH", str(tmp_path / "data" / "telegram_config.json"))
    monkeypatch.setattr(tg, "TELEGRAM_SENT_PATH", str(tmp_path / "data" / "telegram_sent.json"))
    return tmp_path / "data"


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = str(tmp_path / "portfolio.db")
    monkeypatch.setattr(portfolio_db, "get_db_path", lambda: path)
    portfolio_db.init_db()
    conn = portfolio_db.get_connection()
    yield conn
    conn.close()


@pytest.fixture
def sent(monkeypatch):
    """Telegram's sendMessage replaced: every call recorded."""
    calls = []
    monkeypatch.setattr(tg, "send_telegram_message",
                        lambda token, chat, text, timeout=15: calls.append((token, chat, text)) or {"ok": True})
    return calls


@pytest.fixture
def client(files, db, monkeypatch):
    monkeypatch.setattr(wp, "get_password_hash", lambda: "x")
    wp.app.config["TESTING"] = True
    c = wp.app.test_client()
    with c.session_transaction() as s:
        s["authenticated"] = True
    return c


def cfg(enabled=True, **msgs):
    m = tg.default_messages()
    for k, v in msgs.items():
        m[k] = v
    return {"bot_token": TOKEN, "chat_id": "42", "enabled": enabled, "messages": m}


def write_cfg(files, obj):
    files.mkdir(parents=True, exist_ok=True)
    (files / "telegram_config.json").write_text(json.dumps(obj))


def pt(y, mo, d, h, mi):
    """A Pacific wall-clock time as an aware UTC datetime."""
    return datetime(y, mo, d, h, mi, tzinfo=tg.pacific_tz()).astimezone(UTC)


# -- Settings shape -----------------------------------------------------------

def test_defaults_list_every_type_unchecked_at_seven(files):
    c = tg.load_telegram_config()
    assert c == {"bot_token": "", "chat_id": "", "enabled": False,
                 "messages": {k: {"enabled": False, "time": "07:00"} for k in tg.MESSAGE_TYPE_KEYS}}
    assert tg.MESSAGE_TYPE_KEYS == ("portfolio_value", "perps_summary", "watch_list", "risk_gate")    # Landing 95


def test_a_file_from_before_landing_94_converts_on_read(files):
    write_cfg(files, {"bot_token": TOKEN, "chat_id": "42", "enabled": True, "schedule_utc_hour": 9,
                      "include_digest": True, "include_regime": True, "utc_hour": 8,
                      "content": {"daily_digest": True, "market_regime": True}})
    c = tg.load_telegram_config()
    assert c["bot_token"] == TOKEN and c["chat_id"] == "42" and c["enabled"] is True
    assert c["messages"] == tg.default_messages()
    assert not {"schedule_utc_hour", "include_digest", "include_regime", "utc_hour", "content"} & set(c)


def test_a_malformed_stored_entry_falls_back_to_its_default(files):
    write_cfg(files, dict(cfg(), messages={"portfolio_value": {"enabled": "yes", "time": "07:00"},
                                           "risk_gate": {"enabled": True, "time": "25:00"}, "other": 1}))
    assert tg.load_telegram_config()["messages"] == tg.default_messages()


@pytest.mark.parametrize("change,err", [
    ({"bot_token": "abc"}, "Invalid bot token format"),
    ({"bot_token": TOKEN + " "}, "Invalid bot token format"),
    ({"chat_id": "  "}, "Chat ID cannot be empty"),
    ({"enabled": "true"}, "Enabled must be true or false"),
    ({"messages": []}, "messages must be an object"),
    ({"messages": {"daily_digest": {"enabled": True, "time": "07:00"}}}, "Unknown message type: daily_digest"),
    ({"messages": {"risk_gate": {"enabled": True, "time": "07:00", "x": 1}}}, "Risk Gate: expected enabled and time"),
    ({"messages": {"risk_gate": {"enabled": 1, "time": "07:00"}}}, "Risk Gate: enabled must be true or false"),
    ({"messages": {"risk_gate": {"enabled": True, "time": "7:00"}}}, "Risk Gate: time must be HH:MM"),
    ({"messages": {"risk_gate": {"enabled": True, "time": "24:00"}}}, "Risk Gate: time must be HH:MM"),
    ({"messages": {"risk_gate": {"enabled": True, "time": "07:60"}}}, "Risk Gate: time must be HH:MM"),
])
def test_validation_names_the_problem(change, err):
    ok, msg = tg.validate_telegram_config(dict(cfg(), **change))
    assert not ok and msg.startswith(err)


def test_messages_may_leave_types_out_and_keep_their_defaults(files):
    tg.save_telegram_config(dict(cfg(), messages={"risk_gate": {"enabled": True, "time": "06:15"}}))
    m = tg.load_telegram_config()["messages"]
    assert m["risk_gate"] == {"enabled": True, "time": "06:15"} and m["portfolio_value"] == {"enabled": False, "time": "07:00"}


# -- Routes -------------------------------------------------------------------

def test_get_masks_the_token_and_lists_the_types(client, files):
    write_cfg(files, cfg())
    j = client.get("/api/settings/telegram").get_json()
    assert j["bot_token"] == "****" + TOKEN[-4:] and TOKEN not in json.dumps(j)
    assert [t["key"] for t in j["types"]] == list(tg.MESSAGE_TYPE_KEYS) and j["timezone"] == "Pacific"
    assert j["messages"]["portfolio_value"] == {"enabled": False, "time": "07:00"}


def test_save_stores_the_per_type_times(client, files):
    body = cfg(risk_gate={"enabled": True, "time": "06:30"})
    r = client.post("/api/settings/telegram", json=body)
    assert r.status_code == 200 and r.get_json()["messages"]["risk_gate"] == {"enabled": True, "time": "06:30"}
    stored = json.loads((files / "telegram_config.json").read_text())
    assert stored["bot_token"] == TOKEN and stored["messages"]["risk_gate"]["time"] == "06:30"


def test_a_masked_token_keeps_the_stored_one_and_spaces_are_trimmed(client, files):
    write_cfg(files, cfg())
    r = client.post("/api/settings/telegram", json=dict(cfg(), bot_token="****" + TOKEN[-4:], chat_id=" 42 "))
    assert r.status_code == 200
    stored = json.loads((files / "telegram_config.json").read_text())
    assert stored["bot_token"] == TOKEN and stored["chat_id"] == "42"
    new = "987654321:BBH" + "y" * 32
    assert client.post("/api/settings/telegram", json=dict(cfg(), bot_token="  " + new + "\n")).status_code == 200
    assert json.loads((files / "telegram_config.json").read_text())["bot_token"] == new


def test_a_bad_save_is_400_with_the_reason(client, files):
    r = client.post("/api/settings/telegram", json=dict(cfg(), chat_id=""))
    assert r.status_code == 400 and r.get_json()["error"] == "Chat ID cannot be empty"
    assert client.post("/api/settings/telegram", data="x", content_type="application/json").status_code == 400


def test_the_test_route_needs_a_type(client, files, sent):
    write_cfg(files, cfg())
    for body in ({}, {"type": "daily_digest"}, {"type": None}):
        r = client.post("/api/settings/telegram/test", json=body)
        assert r.status_code == 400 and r.get_json()["error"] == "Choose a message type to test."
    assert sent == []


def test_the_test_route_says_what_is_missing(client, files, sent):
    write_cfg(files, dict(cfg(), bot_token=""))
    r = client.post("/api/settings/telegram/test", json={"type": "risk_gate"})
    assert r.status_code == 400 and r.get_json()["error"] == "No bot token saved. Paste it, then Save."
    write_cfg(files, dict(cfg(), chat_id=""))
    r = client.post("/api/settings/telegram/test", json={"type": "risk_gate"})
    assert r.status_code == 400 and r.get_json()["error"] == "No chat ID saved. Paste it, then Save."


def test_the_test_route_sends_that_type_marked_as_a_test(client, files, sent, monkeypatch):
    write_cfg(files, cfg())
    monkeypatch.setattr(wp, "_telegram_build_message", lambda kind, now_utc=None, test=False: "<b>" + kind + "</b>")
    r = client.post("/api/settings/telegram/test", json={"type": "risk_gate"})
    assert r.status_code == 200 and r.get_json()["message"] == "Test sent (1 message(s))"
    assert sent == [(TOKEN, "42", "<i>Test message</i>\n<b>risk_gate</b>")]


def test_telegrams_error_reaches_the_page_without_the_token(client, files, monkeypatch):
    write_cfg(files, cfg())
    monkeypatch.setattr(wp, "_telegram_build_message", lambda kind, now_utc=None, test=False: "x")

    def down(token, chat, text, timeout=15):
        raise RuntimeError("Telegram network error: Max retries exceeded with url: /bot" + token + "/sendMessage")
    monkeypatch.setattr(tg, "send_telegram_message", down)
    r = client.post("/api/settings/telegram/test", json={"type": "risk_gate"})
    assert r.status_code == 400 and TOKEN not in r.get_data(as_text=True)
    assert "Telegram network error" in r.get_json()["error"]
    monkeypatch.setattr(tg, "send_telegram_message",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("Telegram API error: Unauthorized")))
    assert client.post("/api/settings/telegram/test", json={"type": "risk_gate"}).get_json()["error"] == "Telegram API error: Unauthorized"


def test_a_build_failure_is_500_and_sends_nothing(client, files, sent, monkeypatch):
    write_cfg(files, cfg())
    monkeypatch.setattr(wp, "_telegram_build_message", lambda kind, now_utc=None, test=False: 1 / 0)
    r = client.post("/api/settings/telegram/test", json={"type": "portfolio_value"})
    assert r.status_code == 500 and r.get_json()["error"].startswith("Couldn't build the message") and sent == []


# -- Scheduler decisions ------------------------------------------------------

def test_nothing_before_the_time_then_send_at_it():
    c = cfg(risk_gate={"enabled": True, "time": "07:00"})
    assert tg.due_messages(c, {}, pt(2026, 11, 10, 6, 59)) == []
    assert tg.due_messages(c, {}, pt(2026, 11, 10, 7, 0)) == [("risk_gate", "send", "2026-11-10")]


def test_late_by_up_to_three_hours_sends_later_skips():
    c = cfg(risk_gate={"enabled": True, "time": "07:00"})
    assert tg.due_messages(c, {}, pt(2026, 11, 10, 10, 0)) == [("risk_gate", "send", "2026-11-10")]
    assert tg.due_messages(c, {}, pt(2026, 11, 10, 10, 1)) == [("risk_gate", "skip", "2026-11-10")]


def test_handled_today_unchecked_or_master_off_does_nothing():
    c = cfg(risk_gate={"enabled": True, "time": "07:00"})
    assert tg.due_messages(c, {"risk_gate": "2026-11-10"}, pt(2026, 11, 10, 8, 0)) == []
    assert tg.due_messages(c, {"risk_gate": "2026-11-09"}, pt(2026, 11, 10, 8, 0)) == [("risk_gate", "send", "2026-11-10")]
    assert tg.due_messages(cfg(), {}, pt(2026, 11, 10, 8, 0)) == []
    assert tg.due_messages(dict(c, enabled=False), {}, pt(2026, 11, 10, 8, 0)) == []


def test_each_type_keeps_its_own_time():
    c = cfg(portfolio_value={"enabled": True, "time": "06:00"}, risk_gate={"enabled": True, "time": "18:30"})
    assert tg.due_messages(c, {}, pt(2026, 11, 10, 6, 5)) == [("portfolio_value", "send", "2026-11-10")]
    assert tg.due_messages(c, {"portfolio_value": "2026-11-10"}, pt(2026, 11, 10, 18, 30)) == [("risk_gate", "send", "2026-11-10")]


def test_the_time_is_pacific_in_summer_and_winter():
    c = cfg(risk_gate={"enabled": True, "time": "07:00"})
    assert tg.due_messages(c, {}, datetime(2026, 7, 1, 14, 0, tzinfo=UTC))       # 07:00 PDT = 14:00 UTC
    assert not tg.due_messages(c, {}, datetime(2026, 7, 1, 13, 59, tzinfo=UTC))
    assert tg.due_messages(c, {}, datetime(2026, 12, 1, 15, 0, tzinfo=UTC))      # 07:00 PST = 15:00 UTC
    assert not tg.due_messages(c, {}, datetime(2026, 12, 1, 14, 59, tzinfo=UTC))


def test_a_time_in_the_skipped_spring_hour_sends_just_after_it():
    c = cfg(risk_gate={"enabled": True, "time": "02:30"})          # Mar 8, 2026: 02:00 -> 03:00 PDT
    assert tg.due_messages(c, {}, datetime(2026, 3, 8, 9, 59, tzinfo=UTC)) == []          # 01:59 PST
    assert tg.due_messages(c, {}, datetime(2026, 3, 8, 10, 0, tzinfo=UTC)) == [("risk_gate", "send", "2026-03-08")]


def test_a_time_in_the_repeated_autumn_hour_sends_once():
    c = cfg(risk_gate={"enabled": True, "time": "01:30"})          # Nov 1, 2026: 02:00 PDT -> 01:00 PST
    first = datetime(2026, 11, 1, 8, 30, tzinfo=UTC)                # 01:30 PDT
    assert tg.due_messages(c, {}, first) == [("risk_gate", "send", "2026-11-01")]
    assert tg.due_messages(c, {"risk_gate": "2026-11-01"}, first + timedelta(hours=1)) == []   # 01:30 PST


def test_a_late_send_crosses_pacific_midnight():
    c = cfg(risk_gate={"enabled": True, "time": "23:58"})
    assert tg.due_messages(c, {"risk_gate": "2026-11-09"}, pt(2026, 11, 11, 0, 1)) == [("risk_gate", "send", "2026-11-10")]
    assert tg.due_messages(c, {"risk_gate": "2026-11-09"}, pt(2026, 11, 11, 2, 58)) == [("risk_gate", "send", "2026-11-10")]
    assert tg.due_messages(c, {"risk_gate": "2026-11-09"}, pt(2026, 11, 11, 2, 59)) == []        # over 3 hours: lost
    assert tg.due_messages(c, {"risk_gate": "2026-11-10"}, pt(2026, 11, 11, 0, 1)) == []         # yesterday's was sent
    assert tg.due_messages(c, {"risk_gate": "2026-11-10"}, pt(2026, 11, 11, 23, 58)) == [("risk_gate", "send", "2026-11-11")]


def test_the_late_window_around_daylight_saving():
    c = cfg(risk_gate={"enabled": True, "time": "01:30"})
    # Nov 1, 2026: down through both 01:30s; 3 hours after the first one (08:30 UTC) is the limit
    assert tg.due_messages(c, {}, datetime(2026, 11, 1, 11, 30, tzinfo=UTC)) == [("risk_gate", "send", "2026-11-01")]
    assert tg.due_messages(c, {}, datetime(2026, 11, 1, 11, 31, tzinfo=UTC)) == [("risk_gate", "skip", "2026-11-01")]
    c = cfg(risk_gate={"enabled": True, "time": "02:30"})          # Mar 8, 2026: 02:30 does not exist
    assert tg.due_messages(c, {}, datetime(2026, 3, 8, 13, 30, tzinfo=UTC)) == [("risk_gate", "send", "2026-03-08")]
    assert tg.due_messages(c, {}, datetime(2026, 3, 8, 13, 31, tzinfo=UTC)) == [("risk_gate", "skip", "2026-03-08")]


def _arm(old, new, now):
    tg.arm_after_save(old, new, now)
    return tg.due_messages(new, tg.load_sent_state(), now)


def test_ticking_a_type_after_its_time_sends_nothing_until_tomorrow(files):
    old = cfg()
    new = cfg(portfolio_value={"enabled": True, "time": "07:00"})
    assert _arm(old, new, pt(2026, 11, 10, 8, 30)) == []
    assert tg.load_sent_state() == {"portfolio_value": "2026-11-10"}
    assert tg.due_messages(new, tg.load_sent_state(), pt(2026, 11, 11, 7, 0)) == [("portfolio_value", "send", "2026-11-11")]


def test_ticking_before_its_time_still_sends_today(files):
    new = cfg(portfolio_value={"enabled": True, "time": "09:00"})
    assert _arm(cfg(), new, pt(2026, 11, 10, 8, 30)) == []
    assert tg.due_messages(new, tg.load_sent_state(), pt(2026, 11, 10, 9, 0)) == [("portfolio_value", "send", "2026-11-10")]


def test_changing_a_time_or_turning_messages_on_never_sends_at_once(files):
    old = cfg(risk_gate={"enabled": True, "time": "09:00"})
    new = cfg(risk_gate={"enabled": True, "time": "07:00"})
    assert _arm(old, new, pt(2026, 11, 10, 8, 0)) == []
    files.joinpath("telegram_sent.json").unlink()
    on = cfg(risk_gate={"enabled": True, "time": "07:00"})
    assert _arm(dict(on, enabled=False), on, pt(2026, 11, 10, 8, 0)) == []
    files.joinpath("telegram_sent.json").unlink()
    late = cfg(risk_gate={"enabled": True, "time": "23:58"})          # just after midnight: yesterday's 23:58
    assert _arm(cfg(), late, pt(2026, 11, 11, 0, 5)) == [] and tg.load_sent_state() == {"risk_gate": "2026-11-10"}


def test_a_save_that_changes_nothing_about_a_type_does_not_arm_it(files):
    c = cfg(risk_gate={"enabled": True, "time": "07:00"})
    tg.arm_after_save(c, dict(c, chat_id="43"), pt(2026, 11, 10, 8, 0))
    assert tg.load_sent_state() == {}
    assert tg.due_messages(c, {}, pt(2026, 11, 10, 8, 0)) == [("risk_gate", "send", "2026-11-10")]


def test_the_save_route_arms_a_newly_ticked_type(client, files, monkeypatch):
    write_cfg(files, cfg())
    r = client.post("/api/settings/telegram", json=cfg(risk_gate={"enabled": True, "time": "00:00"}))
    assert r.status_code == 200
    today = datetime.now(UTC).astimezone(tg.pacific_tz()).date().isoformat()
    assert tg.load_sent_state() == {"risk_gate": today}                  # 00:00 has always passed today


def test_the_date_is_recorded_before_the_send(files, monkeypatch):
    write_cfg(files, cfg(risk_gate={"enabled": True, "time": "07:00"}))
    seen = []

    def build(kind, test=False):
        seen.append(tg.load_sent_state())
        return "x"

    def boom(*a, **k):
        raise RuntimeError("Telegram API error: Bad Request")
    monkeypatch.setattr(tg, "send_telegram_message", boom)
    out = tg.run_scheduled_tick(pt(2026, 11, 10, 7, 0), build)
    assert seen == [{"risk_gate": "2026-11-10"}]
    assert out == [("risk_gate", "failed", "Telegram API error: Bad Request")]
    assert tg.run_scheduled_tick(pt(2026, 11, 10, 7, 1), build) == []        # never a second copy


def test_one_type_failing_never_stops_the_other(files, sent):
    write_cfg(files, cfg(portfolio_value={"enabled": True, "time": "07:00"}, risk_gate={"enabled": True, "time": "07:00"}))

    def build(kind, test=False):
        if kind == "portfolio_value":
            raise ValueError("no data")
        return "gate"
    out = tg.run_scheduled_tick(pt(2026, 11, 10, 7, 0), build)
    assert out == [("portfolio_value", "failed", "no data"), ("risk_gate", "send", None)]
    assert [t for _tok, _c, t in sent] == ["gate"]
    assert tg.load_sent_state() == {"portfolio_value": "2026-11-10", "risk_gate": "2026-11-10"}


def test_a_skip_is_recorded_and_sends_nothing(files, sent):
    write_cfg(files, cfg(risk_gate={"enabled": True, "time": "07:00"}))
    assert tg.run_scheduled_tick(pt(2026, 11, 10, 15, 0), lambda k, test=False: "x") == [("risk_gate", "skip", None)]
    assert sent == [] and tg.load_sent_state() == {"risk_gate": "2026-11-10"}


def test_an_unreadable_sent_file_reads_as_empty(files):
    files.mkdir(parents=True, exist_ok=True)
    (files / "telegram_sent.json").write_text("not json")
    assert tg.load_sent_state() == {}


def test_escape_and_split():
    assert tg.html_escape("A&B <x> \"q\"") == "A&amp;B &lt;x&gt; \"q\""
    assert tg.split_message("short") == ["short"]
    parts = tg.split_message("\n".join(["line %03d" % i for i in range(1000)]), limit=100)
    assert all(len(p) <= 100 for p in parts) and "\n".join(parts) == "\n".join(["line %03d" % i for i in range(1000)])
    assert tg.split_message("x" * 250, limit=100) == ["x" * 100, "x" * 100, "x" * 50]


def test_a_long_message_goes_out_in_pieces(files, sent):
    n = tg.send_message_type(cfg(), "risk_gate", lambda k, test=False: "\n".join(["y" * 90] * 100))
    assert n == len(sent) == 3 and all(len(t) <= tg.TELEGRAM_MAX_LENGTH for _a, _b, t in sent)


def test_the_app_starts_one_messages_thread_with_its_own_builder(monkeypatch):
    started = []
    monkeypatch.undo()                                        # conftest's no-op spawner off: the real one runs
    monkeypatch.setattr(threading.Thread, "start", lambda self: started.append((self.name, self._target, self._args)))
    wp._spawn_telegram_messages_thread()
    assert started == [("telegram-messages", tg.messages_loop, (wp._telegram_build_message, wp._telegram_after_send))]
    src = open(wp.__file__, encoding="utf-8").read()
    assert "    start_scheduler(_get_portfolio_data_for_snapshot, get_wallet_addresses, compose_total_fn=_compose_total_for_snapshot)\n    _spawn_telegram_messages_thread()\n" in src
    loop = open(tg.__file__, encoding="utf-8").read().split("def messages_loop(build_fn, after_send=None)", 1)[1]
    assert "web_portfolio" not in loop                        # run as a script, that would start a second scheduler


# -- Message builders ---------------------------------------------------------

def add_total(db, hours_ago, total, version=3, now=None, **kw):
    now = now or datetime.utcnow()
    row = dict(timestamp=(now - timedelta(hours=hours_ago)).isoformat(), status="completed",
               definition_version=version, total_usd=total, snapshot_total_usd=total, hyperliquid_usd=0,
               hl_counted=1, wallets_total=2, wallets_completed=2)
    row.update(kw)
    cols = ",".join(row)
    db.execute(f"INSERT INTO portfolio_total_snapshots ({cols}) VALUES ({','.join('?' * len(row))})", list(row.values()))
    db.commit()


def test_portfolio_value_shows_the_total_and_its_24h_change(db):
    now = datetime.utcnow()
    add_total(db, 31, 90000.0, now=now)                                 # 30 h before the latest: outside 20-28 h
    add_total(db, 25, 100000.0, now=now)
    add_total(db, 12, 101000.0, now=now, wallets_completed=1)          # left out (a wallet failed)
    add_total(db, 1, 101500.0, now=now)
    text = wp._telegram_portfolio_value_text(now.replace(tzinfo=UTC))
    lines = text.split("\n")
    assert lines[0] == "<b>Portfolio Value</b>"
    assert lines[1].startswith("Total: $101,500 (as of ") and ("PST" in lines[1] or "PDT" in lines[1])
    assert lines[2] == "24h: +$1,500 (+1.5%)"


def test_portfolio_value_with_no_data_old_data_or_a_definition_change(db):
    now = datetime.utcnow()
    assert wp._telegram_portfolio_value_text(now.replace(tzinfo=UTC)).endswith("No complete portfolio total in the last 3 days.")
    add_total(db, 10, 5000.0, now=now)
    t = wp._telegram_portfolio_value_text(now.replace(tzinfo=UTC))
    assert "Note: the latest complete run is 10 hours old." in t and "24h: no complete run 20 to 28 hours earlier." in t
    add_total(db, 34, 4000.0, version=2, now=now)
    t = wp._telegram_portfolio_value_text(now.replace(tzinfo=UTC))
    assert "24h: not comparable (the total's definition changed)." in t
    add_total(db, 26, 5000.0, now=now)
    add_total(db, 2, 4500.0, now=now)
    assert "24h: -$500 (-10.0%)" in wp._telegram_portfolio_value_text(now.replace(tzinfo=UTC))


def test_risk_gate_lists_the_count_and_four_checks(db, monkeypatch):
    monkeypatch.setattr(wp, "_perp_risk_gate", lambda conn: {
        "unlocked": False, "eligible_count": 3, "target": 20, "expectancy_r": "0.450000", "min_avg_r": "0.2",
        "recent_n": 20, "recent_expectancy_r": None, "pending_reviews": 1, "count_from": "2026-10-05",
        "checks": {"count": False, "average": True, "recent": False, "reviews": False}})
    lines = wp._telegram_risk_gate_text().split("\n")
    assert lines == ["<b>Risk Gate</b>", "Status: Locked",
                     "\u274c Counted trades: 3 of 20",
                     "\u2705 Average: +0.45R (needs above +0.20R)",
                     "\u274c Last 20: n/a (needs above 0R)",
                     "\u274c Trades awaiting review: 1",
                     "Counting trades opened since 2026-10-05."]


def test_risk_gate_runs_on_the_real_gate_with_no_trades(db):
    t = wp._telegram_risk_gate_text()
    assert t.startswith("<b>Risk Gate</b>\nStatus: Locked\n") and "Counted trades: 0 of 20" in t


def test_build_message_knows_only_the_types(db):
    with pytest.raises(ValueError):
        wp._telegram_build_message("daily_digest")


def test_the_settings_card_is_wired_to_the_routes():
    import os
    js = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static", "settings.js"), encoding="utf-8").read()
    card = js.split("function MessagingSection() {", 1)[1].split("// \u2500\u2500 Main Settings Screen", 1)[0]
    assert "api('/api/settings/telegram/test', { method: 'POST', body: JSON.stringify({ type }) })" in card
    assert "const types = cfg.types || [];" in card and "type: 'time', step: 60" in card
    assert "msgErrorText(e," in card and "'Failed to send'" not in card       # the server's own error text shows
    assert "utc_hour" not in card and "daily_digest" not in card              # the old, never-read keys are gone


def test_portfolio_value_compares_only_with_a_run_20_to_28_hours_earlier(db):
    now = datetime.utcnow()
    add_total(db, 13, 1000.0, now=now)                                  # 12 h before the latest
    add_total(db, 31, 900.0, now=now)                                   # 30 h before the latest
    add_total(db, 1, 1100.0, now=now)
    assert "24h: no complete run 20 to 28 hours earlier." in wp._telegram_portfolio_value_text(now.replace(tzinfo=UTC))


def test_after_send_runs_only_for_a_scheduled_send_that_went_out(sent, monkeypatch):
    calls = []
    tg.send_message_type(cfg(), "watch_list", lambda k, test=False: "x", test=True, after_send=calls.append)
    assert calls == []                                                      # a test never keeps a baseline
    tg.send_message_type(cfg(), "watch_list", lambda k, test=False: "x", after_send=calls.append)
    assert calls == ["watch_list"]
    monkeypatch.setattr(tg, "send_telegram_message", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")))
    with pytest.raises(RuntimeError):
        tg.send_message_type(cfg(), "watch_list", lambda k, test=False: "x", after_send=calls.append)
    assert calls == ["watch_list"]                                          # a failed send keeps nothing
