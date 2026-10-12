"""Secret env values are masked in the app's console logs (Landing 30).

An RPC URL carries its API key in the path, and requests puts the URL in its
exception text, so every print / traceback of an RPC failure wrote the key to
Railway's logs. log_redact masks the values of variables whose names contain
RPC_URL, _KEY, SECRET, TOKEN or PASSWORD (for a URL, its long path segments,
query values, user name and password; the host stays), plus Telegram bot
tokens, wherever the process writes to stdout, stderr or a console log
handler.

The key below is made up: a repeated pattern, never a real credential.
"""
import io
import json
import os
import subprocess
import sys

import pytest
import requests
import urllib3

import log_redact as lr

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

FAKE = "Tq7W" + "zk9X" * 7                     # 32 characters, like an Alchemy key
ETH_URL = "https://eth-mainnet.g.alchemy.com/v2/" + FAKE
ETH_MARK = "<redacted:ETHEREUM_RPC_URL>"
ETH_MASKED = "https://eth-mainnet.g.alchemy.com/v2/" + ETH_MARK


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Only the variables a test sets are secrets: drop every secret-named
    variable the machine running the suite happens to have."""
    for name in list(os.environ):
        if lr._is_secret_name(name):
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(lr, "_cache", (None, [], None, 0.0))
    monkeypatch.setattr(lr, "_seen", {})


def _http_error(url):
    """The exception web3's HTTP provider raises on a non-200 answer: the one
    from requests' raise_for_status, whose text ends with the full URL."""
    resp = requests.Response()
    resp.status_code = 401
    resp.reason = "Unauthorized"
    resp.url = url
    try:
        resp.raise_for_status()
    except requests.exceptions.HTTPError as e:
        return e
    raise AssertionError("raise_for_status did not raise")


def _connection_error(host, path):
    """requests' ConnectionError as an unreachable endpoint gives it: the text
    names the host and the path (where the key is), not the full URL."""
    pool = urllib3.HTTPSConnectionPool(host, 443)
    return requests.exceptions.ConnectionError(urllib3.exceptions.MaxRetryError(pool, path))


# ---------------------------------------------------------------------------
# What is masked
# ---------------------------------------------------------------------------

def test_the_key_in_an_rpc_url_is_masked_and_the_host_kept(monkeypatch):
    monkeypatch.setenv("ETHEREUM_RPC_URL", ETH_URL)
    assert lr.redact("call to " + ETH_URL + " failed") == "call to " + ETH_MASKED + " failed"


def test_a_keyless_public_url_stays_readable(monkeypatch):
    monkeypatch.setenv("BASE_RPC_URL", "https://mainnet.base.org")
    monkeypatch.setenv("ROBINHOOD_RPC_URL", "https://rpc.testnet.chain.robinhood.com/rpc")
    text = "for url: https://mainnet.base.org/ and https://rpc.testnet.chain.robinhood.com/rpc"
    assert lr.redact(text) == text


def test_a_websocket_url_key_is_masked(monkeypatch):
    monkeypatch.setenv("ETHEREUM_WS_RPC_URL", "wss://eth-mainnet.g.alchemy.com/v2/" + FAKE)
    assert lr.redact("ws " + FAKE) == "ws <redacted:ETHEREUM_WS_RPC_URL>"


def test_the_key_on_its_own_and_in_the_path_form_are_masked(monkeypatch):
    monkeypatch.setenv("ETHEREUM_RPC_URL", ETH_URL)
    assert lr.redact("url: /v2/" + FAKE + " (Caused by x)") == "url: /v2/" + ETH_MARK + " (Caused by x)"
    assert lr.redact("key=" + FAKE) == "key=" + ETH_MARK


def test_a_requests_http_error_from_an_rpc_call_is_masked(monkeypatch):
    monkeypatch.setenv("ETHEREUM_RPC_URL", ETH_URL)
    text = str(_http_error(ETH_URL))
    assert FAKE in text                         # the leak this landing closes
    out = lr.redact(text)
    assert FAKE not in out
    assert out == "401 Client Error: Unauthorized for url: " + ETH_MASKED


def test_a_requests_connection_error_from_an_rpc_call_is_masked(monkeypatch):
    monkeypatch.setenv("ETHEREUM_RPC_URL", ETH_URL)
    text = str(_connection_error("eth-mainnet.g.alchemy.com", "/v2/" + FAKE))
    assert "/v2/" + FAKE in text                # the path form, not the full URL
    out = lr.redact(text)
    assert FAKE not in out
    assert "/v2/" + ETH_MARK in out


def test_a_web3_call_through_the_http_provider_is_masked(monkeypatch):
    """End to end on web3's own provider: a 401 from the endpoint (served by
    a requests adapter, no network) raises an error whose text holds the key."""
    from web3 import Web3

    class _Unauthorized(requests.adapters.BaseAdapter):
        def send(self, request, **kwargs):
            resp = requests.Response()
            resp.status_code = 401
            resp.reason = "Unauthorized"
            resp.url = request.url
            resp.request = request
            resp._content = b'{"error":"unauthorized"}'
            return resp

        def close(self):
            pass

    session = requests.Session()
    session.mount("https://", _Unauthorized())
    monkeypatch.setenv("ETHEREUM_RPC_URL", ETH_URL)
    w3 = Web3(Web3.HTTPProvider(ETH_URL, session=session, exception_retry_configuration=None))
    with pytest.raises(Exception) as info:
        w3.eth.block_number
    text = str(info.value)
    assert FAKE in text
    assert FAKE not in lr.redact(text)


def test_query_values_and_passwords_in_an_rpc_url_are_masked(monkeypatch):
    monkeypatch.setenv("CUSTOM_RPC_URL", "https://rpc.example.com/eth?apikey=" + FAKE)
    monkeypatch.setenv("OTHER_RPC_URL", "https://user:" + FAKE[::-1] + "@node.example.com/")
    assert lr.redact("apikey=" + FAKE) == "apikey=<redacted:CUSTOM_RPC_URL>"
    assert lr.redact("password " + FAKE[::-1]) == "password <redacted:OTHER_RPC_URL>"


def test_a_percent_encoded_key_is_masked(monkeypatch):
    monkeypatch.setenv("CUSTOM_RPC_URL", "https://rpc.example.com/v1/" + FAKE + "%2Bend")
    assert lr.redact("raw " + FAKE + "+end") == "raw <redacted:CUSTOM_RPC_URL>"


@pytest.mark.parametrize("name", [
    "ZERION_API_KEY", "ETHERSCAN_API_KEY", "FLASK_SECRET_KEY",
    "TELEGRAM_BOT_TOKEN", "WEBHOOK_SECRET", "zerion_api_key",
    "AWS_BEARER_TOKEN_BEDROCK", "APP_PASSWORD_HASH", "OPENAI_API_KEY",
])
def test_key_secret_and_token_variables_are_masked(monkeypatch, name):
    monkeypatch.setenv(name, FAKE)
    assert lr.redact("auth " + FAKE) == "auth <redacted:%s>" % name


def test_short_values_and_other_names_are_left_alone(monkeypatch):
    monkeypatch.setenv("SHORT_KEY", "abc123")                       # under 16
    monkeypatch.setenv("FIFTEEN_TOKEN", "x" * 15)                   # under 16
    monkeypatch.setenv("WALLET_CONFIG_PATH", "/app/data/wallet_config.json")
    monkeypatch.setenv("KEY_PLACEHOLDER", FAKE)                     # name doesn't end in _KEY
    text = "abc123 " + "x" * 15 + " /app/data/wallet_config.json " + FAKE
    assert lr.redact(text) == text


def test_short_path_segments_and_the_host_alone_stay(monkeypatch):
    monkeypatch.setenv("ETHEREUM_RPC_URL", ETH_URL)
    text = "host eth-mainnet.g.alchemy.com, path /v2/"
    assert lr.redact(text) == text


def test_a_key_shared_by_several_urls_gets_a_neutral_marker(monkeypatch):
    """One Alchemy key behind several chains: naming one chain would mislead,
    and the host on the same line already says which chain failed."""
    monkeypatch.setenv("ETHEREUM_RPC_URL", ETH_URL)
    monkeypatch.setenv("ARBITRUM_RPC_URL", "https://arb-mainnet.g.alchemy.com/v2/" + FAKE)
    assert lr.redact("/v2/" + FAKE) == "/v2/<redacted:shared>"
    assert lr.redact(ETH_URL) == "https://eth-mainnet.g.alchemy.com/v2/<redacted:shared>"


def test_text_without_secrets_and_non_text_pass_through(monkeypatch):
    monkeypatch.setenv("ETHEREUM_RPC_URL", ETH_URL)
    assert lr.redact("") == ""
    assert lr.redact("nothing here") == "nothing here"
    assert lr.redact(None) is None
    assert lr.redact(42) == 42


def test_bytes_are_masked_and_other_bytes_kept_exactly(monkeypatch):
    monkeypatch.setenv("ETHEREUM_RPC_URL", ETH_URL)
    assert lr.redact(("x " + FAKE).encode()) == ("x " + ETH_MARK).encode()
    raw = b"\xff\xfe not utf-8 \x80"
    assert lr.redact(raw) is raw
    assert lr.redact(raw + FAKE.encode()) == raw + ETH_MARK.encode()


# ---------------------------------------------------------------------------
# The environment is read when text is written
# ---------------------------------------------------------------------------

def test_a_value_set_later_is_masked_from_then_on(monkeypatch):
    assert lr.redact(FAKE) == FAKE
    monkeypatch.setenv("BASE_RPC_URL", "https://base-mainnet.g.alchemy.com/v2/" + FAKE)
    assert lr.redact(FAKE) == "<redacted:BASE_RPC_URL>"


def test_a_value_changed_in_settings_is_followed_and_the_old_one_stays_masked(monkeypatch):
    """The Settings page saves an RPC URL into os.environ while the app runs.
    Parts of the app keep the old URL until a restart (maxfi_client reads
    BASE_RPC_URL once at import), so the old key stays masked too."""
    monkeypatch.setenv("ETHEREUM_RPC_URL", ETH_URL)
    assert lr.redact(FAKE) == ETH_MARK
    new_key = FAKE[::-1]
    os.environ["ETHEREUM_RPC_URL"] = "https://eth-mainnet.g.alchemy.com/v2/" + new_key
    replaced = "<redacted:ETHEREUM_RPC_URL, replaced>"
    assert lr.redact(new_key) == ETH_MARK
    assert lr.redact(FAKE) == replaced              # still masked, and told apart
    del os.environ["ETHEREUM_RPC_URL"]
    assert lr.redact(new_key + " " + FAKE) == replaced + " " + replaced


def test_an_empty_variable_filled_in_later_is_masked_at_once(monkeypatch):
    """A new install's .env has blank lines such as ETHEREUM_RPC_URL=, which
    the entrypoint exports; Settings later sets the URL without changing the
    number of variables, so the quick check must still see it."""
    monkeypatch.setenv("ETHEREUM_RPC_URL", "")
    assert lr.redact(FAKE) == FAKE
    count = len(os.environ)
    os.environ["ETHEREUM_RPC_URL"] = ETH_URL
    assert len(os.environ) == count
    assert lr.redact(FAKE) == ETH_MARK


def test_a_new_secret_variable_is_masked_at_once(monkeypatch):
    monkeypatch.setenv("ETHEREUM_RPC_URL", ETH_URL)
    assert lr.redact("x") == "x"                            # warm the quick check
    monkeypatch.setenv("NEW_API_KEY", FAKE[::-1])
    assert lr.redact(FAKE[::-1]) == "<redacted:NEW_API_KEY>"


def test_the_periodic_full_read_catches_a_swap_that_keeps_the_count(monkeypatch):
    monkeypatch.setenv("PLAIN_SETTING", "1")
    assert lr.redact("x") == "x"                            # warm the quick check
    monkeypatch.delenv("PLAIN_SETTING")
    monkeypatch.setenv("SWAPPED_API_KEY", FAKE)             # same count, new secret name
    monkeypatch.setattr(lr, "RESCAN_SECONDS", 0.0)
    assert lr.redact(FAKE) == "<redacted:SWAPPED_API_KEY>"


def test_a_key_saved_while_the_list_is_being_rebuilt_is_masked_on_the_next_write(monkeypatch):
    """Found in review: the fingerprint was read after the snapshot, so a
    value saved in between landed in the fingerprint but not in the list,
    and stayed unmasked until the periodic full read."""
    monkeypatch.setenv("ETHEREUM_RPC_URL", ETH_URL)
    assert lr.redact(FAKE) == ETH_MARK
    real = lr._env_snapshot
    new_key = FAKE[::-1]

    def _racing():
        snap = real()
        # Another thread's Settings save lands right after the read.
        os.environ["ETHEREUM_RPC_URL"] = "https://eth-mainnet.g.alchemy.com/v2/" + new_key
        return snap

    monkeypatch.setattr(lr, "_env_snapshot", _racing)
    monkeypatch.setenv("PLAIN_SETTING", "1")        # forces a rebuild on the next write
    lr.redact("x")
    monkeypatch.setattr(lr, "_env_snapshot", real)
    assert lr.redact(new_key) == ETH_MARK


def test_a_variable_added_while_the_list_is_being_rebuilt_is_masked_on_the_next_write(monkeypatch):
    monkeypatch.setenv("ETHEREUM_RPC_URL", ETH_URL)
    assert lr.redact(FAKE) == ETH_MARK
    real = lr._env_snapshot

    def _racing():
        snap = real()
        os.environ["LATE_API_KEY"] = FAKE[::-1]     # added right after the read
        return snap

    monkeypatch.setattr(lr, "_env_snapshot", _racing)
    monkeypatch.setenv("PLAIN_SETTING", "1")
    try:
        lr.redact("x")
        monkeypatch.setattr(lr, "_env_snapshot", real)
        assert lr.redact(FAKE[::-1]) == "<redacted:LATE_API_KEY>"
    finally:
        os.environ.pop("LATE_API_KEY", None)


def test_a_failed_environment_read_keeps_the_last_list(monkeypatch):
    monkeypatch.setenv("ETHEREUM_RPC_URL", ETH_URL)
    assert lr.redact(FAKE) == ETH_MARK

    def _boom():
        raise RuntimeError("dictionary changed size during iteration")

    monkeypatch.setattr(lr, "_env_snapshot", _boom)
    monkeypatch.setattr(lr, "RESCAN_SECONDS", 0.0)          # force the full read
    assert lr.redact(FAKE) == ETH_MARK


def test_the_secret_list_is_reused_while_the_environment_is_unchanged(monkeypatch):
    monkeypatch.setenv("ETHEREUM_RPC_URL", ETH_URL)
    first = lr.secrets_now()
    assert lr.secrets_now() is first
    assert first == [(FAKE, ETH_MARK)]             # the key, not the whole URL


def test_a_value_with_a_non_utf8_byte_is_masked_and_never_breaks_a_write(monkeypatch):
    """A mis-encoded byte in a Railway variable arrives as a surrogate; it
    once made every print and log call raise (found in review)."""
    import logging
    bad_seg = "a" * 20 + "\udcff"
    monkeypatch.setenv("BAD_RPC_URL", "https://x.example.com/v2/" + bad_seg)
    assert lr.redact("seg " + bad_seg) == "seg <redacted:BAD_RPC_URL>"
    buf = io.StringIO()
    s = lr.RedactingStream(buf)
    print("hello", file=s)
    lg = logging.getLogger("test_log_redact.bad")
    h = logging.StreamHandler(s)
    lg.addHandler(h)
    lg.propagate = False
    try:
        lg.error("logged fine")
    finally:
        lg.removeHandler(h)
    assert buf.getvalue() == "hello\nlogged fine\n"


def test_an_internal_masking_error_withholds_the_text_and_keeps_line_breaks(monkeypatch):
    """redact() never raises: the text is withheld, never returned unmasked,
    and print's separate newline write passes so lines stay apart."""
    monkeypatch.setattr(lr, "secrets_now", lambda: [(None, "x")])   # bad data: `in` raises
    assert lr.redact("secret " + FAKE + "\n") == lr._WITHHELD
    assert lr.redact("secret " + FAKE) == lr._WITHHELD.rstrip("\n")
    assert lr.redact("\n") == "\n"
    buf = io.StringIO()
    s = lr.RedactingStream(buf)
    print("one " + FAKE, file=s)
    print("two", file=s)
    assert buf.getvalue() == lr._WITHHELD * 2
    assert FAKE not in buf.getvalue()


def test_a_masking_failure_withholds_the_line_and_never_raises(monkeypatch):
    """The stream's own guard, for an error redact() itself didn't catch."""
    def _boom(text):
        raise ValueError("internal error")

    monkeypatch.setattr(lr, "redact", _boom)
    buf = io.StringIO()
    s = lr.RedactingStream(buf)
    print("secret " + FAKE, file=s)
    assert FAKE not in buf.getvalue()
    assert buf.getvalue().count(lr._WITHHELD) == 2      # the text and print's newline


TG = "7123456789:" + "AAH" + "q9Zk" * 8                    # made-up bot token, real shape


def test_a_telegram_bot_token_is_masked_wherever_it_appears():
    """The bot token comes from a config file, not the environment, and sits
    in the path of every Telegram API URL."""
    text = str(_connection_error("api.telegram.org", "/bot" + TG + "/sendMessage"))
    assert TG in text
    out = lr.redact("Telegram network error: " + text)
    assert TG not in out
    assert "/bot<redacted:telegram bot token>/sendMessage" in out
    assert lr.redact("token " + TG) == "token <redacted:telegram bot token>"


@pytest.mark.parametrize("text", [
    "12:34:56", "1696000000:ok", "ts 1791342458:" + "x" * 10, "ratio 3:1",
    "1791342458:0x" + "ab" * 32,                    # timestamp:tx hash
    "block 21345678:0x" + "cd" * 32,                # block:tx hash
    "tid 123456789012345:0x" + "ef" * 32,           # Hyperliquid tid:hash
    "42161:0x" + "12" * 20, "eip155:42161:0x" + "34" * 20,   # chain:address
    "slot 312345678:" + "5KKK" * 22,                # Solana slot:signature
    "20261011:3f2b8c1e-9a7d-4e21-b6c3-0d5e8f7a9b1c",  # date:uuid
    "12345:So11111111111111111111111111111111111111112",  # id:Solana mint
])
def test_ordinary_colon_text_is_not_taken_for_a_telegram_token(text):
    assert lr.redact(text) == text


@pytest.mark.parametrize("wrap", [
    '"{t}"', '{{"bot_token": "{t}"}}', "bot_token_{t}", "https://api.telegram.org/bot{t}/getMe", "{t}",
])
def test_a_telegram_bot_token_is_masked_in_its_usual_wrappings(wrap):
    out = lr.redact(wrap.format(t=TG))
    assert TG not in out and TG[-20:] not in out
    assert out == wrap.format(t="<redacted:telegram bot token>")


# ---------------------------------------------------------------------------
# The stream wrapper
# ---------------------------------------------------------------------------

def test_the_stream_masks_writes_and_passes_everything_else_through(monkeypatch):
    monkeypatch.setenv("ETHEREUM_RPC_URL", ETH_URL)
    buf = io.StringIO()
    s = lr.RedactingStream(buf)
    assert s.write("a " + FAKE) == len("a " + FAKE)
    assert s.write("plain") == 5
    s.writelines([" x ", ETH_URL, "\n"])
    s.flush()
    assert buf.getvalue() == "a " + ETH_MARK + "plain x " + ETH_MASKED + "\n"
    assert s.getvalue() == buf.getvalue()           # attributes come from the wrapped stream
    assert s.writable() is True
    assert "RedactingStream" in repr(s)


def test_the_stream_can_be_copied_and_used_as_a_context_manager(monkeypatch):
    import copy
    monkeypatch.setenv("ETHEREUM_RPC_URL", ETH_URL)
    buf = io.StringIO()
    c = copy.copy(lr.RedactingStream(buf))
    c.write(FAKE)
    assert buf.getvalue() == ETH_MARK
    with lr.RedactingStream(io.StringIO()) as s:
        s.write("x")


def test_the_stream_keeps_a_real_file_stream_attributes(tmp_path):
    with open(tmp_path / "log.txt", "w", encoding="utf-8") as f:
        s = lr.RedactingStream(f)
        assert s.encoding == "utf-8"
        assert s.fileno() == f.fileno()
        assert s.isatty() is False
        assert s.buffer is f.buffer


def test_print_and_tracebacks_go_through_the_stream(monkeypatch):
    import traceback
    monkeypatch.setenv("ETHEREUM_RPC_URL", ETH_URL)
    buf = io.StringIO()
    s = lr.RedactingStream(buf)
    print("[custom-token] balance read FAILED:", _http_error(ETH_URL), file=s)
    try:
        raise _http_error(ETH_URL)
    except requests.exceptions.HTTPError:
        traceback.print_exc(file=s)
    out = buf.getvalue()
    assert FAKE not in out
    assert out.count(ETH_MARK) >= 2
    assert "Traceback (most recent call last)" in out


def test_the_snapshot_error_is_masked_before_it_is_cut(monkeypatch):
    """snapshot_service cuts the complete-total error to 500 characters and
    prints it: a key straddling the cut would leave a fragment no mask can
    recognise, in the log and in the stored row."""
    from src.engines import snapshot_service as ss
    monkeypatch.setenv("ETHEREUM_RPC_URL", ETH_URL)
    rows = []
    monkeypatch.setattr(ss, "insert_portfolio_total_snapshot", lambda row, user_id: rows.append(row))

    def _compose(portfolio):
        # "ValueError: " (12) + 470 + " url /v2/" (9) puts the key across character 500.
        raise ValueError("x" * 470 + " url /v2/" + FAKE)

    ss._write_portfolio_total_snapshot(_compose, {}, "2026-10-11T00:00:00Z", False, 0.0, 0, 0, 1)
    assert rows and rows[0]["status"] == "failed"
    assert len(rows[0]["error"]) == 500
    assert FAKE[:8] not in rows[0]["error"]
    assert rows[0]["error"].endswith(" url /v2/" + ETH_MARK[:9])


# ---------------------------------------------------------------------------
# install(), in a fresh interpreter so pytest's own capture is not touched
# ---------------------------------------------------------------------------

_INSTALL = r'''
import io, logging, sys, threading, traceback
import requests

URL = sys.argv[1]
# Like gunicorn: a console handler made before the app is imported.
early = logging.StreamHandler(sys.stderr)
glog = logging.getLogger("gunicorn.error")
glog.addHandler(early)
glog.propagate = False
# A handler that writes somewhere else is not the console and stays as it is.
memory = io.StringIO()
mem_handler = logging.StreamHandler(memory)
logging.getLogger("in.memory").addHandler(mem_handler)

import log_redact
log_redact.install()
log_redact.install()

W = log_redact.RedactingStream
assert isinstance(sys.stdout, W) and not isinstance(sys.stdout._stream, W)
assert isinstance(sys.stderr, W) and not isinstance(sys.stderr._stream, W)
assert isinstance(early.stream, W) and not isinstance(early.stream._stream, W)
assert mem_handler.stream is memory

print("stdout line", URL)
print("stderr line", URL, file=sys.stderr, flush=True)
logging.getLogger("in.memory").error("memory line %s", URL)
glog.error("gunicorn line %s", URL)
try:
    raise RuntimeError("failed calling " + URL)
except RuntimeError:
    traceback.print_exc()
    glog.exception("gunicorn traceback")
logging.basicConfig()                       # made after install: defaults to the wrapped stderr
logging.getLogger("late").error("late line %s", URL)

def _boom():
    raise RuntimeError("thread failed calling " + URL)

t = threading.Thread(target=_boom)
t.start(); t.join()
sys.stdout.flush(); sys.stderr.flush()
print("MEMORY:" + ("raw" if URL in memory.getvalue() else "none"))
'''


def _run(script, *args, env_extra=None, cwd=None):
    env = dict(os.environ)
    for name in list(env):
        if lr._is_secret_name(name):
            del env[name]
    env["PYTHONPATH"] = _ROOT + os.pathsep + env.get("PYTHONPATH", "")
    env.update(env_extra or {})
    proc = subprocess.run([sys.executable, "-c", script, *args], cwd=cwd or _ROOT,
                          env=env, capture_output=True, text=True, timeout=300)
    return proc


def test_install_wraps_the_console_streams_and_handlers_once():
    proc = _run(_INSTALL, ETH_URL, env_extra={"ETHEREUM_RPC_URL": ETH_URL})
    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, out[-4000:]
    assert FAKE not in out
    for line in ("stdout line " + ETH_MASKED, "stderr line " + ETH_MASKED,
                 "gunicorn line " + ETH_MASKED, "late line " + ETH_MASKED):
        assert line in out
    assert out.count("Traceback (most recent call last)") == 3   # print_exc, exception(), thread
    assert "failed calling " + ETH_MASKED in out
    assert "thread failed calling " + ETH_MASKED in out
    # Only the console is masked; a handler writing to memory is untouched.
    assert "MEMORY:raw" in out


# ---------------------------------------------------------------------------
# The app: web_portfolio installs it, and the known leak sites are masked
# ---------------------------------------------------------------------------

_APP = r'''
import json, os, sys, threading
_start = threading.Thread.start
threading.Thread.start = lambda self, *a, **k: None   # no scheduler at import
import web_portfolio as wp
threading.Thread.start = _start

import requests, log_redact
assert isinstance(sys.stdout, log_redact.RedactingStream)
assert isinstance(sys.stderr, log_redact.RedactingStream)

URL = os.environ["ETHEREUM_RPC_URL"]
KEY = URL.rsplit("/", 1)[1]
WALLET = "0x" + "cd" * 20
CONTRACT = "0x" + "ab" * 20

def _http_error(*a, **k):
    resp = requests.Response()
    resp.status_code = 401
    resp.reason = "Unauthorized"
    resp.url = URL
    resp.raise_for_status()

try:
    _http_error()
except requests.exceptions.HTTPError as e:
    assert KEY in str(e)                     # the unmasked text holds the key

wp._balance_of_raw = _http_error
wp._custom_token_metadata = _http_error
wp.fetch_dexscreener_price = lambda *a, **k: None
wp.get_wallet_addresses = lambda: [WALLET]
wp.get_custom_tokens = lambda: [{"id": 1, "chain": "ethereum", "contract": CONTRACT,
                                 "symbol": "TST", "decimals": 18, "added_at": "2026-10-11"}]

# 1. Holdings build: "[custom-token] balance read FAILED ... {e}"
rows = wp.build_custom_token_rows({WALLET: {"label": "Test", "type": "evm"}})
print("ROWS", len(rows))
# 2. "[custom-token] metadata still unresolved ... {e}"
wp.resolve_pending_metadata({"id": 1, "chain": "ethereum", "contract": CONTRACT,
                             "symbol": "pending", "decimals": None})
# 3. The add route: traceback.format_exc() on the RPC error
wp.get_password_hash = lambda: "x"
wp.app.config["TESTING"] = True
c = wp.app.test_client()
with c.session_transaction() as s:
    s["authenticated"] = True
r = c.post("/api/custom-tokens", json={"chain": "ethereum", "contract": CONTRACT})
print("ADD", r.status_code, json.dumps(r.get_json()))
# 4. Telegram: the bot token sits in the URL path of a network error
import urllib3
from src.engines import telegram_service as tg
TG = os.environ["TEST_TG_BOT"]
def _tg_down(*a, **k):
    pool = urllib3.HTTPSConnectionPool("api.telegram.org", 443)
    raise requests.exceptions.ConnectionError(
        urllib3.exceptions.MaxRetryError(pool, "/bot" + TG + "/sendMessage"))
tg.requests.post = _tg_down
try:
    tg.send_telegram_message(TG, "1", "hi")
except RuntimeError as e:
    assert TG in str(e)
    print("[Telegram] send failed:", e)
sys.stdout.flush(); sys.stderr.flush()
'''


@pytest.fixture(scope="module")
def app_run(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("redact_app")
    proc = _run(_APP, cwd=str(tmp), env_extra={
        "ETHEREUM_RPC_URL": ETH_URL,
        "TEST_TG_BOT": TG,
        "BAD_RPC_URL": "https://x.example.com/v2/" + "a" * 20 + "\udcff",
        "RAILWAY_VOLUME_MOUNT_PATH": str(tmp / "vol"),
        "DOTENV_PATH": str(tmp / ".env"),
        "WALLET_CONFIG_PATH": str(tmp / "wallet_config.json"),
    })
    return proc


def test_the_app_boots_with_the_wrapper_in_place(app_run):
    out = app_run.stdout + app_run.stderr
    assert app_run.returncode == 0, out[-4000:]
    assert "[startup] db path:" in out


def test_the_app_never_writes_the_key(app_run):
    out = app_run.stdout + app_run.stderr
    assert FAKE not in out
    assert TG not in out
    assert "/bot<redacted:telegram bot token>/sendMessage" in out
    assert lr._WITHHELD.strip() not in out          # the bad byte broke nothing


def test_each_known_leak_site_is_masked(app_run):
    out = app_run.stdout + app_run.stderr
    failed = [ln for ln in out.splitlines() if "balance read FAILED" in ln]
    assert failed and all(ETH_MARK in ln for ln in failed)
    unresolved = [ln for ln in out.splitlines() if "metadata still unresolved" in ln]
    assert unresolved and all(ETH_MARK in ln for ln in unresolved)
    assert "Traceback (most recent call last)" in out
    assert "for url: " + ETH_MASKED in out


def test_the_add_route_answers_as_before(app_run):
    add = [ln for ln in app_run.stdout.splitlines() if ln.startswith("ADD ")][0]
    status, body = add.split(" ", 2)[1:]
    assert status == "400"
    assert json.loads(body) == {"error": "RPC endpoint rejected the request for chain ethereum "
                                         "(authentication failed). Check the API key "
                                         "configuration for this chain."}
