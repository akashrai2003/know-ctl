"""Unit tests for YAML injection prevention in obsidian.py."""
from __future__ import annotations

import pytest

from socialgraph.knowledge.obsidian import _yaml_str


@pytest.mark.parametrize("raw, expected", [
    # Newlines must be escaped
    ("hello\nworld", "hello\\nworld"),
    # Carriage returns
    ("hello\rworld", "hello\\rworld"),
    # Backslash
    ("path\\to\\file", "path\\\\to\\\\file"),
    # Double-quote
    ('say "hello"', 'say \\"hello\\"'),
    # Tab
    ("col1\tcol2", "col1\\tcol2"),
    # NUL byte
    ("null\x00byte", "null\\0byte"),
    # U+2028 LINE SEPARATOR
    ("line\u2028sep", "line\\Lsep"),
    # U+2029 PARAGRAPH SEPARATOR
    ("para\u2029sep", "para\\Psep"),
    # Normal text passes through unchanged
    ("normal text 123", "normal text 123"),
    # None returns empty string
    (None, ""),
    # Empty string
    ("", ""),
    # Unicode letters pass through
    ("こんにちは", "こんにちは"),
])
def test_yaml_str(raw, expected):
    assert _yaml_str(raw) == expected


def test_yaml_str_no_injection():
    """Adversarial author name cannot inject a new YAML key."""
    adversarial = 'Evil\nauthor: injected\nfoo: bar'
    result = _yaml_str(adversarial)
    # Must not contain a literal newline
    assert "\n" not in result
    # The embedded colon should still be present (not the YAML key injection)
    assert "author" in result
