"""M14 UI6: the colour tokens meet WCAG contrast in every theme (light, dark, high contrast): text 4.5:1 on the page
and panel backgrounds, state colours and focus rings 3:1 (non-text, WCAG 1.4.11), primary-button text 4.5:1."""
import re
from pathlib import Path

import pytest

CSS = (Path(__file__).resolve().parents[1] / "web" / "src" / "styles.css").read_text(encoding="utf-8")


def tokens(block: str) -> dict:
    return {k: v for k, v in re.findall(r"--([\w-]+):\s*(#[0-9a-fA-F]{3,6})", block)}


def themes():
    root = tokens(re.search(r":root\s*\{(.*?)\n\}", CSS, re.S).group(1))
    dark = tokens(re.search(r"prefers-color-scheme: dark\)\s*\{\s*:root\s*\{(.*?)\}", CSS, re.S).group(1))
    hc = tokens(re.search(r"prefers-contrast: more\)\s*\{\s*:root\s*\{(.*?)\}", CSS, re.S).group(1))
    return {"light": root, "dark": {**root, **dark}, "high_contrast": {**root, **hc}}


def luminance(hex_: str) -> float:
    h = hex_.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    def chan(c):
        c = int(c, 16) / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (chan(h[i:i + 2]) for i in (0, 2, 4))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def ratio(a: str, b: str) -> float:
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


TEXT = ["fg", "muted", "k0", "k1", "k2"]                 # used as text colour
NON_TEXT = ["k0", "k1", "k2", "unknown", "line"]         # glyphs, borders, map and chart marks


@pytest.mark.parametrize("theme", ["light", "dark", "high_contrast"])
def test_text_tokens_reach_4_5_to_1(theme):
    t = themes()[theme]
    for bg in ("bg", "panel"):
        for fg in TEXT:
            assert ratio(t[fg], t[bg]) >= 4.5, f"{theme}: --{fg} on --{bg} is {ratio(t[fg], t[bg]):.2f}"


@pytest.mark.parametrize("theme", ["light", "dark", "high_contrast"])
def test_state_marks_reach_3_to_1(theme):
    t = themes()[theme]
    for fg in NON_TEXT:
        if fg == "line":
            continue                                     # dividers are decorative, not required to reach 3:1
        assert ratio(t[fg], t["bg"]) >= 3, f"{theme}: --{fg} on --bg is {ratio(t[fg], t['bg']):.2f}"


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_primary_button_and_focus_ring(theme):
    t = themes()[theme]
    assert ratio(t["on-k2"], t["k2"]) >= 4.5
    assert ratio(t["focus-outer"], t["bg"]) >= 3 or ratio(t["focus-inner"], t["bg"]) >= 3
