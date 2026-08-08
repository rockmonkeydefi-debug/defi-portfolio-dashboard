"""Zerion API v1 connector — fetches wallet positions across all EVM chains."""

import base64
import os
import re
import time
from typing import Dict, List, Optional

import requests


class ZerionAPIError(Exception):
    """Raised when the Zerion API returns a non-2xx response."""

    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        super().__init__(f"Zerion API error {status_code}: {message}")


# Regex for valid EVM wallet address: 0x followed by 40 hex chars (42 total)
_WALLET_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")


# ---------------------------------------------------------------------------
# Chain name mapping
# ---------------------------------------------------------------------------

ZERION_CHAIN_MAP: Dict[str, str] = {
    "ethereum": "Ethereum",
    "arbitrum": "Arbitrum",
    "base": "Base",
    "optimism": "Optimism",
    "polygon": "Polygon",
    "avalanche": "Avalanche",
    "bsc": "BSC",
}


def get_chain_name(chain_id: str) -> str:
    """Return the display name for a Zerion chain identifier.

    Looks up *chain_id* in :data:`ZERION_CHAIN_MAP`.  For unknown identifiers
    the first letter is capitalised as a fallback so the result always starts
    with an uppercase character.
    """
    if chain_id in ZERION_CHAIN_MAP:
        return ZERION_CHAIN_MAP[chain_id]
    return chain_id.capitalize() if chain_id else chain_id


def categorize_zerion_positions(positions: list) -> dict:
    """Categorize raw Zerion positions into app groups.

    Uses a two-pass approach:

    1. Identify ``group_id`` values that contain at least one position with
       ``protocol_module`` in ``("liquidity_pool", "farming")``.
    2. Assign each position to exactly one category:

       * ``position_type == "wallet"`` → **tokens**
       * ``protocol_module == "lending"`` → **lending**
       * ``protocol_module in ("liquidity_pool", "farming")`` **or**
         the position's ``group_id`` belongs to an LP group → **lp_basic**
       * ``protocol_module in ("staked", "locked", "reward", "deposit")`` or
         ``position_type in ("staked", "locked", "deposit", "reward")`` → **staking**
       * Anything else falls back to **tokens**

    The total number of positions across all output categories always
    equals the input count — no position is lost or duplicated.
    """
    # Pass 1: find group_ids that contain LP positions
    lp_group_ids: set = set()
    for pos in positions:
        attrs = pos.get("attributes", {})
        module = attrs.get("protocol_module") or ""
        if module in ("liquidity_pool", "farming"):
            group_id = attrs.get("group_id")
            if group_id:
                lp_group_ids.add(group_id)

    # Pass 2: categorize
    tokens: list = []
    lending: list = []
    lp_basic: list = []
    staking: list = []

    for pos in positions:
        attrs = pos.get("attributes", {})
        pos_type = attrs.get("position_type", "wallet")
        module = attrs.get("protocol_module") or ""
        group_id = attrs.get("group_id")

        if pos_type == "wallet":
            tokens.append(pos)
        elif module == "lending":
            lending.append(pos)
        elif module in ("liquidity_pool", "farming"):
            lp_basic.append(pos)
        elif group_id and group_id in lp_group_ids:
            # Deposit/reward legs that belong to an LP group
            lp_basic.append(pos)
        elif module in ("staked", "locked", "reward", "deposit") or pos_type in ("staked", "locked", "deposit", "reward"):
            staking.append(pos)
        else:
            tokens.append(pos)

    return {"tokens": tokens, "lending": lending, "lp_basic": lp_basic, "staking": staking}

def map_zerion_token_to_app(position: dict, wallet: str, wallet_label: str) -> dict:
    """Map a single Zerion wallet position to the app's token format.

    Extracts chain, symbol, balance, value, and price from the Zerion
    position structure and returns a dict matching the app token format
    consumed by the frontend.

    Defaults: ``symbol`` → ``"UNKNOWN"``, ``value_usd`` / ``price_usd`` → ``0.0``.
    """
    attrs = position.get("attributes", {})
    fi = attrs.get("fungible_info", {})
    chain_id = (
        position.get("relationships", {})
        .get("chain", {})
        .get("data", {})
        .get("id", "unknown")
    )

    # Contract address for this chain's implementation (used to dedupe against
    # user-added custom tokens). Empty string when Zerion omits it (e.g. native ETH).
    contract = ""
    for impl in fi.get("implementations", []) or []:
        if impl.get("chain_id") == chain_id and impl.get("address"):
            contract = impl.get("address", "")
            break

    return {
        "chain": get_chain_name(chain_id),
        "symbol": fi.get("symbol", "UNKNOWN"),
        "balance": attrs.get("quantity", {}).get("float", 0.0),
        "value_usd": attrs.get("value") or 0.0,
        "price_usd": attrs.get("price") or 0.0,
        "contract": contract,
        "wallet": wallet,
        "wallet_label": wallet_label,
    }

def map_zerion_lending_to_app(group_positions: list, wallet: str, wallet_label: str) -> dict:
    """Map a group of Zerion lending positions to the app's Aave-compatible format.

    Positions with ``position_type`` in ``("deposit", "staked")`` are classified
    as supplied assets; ``"borrow"`` positions are classified as borrowed assets.
    Absolute values are used for borrowed ``balance`` and ``value_usd`` to ensure
    non-negative output.

    The protocol name is extracted from ``application_metadata.name`` with a
    fallback to the ``protocol`` attribute.

    Fields not available from the Zerion positions endpoint (``health_factor``,
    ``liquidation_threshold``, ``available_borrows_usd``, ``supply_apy``,
    ``borrow_apy``) are set to ``0``; ``liquidation_price`` is set to ``None``.
    """
    supplied: list = []
    borrowed: list = []
    total_supplied_usd = 0.0
    total_borrowed_usd = 0.0

    chain_id = ""
    protocol_name = ""

    for pos in group_positions:
        attrs = pos.get("attributes", {})
        fi = attrs.get("fungible_info", {})
        pos_type = attrs.get("position_type", "")
        value = abs(attrs.get("value") or 0.0)
        price = attrs.get("price") or 0.0
        balance = abs(attrs.get("quantity", {}).get("float", 0.0))

        if not chain_id:
            chain_id = (
                pos.get("relationships", {})
                .get("chain", {})
                .get("data", {})
                .get("id", "")
            )
        if not protocol_name:
            app_meta = attrs.get("application_metadata", {})
            protocol_name = app_meta.get("name", attrs.get("protocol", ""))

        entry = {
            "symbol": fi.get("symbol", "UNKNOWN"),
            "token_address": "",
            "balance": balance,
            "price_usd": price,
            "value_usd": value,
        }

        if pos_type in ("deposit", "staked"):
            entry["supply_apy"] = 0
            entry["collateral_enabled"] = True
            entry["ltv"] = 0
            entry["liquidation_threshold"] = 0
            supplied.append(entry)
            total_supplied_usd += value
        elif pos_type == "borrow":
            entry["borrow_apy"] = 0
            entry["is_variable"] = True
            borrowed.append(entry)
            total_borrowed_usd += value

    chain_name = get_chain_name(chain_id)
    ltv = (total_borrowed_usd / total_supplied_usd * 100) if total_supplied_usd > 0 else 0

    return {
        "chain": chain_id,
        "chain_name": chain_name,
        "protocol_name": protocol_name,
        "total_collateral_usd": total_supplied_usd,
        "total_debt_usd": total_borrowed_usd,
        "available_borrows_usd": 0,
        "ltv": ltv,
        "liquidation_threshold": 0,
        "health_factor": 0,
        "supplied": supplied,
        "borrowed": borrowed,
        "wallet": wallet,
        "wallet_label": wallet_label,
        "liquidation_price": None,
    }


def map_zerion_lp_to_app(group_positions: list, wallet: str, wallet_label: str) -> dict:
    """Map a group of Zerion LP positions (same group_id) to the app's LP format.

    Zerion groups the underlying tokens of a single LP position under the same
    ``group_id``.  Positions with ``position_type == "reward"`` are treated as
    uncollected fees; all others are the principal deposit.

    Duplicate symbols are merged: if two ``deposit`` legs share the same symbol,
    their amounts and values are summed into a single token0/token1 entry.
    """
    first = group_positions[0]
    attrs = first.get("attributes", {})
    chain_id = (
        first.get("relationships", {})
        .get("chain", {})
        .get("data", {})
        .get("id", "unknown")
    )
    app_meta = attrs.get("application_metadata", {})
    protocol_name = app_meta.get("name", attrs.get("protocol", "unknown"))
    protocol_icon_url = (app_meta.get("icon") or {}).get("url", "")
    # Determine the dominant module for this group (liquidity_pool vs farming)
    modules = set()
    for pos in group_positions:
        m = pos.get("attributes", {}).get("protocol_module") or ""
        if m:
            modules.add(m)
    position_module = "farming" if "farming" in modules else "liquidity_pool"

    # Separate deposit (principal) from reward (fees) legs
    deposits: dict = {}  # symbol -> {amount, value, price}
    rewards: dict = {}   # symbol -> {amount, value, price}
    for pos in group_positions:
        a = pos.get("attributes", {})
        fi = a.get("fungible_info", {})
        sym = fi.get("symbol", "?")
        amount = a.get("quantity", {}).get("float", 0.0)
        value = abs(a.get("value") or 0.0)
        price = a.get("price") or 0.0
        pos_type = a.get("position_type", "")

        bucket = rewards if pos_type == "reward" else deposits
        if sym in bucket:
            bucket[sym]["amount"] += amount
            bucket[sym]["value"] += value
        else:
            bucket[sym] = {"amount": amount, "value": value, "price": price}

    # Build token lists from deposits
    dep_symbols = list(deposits.keys())
    pair = "/".join(dep_symbols) if dep_symbols else "UNKNOWN"

    token0_symbol = dep_symbols[0] if len(dep_symbols) > 0 else "?"
    token1_symbol = dep_symbols[1] if len(dep_symbols) > 1 else "?"
    d0 = deposits.get(token0_symbol, {})
    d1 = deposits.get(token1_symbol, {})

    # Fees from reward legs
    r0 = rewards.get(token0_symbol, {})
    r1 = rewards.get(token1_symbol, {})
    fees0 = r0.get("amount", 0.0)
    fees1 = r1.get("amount", 0.0)
    fees0_usd = r0.get("value", 0.0)
    fees1_usd = r1.get("value", 0.0)
    total_fees_usd = fees0_usd + fees1_usd

    total_deposit_value = sum(d["value"] for d in deposits.values())

    return {
        "token_id": None,
        "chain": chain_id,
        "pair": pair,
        "protocol": protocol_name.lower().replace(" ", "_"),
        "protocol_display": protocol_name,
        "protocol_icon_url": protocol_icon_url,
        "token0_symbol": token0_symbol,
        "token1_symbol": token1_symbol,
        "amount0": d0.get("amount", 0.0),
        "amount1": d1.get("amount", 0.0),
        "price0_usd": d0.get("price", 0.0),
        "price1_usd": d1.get("price", 0.0),
        "value0_usd": d0.get("value", 0.0),
        "value1_usd": d1.get("value", 0.0),
        "total_value_usd": total_deposit_value,
        # Fees from reward legs
        "fees_owed0": fees0,
        "fees_owed1": fees1,
        "fees0_usd": fees0_usd,
        "fees1_usd": fees1_usd,
        "total_fees_usd": total_fees_usd,
        "collected_fees_0": 0.0,
        "collected_fees_1": 0.0,
        "collected_fees_0_usd": 0.0,
        "collected_fees_1_usd": 0.0,
        "total_collected_fees_usd": 0.0,
        "total_earned_fees_0": fees0,
        "total_earned_fees_1": fees1,
        "total_earned_fees_usd": total_fees_usd,
        "age_days": None,
        "age_hours": None,
        "daily_apr": None,
        "monthly_apr": None,
        "daily_earnings": None,
        # Range fields — not available from Zerion for basic LPs
        "in_range": True,
        "fee_tier": 0,
        "current_price": 0,
        "price_lower": 0,
        "price_upper": 0,
        "wallet": wallet,
        "wallet_label": wallet_label,
        "source": "zerion",
        "position_module": position_module,
    }







class ZerionConnector:
    """Zerion API v1 connector for fetching wallet positions across EVM chains.

    Only performs GET requests (read-only). Handles Basic auth, wallet
    address validation, rate-limit retry with exponential backoff, and
    a 30-second request timeout.
    """

    BASE_URL = "https://api.zerion.io/v1"
    _MAX_RETRIES = 3
    _BACKOFF_SECONDS = [1, 2, 4]
    _TIMEOUT = 30

    def __init__(self, api_key: Optional[str] = None):
        """Initialize with API key from param or ZERION_API_KEY env var."""
        self.api_key = api_key or os.getenv("ZERION_API_KEY", "")

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    def _auth_header(self) -> Dict[str, str]:
        """Build Basic auth header (base64 of ``key:``)."""
        encoded = base64.b64encode(f"{self.api_key}:".encode()).decode()
        return {
            "Authorization": f"Basic {encoded}",
            "Accept": "application/json",
        }

    def is_configured(self) -> bool:
        """Return True when the API key is a non-empty string."""
        return bool(self.api_key)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_wallet(wallet: str) -> None:
        """Raise ValueError if *wallet* is not a valid EVM address."""
        if not isinstance(wallet, str) or not _WALLET_RE.match(wallet):
            raise ValueError(
                f"Invalid EVM wallet address: {wallet!r} "
                "(must be 0x-prefixed, 42 hex characters)"
            )

    def _get(self, url: str, params: Optional[Dict[str, str]] = None) -> requests.Response:
        """Send a GET request with retry on 429 and raise on non-2xx.

        Retries up to ``_MAX_RETRIES`` times with exponential backoff
        (1 s, 2 s, 4 s) when the server responds with 429.  Raises
        ``ZerionAPIError`` for any other non-2xx status.  Raises
        ``ConnectionError`` on network / timeout errors.
        """
        last_response: Optional[requests.Response] = None

        for attempt in range(self._MAX_RETRIES):
            try:
                response = requests.get(
                    url,
                    params=params,
                    headers=self._auth_header(),
                    timeout=self._TIMEOUT,
                )
            except requests.exceptions.Timeout as exc:
                raise ConnectionError(
                    f"Zerion API request timed out after {self._TIMEOUT}s"
                ) from exc
            except requests.exceptions.ConnectionError as exc:
                raise ConnectionError(
                    f"Network error contacting Zerion API: {exc}"
                ) from exc

            if response.status_code == 429:
                last_response = response
                if attempt < self._MAX_RETRIES - 1:
                    time.sleep(self._BACKOFF_SECONDS[attempt])
                    continue
                # Final attempt also got 429 — fall through to raise
                break

            if response.status_code < 200 or response.status_code >= 300:
                raise ZerionAPIError(response.status_code, response.text)

            return response

        # All retries exhausted on 429
        if last_response is not None:
            raise ZerionAPIError(last_response.status_code, last_response.text)

        # Should never reach here, but just in case
        raise ZerionAPIError(0, "Unknown error during request retries")  # pragma: no cover

    # ------------------------------------------------------------------
    # Public API methods
    # ------------------------------------------------------------------

    def get_wallet_positions(self, wallet: str) -> List[dict]:
        """Fetch all positions for a wallet across all EVM chains.

        Calls ``GET /wallets/{wallet}/positions/`` with query parameters
        ``filter[positions]=no_filter``, ``currency=usd``, ``sort=value``,
        and ``filter[trash]=only_non_trash``.

        Returns the list of position objects from the ``data`` field.
        """
        self._validate_wallet(wallet)

        url = f"{self.BASE_URL}/wallets/{wallet}/positions/"
        params = {
            "filter[positions]": "no_filter",
            "currency": "usd",
            "sort": "value",
            "filter[trash]": "only_non_trash",
        }
        response = self._get(url, params=params)
        return response.json().get("data", [])

    def get_wallet_portfolio(self, wallet: str) -> dict:
        """Fetch portfolio summary for a wallet.

        Calls ``GET /wallets/{wallet}/portfolio`` with ``currency=usd``.

        Returns the portfolio summary dict from the ``data`` field.
        """
        self._validate_wallet(wallet)

        url = f"{self.BASE_URL}/wallets/{wallet}/portfolio"
        params = {"currency": "usd"}
        response = self._get(url, params=params)
        return response.json().get("data", {})

    def get_wallet_transactions(
        self,
        wallet: str,
        chain_ids: Optional[str] = None,
        operation_types: Optional[str] = None,
        fungible_ids: Optional[str] = None,
        sort: str = "mined_at",
        limit: int = 100,
    ) -> List[dict]:
        """Fetch transactions for a wallet with optional filters.

        Args:
            wallet: EVM wallet address.
            chain_ids: Comma-separated chain IDs (e.g. ``"base,arbitrum"``).
            operation_types: Comma-separated types (e.g. ``"deposit,mint"``).
            fungible_ids: Comma-separated fungible IDs to filter by.
            sort: Sort order — ``"mined_at"`` (oldest first) or ``"-mined_at"``.
            limit: Max results per page (default 100).

        Returns the list of transaction objects from the ``data`` field.
        """
        self._validate_wallet(wallet)

        url = f"{self.BASE_URL}/wallets/{wallet}/transactions/"
        params: Dict[str, str] = {
            "currency": "usd",
            "sort": sort,
            "page[size]": str(limit),
            "filter[trash]": "only_non_trash",
        }
        if chain_ids:
            params["filter[chain_ids]"] = chain_ids
        if operation_types:
            params["filter[operation_types]"] = operation_types
        if fungible_ids:
            params["filter[fungible_ids]"] = fungible_ids

        response = self._get(url, params=params)
        return response.json().get("data", [])



