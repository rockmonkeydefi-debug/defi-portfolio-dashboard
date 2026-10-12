"""Mask secret values in everything the app writes to its console logs.

Why (Landing 30): an RPC URL carries its API key in the path
(``https://eth-mainnet.g.alchemy.com/v2/<key>``), and ``requests`` puts the
URL in its exception text ("... for url: https://...", "Max retries exceeded
with url: /v2/<key>"). Any ``print(f"... {e}")``, traceback or logged
exception from an RPC call therefore wrote the key to Railway's logs. Fixing
each print site would miss the rest (the same URLs feed the snapshot service,
the LP connectors and the MaxFi clients) and every print added later, so the
key is masked where the text leaves the process instead.

What is masked, for every environment variable whose name contains
``RPC_URL``, ``_KEY`` (so ``*_API_KEY`` too), ``SECRET``, ``TOKEN`` or
``PASSWORD`` (any letter case):
- a URL value (http, https, ws, wss): each path segment, query value, user
  name and password at least ``MIN_SECRET_LEN`` characters long, in its raw,
  percent-encoded and decoded spellings. The scheme, host and short segments
  stay, so a log reads ``https://eth-mainnet.g.alchemy.com/v2/<redacted:...>``
  and names the chain, and a keyless public URL stays readable. Not caught:
  a key shorter than ``MIN_SECRET_LEN`` (e.g. Grove's 8-character app id in
  ``/v1/<id>``) and a key carried in the host (QuickNode with token auth
  off: ``https://<name>.quiknode.pro/``). Alchemy and Infura, the providers
  Settings knows, use 32-character path keys;
- any other value of at least ``MIN_SECRET_LEN`` characters, whole.
Also a Telegram bot token (``<bot id>:<35-character secret>``) wherever it
appears: it lives in a config file, not the environment, and sits in the path
of every Telegram API URL.

Each match becomes ``<redacted:NAME>``; ``<redacted:shared>`` when the same
text belongs to several variables now (one Alchemy key behind several chain
URLs: the host on the same line names the chain); and ``<redacted:NAME,
replaced>`` for a value no variable holds any more.

The environment is read when text is written, not once at startup: values
loaded from .env later in the import, and RPC URLs saved on the Settings page
(which sets ``os.environ``), are covered from that moment. A value that is
replaced or removed stays masked for the life of the process, because parts
of the app keep the old URL until a restart (maxfi_client reads BASE_RPC_URL
once at import).

Masking never raises: if it fails, the line is withheld and a short notice is
written in its place, rather than writing the line unmasked or breaking every
print and log call.

``install()`` wraps ``sys.stdout``, ``sys.stderr`` and the stream of every
logging handler that already writes to the console (gunicorn creates its
error log handler before it imports the app, holding the original stderr).
Handlers made later default to ``sys.stderr``, the wrapper. It is idempotent.

Not covered: log files (file handlers are left alone; the app logs to the
console only), text written to a file descriptor directly (C extensions,
``os.write``), scripts that run on their own without importing the app, and
error text the app stores in its database or returns from its API (one site
that also prints it, the snapshot service's complete-total error, calls
``redact`` itself).
"""
import os
import re
import sys
import time
import logging
from urllib.parse import quote, unquote, urlsplit, parse_qsl

MIN_SECRET_LEN = 16

_SECRET_NAME_RE = re.compile(r"RPC_URL|_KEY|SECRET|TOKEN|PASSWORD")
_URL_SCHEMES = ("http://", "https://", "ws://", "wss://")
# A Telegram bot token: the bot id, a colon and a 35-character secret (34 in
# a few old tokens). Not after a digit (a longer number), not "0x..." (a
# hash or an address after a block, chain or timestamp), and not followed by
# more token characters (a Solana signature, a mint, a uuid). The id may
# follow "bot" directly, as in ".../bot<token>/sendMessage".
_TELEGRAM_TOKEN_RE = re.compile(r"(?<![0-9])\d{5,12}:(?!0x)[A-Za-z0-9_-]{34,35}(?![A-Za-z0-9_-])")
_TELEGRAM_MARKER = "<redacted:telegram bot token>"
_WITHHELD = "[log_redact] a log line was withheld: masking it failed\n"

# Full re-read of the environment at least this often, even when the quick
# check below sees no change.
RESCAN_SECONDS = 60.0

# Every secret part seen in this process -> the variable names it came from.
# It only grows: a replaced key may still be in use until the next restart.
_seen = {}
# (env snapshot, [(secret, marker)] longest first, quick-check fingerprint,
# time of the full read). Replaced whole, never mutated, so a reader on
# another thread always sees one consistent set.
_cache = (None, [], None, 0.0)


def _is_secret_name(name):
    return bool(_SECRET_NAME_RE.search(str(name).upper()))


def _parts_of(value):
    """The strings to mask for one secret value. A URL: its long path
    segments, query values, user name and password, each also percent-encoded
    and decoded. Anything else: the value itself."""
    value = value.strip()
    if not value.lower().startswith(_URL_SCHEMES):
        return {value} if len(value) >= MIN_SECRET_LEN else set()
    pieces = []
    try:
        u = urlsplit(value)
        pieces += u.path.split("/")
        pieces += [v for _, v in parse_qsl(u.query, keep_blank_values=True)]
        pieces += [p for p in (u.username, u.password) if p]
    except ValueError:
        # Not parseable as a URL: mask the whole value rather than nothing.
        return {value} if len(value) >= MIN_SECRET_LEN else set()
    parts = set()
    for piece in pieces:
        parts.add(piece)
        parts.add(quote(piece, safe="", errors="surrogateescape"))
        parts.add(unquote(piece, errors="surrogateescape"))
    return {p for p in parts if len(p) >= MIN_SECRET_LEN}


def _env_snapshot():
    """(number of variables, sorted ((name, raw value), ...)) for every
    secret-named variable now set. Short and empty values are kept (only
    long parts are masked) so that the quick check notices when Settings
    fills in a variable that was empty, such as the blank ``ETHEREUM_RPC_URL=``
    lines .env.example gives a new install. The count is read before the
    names: a variable added in between makes the stored count stale, so the
    next write reads again rather than trusting a list that lacks it.
    Settings can change os.environ from another thread while this reads it;
    the caller treats any failure as "keep the last list"."""
    count = len(os.environ)
    out = []
    for name in list(os.environ.keys()):
        if _is_secret_name(name):
            out.append((name, os.environ.get(name) or ""))
    out.sort()
    return count, tuple(out)


def _fingerprint_of(snap):
    """The fingerprint a snapshot was read at: built from the snapshot's own
    reads, never a second read, so a value saved while the list was being
    built differs from it and is picked up on the next write."""
    count, items = snap
    return count, tuple(value for _, value in items)


def _fingerprint_now(snap):
    """The same check against the environment as it is now: the number of
    variables and the current value of each secret variable in ``snap``.
    Reading every name costs about 0.5 us per variable on each write; this
    costs a few lookups. A secret variable added or removed changes the
    count, and a value saved in Settings changes its entry. The rare swap
    that keeps both (one variable removed and another added between two
    writes) is caught by the periodic full read."""
    return len(os.environ), tuple(os.environ.get(name) or "" for name, _ in snap[1])


def _pairs_for(items):
    """[(secret, marker)], longest first, from every part seen so far, with
    each part named after the variables that hold it now."""
    current = {}
    for name, value in items:
        for part in _parts_of(value):
            _seen.setdefault(part, set()).add(name)
            current.setdefault(part, set()).add(name)
    pairs = []
    for part, names in list(_seen.items()):
        holders = sorted(current.get(part, ()))
        if holders:
            label = holders[0] if len(holders) == 1 else "shared"
        else:
            old = sorted(names)
            label = (old[0] if len(old) == 1 else "shared") + ", replaced"
        pairs.append((part, "<redacted:%s>" % label))
    pairs.sort(key=lambda kv: (-len(kv[0]), kv[0]))
    return pairs


def secrets_now():
    """[(secret, marker)], longest secret first: every secret part of the
    environment as it is now, plus every part seen earlier in this process.
    On any failure the last good list is returned."""
    global _cache
    try:
        snap, pairs, fp, scanned_at = _cache
        now = time.monotonic()
        if (snap is not None and now - scanned_at < RESCAN_SECONDS
                and _fingerprint_now(snap) == fp):
            return pairs
        new_snap = _env_snapshot()
        if snap is None or new_snap[1] != snap[1]:
            pairs = _pairs_for(new_snap[1])
        _cache = (new_snap, pairs, _fingerprint_of(new_snap), now)
    except Exception:
        pass
    return _cache[1]


def redact(text):
    """``text`` with every secret replaced by its marker. bytes and bytearray
    are masked through a lossless UTF-8 round trip; anything else is returned
    unchanged. Never raises: on an internal error the text is withheld
    (returned as a short notice), never returned unmasked."""
    if isinstance(text, (bytes, bytearray)):
        s = bytes(text).decode("utf-8", "surrogateescape")
        r = redact(s)
        return text if r == s else r.encode("utf-8", "surrogateescape")
    if not isinstance(text, str) or not text:
        return text
    original = text
    try:
        for secret, marker in secrets_now():
            if secret in text:
                text = text.replace(secret, marker)
        if ":" in text:
            text = _TELEGRAM_TOKEN_RE.sub(_TELEGRAM_MARKER, text)
        return text
    except Exception:
        # Whitespace can't hold a secret (print writes its newline on its
        # own); otherwise keep the line break so withheld lines stay apart.
        if not original.strip():
            return original
        return _WITHHELD if original.endswith("\n") else _WITHHELD.rstrip("\n")


class RedactingStream:
    """A text stream that masks secrets in what is written and passes every
    other attribute (encoding, fileno, isatty, flush, buffer, ...) through to
    the stream it wraps."""

    _log_redact_wrapped = True

    def __init__(self, stream):
        self._stream = stream

    def write(self, data):
        try:
            out = redact(data)
        except Exception:
            out = _WITHHELD if isinstance(data, str) else _WITHHELD.encode()
        n = self._stream.write(out)
        if out is not data and isinstance(n, int):
            return len(data)
        return n

    def writelines(self, lines):
        for line in lines:
            self.write(line)

    def __getattr__(self, name):
        if name == "_stream":          # copy / pickle probe an unset instance
            raise AttributeError(name)
        return getattr(self._stream, name)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return self._stream.__exit__(*exc)

    def __repr__(self):
        return "<RedactingStream %r>" % (self._stream,)


def _wrapped(stream):
    return bool(getattr(stream, "_log_redact_wrapped", False))


def _is_console(stream, consoles):
    if stream is None:
        return False
    if any(stream is c for c in consoles):
        return True
    try:
        return stream.fileno() in (1, 2)
    except Exception:
        return False


def install():
    """Wrap sys.stdout, sys.stderr and every logging handler stream that
    writes to the console. Safe to call more than once."""
    consoles = [s for s in (sys.stdout, sys.stderr, sys.__stdout__, sys.__stderr__)
                if s is not None]
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        if stream is not None and not _wrapped(stream):
            setattr(sys, name, RedactingStream(stream))
    loggers = [logging.getLogger()]
    loggers += [lg for lg in list(logging.Logger.manager.loggerDict.values())
                if isinstance(lg, logging.Logger)]
    for lg in loggers:
        for handler in list(lg.handlers):
            stream = getattr(handler, "stream", None)
            if (isinstance(handler, logging.StreamHandler)
                    and not isinstance(handler, logging.FileHandler)
                    and not _wrapped(stream)
                    and _is_console(stream, consoles)):
                handler.stream = RedactingStream(stream)
