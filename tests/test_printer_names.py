"""Unit tests for printer display-name cleanup (no PrusaSlicer needed)."""

from prusaslicer_mcp.server import _display_name


def test_collapses_wx_escaped_ampersand():
    # The vendor bundle stores model names GUI-escaped: "&&" renders as a literal "&".
    assert _display_name("Original Prusa MINI && MINI+ Input Shaper") == "Original Prusa MINI & MINI+ Input Shaper"


def test_collapses_every_occurrence():
    assert _display_name("A && B && C") == "A & B & C"


def test_leaves_single_ampersand_and_plain_names_alone():
    assert _display_name("Original Prusa MINI & MINI+") == "Original Prusa MINI & MINI+"
    assert _display_name("Original Prusa MK4S") == "Original Prusa MK4S"
