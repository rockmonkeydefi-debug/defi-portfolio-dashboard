"""DexFi bonds background cache (level-shift step 3).

Covers _dexfi_fetch_bonds (DexFi's public bond API: /info + per-wallet
/performance-metrics), _dexfi_bonds_refresh_worker's swap rules, the view-time
kick (TTL / in-flight / cooldown) and the snapshot freshen.

Never real network: tests/conftest.py stubs _dexfi_fetch_bonds for every test;
here the REAL fetch is restored and requests.get is replaced by a fake that
dispatches on the URL. Numbers are the live values verified on Sep 29."""
from datetime import datetime, timedelta, timezone

import pytest

import web_portfolio as wp

REAL_FETCH = wp._dexfi_fetch_bonds      # captured before conftest's per-test stub

BONDS2 = "0x" + "1b" * 20        # DexFi Bonds 2 (key 3A)
FUSION2 = "0x" + "21" * 20       # EMP Fusion 2 (Bonds)
EMPTY = "0x" + "e0" * 20         # holds no bonds
NOW = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)

INFO = {"nativePrice": "2670.4843357208847", "bondFundWalletUsd": "4364001.52",
        "currentNftPriceNative": "13059184570033846", "totalSupply": "125135",
        "isNftPriceValid": True, "isEnabled": True, "FUND_WALLET": "0xfund", "detailedBalances": []}
SHARES = {BONDS2: 0.0006506651243493349, FUSION2: 0.0006988625409678042, EMPTY: 0.0}


class _Resp:
    def __init__(self, status, body):
        self.status_code = status
        self._body = body

    def json(self):
        return self._body


@pytest.fixture
def api(monkeypatch):
    """A fake DexFi API. Tests change state["info"], state["info_status"],
    state["shares"] and state["fail"] (wallets whose metrics call raises)."""
    state = {"info": dict(INFO), "info_status": 200, "shares": dict(SHARES), "fail": set(), "calls": []}

    def get(url, timeout=None, **kw):
        state["calls"].append(url)
        assert timeout == wp.DEXFI_REQUEST_TIMEOUT_SECONDS
        if url == f"{wp.DEXFI_BONDS_API}/info":
            return _Resp(state["info_status"], state["info"])
        prefix = f"{wp.DEXFI_BONDS_API}/performance-metrics?account="
        assert url.startswith(prefix), url
        addr = url[len(prefix):]
        if addr in state["fail"]:
            raise TimeoutError("read timed out")
        return _Resp(200, {"netDeposits": 1.0, "totalProfits": 0.1, "bondsHoldRank": 7,
                           "bondsHoldShare": state["shares"][addr]})
    monkeypatch.setattr(wp, "_dexfi_fetch_bonds", REAL_FETCH)
    monkeypatch.setattr(wp.requests, "get", get)
    return state


def _prime(wallets, fetched_at="2026-09-29T09:00:00+00:00"):
    wp._DEXFI_BONDS_CACHE.update({"fetched_at": fetched_at, "info": {"bond_fund_usd": 1.0},
                                  "wallets": wallets, "error": None})


# ── fetch + worker ─────────────────────────────────────────────────────────

def test_success_rows_values_and_zero_share_wallet_has_no_row(api):
    wp._dexfi_bonds_refresh_worker([BONDS2, FUSION2, EMPTY], now_utc=NOW)
    cache = wp._DEXFI_BONDS_CACHE
    assert set(cache["wallets"]) == {BONDS2, FUSION2}
    assert cache["wallets"][BONDS2]["value_usd"] == pytest.approx(2839.50, abs=0.01)
    assert cache["wallets"][FUSION2]["value_usd"] == pytest.approx(3049.84, abs=0.01)
    assert cache["wallets"][BONDS2]["units_est"] == pytest.approx(0.0006506651243493349 * 125135)
    assert cache["info"] == {"bond_fund_usd": 4364001.52, "nav_eth": pytest.approx(0.013059184570033846),
                             "eth_usd": pytest.approx(2670.4843357208847), "total_supply": 125135.0}
    assert cache["fetched_at"] == NOW.isoformat() and cache["error"] is None
    assert cache["wallets_checked"] == 3 and wp._DEXFI_BONDS_IN_FLIGHT is False


@pytest.mark.parametrize("change", ["invalid_price", "disabled", "http_500"])
def test_bad_info_keeps_every_prior_value(api, change):
    prior = {BONDS2: {"share": 0.1, "value_usd": 1.0, "fetched_at": "2026-09-29T09:00:00+00:00"}}
    _prime(dict(prior))
    if change == "invalid_price":
        api["info"]["isNftPriceValid"] = False
    elif change == "disabled":
        api["info"]["isEnabled"] = False
    else:
        api["info_status"] = 500
    wp._dexfi_bonds_refresh_worker([BONDS2, FUSION2], now_utc=NOW)
    cache = wp._DEXFI_BONDS_CACHE
    assert cache["error"] == ("info HTTP 500" if change == "http_500" else "DexFi price flagged invalid")
    assert cache["wallets"] == prior and cache["fetched_at"] == "2026-09-29T09:00:00+00:00"
    assert all("performance-metrics" not in u for u in api["calls"])      # no wallet fetched


def test_wallet_timeout_keeps_its_prior_row_stale_with_its_own_fetch_time(api):
    old = {"share": 0.0006, "value_usd": 2618.0, "units_est": 75.0, "fetched_at": "2026-09-29T08:00:00+00:00"}
    _prime({BONDS2: dict(old)})
    api["fail"] = {BONDS2}
    wp._dexfi_bonds_refresh_worker([BONDS2, FUSION2], now_utc=NOW)
    wallets = wp._DEXFI_BONDS_CACHE["wallets"]
    assert wallets[BONDS2]["stale"] is True and wallets[BONDS2]["fetched_at"] == old["fetched_at"]
    assert wallets[BONDS2]["value_usd"] == 2618.0 and "TimeoutError" in wallets[BONDS2]["error"]
    assert wallets[FUSION2]["value_usd"] == pytest.approx(3049.84, abs=0.01) and "stale" not in wallets[FUSION2]
    assert wp._DEXFI_BONDS_CACHE["fetched_at"] == NOW.isoformat()


def test_every_wallet_failing_keeps_prior_values(api):
    prior = {BONDS2: {"share": 0.1, "value_usd": 1.0, "fetched_at": "2026-09-29T09:00:00+00:00"}}
    _prime(dict(prior))
    api["fail"] = {BONDS2, FUSION2}
    wp._dexfi_bonds_refresh_worker([BONDS2, FUSION2], now_utc=NOW)
    assert wp._DEXFI_BONDS_CACHE["wallets"] == prior
    assert wp._DEXFI_BONDS_CACHE["error"].startswith("every wallet failed")


def test_redeemed_wallet_row_is_removed(api):
    _prime({BONDS2: {"share": 0.1, "value_usd": 1.0, "fetched_at": "2026-09-29T09:00:00+00:00"}})
    api["shares"][BONDS2] = 0.0
    wp._dexfi_bonds_refresh_worker([BONDS2, FUSION2], now_utc=NOW)
    assert set(wp._DEXFI_BONDS_CACHE["wallets"]) == {FUSION2}


# ── kick + snapshot freshen ────────────────────────────────────────────────

@pytest.fixture
def spawns(monkeypatch):
    calls = []
    monkeypatch.setattr(wp, "_spawn_dexfi_bonds_refresh_thread", lambda wallets: calls.append(list(wallets)))
    monkeypatch.setattr(wp, "_hl_accounts_wallets", lambda: [BONDS2, FUSION2])
    return calls


def test_kick_respects_ttl_in_flight_and_cooldown(spawns):
    assert wp._maybe_kick_dexfi_bonds_refresh(NOW) is True                 # cold cache
    assert spawns == [[BONDS2, FUSION2]] and wp._DEXFI_BONDS_IN_FLIGHT is True
    assert wp._maybe_kick_dexfi_bonds_refresh(NOW + timedelta(minutes=45)) is False   # in flight
    wp._DEXFI_BONDS_IN_FLIGHT = False
    assert wp._maybe_kick_dexfi_bonds_refresh(NOW + timedelta(minutes=10)) is False   # cooldown
    wp._DEXFI_BONDS_CACHE["fetched_at"] = (NOW + timedelta(minutes=40)).isoformat()
    assert wp._maybe_kick_dexfi_bonds_refresh(NOW + timedelta(minutes=60)) is False   # fresh (20 min)
    assert wp._maybe_kick_dexfi_bonds_refresh(NOW + timedelta(minutes=71)) is True    # stale, cooled down
    assert len(spawns) == 2


def test_kick_with_no_wallets_does_nothing(monkeypatch, spawns):
    monkeypatch.setattr(wp, "_hl_accounts_wallets", lambda: [])
    assert wp._maybe_kick_dexfi_bonds_refresh(NOW) is False and spawns == []


def test_snapshot_runs_the_worker_inline_when_stale(monkeypatch, spawns):
    ran = []

    def worker(wallets, now_utc=None):
        ran.append(list(wallets))
        wp._DEXFI_BONDS_CACHE.update({"fetched_at": NOW.isoformat(), "wallets": {BONDS2: {"value_usd": 1.0}}})
        wp._DEXFI_BONDS_IN_FLIGHT = False
    monkeypatch.setattr(wp, "_dexfi_bonds_refresh_worker", worker)
    state = wp._dexfi_bonds_state_for_snapshot(NOW)
    assert ran == [[BONDS2, FUSION2]] and spawns == []
    assert state["wallets"] == {BONDS2: {"value_usd": 1.0}}
    state["wallets"].clear()                                                # a copy, not the cache
    assert wp._DEXFI_BONDS_CACHE["wallets"] == {BONDS2: {"value_usd": 1.0}}


def test_snapshot_fresh_cache_does_not_refetch(monkeypatch, spawns):
    monkeypatch.setattr(wp, "_dexfi_bonds_refresh_worker",
                        lambda wallets, now_utc=None: (_ for _ in ()).throw(AssertionError("fetched")))
    _prime({BONDS2: {"value_usd": 1.0}}, fetched_at=(NOW - timedelta(minutes=5)).isoformat())
    assert wp._dexfi_bonds_state_for_snapshot(NOW)["wallets"] == {BONDS2: {"value_usd": 1.0}}


def test_snapshot_waits_for_an_in_flight_refresh(monkeypatch, spawns):
    wp._DEXFI_BONDS_IN_FLIGHT = True
    sleeps = []

    def sleep(sec):
        sleeps.append(sec)
        if len(sleeps) == 3:
            wp._DEXFI_BONDS_IN_FLIGHT = False
    wp._dexfi_bonds_state_for_snapshot(NOW, sleep=sleep)
    assert sleeps == [wp.HL_SNAPSHOT_POLL_SECONDS] * 3
