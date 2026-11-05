"""Telegram service — config management, validation, message sending and formatting."""

import os
import re
import json
import tempfile
import threading
from datetime import datetime, timedelta, timezone

import requests

TELEGRAM_CONFIG_PATH = os.path.join("data", "telegram_config.json")

# Landing 94 (Nov 4, Glenn): the Messaging settings hold one entry per message type, each with its own
# checkbox and a send time typed in Pacific time ("HH:MM", America/Los_Angeles, daylight saving included).
# The Daily Digest and Market Regime are no longer message types (ruled Nov 4, 1 C); their formatter code
# below stays, unused. A file written before L94 converts on read: its token, chat id and Enabled carry
# over, and every message type starts unchecked at DEFAULT_MESSAGE_TIME.
# MESSAGE_TYPES: (key, label, what it sends), in the order the settings card lists them. Landing 95 adds
# the Spot and Perps summaries here.
MESSAGE_TYPES = (
    ("portfolio_value", "Portfolio Value", "The total portfolio value and its change over 24 hours."),
    ("risk_gate", "Risk Gate", "Counted perp trades toward the risk gate and its four checks."),
)
MESSAGE_TYPE_KEYS = tuple(k for k, _label, _desc in MESSAGE_TYPES)
DEFAULT_MESSAGE_TIME = "07:00"
PACIFIC_TZ_NAME = "America/Los_Angeles"

TELEGRAM_CONFIG_DEFAULTS = {
    "bot_token": "",
    "chat_id": "",
    "enabled": False,
}

_BOT_TOKEN_REGEX = re.compile(r"^\d+:[A-Za-z0-9_-]+$")
_TIME_REGEX = re.compile(r"^([01][0-9]|2[0-3]):[0-5][0-9]$")


def default_messages() -> dict:
    """Every message type unchecked at DEFAULT_MESSAGE_TIME."""
    return {k: {"enabled": False, "time": DEFAULT_MESSAGE_TIME} for k in MESSAGE_TYPE_KEYS}


def _normalize(data: dict) -> dict:
    """The stored dict as the current shape: bot_token, chat_id, enabled and messages (every known type, a
    missing or malformed entry replaced by its default). Keys from before Landing 94 (schedule_utc_hour,
    include_digest, include_regime, and the page's own utc_hour / content) are dropped."""
    out = dict(TELEGRAM_CONFIG_DEFAULTS)
    for k in TELEGRAM_CONFIG_DEFAULTS:
        if k in data:
            out[k] = data[k]
    msgs = default_messages()
    stored = data.get("messages")
    if isinstance(stored, dict):
        for k in MESSAGE_TYPE_KEYS:
            e = stored.get(k)
            if (isinstance(e, dict) and isinstance(e.get("enabled"), bool)
                    and isinstance(e.get("time"), str) and _TIME_REGEX.match(e["time"])):
                msgs[k] = {"enabled": e["enabled"], "time": e["time"]}
    out["messages"] = msgs
    return out


def load_telegram_config() -> dict:
    """Load Telegram configuration from JSON file, in the current shape (_normalize).

    Returns defaults if file is missing or corrupted.
    """
    if not os.path.exists(TELEGRAM_CONFIG_PATH):
        return _normalize({})
    try:
        with open(TELEGRAM_CONFIG_PATH, "r") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            print(f"[Telegram] Config file corrupt (not a dict), using defaults")
            return _normalize({})
        return _normalize(data)
    except (json.JSONDecodeError, ValueError, UnicodeDecodeError) as e:
        print(f"[Telegram] Config file corrupt, using defaults: {e}")
        return _normalize({})
    except (IOError, OSError) as e:
        print(f"[Telegram] Cannot read config file, using defaults: {e}")
        return _normalize({})


def validate_telegram_config(data: dict) -> tuple:
    """Validate Telegram configuration fields.

    Body: {"bot_token", "chat_id", "enabled", "messages": {<type>: {"enabled", "time" ("HH:MM", Pacific)}}}.
    "messages" may leave types out (they keep their defaults); an unknown type or key is refused.
    Returns (True, '') on success, (False, error_message) on failure.
    """
    if not isinstance(data, dict):
        return (False, "Config must be a dictionary")

    bot_token = data.get("bot_token", "")
    if not isinstance(bot_token, str) or not _BOT_TOKEN_REGEX.match(bot_token):
        return (False, "Invalid bot token format (paste the whole token from BotFather, no spaces)")

    chat_id = data.get("chat_id", "")
    if not isinstance(chat_id, str) or not chat_id.strip():
        return (False, "Chat ID cannot be empty")

    enabled = data.get("enabled", False)
    if not isinstance(enabled, bool):
        return (False, "Enabled must be true or false")

    msgs = data.get("messages", {})
    if not isinstance(msgs, dict):
        return (False, "messages must be an object")
    labels = {k: label for k, label, _d in MESSAGE_TYPES}
    for k, e in msgs.items():
        if k not in labels:
            return (False, f"Unknown message type: {k}")
        if not isinstance(e, dict) or set(e) - {"enabled", "time"}:
            return (False, f"{labels[k]}: expected enabled and time")
        if not isinstance(e.get("enabled"), bool):
            return (False, f"{labels[k]}: enabled must be true or false")
        t = e.get("time")
        if not isinstance(t, str) or not _TIME_REGEX.match(t):
            return (False, f"{labels[k]}: time must be HH:MM (00:00 to 23:59)")

    return (True, "")


def save_telegram_config(config: dict) -> None:
    """Validate and atomically save Telegram configuration to disk, in the current shape."""
    ok, err = validate_telegram_config(config)
    if not ok:
        raise ValueError(err)
    _atomic_write_json(TELEGRAM_CONFIG_PATH, _normalize(config))


def _atomic_write_json(path: str, obj) -> None:
    """Write obj as JSON to path through a temp file and a rename."""
    dir_name = os.path.dirname(path)
    os.makedirs(dir_name, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(obj, f, indent=2)
        os.replace(tmp_path, path)
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


# ---------------------------------------------------------------------------
# Landing 94: scheduled messages (one per message type, each at its own Pacific time)
# ---------------------------------------------------------------------------

TELEGRAM_SENT_PATH = os.path.join("data", "telegram_sent.json")
# A send missed by up to this long (a deploy restart at the send time) still goes out; later, that day is
# skipped (ruled Nov 4, 2 A).
LATE_SEND_GRACE_SECONDS = 3 * 3600


def html_escape(text) -> str:
    """Text for a parse_mode=HTML message: &, < and > escaped (Telegram's three)."""
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def split_message(text: str, limit: int = TELEGRAM_MAX_LENGTH) -> list:
    """text in pieces of at most `limit` characters, cut at line ends where possible (a single line longer
    than the limit is cut inside the line)."""
    if len(text) <= limit:
        return [text]
    parts, cur = [], ""
    for line in text.split("\n"):
        while len(line) > limit:
            if cur:
                parts.append(cur)
                cur = ""
            parts.append(line[:limit])
            line = line[limit:]
        cand = line if not cur else cur + "\n" + line
        if len(cand) > limit:
            parts.append(cur)
            cur = line
        else:
            cur = cand
    if cur:
        parts.append(cur)
    return parts


def pacific_tz():
    """The America/Los_Angeles zone (the tzdata package backs it where the system has no zone files)."""
    from zoneinfo import ZoneInfo
    return ZoneInfo(PACIFIC_TZ_NAME)


def load_sent_state() -> dict:
    """{message type: the Pacific date ("YYYY-MM-DD") of its last scheduled send, sent or skipped}; {} when
    the file is missing or unreadable."""
    try:
        with open(TELEGRAM_SENT_PATH, "r") as f:
            data = json.load(f)
        return {k: v for k, v in data.items() if isinstance(k, str) and isinstance(v, str)} if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_sent_state(state: dict) -> None:
    _atomic_write_json(TELEGRAM_SENT_PATH, state)


_SENT_LOCK = threading.Lock()   # the scheduler and the settings save both update the sent state


def _scheduled_instants(e: dict, local: datetime, tz):
    """(yesterday's, today's) send time for entry e as aware UTC instants, and today's as a Pacific wall clock."""
    hh, mm = (int(x) for x in e["time"].split(":"))
    wall = local.replace(tzinfo=None)
    today_wall = wall.replace(hour=hh, minute=mm, second=0, microsecond=0)
    yday_wall = today_wall - timedelta(days=1)
    return (yday_wall.replace(tzinfo=tz).astimezone(timezone.utc),
            today_wall.replace(tzinfo=tz).astimezone(timezone.utc), today_wall)


def due_messages(config: dict, sent: dict, now_utc: datetime) -> list:
    """What the scheduler does now, as [(type, "send" | "skip", Pacific date to record)]. Pure.

    Nothing while the master Enabled is off. For each checked type, `sent` holds the Pacific date of the
    last send time it handled (dates compare as text, "YYYY-MM-DD"):
    - today's time not yet handled and the Pacific wall clock has reached it: "send" if it passed at most
      LATE_SEND_GRACE_SECONDS ago, else "skip" (a long outage: nothing until tomorrow);
    - otherwise, yesterday's time not handled and passed at most LATE_SEND_GRACE_SECONDS ago (an outage
      across Pacific midnight, say a 23:58 time and a restart until 00:01): "send" for yesterday.
    A save that ticks a type, changes its time or turns messages on marks the send time already passed as
    handled (arm_after_save), so a change never sends at once. Daylight saving: a time inside the skipped
    spring hour sends at the first minute after it; in the repeated autumn hour it sends once."""
    if not config.get("enabled"):
        return []
    tz = pacific_tz()
    local = now_utc.astimezone(tz)
    today = local.date().isoformat()
    yday = (local.date() - timedelta(days=1)).isoformat()
    wall = local.replace(tzinfo=None)
    out = []
    for k in MESSAGE_TYPE_KEYS:
        e = (config.get("messages") or {}).get(k) or {}
        if not e.get("enabled"):
            continue
        last = sent.get(k, "")
        if last >= today:
            continue
        yday_utc, today_utc, today_wall = _scheduled_instants(e, local, tz)
        if wall >= today_wall:
            late = (now_utc - today_utc).total_seconds()
            out.append((k, "send" if late <= LATE_SEND_GRACE_SECONDS else "skip", today))
        elif last < yday and 0 <= (now_utc - yday_utc).total_seconds() <= LATE_SEND_GRACE_SECONDS:
            out.append((k, "send", yday))
    return out


def arm_after_save(old: dict, new: dict, now_utc: datetime) -> None:
    """After a save: for each checked type that was just ticked, had its time changed, or was ticked when
    messages were turned on, record its most recent passed send time (today's, else yesterday's) as handled,
    so the change sends nothing until the next send time (ruled: late sends are for outages only)."""
    tz = pacific_tz()
    local = now_utc.astimezone(tz)
    today = local.date().isoformat()
    yday = (local.date() - timedelta(days=1)).isoformat()
    wall = local.replace(tzinfo=None)
    master_on = bool(new.get("enabled")) and not bool(old.get("enabled"))
    with _SENT_LOCK:
        sent = load_sent_state()
        changed = False
        for k in MESSAGE_TYPE_KEYS:
            ne = (new.get("messages") or {}).get(k) or {}
            oe = (old.get("messages") or {}).get(k) or {}
            if not ne.get("enabled"):
                continue
            if not (master_on or not oe.get("enabled") or oe.get("time") != ne.get("time")):
                continue
            _y, _t, today_wall = _scheduled_instants(ne, local, tz)
            mark = today if wall >= today_wall else yday
            if sent.get(k, "") < mark:
                sent[k] = mark
                changed = True
        if changed:
            save_sent_state(sent)


def send_message_type(config: dict, kind: str, build_fn, timeout: int = 15, test: bool = False) -> int:
    """Build one message type with build_fn(kind) -> text and send it (split at 4096 characters). Returns
    how many messages went out. Raises RuntimeError (Telegram's or the network's error, any bot token
    masked) or ValueError (not configured)."""
    bot_token = config.get("bot_token", "")
    chat_id = config.get("chat_id", "")
    if not bot_token:
        raise ValueError("No bot token saved. Paste it, then Save.")
    if not chat_id:
        raise ValueError("No chat ID saved. Paste it, then Save.")
    text = build_fn(kind)
    if test:
        text = "<i>Test message</i>\n" + text
    parts = split_message(text)
    for part in parts:
        try:
            send_telegram_message(bot_token, chat_id, part, timeout=timeout)
        except RuntimeError as exc:
            from log_redact import redact
            raise RuntimeError(redact(str(exc)).replace(bot_token, "<redacted>")) from None
    return len(parts)


def run_scheduled_tick(now_utc: datetime, build_fn) -> list:
    """One scheduler pass: read the settings and the sent state, record each due type's date BEFORE its
    send (a crash or restart mid-send costs that message, never a second copy), then send. One type
    failing never stops the others. Returns [(type, action, error or None)]."""
    config = load_telegram_config()
    with _SENT_LOCK:
        sent = load_sent_state()
        due = due_messages(config, sent, now_utc)
        for kind, _action, day in due:
            sent[kind] = day
        if due:
            save_sent_state(sent)
    results = []
    for kind, action, day in due:
        if action == "skip":
            print(f"[Telegram] {kind}: skipped today (send time passed more than 3 hours ago)", flush=True)
            results.append((kind, "skip", None))
            continue
        try:
            n = send_message_type(config, kind, build_fn)
            print(f"[Telegram] {kind}: sent ({n} message(s))", flush=True)
            results.append((kind, "send", None))
        except Exception as exc:
            from log_redact import redact
            err = redact(str(exc))
            print(f"[Telegram] {kind}: send failed: {err}", flush=True)
            results.append((kind, "failed", err))
    return results


def messages_loop(build_fn) -> None:
    """The scheduler thread's body: run_scheduled_tick about once a minute, forever. An error in a pass is
    logged by its type only (never its text, which could carry the token) and the loop carries on."""
    import time
    while True:
        try:
            run_scheduled_tick(datetime.now(timezone.utc), build_fn)
        except Exception as e:
            print(f"[Telegram] scheduler error: {type(e).__name__}", flush=True)
        time.sleep(60 - datetime.now(timezone.utc).second)
