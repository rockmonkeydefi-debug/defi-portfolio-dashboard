"""Landing 29 wiring: the Add custom token form checks the chosen chain's
address format, and its rules mirror the server's (static/portfolio2.js
source read as text; behaviour is covered by the headless browser check)."""
import pathlib
import re
import threading

_orig_start = threading.Thread.start
threading.Thread.start = lambda self, *a, **k: None
try:
    import web_portfolio as wp
finally:
    threading.Thread.start = _orig_start

SRC = (pathlib.Path(__file__).resolve().parent.parent / "static" / "portfolio2.js").read_text(encoding="utf-8")


def _rules_block():
    m = re.search(r"const CT_ADDRESS_RULES = \{(.*?)\n\};", SRC, re.S)
    assert m, "CT_ADDRESS_RULES not found"
    return m.group(1)


def _js_regex(fmt):
    m = re.search(fmt + r":\s*\{\s*re:\s*/(.+?)/,", _rules_block())
    assert m, f"no rule for {fmt}"
    return m.group(1)


def test_every_server_format_has_a_form_rule():
    formats = {cfg.get("address_format", "evm") for cfg in wp.CUSTOM_TOKEN_CHAINS.values()}
    assert formats == {"evm", "base58"}
    for fmt in formats:
        _js_regex(fmt)


def test_base58_rule_matches_the_server_pattern():
    assert _js_regex("base58") == wp._SPOT_BASE58_ADDRESS_RE.pattern


def test_evm_rule_accepts_what_the_server_accepts():
    js = re.compile(_js_regex("evm"))
    good = "0xA1FBB38bF486b97108aA87E92008187CA06998f6"
    for addr, ok in ((good, True), (good.lower(), True), ("0x123", False), ("A1FBB38bF486b97108aA87E92008187CA06998f6xx", False)):
        assert bool(js.match(addr)) == ok == bool(wp.is_valid_address(addr)), addr


def test_submit_and_field_use_the_chain_rule():
    body = SRC[SRC.index("function AddCustomToken"):SRC.index("function TokenHoldings")]
    assert "const rule = ctAddressRule(chains, chain);" in body
    assert "if (!rule.re.test(addr)) { setErr(rule.error); return; }" in body
    assert "/^0x[0-9a-fA-F]{40}$/.test(addr)" not in body          # no hardcoded EVM-only check left
    assert "label={ctAddressRule(chains, chain).label}" in body
    assert "placeholder={ctAddressRule(chains, chain).placeholder}" in body


def test_unknown_or_missing_format_falls_back_to_evm():
    fn = SRC[SRC.index("function ctAddressRule"):SRC.index("function AddCustomToken")]
    assert "(c && c.format) || 'evm'" in fn and "|| CT_ADDRESS_RULES.evm" in fn
