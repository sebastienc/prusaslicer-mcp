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


def test_parse_stats(tmp_path):
    p = tmp_path / "a.gcode"
    p.write_text(SAMPLE)
    s = parse_gcode_stats(p)
    assert s.estimated_time == "1h 21m 49s"
    assert s.estimated_time_seconds == 3600 + 21 * 60 + 49
    assert s.filament_used_mm == 1292.02
    assert s.filament_used_g == 3.85
    assert s.filament_cost == 0.14
    assert s.layer_count == 2


def test_binary_gcode_rejected(tmp_path):
    p = tmp_path / "a.bgcode"
    p.write_bytes(b"GCDE" + b"\0" * 16)
    with pytest.raises(ValueError):
        parse_gcode_stats(p)
