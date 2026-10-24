"""Landing 64 (Oct 23, Glenn "A,a"): a disabled button looks disabled on every page.

static/style.css: .tv-btn:disabled is faded to 0.45 with a "not allowed"
cursor, and the .tv-btn hover rules skip :disabled, so a disabled button shows
no hover change (before, a disabled plain button still changed colour under the
mouse). The skip sits inside :where(), which adds no weight: a plain
:not(:disabled) would outrank .tv-btn.primary and turn an enabled gold button
dark under the mouse.
The Spot cards' own rule (Landing 60) is gone, and the Perps helper prpBtn no
longer dims inline (it was 0.5 with a normal cursor), so every disabled
.tv-btn looks the same. Buttons that set their own opacity inline keep it.

A browser sweep of every page against main is in the landing record; these
read the source files only.
"""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NL = chr(10)


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
        return fh.read()


def _rules(css):
    """The stylesheet without its comments, so a comment that names a selector is not read as a rule."""
    return re.sub("/[*].*?[*]/", "", css, flags=re.S)


def test_one_disabled_look_for_every_tv_btn():
    css = _read("static/style.css")
    assert css.count(".tv-btn:disabled { opacity: 0.45; cursor: not-allowed; }") == 1
    assert ".spot-card .tv-btn:disabled" not in css                  # the Spot cards' own rule is gone
    other = [m for m in re.findall("[.]tv-btn[^{,]*:disabled[^{,]*[{]", _rules(css)) if ":not(:disabled)" not in m]
    assert other == [".tv-btn:disabled {"], other                    # no second, scoped disabled rule


def test_hover_rules_skip_disabled_buttons():
    css = _read("static/style.css")
    for rule in (".tv-btn:hover:where(:not(:disabled)) { background: var(--panel2); }",
                 ".tv-btn.primary:hover:where(:not(:disabled)) { opacity: 0.9; }",
                 ".tv-btn.danger:hover:where(:not(:disabled)) { background: var(--fail-soft); }"):
        assert css.count(rule) == 1, rule
    plain = [m for m in re.findall("[.]tv-btn[.a-z-]*:hover[^{]*[{]", _rules(css)) if ":where(:not(:disabled))" not in m]
    assert plain == [], plain                                        # every .tv-btn hover rule skips disabled buttons, with no added weight
    assert css.index(".tv-btn:hover:where(") < css.index(".tv-btn.primary {")   # so .tv-btn.primary keeps its gold under the mouse


def test_perps_buttons_take_the_stylesheet_look():
    js = _read("static/perps.js")
    start = js.index("function prpBtn(disabled, base) {")
    helper = js[start:js.index(NL + "}" + NL, start)]
    assert "return Object.assign({}, base || {});" in helper
    assert "opacity" not in helper and "cursor" not in helper
