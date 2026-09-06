"""Tests for classify_wallet_address (web_portfolio.py) and the matching
Solana acceptance in ZerionConnector._validate_wallet / ZERION_CHAIN_MAP
(src/connectors/zerion.py).

web_portfolio spawns a background scheduler on non-__main__ import; we
neutralize threading.Thread.start during import (established pattern in the
other route test files) so no thread starts.
"""
import threading

_orig_start = threading.Thread.start
threading.Thread.start = lambda self, *a, **k: None
try:
    import web_portfolio as wp
finally:
    threading.Thread.start = _orig_start

import pytest

from src.connectors.zerion import ZerionConnector, get_chain_name

SOLANA_ADDR = "2gxbfDnJT5ifnnziZjEPd2BpHrHgEhaCfpbf3Hi1eTJ6"


# ── classify_wallet_address ───────────────────────────────────────────────

def test_classify_lowercase_evm():
    assert wp.classify_wallet_address("0x1234567890123456789012345678901234567890") == 'evm'


def test_classify_checksummed_evm():
    # is_valid_address only checks 0x + 40 hex chars (no checksum validation),
    # so a mixed-case address classifies identically to an all-lowercase one.
    assert wp.classify_wallet_address("0x5B38Da6a701c568545dCfcB03FcB875f56beddC4") == 'evm'


def test_classify_solana_address():
    assert wp.classify_wallet_address(SOLANA_ADDR) == 'solana'


def test_classify_xpub_prefixed_string():
    xpub_like = "xpub" + "K" * 103  # 107 chars total
    assert len(xpub_like) == 107
    assert wp.classify_wallet_address(xpub_like) == 'bitcoin_xpub'


def test_classify_base58_length_string_with_excluded_chars_is_none():
    # base58 excludes '0', 'O', 'I', 'l' - a base58-length string containing
    # either must fail the regex and classify as unrecognized.
    with_zero = SOLANA_ADDR[:-1] + "0"
    with_ell = SOLANA_ADDR[:-1] + "l"
    assert wp.classify_wallet_address(with_zero) is None
    assert wp.classify_wallet_address(with_ell) is None


def test_classify_empty_string_is_none():
    assert wp.classify_wallet_address("") is None


def test_classify_short_evm_like_string_is_none():
    assert wp.classify_wallet_address("0x" + "a" * 39) is None


# ── ZerionConnector._validate_wallet ─────────────────────────────────────

def test_validate_wallet_accepts_solana_address():
    ZerionConnector._validate_wallet(SOLANA_ADDR)  # must not raise


def test_validate_wallet_accepts_evm_address():
    ZerionConnector._validate_wallet("0x1234567890123456789012345678901234567890")  # must not raise


def test_validate_wallet_rejects_garbage():
    with pytest.raises(ValueError):
        ZerionConnector._validate_wallet("not-an-address")


# ── ZERION_CHAIN_MAP / get_chain_name ────────────────────────────────────

def test_get_chain_name_solana():
    assert get_chain_name("solana") == "Solana"


# ── Route: POST /api/wallets with a Solana address ───────────────────────
# Fixture pattern copied from tests/test_wallets_route.py: WALLET_CONFIG_FILE
# is monkeypatched to a per-test tmp path so save_wallet_config's real file
# round-trip is exercised. ENV_FILE is likewise monkeypatched here since
# api_add_wallet (unlike the PUT route test_wallets_route.py covers) also
# calls save_wallet_addresses(), which writes WALLET_ADDRESS via
# dotenv.set_key(ENV_FILE, ...) - this must not touch the repo's real .env.

@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(wp, "get_password_hash", lambda: "x")
    monkeypatch.setattr(wp, "WALLET_CONFIG_FILE", str(tmp_path / "wallet_config.json"))
    monkeypatch.setattr(wp, "ENV_FILE", str(tmp_path / ".env"))
    wp.app.config["TESTING"] = True
    c = wp.app.test_client()
    with c.session_transaction() as sess:
        sess["authenticated"] = True
    return c


def test_post_wallets_with_solana_address_succeeds_and_saves_type(client):
    resp = client.post("/api/wallets", json={"address": SOLANA_ADDR, "label": ""})
    assert resp.status_code == 200
    assert resp.get_json()["success"] is True

    saved = wp.load_wallet_config()
    assert saved[SOLANA_ADDR]["type"] == "solana"
    assert saved[SOLANA_ADDR]["label"].startswith("Solana Wallet")
