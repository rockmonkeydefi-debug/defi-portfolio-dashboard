"""Tests for Uniswap V3 gap discovery — positions balanceOf can't enumerate.

`tokenOfOwnerByIndex` only sees NFTs the wallet currently holds, so a position
custodied by a manager/staking contract is invisible to it even though the
wallet still owns it economically and Zerion still reports it. That gap is what
left one of two same-pool positions showing UNKNOWN. These tests pin the
recovery path and — more importantly — its safety guards, since attributing the
wrong position's range to a row would be worse than showing no range at all.
"""
import threading

_orig_start = threading.Thread.start
threading.Thread.start = lambda self, *a, **k: None
try:
    import web_portfolio as wp
finally:
    threading.Thread.start = _orig_start

from src.connectors.uniswap_v3 import UniswapV3Connector
from src.models import Chain, LPType, Protocol

WALLET = "0x1111111111111111111111111111111111111111"
MANAGER_CONTRACT = "0x2222222222222222222222222222222222222222"
OTHER_EOA = "0x3333333333333333333333333333333333333333"
WETH = "0x4200000000000000000000000000000000000006"
USDC = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"

PAIR_WETH_USDC = wp.lp_pair_key("WETH", "USDC")


class _Call:
    def __init__(self, v):
        self._v = v

    def call(self):
        if isinstance(self._v, Exception):
            raise self._v
        return self._v


class _PMFunctions:
    def __init__(self, positions_by_id, owners_by_id):
        self._positions = positions_by_id
        self._owners = owners_by_id

    def positions(self, token_id):
        return _Call(self._positions[token_id])

    def ownerOf(self, token_id):
        return _Call(self._owners[token_id])


class _Eth:
    def __init__(self, chain_id, code_by_address):
        self.chain_id = chain_id
        self._code = code_by_address

    def get_code(self, address):
        return self._code.get(address, b"")


class _W3:
    def __init__(self, chain_id, code_by_address):
        self.eth = _Eth(chain_id, code_by_address)


def _position_tuple(token0, token1, tick_lower, tick_upper, liquidity, fee=3000):
    # (nonce, operator, token0, token1, fee, tickLower, tickUpper, liquidity, ...)
    return (0, "0x0", token0, token1, fee, tick_lower, tick_upper, liquidity, 0, 0, 0, 0)


def _make_connector(positions_by_id, owners_by_id, code_by_address=None, chain_id=8453):
    c = UniswapV3Connector.__new__(UniswapV3Connector)  # bypass __init__ (no RPC)
    c.chain = Chain.BASE
    c.position_manager_address = "0x03a520b32C04BF3bEEf7BEb72E919cf822Ed34f1"
    c.w3 = _W3(chain_id, code_by_address or {})
    c.position_manager = type("PM", (), {"functions": _PMFunctions(positions_by_id, owners_by_id)})()
    c._compute_pool_address = lambda t0, t1, fee: "0xpool"

    def _meta(addr):
        return type("M", (), {"symbol": "WETH" if addr == WETH else "USDC"})()
    c._get_token_metadata = _meta
    return c


def _patch_discovery(monkeypatch, token_ids):
    import src.connectors.erc721_discovery as disc
    monkeypatch.setattr(disc, "discover_incoming_token_ids",
                        lambda chain_id, contract, wallet, api_key=None: token_ids)


# ─── the recovery path ────────────────────────────────────────────────────────

def test_recovers_manager_held_position(monkeypatch):
    """The reported case: one of two same-pool positions sits with a manager
    contract, so balanceOf misses it. It should be recovered with real ticks."""
    _patch_discovery(monkeypatch, [777])
    c = _make_connector(
        positions_by_id={777: _position_tuple(WETH, USDC, -1000, 1000, 10**18)},
        owners_by_id={777: MANAGER_CONTRACT},
        code_by_address={MANAGER_CONTRACT: b"\x60\x60"},  # a contract
    )

    found = c.discover_unenumerated_positions(WALLET, {PAIR_WETH_USDC: 1}, wp.lp_pair_key)

    assert len(found) == 1
    assert found[0].token_id == 777
    assert found[0].tick_lower == -1000
    assert found[0].tick_upper == 1000
    assert found[0].lp_type is LPType.V3
    assert found[0].protocol is Protocol.UNISWAP_V3


def test_recovers_position_still_owned_by_wallet(monkeypatch):
    """Enumeration can also miss a directly-held NFT (e.g. tokenOfOwnerByIndex
    reverted); ownership by the wallet itself is unambiguously ours."""
    _patch_discovery(monkeypatch, [777])
    c = _make_connector(
        positions_by_id={777: _position_tuple(WETH, USDC, -500, 500, 10**18)},
        owners_by_id={777: WALLET},
    )
    found = c.discover_unenumerated_positions(WALLET, {PAIR_WETH_USDC: 1}, wp.lp_pair_key)
    assert [p.token_id for p in found] == [777]


# ─── safety guards: never attribute the wrong position ────────────────────────

def test_ambiguous_candidates_yield_nothing(monkeypatch):
    """Two open candidates on the same pair but only one missing: we cannot tell
    which is the reported position, so neither is used (tier-3 nulls instead)."""
    _patch_discovery(monkeypatch, [777, 888])
    c = _make_connector(
        positions_by_id={
            777: _position_tuple(WETH, USDC, -1000, 1000, 10**18),
            888: _position_tuple(WETH, USDC, -2000, 2000, 10**18),
        },
        owners_by_id={777: MANAGER_CONTRACT, 888: MANAGER_CONTRACT},
        code_by_address={MANAGER_CONTRACT: b"\x60\x60"},
    )
    assert c.discover_unenumerated_positions(WALLET, {PAIR_WETH_USDC: 1}, wp.lp_pair_key) == []


def test_sold_position_is_excluded(monkeypatch):
    """NFT now held by a different EOA — sold, not custodied. Not our position."""
    _patch_discovery(monkeypatch, [777])
    c = _make_connector(
        positions_by_id={777: _position_tuple(WETH, USDC, -1000, 1000, 10**18)},
        owners_by_id={777: OTHER_EOA},
        code_by_address={},  # no code -> EOA
    )
    assert c.discover_unenumerated_positions(WALLET, {PAIR_WETH_USDC: 1}, wp.lp_pair_key) == []


def test_closed_position_is_excluded(monkeypatch):
    """Zero liquidity means the position is closed — no live range to show."""
    _patch_discovery(monkeypatch, [777])
    c = _make_connector(
        positions_by_id={777: _position_tuple(WETH, USDC, -1000, 1000, 0)},
        owners_by_id={777: MANAGER_CONTRACT},
        code_by_address={MANAGER_CONTRACT: b"\x60\x60"},
    )
    assert c.discover_unenumerated_positions(WALLET, {PAIR_WETH_USDC: 1}, wp.lp_pair_key) == []


def test_unwanted_pair_is_ignored(monkeypatch):
    """Only pairs Zerion actually reports as missing are considered — this
    closes a known gap, it does not invent positions."""
    _patch_discovery(monkeypatch, [777])
    c = _make_connector(
        positions_by_id={777: _position_tuple(WETH, USDC, -1000, 1000, 10**18)},
        owners_by_id={777: MANAGER_CONTRACT},
        code_by_address={MANAGER_CONTRACT: b"\x60\x60"},
    )
    other_pair = wp.lp_pair_key("DAI", "USDC")
    assert c.discover_unenumerated_positions(WALLET, {other_pair: 1}, wp.lp_pair_key) == []


def test_already_enumerated_token_is_excluded(monkeypatch):
    """A position get_positions already enriched must not be added twice."""
    _patch_discovery(monkeypatch, [777])
    c = _make_connector(
        positions_by_id={777: _position_tuple(WETH, USDC, -1000, 1000, 10**18)},
        owners_by_id={777: WALLET},
    )
    found = c.discover_unenumerated_positions(
        WALLET, {PAIR_WETH_USDC: 1}, wp.lp_pair_key, exclude_token_ids=[777]
    )
    assert found == []


# ─── degradation: every failure mode yields "nothing found", never a raise ────

def test_no_wanted_pairs_short_circuits(monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("discovery must not run when nothing is missing")
    import src.connectors.erc721_discovery as disc
    monkeypatch.setattr(disc, "discover_incoming_token_ids", _boom)
    c = _make_connector({}, {})
    assert c.discover_unenumerated_positions(WALLET, {}, wp.lp_pair_key) == []


def test_discovery_unavailable_returns_empty(monkeypatch):
    """No Etherscan key / query failed -> None -> treat as nothing found."""
    _patch_discovery(monkeypatch, None)
    c = _make_connector({}, {})
    assert c.discover_unenumerated_positions(WALLET, {PAIR_WETH_USDC: 1}, wp.lp_pair_key) == []


def test_position_read_failure_is_isolated(monkeypatch):
    """One unreadable candidate must not stop a readable one from being found."""
    _patch_discovery(monkeypatch, [666, 777])
    c = _make_connector(
        positions_by_id={
            666: RuntimeError("RPC blew up"),
            777: _position_tuple(WETH, USDC, -1000, 1000, 10**18),
        },
        owners_by_id={666: MANAGER_CONTRACT, 777: MANAGER_CONTRACT},
        code_by_address={MANAGER_CONTRACT: b"\x60\x60"},
    )
    found = c.discover_unenumerated_positions(WALLET, {PAIR_WETH_USDC: 1}, wp.lp_pair_key)
    assert [p.token_id for p in found] == [777]


# ─── erc721_discovery helper ──────────────────────────────────────────────────

def test_discovery_helper_requires_api_key(monkeypatch):
    from src.connectors import erc721_discovery as disc
    monkeypatch.delenv("ETHERSCAN_API_KEY", raising=False)
    assert disc.discover_incoming_token_ids(8453, "0xcontract", WALLET) is None


def test_discovery_helper_rejects_unsupported_chain(monkeypatch):
    from src.connectors import erc721_discovery as disc
    monkeypatch.setenv("ETHERSCAN_API_KEY", "k")
    assert disc.discover_incoming_token_ids(999999, "0xcontract", WALLET) is None


def test_discovery_helper_supports_base():
    from src.connectors.erc721_discovery import ETHERSCAN_V2_CHAIN_IDS
    assert {1, 42161, 8453} <= ETHERSCAN_V2_CHAIN_IDS
