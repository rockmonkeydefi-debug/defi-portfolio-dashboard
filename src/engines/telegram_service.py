"""Telegram service — config management, validation, message sending and formatting."""

import os
import re
import json
import tempfile
from datetime import datetime, timezone

import requests

TELEGRAM_CONFIG_PATH = os.path.join("data", "telegram_config.json")

TELEGRAM_CONFIG_DEFAULTS = {
    "bot_token": "",
    "chat_id": "",
    "schedule_utc_hour": 9,
    "enabled": False,
    "include_digest": True,
    "include_regime": True,
}

_BOT_TOKEN_REGEX = re.compile(r"^\d+:[A-Za-z0-9_-]+$")


def load_telegram_config() -> dict:
    """Load Telegram configuration from JSON file.

    Returns defaults if file is missing or corrupted.
    """
    if not os.path.exists(TELEGRAM_CONFIG_PATH):
        return dict(TELEGRAM_CONFIG_DEFAULTS)
    try:
        with open(TELEGRAM_CONFIG_PATH, "r") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            print(f"[Telegram] Config file corrupt (not a dict), using defaults")
            return dict(TELEGRAM_CONFIG_DEFAULTS)
        # Merge with defaults so any missing keys get filled in
        merged = dict(TELEGRAM_CONFIG_DEFAULTS)
        merged.update(data)
        return merged
    except (json.JSONDecodeError, ValueError, UnicodeDecodeError) as e:
        print(f"[Telegram] Config file corrupt, using defaults: {e}")
        return dict(TELEGRAM_CONFIG_DEFAULTS)
    except (IOError, OSError) as e:
        print(f"[Telegram] Cannot read config file, using defaults: {e}")
        return dict(TELEGRAM_CONFIG_DEFAULTS)


def validate_telegram_config(data: dict) -> tuple:
    """Validate Telegram configuration fields.

    Returns (True, '') on success, (False, error_message) on failure.
    """
    if not isinstance(data, dict):
        return (False, "Config must be a dictionary")

    bot_token = data.get("bot_token", "")
    if not isinstance(bot_token, str) or not _BOT_TOKEN_REGEX.match(bot_token):
        return (False, "Invalid bot token format")

    chat_id = data.get("chat_id", "")
    if not isinstance(chat_id, str) or not chat_id.strip():
        return (False, "Chat ID cannot be empty")

    hour = data.get("schedule_utc_hour", 9)
    if not isinstance(hour, int) or hour < 0 or hour > 23:
        return (False, "Schedule hour must be 0–23")

    enabled = data.get("enabled", False)
    if not isinstance(enabled, bool):
        return (False, "Enabled must be a boolean")

    include_digest = data.get("include_digest", True)
    if not isinstance(include_digest, bool):
        return (False, "include_digest must be a boolean")

    include_regime = data.get("include_regime", True)
    if not isinstance(include_regime, bool):
        return (False, "include_regime must be a boolean")

    if enabled and not include_digest and not include_regime:
        return (False, "At least one content section required when enabled")

    return (True, "")


def save_telegram_config(config: dict) -> None:
    """Validate and atomically save Telegram configuration to disk."""
    ok, err = validate_telegram_config(config)
    if not ok:
        raise ValueError(err)

    os.makedirs(os.path.dirname(TELEGRAM_CONFIG_PATH), exist_ok=True)

    # Atomic write: write to temp file then rename
    dir_name = os.path.dirname(TELEGRAM_CONFIG_PATH)
    fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(config, f, indent=2)
        os.replace(tmp_path, TELEGRAM_CONFIG_PATH)
    except Exception:
        # Clean up temp file on failure
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def mask_bot_token(token: str) -> str:
    """Mask a bot token, showing only the last 4 characters.

    Returns ``"****" + last4`` when the token is longer than 4 characters,
    otherwise returns ``"****"``.
    """
    if len(token) > 4:
        return "****" + token[-4:]
    return "****"


def send_telegram_message(
    bot_token: str, chat_id: str, text: str, timeout: int = 15
) -> dict:
    """Send an HTML message via the Telegram Bot API.

    Posts to ``https://api.telegram.org/bot{bot_token}/sendMessage`` with
    ``parse_mode`` set to ``HTML``.

    Args:
        bot_token: Telegram bot token.
        chat_id: Target chat identifier.
        text: Message body (HTML allowed).
        timeout: HTTP request timeout in seconds.

    Returns:
        The parsed JSON response from Telegram on success.

    Raises:
        RuntimeError: On non-200 status (includes Telegram error description)
            or on any network / connection error.
    """
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}

    try:
        resp = requests.post(url, json=payload, timeout=timeout)
    except requests.RequestException as exc:
        raise RuntimeError(f"Telegram network error: {exc}") from exc

    if resp.status_code != 200:
        try:
            description = resp.json().get("description", resp.text)
        except (ValueError, KeyError):
            description = resp.text
        raise RuntimeError(f"Telegram API error: {description}")

    return resp.json()


# ---------------------------------------------------------------------------
# Message formatting helpers
# ---------------------------------------------------------------------------

TELEGRAM_MAX_LENGTH = 4096


def format_range_bar(
    range_lower: float,
    range_upper: float,
    current_price: float,
    width: int = 10,
) -> str:
    """Build a Unicode bar showing price position within an LP range.

    Uses ▓ for the filled portion and ░ for the empty portion.
    Shows bounds, current price, and percentage position.
    If the price is below the range the percentage reads ``BELOW``;
    if above, ``ABOVE``.

    Args:
        range_lower: Lower bound of the LP range.
        range_upper: Upper bound of the LP range.
        current_price: Current market price.
        width: Number of bar characters (default 10).

    Returns:
        Formatted string, e.g.
        ``[1800 ▓▓▓▓▓▓▓░░░ 2200] price: 2050 (62%)``
    """
    span = range_upper - range_lower
    if span <= 0:
        filled = 0
        pct_label = "BELOW" if current_price < range_lower else "ABOVE"
    elif current_price <= range_lower:
        filled = 0
        pct_label = "BELOW"
    elif current_price >= range_upper:
        filled = width
        pct_label = "ABOVE"
    else:
        ratio = (current_price - range_lower) / span
        pct = int(round(ratio * 100))
        filled = int(round(ratio * width))
        # Clamp filled to valid range
        filled = max(0, min(width, filled))
        pct_label = f"{pct}%"

    bar = "▓" * filled + "░" * (width - filled)

    # Format price values — strip trailing zeros for cleaner display
    def _fmt(v: float) -> str:
        if v == int(v) and abs(v) < 1e15:
            return str(int(v))
        return f"{v:g}"

    lower_s = _fmt(range_lower)
    upper_s = _fmt(range_upper)
    price_s = _fmt(current_price)

    return f"[{lower_s} {bar} {upper_s}] price: {price_s} ({pct_label})"


def _ordinal(day: int) -> str:
    """Return the ordinal suffix for a day number (1st, 2nd, 3rd, 4th …)."""
    if 11 <= day <= 13:
        return "th"
    last = day % 10
    if last == 1:
        return "st"
    if last == 2:
        return "nd"
    if last == 3:
        return "rd"
    return "th"


def format_digest_message(digest: dict) -> str:
    """Format a Daily Digest dict into an HTML Telegram message.

    The message includes a greeting, date header with ordinal suffix,
    portfolio totals, position counts, LP details with range bars,
    lending health factors, hedge PnL, and out-of-range warnings.

    If the full message exceeds 4096 characters the LP and hedge
    detail sections are truncated and a note is appended.

    Args:
        digest: Dict with keys total_value_usd, value_change_24h_pct,
            value_change_24h_usd, fees_24h_usd, average_apr,
            token_count, lp_count, lending_count, hedge_count,
            lp_summary, lending_health, hedge_health,
            positions_out_of_range.

    Returns:
        HTML-formatted string suitable for Telegram ``sendMessage``.
    """
    now = datetime.now(timezone.utc)
    day = now.day
    month_name = now.strftime("%B")
    date_str = f"{month_name} {day}{_ordinal(day)}"

    # --- Header ---
    change_pct = digest.get("value_change_24h_pct")
    change_usd = digest.get("value_change_24h_usd")
    has_24h_change = change_pct is not None and change_usd is not None

    if has_24h_change:
        arrow = "▲" if change_pct >= 0 else "▼"
        sign = "+" if change_pct >= 0 else ""
        usd_sign = "+" if change_usd >= 0 else ""
        change_str = f"({arrow} {sign}{change_pct:.2f}% / {usd_sign}${change_usd:,.2f})"
    else:
        change_str = "(24h change: N/A)"

    total_val = digest.get("total_value_usd", 0.0)
    fees_24h = digest.get("fees_24h_usd") or 0.0
    avg_apr = digest.get("average_apr") or 0.0

    lines: list[str] = [
        "Good day! Here is your performance digest for the last 24hrs.",
        "",
        f"<b>📊 Daily Portfolio Digest for {date_str}</b>",
        "",
        f"💰 Total: ${total_val:,.2f} {change_str}",
        f"📈 Fees 24h: ${fees_24h:,.2f} | Avg APR: {avg_apr:.1f}%",
        f"📦 {digest.get('token_count', 0)} tokens · {digest.get('lp_count', 0)} LPs · {digest.get('lending_count', 0)} lending · {digest.get('hedge_count', 0)} hedges",
    ]

    # --- LP Positions ---
    lp_summary = digest.get("lp_summary") or []
    lp_lines: list[str] = []
    if lp_summary:
        lp_lines.append("")
        lp_lines.append("<b>LP Positions</b>")
        for lp in lp_summary:
            pair = lp.get("pair", "?/?")
            value = lp.get("value_usd", 0.0)
            apr = lp.get("apr") or 0.0
            total_fees = lp.get("total_earned_fees_usd", 0.0)
            uncollected = lp.get("fees_uncollected_usd", 0.0)
            collected = max(0, total_fees - uncollected)
            in_range = lp.get("in_range", True)
            r_lower = lp.get("range_lower", 0.0)
            r_upper = lp.get("range_upper", 0.0)
            c_price = lp.get("current_price", 0.0)

            # Build fee string with collected/uncollected breakdown
            fee_str = ""
            if total_fees > 0.01:
                fee_str = f" · fees ${total_fees:,.2f}"
                if collected > 0.01 and uncollected > 0.01:
                    fee_str += f" (${collected:,.0f} collected + ${uncollected:,.0f} pending)"
                elif uncollected > 0.01:
                    fee_str += " (uncollected)"

            bar = format_range_bar(r_lower, r_upper, c_price)
            if in_range:
                lp_lines.append(
                    f"✅ {pair} — ${value:,.2f} · {apr:.0f}% APR{fee_str}"
                )
            else:
                lp_lines.append(
                    f"⚠️ {pair} — OUT OF RANGE — ${value:,.2f}"
                )
            lp_lines.append(f"  {bar}")

    # --- Lending ---
    lending_health = digest.get("lending_health") or []
    lending_lines: list[str] = []
    if lending_health:
        lending_lines.append("")
        lending_lines.append("<b>Lending</b>")
        for lend in lending_health:
            protocol = lend.get("protocol", "?")
            chain = lend.get("chain", "?")
            hf = lend.get("health_factor", 0.0) or 0.0
            ltv = lend.get("ltv", 0.0) or 0.0
            collateral = lend.get("collateral_usd", 0.0) or 0.0
            debt = lend.get("debt_usd", 0.0) or 0.0
            # Headline. HF=999 sentinel means "no debt" — show just collateral
            # rather than a meaningless health factor.
            if debt > 0:
                lending_lines.append(
                    f"{protocol} ({chain}) — HF: {hf:.2f} · LTV: {ltv:.1f}%"
                )
                lending_lines.append(
                    f"  ${collateral:,.0f} supplied · ${debt:,.0f} borrowed"
                )
            else:
                lending_lines.append(
                    f"{protocol} ({chain}) — ${collateral:,.0f} supplied (no debt)"
                )
            # Per-asset detail. Indent so it nests visually under the headline.
            for s in (lend.get("supplied") or []):
                sym = s.get("symbol", "?")
                bal = s.get("balance") or 0
                val = s.get("value_usd") or 0
                apy = s.get("apy") or 0
                apy_str = f" @ {apy:.2f}% APY" if apy else ""
                lending_lines.append(
                    f"  ↑ {bal:,.4f} {sym} (${val:,.2f}){apy_str}"
                )
            for b in (lend.get("borrowed") or []):
                sym = b.get("symbol", "?")
                bal = b.get("balance") or 0
                val = b.get("value_usd") or 0
                apy = b.get("apy") or 0
                apy_str = f" @ {apy:.2f}% APY" if apy else ""
                lending_lines.append(
                    f"  ↓ {bal:,.4f} {sym} (${val:,.2f}){apy_str}"
                )

    # --- Hedges ---
    hedge_health = digest.get("hedge_health") or []
    hedge_lines: list[str] = []
    if hedge_health:
        hedge_lines.append("")
        hedge_lines.append("<b>Hedges</b>")
        for h in hedge_health:
            market = h.get("market", "?")
            platform = h.get("platform", "?")
            pnl = h.get("pnl_usd", 0.0)
            liq_dist = h.get("liq_distance_pct", 0.0)
            leverage = h.get("leverage", 1.0)
            pnl_sign = "+" if pnl >= 0 else ""
            hedge_lines.append(
                f"{market} {leverage:.0f}x — PnL: {pnl_sign}${pnl:,.2f} · Liq: {liq_dist:.1f}% away"
            )

    # --- Out of Range ---
    oor = digest.get("positions_out_of_range") or []
    oor_lines: list[str] = []
    if oor:
        oor_lines.append("")
        oor_parts = []
        for p in oor:
            if isinstance(p, dict):
                oor_parts.append(f"{p.get('pair', '?')} ({p.get('chain', '?')})")
            else:
                oor_parts.append(str(p))
        oor_lines.append("⚠️ Out of Range: " + ", ".join(oor_parts))

    # --- Assemble with truncation ---
    header_text = "\n".join(lines)
    lending_text = "\n".join(lending_lines)
    oor_text = "\n".join(oor_lines)

    # These are the sections we may truncate
    lp_text = "\n".join(lp_lines)
    hedge_text = "\n".join(hedge_lines)

    full_msg = "\n".join(
        part for part in [header_text, lp_text, lending_text, hedge_text, oor_text] if part
    )

    if len(full_msg) <= TELEGRAM_MAX_LENGTH:
        return full_msg

    # Truncation needed — progressively remove LP and hedge detail lines
    truncation_note = "\n\n… (truncated — view full details on the dashboard)"
    budget = TELEGRAM_MAX_LENGTH - len(truncation_note)

    # Try removing hedge details first, then LP details
    for trim_hedge in (False, True):
        for trim_lp in (False, True):
            h_text = "" if trim_hedge else hedge_text
            l_text = "" if trim_lp else lp_text
            candidate = "\n".join(
                part for part in [header_text, l_text, lending_text, h_text, oor_text] if part
            )
            if len(candidate) <= budget:
                return candidate + truncation_note

    # Last resort: just header + oor + truncation note
    candidate = "\n".join(
        part for part in [header_text, oor_text] if part
    )
    if len(candidate) <= budget:
        return candidate + truncation_note

    # Absolute last resort: hard-truncate
    return full_msg[:budget] + truncation_note


def _format_regime_period(label: str, period: dict) -> str:
    """Format a single regime period (short-term or mid-term) as HTML lines.

    Sorts the three regimes (bull, bear, sideways) by probability descending,
    shows the dominant one in UPPERCASE, and appends the reasoning text.
    """
    probs = [
        ("Bull", period.get("bull", 0)),
        ("Bear", period.get("bear", 0)),
        ("Sideways", period.get("sideways", 0)),
    ]
    # Sort descending by probability
    probs.sort(key=lambda x: x[1], reverse=True)

    parts: list[str] = []
    for i, (name, pct) in enumerate(probs):
        display = name.upper() if i == 0 else name
        parts.append(f"{display} {pct}%")

    regime_line = f"<b>{label}:</b> " + " | ".join(parts)
    reasoning = period.get("reasoning", "")
    if reasoning:
        return f"{regime_line}\n{reasoning}"
    return regime_line


def format_regime_message(regime: dict | None) -> str:
    """Format a Market Regime Assessment dict into an HTML Telegram message.

    The message includes short-term (7d) and mid-term (30d) regime
    probabilities with the dominant label shown first in uppercase,
    reasoning text for each period, macro environment, and data confidence.

    When *regime* is ``None``, returns a fallback note directing the user
    to generate a report from the dashboard.

    Args:
        regime: Dict with keys ``short_term_7d``, ``mid_term_30d``,
            ``macro_environment``, and ``data_confidence``.  Each period
            sub-dict contains ``bull``, ``bear``, ``sideways`` percentages
            and a ``reasoning`` string.

    Returns:
        HTML-formatted string suitable for Telegram ``sendMessage``.
    """
    header = "🔮 <b>Market Regime Assessment</b>"

    if regime is None:
        return f"{header}\n\nNo AI report available — generate one from the dashboard"

    lines: list[str] = [f"<b>🔮 Market Regime Assessment</b>"]

    # Short-term
    short = regime.get("short_term_7d")
    if short:
        lines.append("")
        lines.append(_format_regime_period("Short-term (7d)", short))

    # Mid-term
    mid = regime.get("mid_term_30d")
    if mid:
        lines.append("")
        lines.append(_format_regime_period("Mid-term (30d)", mid))

    # Macro environment
    macro = regime.get("macro_environment")
    if macro:
        lines.append("")
        lines.append(f"<b>Macro:</b> {macro}")

    # Data confidence
    confidence = regime.get("data_confidence")
    if confidence:
        lines.append(f"<b>Confidence:</b> {confidence}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Notification content builder
# ---------------------------------------------------------------------------


def build_notification_content(config: dict) -> list[str]:
    """Build the notification message(s) based on config flags.

    Fetches the latest digest from ``daily_digests`` and the latest regime
    from ``ai_reports`` as needed, formats them, and returns a list of
    message strings ready to send.

    Rules:
    - If neither ``include_digest`` nor ``include_regime`` is enabled,
      return an empty list.
    - If only one section is enabled, return ``[that_message]``.
    - If both are enabled and the combined length (with ``\\n\\n``
      separator) is ≤ 4096 chars, return a single combined message.
    - If both are enabled and the combined length exceeds 4096 chars,
      return ``[digest_msg, regime_msg]`` as two separate messages.

    Args:
        config: Telegram configuration dict with ``include_digest`` and
            ``include_regime`` boolean flags.

    Returns:
        A list of HTML message strings (0, 1, or 2 elements).
    """
    include_digest = config.get("include_digest", False)
    include_regime = config.get("include_regime", False)

    if not include_digest and not include_regime:
        return []

    from src.storage.portfolio_db import get_connection

    digest_msg: str | None = None
    regime_msg: str | None = None

    if include_digest:
        try:
            conn = get_connection()
            row = conn.execute(
                "SELECT digest_json FROM daily_digests ORDER BY timestamp DESC LIMIT 1"
            ).fetchone()
            conn.close()
            if row and row["digest_json"]:
                digest_data = json.loads(row["digest_json"])
                digest_msg = format_digest_message(digest_data)
        except Exception as exc:
            print(f"[Telegram] Error fetching digest: {exc}")

    if include_regime:
        regime_data = None
        try:
            conn = get_connection()
            row = conn.execute(
                "SELECT market_regime_json FROM ai_reports ORDER BY timestamp DESC LIMIT 1"
            ).fetchone()
            conn.close()
            if row and row["market_regime_json"]:
                regime_data = json.loads(row["market_regime_json"])
        except Exception as exc:
            print(f"[Telegram] Error fetching regime: {exc}")
        # format_regime_message handles None gracefully
        regime_msg = format_regime_message(regime_data)

    # Assemble result
    if digest_msg and regime_msg:
        combined = digest_msg + "\n\n" + regime_msg
        if len(combined) <= TELEGRAM_MAX_LENGTH:
            return [combined]
        return [digest_msg, regime_msg]

    if digest_msg:
        return [digest_msg]

    if regime_msg:
        return [regime_msg]

    return []


# ---------------------------------------------------------------------------
# Daily notification orchestrator
# ---------------------------------------------------------------------------


def send_daily_notification() -> None:
    """Orchestrate daily Telegram notification.

    Loads config, exits early if disabled, builds content based on
    config flags, and sends each message via the Telegram Bot API.
    """
    config = load_telegram_config()

    if not config.get("enabled", False):
        return

    bot_token = config.get("bot_token", "")
    chat_id = config.get("chat_id", "")

    if not bot_token or not chat_id:
        print("[Telegram] Skipping notification — bot_token or chat_id not configured")
        return

    messages = build_notification_content(config)
    if not messages:
        print("[Telegram] No content to send (both sections disabled or empty)")
        return

    for msg in messages:
        try:
            send_telegram_message(bot_token, chat_id, msg)
        except Exception as exc:
            print(f"[Telegram] Failed to send message: {exc}")
            raise

    print(f"[Telegram] Daily notification sent ({len(messages)} message(s))")
