"""Age wording on the carried-price clause (Landing 40, Oct 15).

portfolio_total ruling 7 flags custom-token prices carried from
custom_token_price_snapshot with one display-only clause per part. Its age
was printed as f"{hours:.0f} h old", so a price carried from a fetch under
30 minutes ago read "0 h old". The clause now uses _age_text (Landing 39):
", N min old" while the age rounds under 60 minutes (at least 1), else
", N h old", the same wording as the carried-balance clause. No value,
total or detail field changes.

Pure compose_total calls; no database, no network. Addresses are synthetic.
"""
from datetime import datetime, timedelta, timezone

import pytest

import portfolio_total as pt

NOW = datetime(2026, 10, 15, 15, 0, tzinfo=timezone.utc)
A = "0x" + "a" * 40
TOKEN = "0x" + "7c" * 20                       # synthetic ERC-20 contract
MINT = "MintAgeTextXyz" + "6" * 28             # synthetic Solana mint


def _c(result, key):
    return next(c for c in result["components"] if c["key"] == key)


def _carried(hours=3.0, value=3800.0, **kw):
    """A custom-token row priced at a carried last good price."""
    row = {"chain": "Base", "symbol": "PLAZM", "balance": value / 0.038, "value_usd": value,
           "price_usd": 0.038, "contract": TOKEN, "wallet": A, "source": "custom",
           "balance_failed": False, "price_stale": True,
           "price_as_of": None if hours is None else (NOW - timedelta(hours=hours)).isoformat()}
    row.update(kw)
    return row


def _stale_balance(hours, value=4200.0):
    """A custom-token row served at its last good balance (ruling 11)."""
    return {"chain": "Solana", "symbol": "SOLX", "balance": value / 2.0, "value_usd": value,
            "price_usd": 2.0, "contract": MINT, "wallet": A, "source": "custom",
            "balance_failed": False, "price_stale": False, "price_as_of": None,
            "balance_stale": True, "balance_as_of": (NOW - timedelta(hours=hours)).isoformat()}


def _portfolio(*extra):
    return {
        "tokens": [{"symbol": "ETH", "value_usd": 2000.0, "wallet": A},
                   {"symbol": "USDC", "value_usd": 300.0, "wallet": A}] + list(extra),
        "lp_positions": [], "aave_positions": [], "gmx_positions": [], "staking_positions": [],
        "total_tokens_value": 2300.0, "total_lp_value": 0.0, "total_uncollected_fees": 0.0,
        "total_value": 2300.0, "wallet_labels": {A: "Rabby"}, "fetched_at": "2026-10-15T14:50:00",
    }


def _compose(p):
    return pt.compose_total(p, [], set(), True, {}, {"fetched_at": None, "wallets": {}, "error": None}, NOW)


@pytest.mark.parametrize("hours, text", [
    (20 / 60, "20 min old"),       # printed "0 h old" before Landing 40
    (40 / 60, "40 min old"),       # printed "1 h old" before Landing 40
    (5 / 3600, "1 min old"),       # never "0 min old"
    (59.7 / 60, "1 h old"),        # rounds to 60 minutes
    (1.0, "1 h old"),
    (3.0, "3 h old"),
    (23.6, "24 h old")])
def test_carried_price_age_wording(hours, text):
    wt = _c(_compose(_portfolio(_carried(hours=hours))), "wallet_tokens")
    assert wt["warnings"] == [f"1 token at last good price — about $3,800 (PLAZM, {text})"]
    assert wt["detail"]["stale"]["price_oldest_hours"] == pytest.approx(hours)


def test_oldest_row_sets_the_age():
    other = _carried(hours=10 / 60, value=1200.0, symbol="VIRT", contract="0x" + "ab" * 20)
    wt = _c(_compose(_portfolio(_carried(hours=50 / 60), other)), "wallet_tokens")
    assert wt["warnings"] == ["2 tokens at last good price — about $5,000 (PLAZM, VIRT, 50 min old)"]


def test_missing_time_has_no_age():
    wt = _c(_compose(_portfolio(_carried(hours=None))), "wallet_tokens")
    assert wt["warnings"] == ["1 token at last good price — about $3,800 (PLAZM)"]
    assert wt["detail"]["stale"]["price_oldest_hours"] is None


def test_small_carried_price_stays_detail_only():
    wt = _c(_compose(_portfolio(_carried(hours=20 / 60, value=300.0))), "wallet_tokens")
    assert wt["warnings"] == []
    assert wt["detail"]["stale"]["est_usd"] == 300.0


def test_both_clauses_use_the_same_wording_and_order():
    wt = _c(_compose(_portfolio(_carried(hours=20 / 60), _stale_balance(15 / 60))), "wallet_tokens")
    assert wt["warnings"] == [
        "1 token at last good price — about $3,800 (PLAZM, 20 min old); "
        "1 token at last good balance — about $4,200 (SOLX, 15 min old)"]


def test_values_do_not_depend_on_the_age():
    fresh = _compose(_portfolio(_carried(hours=20 / 60)))
    old = _compose(_portfolio(_carried(hours=5.0)))
    assert fresh["total_usd"] == old["total_usd"]
    assert [c["value_usd"] for c in fresh["components"]] == [c["value_usd"] for c in old["components"]]
    assert _c(fresh, "wallet_tokens")["value_usd"] == pytest.approx(2000.0 + 3800.0)
