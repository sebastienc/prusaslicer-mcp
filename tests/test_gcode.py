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


# --------------------------------------------------------------------------- more footers and edge cases


@pytest.fixture
def write_gcode(tmp_path):
    """Factory: write G-code text or bytes to a file and return its path."""

    def write(content: str | bytes) -> object:
        path = tmp_path / "x.gcode"
        path.write_bytes(content.encode() if isinstance(content, str) else content)
        return path

    return write


def footer(**lines: str) -> str:
    """A footer with only the given lines, e.g. footer(time='1h', grams='3.85')."""
    templates = {
        "mm": "; filament used [mm] = {}",
        "cm3": "; filament used [cm3] = {}",
        "grams": "; total filament used [g] = {}",
        "cost": "; total filament cost = {}",
        "time": "; estimated printing time (normal mode) = {}",
        "silent": "; estimated printing time (silent mode) = {}",
    }
    return "\n".join(templates[k].format(v) for k, v in lines.items()) + "\n"


@pytest.mark.parametrize(
    ("text", "seconds"),
    [
        ("45s", 45),
        ("5m 5s", 305),
        ("1h 5m", 3900),
        ("2d", 172800),
        ("1d 2h 3m 4s", 86400 + 2 * 3600 + 3 * 60 + 4),
    ],
)
def test_print_time_is_converted_to_seconds_for_every_unit(write_gcode, text, seconds):
    # Given a footer whose print time uses some of the units d, h, m and s
    path = write_gcode(footer(time=text))

    # When the statistics are parsed
    stats = parse_gcode_stats(path)

    # Then the text is kept and the seconds add up
    assert stats.estimated_time == text
    assert stats.estimated_time_seconds == seconds


def test_unrecognised_print_time_keeps_its_text_but_has_no_seconds(write_gcode):
    # Given a footer whose print time has no d/h/m/s units in it
    path = write_gcode(footer(time="n/a"))

    # When the statistics are parsed
    stats = parse_gcode_stats(path)

    # Then the text is reported as written, and no invented "0 seconds" is claimed
    assert stats.estimated_time == "n/a"
    assert stats.estimated_time_seconds is None


def test_silent_mode_time_alone_is_not_used(write_gcode):
    # Given a footer that only has a silent-mode estimate
    path = write_gcode(footer(silent="2h"))

    # When the statistics are parsed
    stats = parse_gcode_stats(path)

    # Then no print time is reported
    assert stats.estimated_time is None


def test_normal_mode_time_wins_over_silent_mode(write_gcode):
    # Given a footer with both estimates, silent first
    path = write_gcode(footer(silent="2h", time="1h"))

    # When the statistics are parsed
    stats = parse_gcode_stats(path)

    # Then the normal-mode estimate is reported
    assert stats.estimated_time == "1h"


def test_filament_volume_is_read(write_gcode):
    # Given a footer with a filament volume
    path = write_gcode(footer(cm3="3.11"))

    # When the statistics are parsed
    stats = parse_gcode_stats(path)

    # Then the volume is reported in cm3
    assert stats.filament_used_cm3 == 3.11


def test_whole_number_values_are_read_as_numbers(write_gcode):
    # Given a footer whose values have no decimal point
    path = write_gcode(footer(mm="5", grams="2", cost="1"))

    # When the statistics are parsed
    stats = parse_gcode_stats(path)

    # Then they are still numbers
    assert (stats.filament_used_mm, stats.filament_used_g, stats.filament_cost) == (5.0, 2.0, 1.0)


def test_g_code_without_a_footer_reports_only_the_layers_it_has(write_gcode):
    # Given G-code with two layer changes and no statistics at all
    path = write_gcode(";LAYER_CHANGE\nG1 X1\n;LAYER_CHANGE\nG1 X2\n")

    # When the statistics are parsed
    stats = parse_gcode_stats(path)

    # Then the layers are counted and every other field is unknown
    assert stats.layer_count == 2
    assert stats.model_dump(exclude={"layer_count"}) == {
        "estimated_time": None,
        "estimated_time_seconds": None,
        "filament_used_mm": None,
        "filament_used_cm3": None,
        "filament_used_g": None,
        "filament_cost": None,
    }


def test_an_empty_file_has_no_statistics_at_all(write_gcode):
    # Given an empty G-code file
    path = write_gcode("")

    # When the statistics are parsed
    stats = parse_gcode_stats(path)

    # Then every field is unknown
    assert stats.model_dump() == {key: None for key in stats.model_dump()}


def test_only_layer_change_comments_at_the_start_of_a_line_are_counted(write_gcode):
    # Given look-alikes: indented, spaced, mid-line, and a different comment, plus two real ones
    path = write_gcode(
        ";LAYER_CHANGE\n  ;LAYER_CHANGE\n; LAYER_CHANGE\nG1 X1 ;LAYER_CHANGE\n;AFTER_LAYER_CHANGE\n;LAYER_CHANGE\n"
    )

    # When the statistics are parsed
    stats = parse_gcode_stats(path)

    # Then only the two real layer changes are counted
    assert stats.layer_count == 2


def test_statistics_are_found_in_front_of_a_large_config_dump(write_gcode):
    # Given a footer followed by a 100 KB block of config comments, as PrusaSlicer appends
    config_dump = "; some_setting = " + "x" * 80 + "\n"
    path = write_gcode(";LAYER_CHANGE\n" + footer(time="1h", grams="3.85") + config_dump * 1200)

    # When the statistics are parsed
    stats = parse_gcode_stats(path)

    # Then the footer is still found
    assert (stats.estimated_time, stats.filament_used_g) == ("1h", 3.85)


def test_layers_are_counted_over_the_whole_file_while_statistics_come_from_its_end(write_gcode):
    # Given 1000 layer changes, then 600 KB of moves, then the footer: the layers are far from the footer
    moves = "G1 X1 Y1 E0.1 F1500\n" * 30000
    path = write_gcode(";LAYER_CHANGE\n" * 1000 + moves + footer(grams="9.5"))

    # When the statistics are parsed
    stats = parse_gcode_stats(path)

    # Then every layer is counted and the footer is still read
    assert stats.layer_count == 1000
    assert stats.filament_used_g == 9.5


def test_windows_line_endings_do_not_disturb_parsing(write_gcode):
    # Given a G-code file with CRLF line endings
    text = ";LAYER_CHANGE\r\n" + footer(time="1h 2m", mm="10.5", grams="1.5").replace("\n", "\r\n")
    path = write_gcode(text)

    # When the statistics are parsed
    stats = parse_gcode_stats(path)

    # Then values and layers come out clean
    assert (stats.estimated_time, stats.estimated_time_seconds) == ("1h 2m", 3720)
    assert (stats.filament_used_mm, stats.filament_used_g, stats.layer_count) == (10.5, 1.5, 1)


def test_bytes_that_are_not_text_do_not_break_parsing(write_gcode):
    # Given stray non-UTF-8 bytes in front of a valid footer
    path = write_gcode(b"; name = caf\xe9 \xff\xfe\n" + footer(grams="2.5").encode())

    # When the statistics are parsed
    stats = parse_gcode_stats(path)

    # Then the footer is still read
    assert stats.filament_used_g == 2.5
