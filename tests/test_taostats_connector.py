"""src/connectors/taostats.py: fetch_account (fake get; no network) and the
pure parse_account, against a real Sep 30 account response with the
addresses replaced by the public Substrate dev addresses (ALICE = wallet and
coldkey, BOB = hotkey)."""
import copy
import json
import os

import pytest

from src.connectors import taostats as ts

ALICE = "5GrwvaEF5zXb26Fz9rcQpDWS57CtERHpNehXCPcNoHGKutQY"
BOB = "5FHneW46xGXgs5mUiveU4sbTyGBzmstUspZC92UhjJM694ty"
DUMMY_KEY = "dummy-key-123"
FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "taostats_account_5_subnets.json")


def _payload():
    with open(FIXTURE) as f:
        return json.load(f)


# ── parse_account ─────────────────────────────────────────────────────────

def test_parse_fixture():
    h = ts.parse_account(_payload(), ALICE)
    assert (h["free_rao"], h["reserved_rao"], h["root_rao"], h["liquidity_rao"], h["total_rao"]) == (
        1745899673, 93000000, 0, 0, 12577601758)
    assert [a["netuid"] for a in h["alpha"]] == [51, 80, 105, 107, 110]
    sn105 = next(a for a in h["alpha"] if a["netuid"] == 105)
    assert (sn105["alpha_rao"], sn105["as_tao_rao"], sn105["hotkeys"]) == (327679279493, 2150880237, 1)
    assert h["parts_rao"] == h["total_rao"] and h["diff_rao"] == 0
    assert h["alpha_as_tao_field_rao"] == 10738702085
    assert (h["as_of"], h["block"], h["address"]) == ("2026-09-30T01:29:24Z", 9177434, ALICE)
    assert json.loads(json.dumps(h)) == h                        # JSON-safe, ints only
    assert all(isinstance(h[k], int) for k in ("free_rao", "total_rao", "parts_rao", "diff_rao"))


def test_parse_no_alpha_variant():
    p = _payload()
    acct = p["data"][0]
    acct.update(alpha_balances=[], balance_free="12802160052", balance_total="12802160052", balance_staked="0",
                balance_staked_alpha_as_tao="0", balance_reserved="0")
    h = ts.parse_account(p, ALICE)
    assert h["alpha"] == [] and h["diff_rao"] == 0 and h["free_rao"] == 12802160052


def test_parse_rejects_unexpected_shapes():
    with pytest.raises(ts.TaostatsError, match="unexpected account response"):
        ts.parse_account(_payload(), BOB)                          # address mismatch
    empty = _payload()
    empty["data"] = []
    with pytest.raises(ts.TaostatsError, match="unexpected account response"):
        ts.parse_account(empty, ALICE)
    no_ts = _payload()
    del no_ts["data"][0]["timestamp"]
    with pytest.raises(ts.TaostatsError, match="unexpected account response"):
        ts.parse_account(no_ts, ALICE)


def test_parse_sums_one_subnet_across_hotkeys():
    p = _payload()
    acct = p["data"][0]
    extra = copy.deepcopy(acct["alpha_balances"][0])               # SN51 again, on another hotkey
    extra.update(hotkey="second-hotkey", balance="1000", balance_as_tao="10")
    acct["alpha_balances"].append(extra)
    acct["balance_total"] = str(int(acct["balance_total"]) + 10)
    h = ts.parse_account(p, ALICE)
    sn51 = next(a for a in h["alpha"] if a["netuid"] == 51)
    assert (sn51["alpha_rao"], sn51["as_tao_rao"], sn51["hotkeys"]) == (22531338022 + 1000, 2139791461 + 10, 2)
    assert h["diff_rao"] == 0


# ── fetch_account ─────────────────────────────────────────────────────────

class _Resp:
    def __init__(self, status, body=None):
        self.status_code = status
        self._body = body

    def json(self):
        return self._body


def test_fetch_sends_raw_key_and_address():
    calls = []

    def get(url, params=None, headers=None, timeout=None):
        calls.append((url, params, headers, timeout))
        return _Resp(200, _payload())
    body = ts.fetch_account(ALICE, DUMMY_KEY, get=get)
    assert body["data"][0]["address"]["ss58"] == ALICE
    ((url, params, headers, timeout),) = calls
    assert url == "https://api.taostats.io/api/account/latest/v1"
    assert params == {"address": ALICE}
    assert headers == {"accept": "application/json", "authorization": DUMMY_KEY}      # raw, no "Bearer"
    assert timeout == ts.REQUEST_TIMEOUT_SECONDS


def test_fetch_errors_never_carry_the_key():
    with pytest.raises(ts.TaostatsError) as e429:
        ts.fetch_account(ALICE, DUMMY_KEY, get=lambda *a, **k: _Resp(429))
    assert str(e429.value) == "rate limited (HTTP 429)"
    with pytest.raises(ts.TaostatsError) as e500:
        ts.fetch_account(ALICE, DUMMY_KEY, get=lambda *a, **k: _Resp(500))
    assert str(e500.value) == "HTTP 500"

    def boom(*a, **k):
        raise ConnectionError("boom dummy-key-123")
    with pytest.raises(ts.TaostatsError) as econn:
        ts.fetch_account(ALICE, DUMMY_KEY, get=boom)
    assert str(econn.value) == "ConnectionError"
    assert DUMMY_KEY not in str(econn.value) and DUMMY_KEY not in repr(econn.value)
    assert econn.value.__cause__ is None and econn.value.__suppress_context__

    class _BadJson(_Resp):
        def json(self):
            raise ValueError("not json dummy-key-123")
    with pytest.raises(ts.TaostatsError) as ejson:
        ts.fetch_account(ALICE, DUMMY_KEY, get=lambda *a, **k: _BadJson(200))
    assert str(ejson.value) == "ValueError"
