"""Bittensor (TAO) wallet type, commit 1: SS58 prefix-42 validation
(is_valid_bittensor_address), classify_wallet_address -> 'bittensor',
POST /api/wallets saving type 'bittensor', and the shared wallet split
(_wallet_groups) that keeps Bittensor wallets away from Zerion, custom-token
balanceOf reads and GMX.

Only public Substrate dev addresses (Alice, Bob) are used. No network.

web_portfolio spawns a background scheduler on non-__main__ import; we
neutralize threading.Thread.start during import (established pattern) so no
thread starts.
"""
import threading

_orig_start = threading.Thread.start
threading.Thread.start = lambda self, *a, **k: None
try:
    import web_portfolio as wp
finally:
    threading.Thread.start = _orig_start

import pytest

ALICE = "5GrwvaEF5zXb26Fz9rcQpDWS57CtERHpNehXCPcNoHGKutQY"
BOB = "5FHneW46xGXgs5mUiveU4sbTyGBzmstUspZC92UhjJM694ty"
OTHER_PREFIX = "HNZata7iMYWmk5RvZRTiAsSDhV8366zq2YGb3tLH5Upf74F"     # another SS58 network
SOLANA_ADDR = "2gxbfDnJT5ifnnziZjEPd2BpHrHgEhaCfpbf3Hi1eTJ6"
EVM1 = "0x1234567890123456789012345678901234567890"
EVM2 = "0x5B38Da6a701c568545dCfcB03FcB875f56beddC4"
XPUB = "xpub" + "K" * 103


# Fixture pattern copied from tests/test_wallet_classification.py:
# WALLET_CONFIG_FILE and ENV_FILE point at per-test tmp paths, so the real
# wallet_config.json and .env are never touched.
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


# ── is_valid_bittensor_address ────────────────────────────────────────────

def test_valid_dev_addresses_accepted():
    assert wp.is_valid_bittensor_address(ALICE) is True
    assert wp.is_valid_bittensor_address(BOB) is True


def test_one_char_typo_rejected():
    assert wp.is_valid_bittensor_address(ALICE[:-1] + "R") is False


def test_other_network_prefix_rejected():
    assert wp.is_valid_bittensor_address(OTHER_PREFIX) is False


def test_malformed_rejected():
    for bad in (ALICE[:-1], ALICE + "a", ALICE[:-1] + "0", ALICE[:-1] + "l", "5" + "z" * 47, "", None,
                SOLANA_ADDR, EVM1):
        assert wp.is_valid_bittensor_address(bad) is False, bad


# ── classify_wallet_address ───────────────────────────────────────────────

def test_classify_bittensor():
    assert wp.classify_wallet_address(ALICE) == 'bittensor'
    assert wp.classify_wallet_address(SOLANA_ADDR) == 'solana'
    assert wp.classify_wallet_address(EVM1) == 'evm'


def test_classify_typo_is_none():
    assert wp.classify_wallet_address(ALICE[:-1] + "R") is None


# ── POST /api/wallets ─────────────────────────────────────────────────────

def test_post_bittensor_saves_type_and_default_label(client):
    resp = client.post("/api/wallets", json={"address": ALICE, "label": ""})
    assert resp.status_code == 200 and resp.get_json()["success"] is True
    saved = wp.load_wallet_config()[ALICE]
    assert saved["type"] == "bittensor" and saved["label"] == "Bittensor"


def test_post_bittensor_keeps_given_label(client):
    resp = client.post("/api/wallets", json={"address": BOB, "label": "TAO bot"})
    assert resp.status_code == 200
    saved = wp.load_wallet_config()[BOB]
    assert saved["label"] == "TAO bot" and saved["type"] == "bittensor"


def test_post_ss58_typo_returns_checksum_error(client):
    typo = ALICE[:-1] + "R"
    resp = client.post("/api/wallets", json={"address": typo, "label": ""})
    assert resp.status_code == 400
    assert "checksum" in resp.get_json()["error"]
    assert typo not in wp.load_wallet_config()


# ── _wallet_groups ────────────────────────────────────────────────────────

def test_wallet_groups_split_preserves_order():
    config = {SOLANA_ADDR: {"type": "solana"}, XPUB: {"type": "bitcoin_xpub"}, ALICE: {"type": "bittensor"},
              EVM1: {"label": "a"}, EVM2: {}}
    assert wp._wallet_groups([EVM1, SOLANA_ADDR, XPUB, ALICE, EVM2], config) == {
        "evm": [EVM1, EVM2], "solana": [SOLANA_ADDR], "bitcoin_xpub": [XPUB], "bittensor": [ALICE]}


def test_wallet_groups_untyped_ss58_is_bittensor():
    groups = wp._wallet_groups([BOB], {BOB: {}})
    assert groups["bittensor"] == [BOB] and BOB not in groups["evm"]


def test_wallet_groups_untyped_legacy_non_evm_stays_evm():
    # Pins today's rule: an untyped wallet that is not a valid SS58 address
    # stays in the EVM group, whatever its format.
    groups = wp._wallet_groups([SOLANA_ADDR], {SOLANA_ADDR: {"label": "old"}})
    assert groups["evm"] == [SOLANA_ADDR] and groups["solana"] == []
