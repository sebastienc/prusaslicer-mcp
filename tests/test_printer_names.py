"""Unit tests for printer display-name cleanup (no PrusaSlicer needed)."""

import pytest

from prusaslicer_mcp.server import _display_name


@pytest.mark.parametrize(
    ("stored", "shown"),
    [
        # The vendor bundle stores model names GUI-escaped: "&&" renders as a literal "&".
        ("Original Prusa MINI && MINI+ Input Shaper", "Original Prusa MINI & MINI+ Input Shaper"),
        ("A && B && C", "A & B & C"),
    ],
    ids=["wx-escaped-ampersand", "every-occurrence"],
)
def test_wx_escaped_ampersand_is_unescaped(stored, shown):
    # Given a model name as stored in the vendor bundle

    # When it is prepared for display
    result = _display_name(stored)

    # Then each "&&" has become a single "&"
    assert result == shown


@pytest.mark.parametrize(
    "name",
    ["Original Prusa MINI & MINI+", "Original Prusa MK4S"],
    ids=["single-ampersand", "plain-name"],
)
def test_name_without_a_doubled_ampersand_is_unchanged(name):
    # Given a name with no "&&" in it

    # When it is prepared for display
    result = _display_name(name)

    # Then it comes back exactly as it was
    assert result == name
