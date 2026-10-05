"""Advisor v1, Landing 8c-2: the exit reason for a revised exit.

- PUT /api/trading/trades/<trade_id>/annotation takes exit_reason (a key from
  perp_rules.EXIT_REASONS, or null) and exit_reason_note, for closed perp
  trades only; "other" needs a note; clearing the reason clears the note.
- An earlier key / note goes to note_revisions (kinds trade_exit_reason and
  trade_exit_reason_note), which a pre-8c-2 database gets by a one-time
  rebuild of note_revisions (rows, ids, counter and index kept).
- The trades route carries both fields; X1 passes once a reason is saved.
- static/perpsrules.js lists the same keys and labels as the engine.

Reuses the route fixtures of tests/test_perp_rules.py (BTC trigger exit, ETH
revised exit by a market order, SOL open, DOGE manual perp). No network.
"""
import os
import re
import sqlite3

import pytest

from test_perp_rules import db, client, advisor, ids_by_symbol, by_rule  # noqa: F401  (fixtures)
import web_portfolio as wp
import src.storage.portfolio_db as portfolio_db
from src.engines import perp_rules as pr

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def put(client, tid, body):
    return client.put('/api/trading/trades/' + tid + '/annotation', json=body)


def get_trades(client, monkeypatch):
    # The trades route starts background refreshes; the advisor fixtures make
    # those raise, so they are silenced here (no network either way).
    for name in ("_maybe_kick_hl_trades_refresh", "_maybe_kick_txflow_trades_refresh",
                 "_maybe_kick_hl_accounts_refresh", "_maybe_kick_txflow_refresh", "_trade_snapshot_pass",
                 "_trade_exit_pass_safe", "_trade_snapshot_worker"):
        monkeypatch.setattr(wp, name, lambda *a, **k: None)
    r = client.get('/api/trading/trades')
    assert r.status_code == 200, r.get_data(as_text=True)
    return r.get_json()


def revisions(db):
    return [tuple(r) for r in db.execute("SELECT kind, ref, old_text, action FROM note_revisions ORDER BY id")]


# ── the route ────────────────────────────────────────────────────────────

def test_save_reason_and_x1_passes(db, client, monkeypatch):
    eth = ids_by_symbol(db)["ETH"]
    assert by_rule(advisor(client).get_json()["trades"][eth])["X1"]["verdict"] == "fail"
    r = put(client, eth, {"exit_reason": "emotional"})
    assert r.status_code == 200, r.get_data(as_text=True)
    ann = r.get_json()["annotation"]
    assert ann["exit_reason"] == "emotional" and ann["exit_reason_note"] is None
    x1 = by_rule(advisor(client).get_json()["trades"][eth])["X1"]
    assert x1["verdict"] == "pass" and x1["evidence"] == "revised exit (Market); reason: Emotional"
    trades = get_trades(client, monkeypatch)["trades"]
    t = next(t for t in trades if t["trade_id"] == eth)
    assert t["annotation"]["exit_reason"] == "emotional" and t["annotation"]["exit_reason_note"] is None


def test_notes_alone_no_longer_pass(db, client):
    eth = ids_by_symbol(db)["ETH"]
    assert put(client, eth, {"notes": "took it off, felt toppy"}).status_code == 200
    assert by_rule(advisor(client).get_json()["trades"][eth])["X1"]["verdict"] == "fail"


def test_other_needs_a_note(db, client):
    eth = ids_by_symbol(db)["ETH"]
    r = put(client, eth, {"exit_reason": "other"})
    assert r.status_code == 400 and "needs a note" in r.get_json()["error"]
    assert put(client, eth, {"exit_reason": "other", "exit_reason_note": "   "}).status_code == 400
    r = put(client, eth, {"exit_reason": "other", "exit_reason_note": "funding flipped hard"})
    assert r.status_code == 200
    # Removing the note while "other" stays is refused; the stored note is untouched.
    assert put(client, eth, {"exit_reason_note": None}).status_code == 400
    row = db.execute("SELECT exit_reason, exit_reason_note FROM trade_annotations WHERE trade_id = ?", (eth,)).fetchone()
    assert tuple(row) == ("other", "funding flipped hard")


def test_bad_values_refused(db, client):
    eth = ids_by_symbol(db)["ETH"]
    for body in ({"exit_reason": "panic"}, {"exit_reason": 3}, {"exit_reason": True},
                 {"exit_reason_note": 5}, {"exit_reason_note": "x" * (wp.TRADE_NOTE_MAX + 1)},
                 {"exit_reason_note": "a note with no reason"}):
        r = put(client, eth, body)
        assert r.status_code == 400, body
    assert db.execute("SELECT COUNT(*) FROM trade_annotations WHERE trade_id = ?", (eth,)).fetchone()[0] == 0


def test_closed_perp_only(db, client, monkeypatch):
    ids = ids_by_symbol(db)
    r = put(client, ids["SOL"], {"exit_reason": "time_stop"})                   # open
    assert r.status_code == 400 and "closed perp trades only" in r.get_json()["error"]
    assert put(client, ids["DOGE"], {"exit_reason": "time_stop"}).status_code == 400   # manual: trade log
    real = wp._trades_build

    def with_spot(conn, extras=None):
        trades, anns = real(conn, extras)
        spot = dict(trades[0], trade_id="spot1", market="spot", status="closed", source="zerion")
        return trades + [spot], anns
    monkeypatch.setattr(wp, "_trades_build", with_spot)
    r = put(client, "spot1", {"exit_reason": "time_stop"})
    assert r.status_code == 400 and "closed perp trades only" in r.get_json()["error"]
    # A spot trade still saves its other fields as before.
    assert put(client, "spot1", {"notes": "fine"}).status_code == 200


def test_changes_are_kept_in_note_revisions(db, client):
    eth = ids_by_symbol(db)["ETH"]
    assert put(client, eth, {"exit_reason": "emotional", "exit_reason_note": "fomo exit"}).status_code == 200
    assert revisions(db) == []                                                  # nothing replaced yet
    assert put(client, eth, {"exit_reason": "time_stop"}).status_code == 200      # note carries over
    assert revisions(db) == [("trade_exit_reason", eth, "emotional", "edit")]
    assert put(client, eth, {"exit_reason_note": "nothing happened for 3 days"}).status_code == 200
    assert revisions(db)[-1] == ("trade_exit_reason_note", eth, "fomo exit", "edit")
    r = put(client, eth, {"exit_reason": None})                                 # clears the note too
    assert r.status_code == 200 and r.get_json()["annotation"]["exit_reason_note"] is None
    assert revisions(db)[-2:] == [("trade_exit_reason", eth, "time_stop", "edit"),
                                  ("trade_exit_reason_note", eth, "nothing happened for 3 days", "edit")]
    assert by_rule(advisor(client).get_json()["trades"][eth])["X1"]["verdict"] == "fail"


def test_unattached_row_with_only_an_exit_reason_is_listed(db, client, monkeypatch):
    db.execute("INSERT INTO trade_annotations (trade_id, market, exit_reason, created_at, updated_at) "
               "VALUES ('gone', 'perp', 'emotional', 'x', 'x')")
    db.commit()
    body = get_trades(client, monkeypatch)
    assert [a["trade_id"] for a in body["unattached_annotations"]] == ["gone"]


# ── the note_revisions rebuild ───────────────────────────────────────────

OLD_NOTE_REVISIONS = """CREATE TABLE note_revisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL CHECK (kind IN ('spot_summary','spot_update','trade_notes','trade_deviation_note')),
    ref TEXT NOT NULL,
    old_text TEXT NOT NULL,
    action TEXT NOT NULL CHECK (action IN ('edit','delete')),
    revised_at TEXT NOT NULL
)"""


@pytest.fixture
def old_db(tmp_path, monkeypatch):
    path = str(tmp_path / "old.db")
    conn = sqlite3.connect(path)
    conn.execute(OLD_NOTE_REVISIONS)
    conn.execute("CREATE INDEX idx_note_revisions_ref ON note_revisions (kind, ref)")
    for i in range(1, 6):
        conn.execute("INSERT INTO note_revisions (kind, ref, old_text, action, revised_at) VALUES (?, ?, ?, ?, ?)",
                     ("trade_notes" if i % 2 else "spot_update", f"r{i}", f"text {i}", "edit", f"2026-10-0{i}"))
    conn.execute("DELETE FROM note_revisions WHERE id = 5")             # the counter stays at 5
    conn.commit()
    conn.close()
    monkeypatch.setattr(portfolio_db, "get_db_path", lambda: path)
    return path


def test_rebuild_keeps_rows_ids_counter_and_index(old_db):
    portfolio_db.init_db()
    conn = sqlite3.connect(old_db)
    rows = conn.execute("SELECT id, kind, ref, old_text, action, revised_at FROM note_revisions ORDER BY id").fetchall()
    assert rows == [(i, "trade_notes" if i % 2 else "spot_update", f"r{i}", f"text {i}", "edit", f"2026-10-0{i}")
                    for i in range(1, 5)]
    sql = conn.execute("SELECT sql FROM sqlite_master WHERE name = 'note_revisions'").fetchone()[0]
    assert "'trade_exit_reason'" in sql and "'trade_exit_reason_note'" in sql
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master")}
    assert "idx_note_revisions_ref" in names and "note_revisions_8c2" not in names
    conn.execute("INSERT INTO note_revisions (kind, ref, old_text, action, revised_at) "
                 "VALUES ('trade_exit_reason', 't', 'emotional', 'edit', 'now')")
    assert conn.execute("SELECT MAX(id) FROM note_revisions").fetchone()[0] == 6   # id 5 is never reused
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO note_revisions (kind, ref, old_text, action, revised_at) "
                     "VALUES ('other', 'r', 't', 'edit', 'now')")
    cols = [r[1] for r in conn.execute("PRAGMA table_info(trade_annotations)")]
    assert cols[-2:] == ["exit_reason", "exit_reason_note"]
    conn.close()


def test_rebuild_runs_once(old_db, capsys):
    portfolio_db.init_db()
    portfolio_db.init_db()
    out = capsys.readouterr().out
    assert out.count("note_revisions rebuilt") == 1
    conn = sqlite3.connect(old_db)
    assert conn.execute("SELECT COUNT(*) FROM note_revisions").fetchone()[0] == 4
    conn.close()


def test_failed_rebuild_keeps_the_old_table(old_db, capsys):
    # A view on note_revisions makes the RENAME step fail after the DROP: the
    # whole rebuild must roll back to the old table with every row.
    conn = sqlite3.connect(old_db)
    conn.execute("CREATE VIEW nr_view AS SELECT id FROM note_revisions")
    conn.commit()
    conn.close()
    portfolio_db.init_db()
    assert "rebuild failed, old table kept" in capsys.readouterr().out
    conn = sqlite3.connect(old_db)
    sql = conn.execute("SELECT sql FROM sqlite_master WHERE name = 'note_revisions'").fetchone()[0]
    assert "'trade_exit_reason'" not in sql
    assert conn.execute("SELECT COUNT(*) FROM note_revisions").fetchone()[0] == 4
    assert conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE name = 'note_revisions_8c2'").fetchone()[0] == 0
    conn.close()


def test_fresh_database_has_the_new_kinds(db):
    sql = db.execute("SELECT sql FROM sqlite_master WHERE name = 'note_revisions'").fetchone()[0]
    assert all(f"'{k}'" in sql for k in portfolio_db.NOTE_REVISION_KINDS)


# ── the page keeps the same list ─────────────────────────────────────────

def test_page_lists_the_same_keys_and_labels():
    src = open(os.path.join(REPO, "static", "perpsrules.js"), encoding="utf-8").read()
    block = re.search(r"const PRP_EXIT_REASONS = \[(.*?)\];", src, re.S).group(1)
    pairs = re.findall(r"\['([a-z_]+)', '([^']+)'", block)
    assert [k for k, _ in pairs] == list(pr.EXIT_REASON_KEYS)
    assert dict(pairs) == dict(pr.EXIT_REASONS)
