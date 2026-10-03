import re

import pytest

from invoice_view import md_escape

SPECIAL = r"\`*_{}[]()#+-.!|<>~$&:"


@pytest.mark.parametrize("hostile", [
    "![x](http://evil.example/p.png)",
    "**bold** <b>hi</b> [a](http://x)",
    "<script>alert(1)</script>",
    "| a | b |\n| - | - |",
    "# heading\n> quote",
    "www.example.com and https://example.com",
])
def test_every_markdown_character_is_escaped(hostile):
    out = md_escape(hostile)
    # a special character is only allowed where it is preceded by a backslash that escapes it
    unescaped = re.findall(r"(?<!\\)[" + re.escape(SPECIAL) + r"]", re.sub(r"\\.", "", out))
    assert unescaped == []
    assert "http://" not in out and "https://" not in out and "<b>" not in out


def test_plain_text_survives_and_none_is_empty():
    assert md_escape(None) == ""
    assert md_escape("QF481") == "QF481"
    assert md_escape("Push back") == "Push back"
    assert md_escape(12) == "12"
