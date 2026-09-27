"""Hyperliquid account mode: perp equity counted once (Sep 27 fix).

Unified / portfolio-margin accounts hold their perp equity inside spot USDC
(Hyperliquid docs: "For API users, unified account and portfolio margin show
all balances and holds in the spot clearinghouse state."), so
portfolio_total.compose_total counts perp only for standard-mode accounts
('disabled'); any other mode, or a failed mode read, counts spot only with a
warning. web_portfolio._hl_fetch_accounts reads the mode with userAbstraction
for each wallet it keeps.

No network: the fetch runs only against a fake `post`; the spawner is
conftest's autouse no-op."""
from datetime import datetime, timezone

import pytest

import portfolio_total as pt
import web_portfolio as wp

NOW = datetime(2026, 9, 27, 12, 0, tzinfo=timezone.utc)
FETCHED = "2026-09-27T11:58:00+00:00"
A = "0x" + "a" * 40
B = "0x" + "b" * 40
C = "0x" + "c" * 40
_REAL_FETCH = wp._hl_fetch_accounts   # captured before any test patches it


def _portfolio():
    return {"tokens": [{"symbol": "ETH", "value_usd": 2000.0, "wallet": A}], "lp_positions": [],
            "aave_positions": [], "gmx_positions": [], "staking_positions": [],
            "total_tokens_value": 2000.0, "total_lp_value": 0.0, "total_uncollected_fees": 0.0,
            "total_value": 2000.0, "wallet_labels": {A: "Rabby", B: "Hyperliquid RM"},
            "fetched_at": "2026-09-27T11:50:00"}


def _wallet(perp, usdc, mode="__absent__", mode_error=None, **extra):
    w = {"perp_account_value": perp, "open_perps": 1 if perp else 0,
         "spot": [{"coin": "USDC", "amount": usdc, "price": 1.0, "value": usdc}] if usdc else []}
    if mode != "__absent__":
        w["mode"] = mode
    if mode_error is not None:
        w["mode_error"] = mode_error
    w.update(extra)
    return w


def _compose(wallets):
    state = {"fetched_at": FETCHED, "wallets": wallets, "error": None, "wallets_checked": len(wallets)}
    return pt.compose_total(_portfolio(), [], set(), True, {}, state, NOW)


def _hl(result):
    return next(c for c in result["components"] if c["key"] == "hyperliquid")


def _mode_warnings(hl):
    return [w for w in hl["warnings"] if "account mode" in w]


def _assert_total_is_counted_sum(result):
    assert result["total_usd"] == pytest.approx(sum(c["value_usd"] for c in result["components"] if c["counted"]))


# ── compose_total: counting by mode ────────────────────────────────────────

@pytest.mark.parametrize("mode", ["unifiedAccount", "portfolioMargin"])
def test_perp_inside_spot_counts_spot_only(mode):
    r = _compose({A: _wallet(228.61, 1456.71, mode=mode)})
    hl = _hl(r)
    assert hl["counted"] is True
    assert hl["value_usd"] == pytest.approx(1456.71)
    row = hl["detail"]["wallets"][0]
    assert (row["mode"], row["perp_treatment"]) == (mode, "inside_spot")
    assert row["perp_account_value"] == 228.61                       # still reported
    assert _mode_warnings(hl) == []
    _assert_total_is_counted_sum(r)


def test_disabled_counts_perp_plus_spot():
    r = _compose({A: _wallet(228.61, 1456.71, mode="disabled")})
    hl = _hl(r)
    assert hl["value_usd"] == pytest.approx(228.61 + 1456.71)
    row = hl["detail"]["wallets"][0]
    assert (row["mode"], row["perp_treatment"]) == ("disabled", "counted")
    assert _mode_warnings(hl) == []
    _assert_total_is_counted_sum(r)


@pytest.mark.parametrize("mode, mode_error, warning", [
    ("default", None, "Rabby: account mode 'default' not recognised — perp $1,228.61 not counted (spot only)"),
    ("somethingNew", None, "Rabby: account mode 'somethingNew' not recognised — perp $1,228.61 not counted (spot only)"),
    (None, "TimeoutError: hl timeout",
     "Rabby: account mode unavailable (TimeoutError: hl timeout) — perp $1,228.61 not counted (spot only)"),
    (None, None, "Rabby: account mode unavailable (not read) — perp $1,228.61 not counted (spot only)"),
    ("__absent__", None, "Rabby: account mode unavailable (not read) — perp $1,228.61 not counted (spot only)"),
])
def test_unknown_or_unread_mode_counts_spot_only_with_warning(mode, mode_error, warning):
    r = _compose({A: _wallet(1228.61, 1456.71, mode=mode, mode_error=mode_error)})
    hl = _hl(r)
    assert hl["value_usd"] == pytest.approx(1456.71)
    row = hl["detail"]["wallets"][0]
    assert row["perp_treatment"] == "not_counted_unknown_mode"
    assert row["mode"] == (None if mode == "__absent__" else mode)
    assert _mode_warnings(hl) == [warning]
    _assert_total_is_counted_sum(r)


@pytest.mark.parametrize("mode", ["default", None])
def test_unknown_mode_no_warning_when_perp_is_zero(mode):
    hl = _hl(_compose({A: _wallet(0.0, 500.0, mode=mode)}))
    assert hl["value_usd"] == pytest.approx(500.0)
    assert hl["detail"]["wallets"][0]["perp_treatment"] == "not_counted_unknown_mode"
    assert _mode_warnings(hl) == []


def test_two_wallets_mixed_modes():
    r = _compose({A: _wallet(100.0, 1000.0, mode="unifiedAccount"), B: _wallet(50.0, 200.0, mode="disabled")})
    hl = _hl(r)
    assert hl["value_usd"] == pytest.approx(1000.0 + 50.0 + 200.0)
    assert {w["label"]: w["perp_treatment"] for w in hl["detail"]["wallets"]} == {
        "Rabby": "inside_spot", "Hyperliquid RM": "counted"}
    _assert_total_is_counted_sum(r)


def test_production_regression_sep27():
    # Both production accounts are unified: spot USDC already holds the perp equity.
    r = _compose({A: _wallet(222.676897, 1450.78, mode="unifiedAccount"),
                  B: _wallet(431.166988, 5938.36, mode="unifiedAccount")})
    hl = _hl(r)
    assert hl["value_usd"] == pytest.approx(7389.14, abs=0.01)
    assert abs(hl["value_usd"] - 8042.98) > 600                         # the old perp + spot figure
    assert [w["perp_account_value"] for w in hl["detail"]["wallets"]] == [222.676897, 431.166988]
    assert r["total_usd"] == pytest.approx(2000.0 + 7389.14, abs=0.01)
    _assert_total_is_counted_sum(r)


def test_source_text_names_the_mode_rule():
    hl = _hl(_compose({A: _wallet(1.0, 1.0, mode="disabled")}))
    assert hl["source"] == ("Hyperliquid info API: priced spot balances + perp accountValue for standard-mode "
                            "accounts only (unified / portfolio-margin accounts hold perp equity inside spot USDC) "
                            "(15-min background cache)")


# ── _hl_fetch_accounts: the userAbstraction read ───────────────────────────

def _post(modes, fail_wallet=None):
    """A: perp + spot, B: all zero (skipped), C: perp only. `modes` maps a
    wallet to a return value, or to an Exception instance to raise."""
    meta = {"tokens": [{"name": "USDC", "index": 0}], "universe": []}
    calls = []

    def post(payload):
        calls.append(payload)
        t = payload["type"]
        if t == "spotMetaAndAssetCtxs":
            return [meta, []]
        user = payload["user"]
        if t == "userAbstraction":
            m = modes[user]
            if isinstance(m, Exception):
                raise m
            return m
        if user == fail_wallet:
            raise TimeoutError("hl timeout")
        if t == "clearinghouseState":
            v = {A: "100.0", B: "0.0", C: "40.0"}[user]
            return {"marginSummary": {"accountValue": v}, "assetPositions": []}
        if t == "spotClearinghouseState":
            return {"balances": [{"coin": "USDC", "total": "900"}] if user == A else []}
        raise AssertionError(t)
    post.calls = calls
    return post


def _mode_calls(post):
    return [c["user"] for c in post.calls if c["type"] == "userAbstraction"]


def test_fetch_reads_mode_only_for_kept_wallets():
    post = _post({A: "unifiedAccount", C: "disabled"}, fail_wallet=C)
    res = wp._hl_fetch_accounts([A, B, C], post=post)
    assert _mode_calls(post) == [A]                                     # B all-zero, C failed
    assert res["wallets"][A]["mode"] == "unifiedAccount"
    assert "mode_error" not in res["wallets"][A]
    assert list(res["wallets"]) == [A] and list(res["errors"]) == [C]


def test_fetch_stores_str_modes():
    post = _post({A: "portfolioMargin", C: "disabled"})
    res = wp._hl_fetch_accounts([A, C], post=post)
    assert {a: w["mode"] for a, w in res["wallets"].items()} == {A: "portfolioMargin", C: "disabled"}
    assert _mode_calls(post) == [A, C]


def test_fetch_non_str_mode_response():
    res = wp._hl_fetch_accounts([A], post=_post({A: {"mode": "unifiedAccount"}}))
    w = res["wallets"][A]
    assert w["mode"] is None
    assert w["mode_error"] == "unexpected userAbstraction response: dict"
    assert res["errors"] == {}


def test_fetch_mode_call_raising_keeps_wallet():
    res = wp._hl_fetch_accounts([A], post=_post({A: RuntimeError("abstraction down")}))
    w = res["wallets"][A]
    assert (w["perp_account_value"], w["spot"][0]["value"]) == (100.0, 900.0)
    assert w["mode"] is None and w["mode_error"] == "RuntimeError: abstraction down"
    assert A not in res["errors"]


# ── worker: a failed refresh keeps the previous row's mode ─────────────────

def test_worker_stale_row_keeps_previous_mode(monkeypatch):
    wp._HL_ACCOUNTS_CACHE.update({"fetched_at": "2026-09-27T11:00:00+00:00", "wallets": {
        C: {"perp_account_value": 40.0, "open_perps": 0, "spot": [], "mode": "unifiedAccount"}}})
    monkeypatch.setattr(wp, "_HL_ACCOUNTS_IN_FLIGHT", True)
    post = _post({A: "disabled", C: "disabled"}, fail_wallet=C)
    monkeypatch.setattr(wp, "_hl_fetch_accounts", lambda wallets: _REAL_FETCH(wallets, post=post))
    wp._hl_accounts_refresh_worker([A, C], now_utc=NOW)
    c = wp._HL_ACCOUNTS_CACHE
    assert c["wallets"][A]["mode"] == "disabled"
    assert c["wallets"][C]["stale"] is True and c["wallets"][C]["mode"] == "unifiedAccount"
    assert wp._HL_ACCOUNTS_IN_FLIGHT is False
