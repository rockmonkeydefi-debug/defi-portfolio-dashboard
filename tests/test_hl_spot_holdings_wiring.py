"""Landing 85: the page side of Hyperliquid spot on Token Holdings
(static/portfolio2.js). The rows come from their own request and are merged
into the Token Holdings table only: they never enter `portfolio`, so no total,
snapshot or Dry powder figure can see them. USDC there is perp margin: its own
group and a label. A Unit-issued coin (UETH) is grouped with its asset. A coin
with no price shows and never turns a sum into NaN. These read the source and
run the page's own helpers in node; the headless checks for the landing
exercise the browser."""
import json
import os
import re
import shutil
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HAS_NODE = shutil.which("node") is not None
MID_DOT = chr(0xB7)


def _src():
    with open(os.path.join(ROOT, "static", "portfolio2.js"), encoding="utf-8") as f:
        return f.read()


def _function(src, name):
    """The text of `function name(...) { ... }`, found by matching braces."""
    start = src.index("function " + name + "(")
    depth, i = 0, src.index("{", start)
    for j in range(i, len(src)):
        if src[j] == "{":
            depth += 1
        elif src[j] == "}":
            depth -= 1
            if depth == 0:
                return src[start:j + 1]
    raise AssertionError(name)


def _helpers_region(src):
    return src[src.index("// Hyperliquid spot rows (Landing 85)"):src.index("// Declutter custom-token zero rows.")]


def _run(expr, data):
    src = _src()
    groups = re.search(r"const TOKEN_GROUPS = \{.*?\n\};", src, re.S).group(0)
    parts = [groups] + [_function(src, n) for n in ("isYieldToken", "isStablecoin", "tokenGroup", "tokenKeyOf")]
    parts.append(_helpers_region(src))
    script = "\n".join(parts) + "\nconst data = JSON.parse(process.argv[1]);\nconsole.log(JSON.stringify(" + expr + "));"
    res = subprocess.run(["node", "-e", script, json.dumps(data)], capture_output=True, text=True, timeout=30)
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout)


def _resp(*rows, **extra):
    base = {"status": "ok", "as_of": "2026-11-01T12:00:00+00:00", "rows": list(rows), "unread": [], "refresh_failed": False}
    base.update(extra)
    return base


def _row(coin, amount, price, wallet="0xw1", label="Hyperliquid RM", **kw):
    priced = price is not None
    row = {"wallet": wallet, "wallet_label": label, "venue_label": label + " App", "coin": coin,
           "canonical": {"UETH": "ETH", "UBTC": "BTC", "USOL": "SOL"}.get(coin.upper(), coin.upper()),
           "balance": amount, "price_usd": price, "value_usd": amount * price if priced else None,
           "priced": priced, "margin": coin.upper() == "USDC", "stale": False}
    row.update(kw)
    return row


# -- source pins ------------------------------------------------------------

def test_the_helpers_sit_above_the_blocks_other_tests_slice():
    src = _src()
    assert src.index("// Hyperliquid spot rows (Landing 85)") < src.index("// Declutter custom-token zero rows.")
    assert src.index("function hlSpotToTokenRows") < src.index("function consolidateCustomZeros")
    # tests/test_custom_tokens_solana_wiring.py slices AddCustomToken .. TokenHoldings: nothing new inside it
    block = src[src.index("function AddCustomToken"):src.index("function TokenHoldings")]
    assert "hlSpot" not in block and "HL_" not in block


def test_the_page_asks_for_the_rows_on_their_own_and_never_puts_them_in_portfolio():
    src = _src()
    screen = src[src.index("function PortfolioScreen"):src.index("window.PortfolioScreen")]
    assert "api('/api/portfolio/hyperliquid-spot').catch(() => null)" in screen
    assert "setHlSpot(hl || null);" in screen
    assert "hlSpot={hlSpot && hlSpot.status === 'loading'" in screen
    assert screen.count("setPortfolio(") == 1 and "setPortfolio(pf);" in screen
    # the merge happens in the table component alone
    assert "const hlRows = useMemo(() => hlSpotToTokenRows(hlSpot), [hlSpot]);" in src
    assert "...pendingRows, ...hlRows]" in src
    code = "\n".join(l for l in _helpers_region(src).split("\n") if not l.strip().startswith("//"))
    assert "portfolio" not in code.replace("hyperliquid", "")


def test_a_loading_answer_is_asked_again_a_few_times_then_left_alone():
    src = _src()
    assert "hlSpot.status !== 'loading' || hlTries >= 8) return undefined;" in src
    assert "}, 6000);" in src and "setHlTries(n => n + 1);" in src


def test_hyperliquid_rows_have_their_own_filter_key_group_and_dust_rule():
    src = _src()
    assert "if (t._key) return t._key;" in _function(src, "tokenKeyOf")
    assert "t._group || tokenGroup(t.symbol)" in src and "[HL_MARGIN_GROUP]:[]" in src
    assert "t.source !== 'custom' && !t._unpriced && t.value_usd < dustThreshold" in src
    assert "t.source === 'custom' || t._unpriced || showDust" in src
    assert "t.chip_label || t.symbol" in src
    assert "t.source === 'hyperliquid' ? t.venue_label : t.wallet_label" in src


def test_the_new_page_code_is_ascii_and_builds_the_middle_dot_from_its_code_point():
    region = _helpers_region(_src())
    assert all(ord(c) < 128 for c in region)
    assert "const HL_DOT = ' ' + String.fromCharCode(183) + ' ';" in region


# -- the helpers, run in node -----------------------------------------------

needs_node = pytest.mark.skipif(not HAS_NODE, reason="node not installed")


@needs_node
def test_only_an_ok_answer_with_rows_makes_rows():
    for bad in (None, {}, {"status": "loading", "rows": []}, {"status": "error"}, {"status": "ok", "rows": "x"}):
        assert _run("hlSpotToTokenRows(data)", bad) == []
    assert _run("hlSpotToTokenRows(data)", _resp()) == []


@needs_node
def test_usdc_is_perp_margin_in_its_own_group_with_its_own_key():
    rows = _run("hlSpotToTokenRows(data)", _resp(_row("USDC", 100.0, 1.0)))
    r = rows[0]
    assert r["display_symbol"] == "USDC " + MID_DOT + " Hyperliquid (perp margin)"
    assert r["chip_label"] == "USDC " + MID_DOT + " Hyperliquid"
    assert r["_group"] == "Hyperliquid margin" and r["hl_margin"] is True
    assert r["_key"] == "hl:USDC" and r["chain"] == "hyperliquid" and r["source"] == "hyperliquid"
    assert r["value_usd"] == 100.0 and r["contract"] == ""
    assert _run("tokenKeyOf(data)", {"symbol": "USDC", "contract": "0xABC"}) == "c:0xabc"
    assert _run("tokenKeyOf(data)", {"symbol": "BTC", "contract": ""}) == "sym:BTC"
    assert _run("tokenKeyOf(data)", r) == "hl:USDC"


@needs_node
def test_a_unit_coin_groups_with_its_asset_and_keeps_its_name():
    rows = _run("hlSpotToTokenRows(data)", _resp(_row("UETH", 2.5, 3000.0), _row("UBTC", 1.0, 90000.0),
                                                 _row("HYPE", 10.0, 20.0)))
    by = {r["symbol"]: r for r in rows}
    assert by["UETH"]["_group"] == "ETH" and by["UETH"]["avatar_symbol"] == "ETH" and by["UETH"]["display_symbol"] == "UETH"
    assert by["UBTC"]["_group"] == "BTC" and by["UBTC"]["avatar_symbol"] == "BTC"
    assert by["HYPE"]["_group"] == "Other" and by["HYPE"]["avatar_symbol"] == "HYPE"
    assert by["UETH"]["_key"] == "hl:UETH" and by["UETH"]["hl_margin"] is False


@needs_node
def test_a_coin_without_a_price_shows_with_zero_value_and_no_nan():
    rows = _run("hlSpotToTokenRows(data)", _resp(_row("ZZZ", 5.0, None), _row("HYPE", 10.0, 20.0)))
    zzz = next(r for r in rows if r["symbol"] == "ZZZ")
    assert zzz["_unpriced"] is True and zzz["price_usd"] is None and zzz["value_usd"] == 0 and zzz["balance"] == 5.0
    total = _run("hlSpotToTokenRows(data).reduce((s, t) => s + t.value_usd, 0)", _resp(_row("ZZZ", 5.0, None), _row("HYPE", 10.0, 20.0)))
    assert total == 200.0
    nonfinite = _run("hlSpotToTokenRows(data)", _resp(_row("BAD", 1.0, 2.0, value_usd=None, priced=True)))
    assert nonfinite[0]["_unpriced"] is True and nonfinite[0]["value_usd"] == 0


@needs_node
def test_a_stale_wallet_is_flagged_and_the_wallet_badge_label_is_the_app_label():
    rows = _run("hlSpotToTokenRows(data)", _resp(_row("HYPE", 1.0, 2.0, stale=True)))
    assert rows[0]["hl_stale"] is True
    assert rows[0]["venue_label"] == "Hyperliquid RM App" and rows[0]["wallet_label"] == "Hyperliquid RM"
    assert rows[0]["wallet"] == "0xw1"


@needs_node
def test_the_notice_says_what_is_missing_and_stays_quiet_when_all_is_there():
    assert _run("hlSpotNotice(data)", _resp()) == ""
    assert _run("hlSpotNotice(data)", None) == "Hyperliquid balances are unavailable."
    assert _run("hlSpotNotice(data)", {"status": "loading", "rows": []}) == "Hyperliquid balances are loading..."
    assert _run("hlSpotNotice(data)", {"status": "error", "rows": []}) == "Hyperliquid balances could not be read."
    both = _run("hlSpotNotice(data)", _resp(unread=["Rabby (Hyperliquid)", "Other"], refresh_failed=True))
    assert both == ("Hyperliquid not read for Rabby (Hyperliquid), Other. "
                    "The last Hyperliquid refresh failed; those balances may be out of date.")


@needs_node
def test_no_hyperliquid_row_can_land_in_the_stablecoins_group_by_its_name():
    coins = ["USDC", "USDH", "USDT0", "USDE", "USDHL", "usdt", "DAI", "FRAX", "UETH", "HYPE", "PURR"]
    rows = _run("hlSpotToTokenRows(data)", _resp(*[_row(c, 1.0, 1.0) for c in coins]))
    groups = {r["symbol"]: r["_group"] for r in rows}
    assert "Stablecoins" not in groups.values(), groups
    assert all(groups[c] == "Hyperliquid margin" for c in ("USDC", "USDH", "USDT0", "USDE", "USDHL", "usdt", "DAI", "FRAX"))
    assert groups["UETH"] == "ETH" and groups["HYPE"] == "Other" and groups["PURR"] == "Other"
    assert all(r["_group"] for r in rows)                    # always explicit: no fall-through to tokenGroup(symbol)
    # only USDC carries the perp-margin label
    assert [r["symbol"] for r in rows if r["display_symbol"] != r["symbol"]] == ["USDC"]


@needs_node
def test_a_polling_that_gave_up_says_so():
    assert _run("hlSpotNotice(data)", {"status": "loading", "rows": [], "gave_up": True}) == (
        "Hyperliquid balances are still loading. Reload the page to ask again.")


def test_the_page_marks_a_given_up_poll_and_never_lets_a_slow_answer_undo_an_ok():
    src = _src()
    assert "hlSpot && hlSpot.status === 'loading' && hlTries >= 8 ? { ...hlSpot, gave_up: true } : hlSpot" in src
    assert "(prev && prev.status === 'ok' && d.status !== 'ok') ? prev : d" in src
