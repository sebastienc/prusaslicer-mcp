"""Unit tests for G-code statistics parsing (no PrusaSlicer needed)."""

import pytest

from prusaslicer_mcp.gcode import parse_gcode_stats

SAMPLE = """;LAYER_CHANGE
G1 X1 Y1
;LAYER_CHANGE
G1 X2 Y2
; filament used [mm] = 1292.02
; filament used [cm3] = 3.11
; total filament used [g] = 3.85
; total filament cost = 0.14
; estimated printing time (normal mode) = 1h 21m 49s
"""


@pytest.fixture
def sliced_gcode(tmp_path):
    """A text G-code file with two layers and PrusaSlicer's footer comments."""
    path = tmp_path / "a.gcode"
    path.write_text(SAMPLE)
    return path


@pytest.mark.parametrize(
    ("field", "expected"),
    [
        ("estimated_time", "1h 21m 49s"),
        ("estimated_time_seconds", 3600 + 21 * 60 + 49),
        ("filament_used_mm", 1292.02),
        ("filament_used_g", 3.85),
        ("filament_cost", 0.14),
        ("layer_count", 2),
    ],
)
def test_statistic_is_read_from_the_footer(sliced_gcode, field, expected):
    # Given a text G-code file with PrusaSlicer's footer comments (the sliced_gcode fixture)

    # When its statistics are parsed
    stats = parse_gcode_stats(sliced_gcode)

    # Then the field holds the value written in the footer
    assert getattr(stats, field) == expected


def test_binary_gcode_is_rejected(tmp_path):
    # Given a binary G-code file, which starts with the magic bytes "GCDE"
    path = tmp_path / "a.bgcode"
    path.write_bytes(b"GCDE" + b"\0" * 16)

    # When / Then parsing it is refused, because the statistics cannot be read from it
    with pytest.raises(ValueError, match="Binary G-code"):
        parse_gcode_stats(path)
