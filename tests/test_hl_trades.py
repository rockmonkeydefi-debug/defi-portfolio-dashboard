"""hl_trades (pure perp-cycle engine, HANDOFF_trading_performance.md Commit 3):
golden parity with tests/fixtures/hl_trading/expected_cycles.json for both
recorded wallets, order independence within a timestamp, the extra keys
(flags, stop_source, trade_key), and small hand-built cases for flips,
liquidations, pre-window positions, funding attribution and stop selection.
No network, no DB. Fixture files are read-only."""
import json
import os
import random
from decimal import Decimal

import pytest

import hl_trades

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "hl_trading")
H = 3600000
T0 = 1789257600000                  # a UTC day start


def _load(wallet, kind):
    with open(os.path.join(FIX, f"{wallet}.{kind}.json")) as f:
        return json.load(f)


def _golden():
    with open(os.path.join(FIX, "expected_cycles.json")) as f:
        return json.load(f)


def _build(wallet):
    return hl_trades.build_cycles(wallet, _load(wallet, "fills"), _load(wallet, "funding"), _load(wallet, "hist_orders"))


# ── golden parity ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("wallet", ["rm", "rabby"])
def test_golden_parity(wallet):
    gold = _golden()
    expected = [c for c in gold["cycles"] if c["wallet"] == wallet]
    got = _build(wallet)
    assert len(got["cycles"]) == len(expected) == gold["wallets"][wallet]["cycles"]
    keys = list(expected[0].keys())
    assert [{k: c[k] for k in keys} for c in got["cycles"]] == expected
    assert got["unattributed_funding"] == gold["wallets"][wallet]["unattributed_funding"]
    assert got["skipped_partial_fills"] == 0


@pytest.mark.parametrize("wallet", ["rm", "rabby"])
def test_cycle_keys_and_extras(wallet):
    gold_keys = set(_golden()["cycles"][0].keys())
    for c in _build(wallet)["cycles"]:
        assert set(c.keys()) == gold_keys | {"flags", "stop_source", "trade_key",
                                             "avg_entry_px", "avg_exit_px", "initial_stop_px"}
        assert c["trade_key"] == f"{wallet}|{c['coin']}|{c['first_tid']}"
        assert isinstance(c["open_time"], int) and isinstance(c["first_tid"], int)
        assert c["stop_source"] == "hl_order" and c["initial_stop"] is not None    # every golden cycle has a stop
        assert c["flags"] == []
        assert c["coin"] != "PUMP" or (c["avg_entry"], c["avg_entry_px"]) == ("0.004578", "0.00457763")   # cheap coin: full precision


@pytest.mark.parametrize("wallet", ["rm", "rabby"])
def test_shuffled_input_gives_the_same_result(wallet):
    fills = _load(wallet, "fills")
    times = [f["time"] for f in fills]
    assert len(times) > len(set(times))          # the fixture has same-time fills to reorder
    base = _build(wallet)
    for seed in range(5):
        shuffled = list(fills)
        random.Random(seed).shuffle(shuffled)
        got = hl_trades.build_cycles(wallet, shuffled, _load(wallet, "funding"), _load(wallet, "hist_orders"))
        assert got == base


# ── synthetic helpers ────────────────────────────────────────────────────

_TID = [1000]


def fill(coin, side, sz, px, start, t, closed_pnl="0", fee="0", dir_=None, **extra):
    _TID[0] += 1
    s, z = Decimal(start), Decimal(sz)
    end = s + z if side == "B" else s - z
    if dir_ is None:
        dir_ = ("Open Long" if side == "B" else "Open Short") if abs(end) > abs(s) else \
               ("Close Short" if side == "B" else "Close Long")
    f = {"coin": coin, "side": side, "sz": str(sz), "px": str(px), "startPosition": str(start), "time": t,
         "tid": _TID[0], "closedPnl": str(closed_pnl), "fee": str(fee), "dir": dir_, "feeToken": "USDC"}
    f.update(extra)
    return f


def stop(oid, coin, side, trigger, placed, order_type="Stop Market", children=None):
    return {"order": {"coin": coin, "side": side, "oid": oid, "timestamp": placed, "isTrigger": True,
                      "reduceOnly": True, "orderType": order_type, "triggerPx": str(trigger),
                      "children": children or []}, "status": "open", "statusTimestamp": placed}


def status(rec, st, at):
    return {"order": dict(rec["order"]), "status": st, "statusTimestamp": at}


def hourly(coin, usdc, t):
    return {"time": t, "delta": {"type": "funding", "coin": coin, "usdc": str(usdc), "nSamples": None}}


def daily(coin, usdc, t):
    return {"time": t, "delta": {"type": "funding", "coin": coin, "usdc": str(usdc), "nSamples": 24}}


def only(res):
    assert len(res["cycles"]) == 1
    return res["cycles"][0]


# ── flips, liquidations, pre-window positions ───────────────────────────

def test_flip_splits_into_two_cycles():
    fs = [fill("ETH", "B", "1", "100", "0", T0, fee="0.1"),
          fill("ETH", "A", "3", "110", "1", T0 + H, closed_pnl="10", fee="0.3", dir_="Long > Short"),
          fill("ETH", "B", "2", "105", "-2", T0 + 2 * H, closed_pnl="10", fee="0.2")]
    a, b = hl_trades.build_cycles("w", fs, [], [])["cycles"]
    assert (a["direction"], a["status"], a["close_time"]) == ("long", "closed", T0 + H)
    assert a["fees"] == "0.200000" and a["gross_closed_pnl"] == "10.000000" and a["avg_exit"] == "110.000000"
    assert a["peak_size"] == "1.000000" and "flip_split" in a["flags"]
    assert (b["direction"], b["status"], b["open_time"], b["first_tid"]) == ("short", "closed", T0 + H, fs[1]["tid"])
    assert b["fees"] == "0.400000" and b["gross_closed_pnl"] == "10.000000"
    assert b["avg_entry"] == "110.000000" and b["avg_exit"] == "105.000000" and b["peak_size"] == "2.000000"
    assert "flip_split" in b["flags"]
    assert Decimal(a["fees"]) + Decimal(b["fees"]) == Decimal("0.6")


def test_liquidation_flags_the_cycle():
    for extra in ({"liquidation": {"markPx": "90", "method": "market"}}, {"dir_": "Liquidated Isolated Long"}):
        fs = [fill("SOL", "B", "2", "100", "0", T0), fill("SOL", "A", "2", "90", "2", T0 + H, closed_pnl="-20", **extra)]
        c = only(hl_trades.build_cycles("w", fs, [], []))
        assert c["status"] == "closed" and "liquidated" in c["flags"]


def test_pre_window_partial_position_is_skipped_and_counted():
    fs = [fill("BTC", "A", "1", "100", "3", T0), fill("BTC", "A", "2", "101", "2", T0 + H),
          fill("BTC", "B", "1", "102", "0", T0 + 2 * H)]
    res = hl_trades.build_cycles("w", fs, [], [])
    c = only(res)
    assert res["skipped_partial_fills"] == 2
    assert (c["open_time"], c["status"], c["direction"]) == (T0 + 2 * H, "open", "long")


def test_same_time_fills_follow_the_position_chain():
    fs = [fill("ETH", "B", "1", "100", "0", T0), fill("ETH", "B", "1", "101", "1", T0),
          fill("ETH", "A", "2", "110", "2", T0 + H, closed_pnl="19")]
    fs[0]["tid"], fs[1]["tid"] = fs[1]["tid"], fs[0]["tid"]      # tid order disagrees with the chain
    c = only(hl_trades.build_cycles("w", list(reversed(fs)), [], []))
    assert c["first_tid"] == fs[0]["tid"] and c["fill_count"] == 3 and c["flags"] == ["stop_missing"]


# ── funding attribution ──────────────────────────────────────────────────

def test_daily_funding_split_by_overlap():
    fs = [fill("ETH", "B", "1", "100", "0", T0 + 1 * H), fill("ETH", "A", "1", "100", "1", T0 + 3 * H),
          fill("ETH", "B", "1", "100", "0", T0 + 10 * H), fill("ETH", "A", "1", "100", "1", T0 + 16 * H)]
    res = hl_trades.build_cycles("w", fs, [daily("ETH", "-8", T0)], [])
    a, b = res["cycles"]
    assert (a["funding"], b["funding"]) == ("-2.000000", "-6.000000")
    assert res["unattributed_funding"] == "0.000000"


def test_hourly_funding_boundaries():
    fs = [fill("ETH", "B", "1", "100", "0", T0 + 1 * H), fill("ETH", "A", "1", "100", "1", T0 + 3 * H),
          fill("ETH", "B", "1", "100", "0", T0 + 5 * H), fill("ETH", "A", "1", "100", "1", T0 + 7 * H)]
    funding = [hourly("ETH", "-1", T0 + 3 * H),     # at the first close -> first cycle
               hourly("ETH", "-2", T0 + 5 * H)]     # at the second open -> neither
    res = hl_trades.build_cycles("w", fs, funding, [])
    a, b = res["cycles"]
    assert (a["funding"], b["funding"]) == ("-1.000000", "0.000000")
    assert res["unattributed_funding"] == "-2.000000"


# ── stop selection ───────────────────────────────────────────────────────

def _long_cycle(close=True):
    fs = [fill("ETH", "B", "2", "100", "0", T0 + 10 * H, fee="1")]
    if close:
        fs.append(fill("ETH", "A", "2", "110", "2", T0 + 20 * H, closed_pnl="20", fee="1"))
    return fs


def test_stop_cancelled_before_open_is_ignored():
    s = stop(1, "ETH", "A", "95", T0 + 5 * H)
    c = only(hl_trades.build_cycles("w", _long_cycle(), [], [s, status(s, "canceled", T0 + 8 * H)]))
    assert c["initial_stop"] is None and c["r_multiple"] is None
    assert c["stop_source"] is None and "stop_missing" in c["flags"]


def test_stop_placed_after_open_is_used():
    s = stop(2, "ETH", "A", "95", T0 + 10 * H + 300000)
    c = only(hl_trades.build_cycles("w", _long_cycle(), [], [s]))
    assert c["initial_stop"] == "95.000000" and c["stop_placed"] == T0 + 10 * H + 300000
    assert c["stop_source"] == "hl_order" and "stop_missing" not in c["flags"]
    # net = 20 - 2 = 18; risk = |100 - 95| x 2 = 10
    assert c["r_multiple"] == "1.800000"


def test_alive_stop_at_open_beats_a_later_one():
    early = stop(3, "ETH", "A", "96", T0 + 10 * H)
    later = stop(4, "ETH", "A", "90", T0 + 11 * H)
    c = only(hl_trades.build_cycles("w", _long_cycle(), [], [later, early]))
    assert c["initial_stop"] == "96.000000"


def test_child_only_stop_is_ignored():
    entry = {"order": {"coin": "ETH", "side": "B", "oid": 7, "timestamp": T0 + 10 * H, "isTrigger": False,
                       "reduceOnly": False, "orderType": "Limit", "triggerPx": "0.0",
                       "children": [stop(8, "ETH", "A", "95", T0 + 10 * H)["order"]]},
             "status": "filled", "statusTimestamp": T0 + 10 * H}
    c = only(hl_trades.build_cycles("w", _long_cycle(), [], [entry]))
    assert c["initial_stop"] is None and "stop_missing" in c["flags"]


def test_no_stop():
    c = only(hl_trades.build_cycles("w", _long_cycle(), [], []))
    assert (c["initial_stop"], c["r_multiple"], c["stop_source"], c["stop_placed"]) == (None, None, None, None)
    assert "stop_missing" in c["flags"]


def test_open_cycle_has_no_r():
    s = stop(9, "ETH", "A", "95", T0 + 10 * H)
    c = only(hl_trades.build_cycles("w", _long_cycle(close=False), [], [s]))
    assert c["status"] == "open" and c["initial_stop"] == "95.000000" and c["r_multiple"] is None
    assert c["close_time"] is None and c["avg_exit"] is None


def test_short_uses_side_b_stops_and_the_short_r():
    fs = [fill("BTC", "A", "1", "200", "0", T0 + 10 * H, fee="0.5"),
          fill("BTC", "B", "1", "180", "-1", T0 + 12 * H, closed_pnl="20", fee="0.5")]
    wrong_side = stop(10, "BTC", "A", "190", T0 + 10 * H)
    right = stop(11, "BTC", "B", "210", T0 + 10 * H)
    c = only(hl_trades.build_cycles("w", fs, [], [wrong_side, right]))
    assert c["direction"] == "short" and c["initial_stop"] == "210.000000"
    # net = 20 - 1 = 19; risk = |200 - 210| x 1 = 10
    assert c["net_pnl"] == "19.000000" and c["r_multiple"] == "1.900000"


def test_spot_fills_are_ignored():
    fs = [fill("@107", "B", "5", "1", "0", T0)]
    assert hl_trades.build_cycles("w", fs, [], [])["cycles"] == []
