"""Unit tests for G-code statistics parsing (no PrusaSlicer needed)."""

import pytest

from prusaslicer_mcp.gcode import (
    LayerGap,
    filament_by_feature,
    find_layer_gaps,
    layer_gap_warning,
    parse_gcode_stats,
    read_layer_heights,
)

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
    assert stats.model_dump() == dict.fromkeys(stats.model_dump())


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


# --------------------------------------------------------------------------- several extruders


@pytest.mark.parametrize(
    ("line", "field", "expected"),
    [
        ("mm", "filament_used_mm", 1392.52),
        ("cm3", "filament_used_cm3", 1392.52),
    ],
)
def test_filament_used_adds_up_every_extruder(write_gcode, line, field, expected):
    # Given a footer that lists one value per extruder, as PrusaSlicer writes for multi-material prints
    path = write_gcode(footer(**{line: "1292.02, 100.50, 0.00"}))

    # When the statistics are parsed
    stats = parse_gcode_stats(path)

    # Then the figure is the total over all extruders, not just the first
    assert getattr(stats, field) == pytest.approx(expected)


def test_unused_extruders_do_not_change_the_total(write_gcode):
    # Given a five-extruder printer where only the first extruder was used
    path = write_gcode(footer(mm="22500.76, 0.00, 0.00, 0.00, 0.00", cm3="54.12, 0.00, 0.00, 0.00, 0.00"))

    # When the statistics are parsed
    stats = parse_gcode_stats(path)

    # Then the totals equal the first extruder's values
    assert (stats.filament_used_mm, stats.filament_used_cm3) == (22500.76, 54.12)


def test_total_weight_and_cost_are_not_summed_twice(write_gcode):
    # Given a footer with a per-extruder weight line as well as the total lines
    text = "; filament used [g] = 3.00, 4.00\n" + footer(grams="7.00", cost="0.30")
    path = write_gcode(text)

    # When the statistics are parsed
    stats = parse_gcode_stats(path)

    # Then the totals PrusaSlicer wrote are used as they are
    assert (stats.filament_used_g, stats.filament_cost) == (7.0, 0.3)


# --------------------------------------------------------------------------- layers that were never printed


def layers(*heights: float) -> str:
    """G-code with a layer change at each height, in the form PrusaSlicer writes."""
    return "".join(f";LAYER_CHANGE\n;Z:{h}\n;HEIGHT:0.2\nG1 X1 Y1\n" for h in heights)


def test_layer_heights_are_read_in_order_from_the_z_comments(write_gcode):
    # Given G-code with three layers, a travel move to some Z, and other comments that look similar
    path = write_gcode(layers(0.2, 0.4) + "G1 Z5 F720\n; Z:99 is not a marker\nG1 X1 ;Z:77 nor is this\n" + layers(0.6))

    # When the layer heights are read
    heights = read_layer_heights(path)

    # Then only the ;Z: markers count
    assert heights == [0.2, 0.4, 0.6]


def test_layer_heights_survive_windows_line_endings(write_gcode):
    # Given G-code with CRLF line endings
    path = write_gcode(layers(0.2, 0.4).replace("\n", "\r\n"))

    # When the layer heights are read
    heights = read_layer_heights(path)

    # Then the values are clean numbers
    assert heights == [0.2, 0.4]


def test_g_code_without_layer_markers_has_no_layer_heights(write_gcode):
    # Given G-code with no ;Z: comments
    path = write_gcode("G1 X1 Y1\n")

    # When the layer heights are read
    heights = read_layer_heights(path)

    # Then there are none
    assert heights == []


def steps(start: float, step: float, count: int) -> list[float]:
    return [round(start + step * i, 4) for i in range(count)]


@pytest.mark.parametrize(
    "heights",
    [
        steps(0.2, 0.2, 50),
        [0.3, *steps(0.45, 0.15, 40)],
        [0.2, 0.27, 0.34, 0.5, 0.7, 0.95, 1.2, 1.5, 1.8, 2.1, 2.4],
        [0.2, 0.4, 0.6, 0.2, 0.4, 0.6],
        [*steps(0.2, 0.2, 25), 0.2, 0.4, 0.6],
        [0.2, 0.4],
        [],
    ],
    ids=[
        "uniform",
        "thick-first-layer",
        "variable-layer-height",
        "objects-printed-one-after-another",
        "tall-object-then-short-object",
        "too-few-layers",
        "none",
    ],
)
def test_a_normal_print_has_no_gaps(heights):
    # Given layer heights from an ordinary print

    # When gaps are looked for
    gaps = find_layer_gaps(heights)

    # Then there are none
    assert gaps == []


def test_a_jump_far_larger_than_a_layer_is_a_gap():
    # Given a print that stops at 0.4 mm and carries on at 9 mm
    heights = [0.2, 0.4, 9.0, 9.2, 9.4]

    # When gaps are looked for
    gaps = find_layer_gaps(heights)

    # Then the empty stretch is reported
    assert gaps == [LayerGap(from_mm=0.4, to_mm=9.0)]


def test_every_gap_is_reported_in_order():
    # Given a print with two separate empty stretches
    heights = [0.2, 0.4, 9.0, 9.2, 9.4, 12.0, 12.2, 12.4]

    # When gaps are looked for
    gaps = find_layer_gaps(heights)

    # Then both are reported, earliest first
    assert gaps == [LayerGap(from_mm=0.4, to_mm=9.0), LayerGap(from_mm=9.4, to_mm=12.0)]


@pytest.mark.parametrize(
    ("jump", "is_gap"),
    [(0.6, False), (0.8, True)],
    ids=["exactly-three-layers-is-normal", "four-layers-is-a-gap"],
)
def test_the_gap_threshold_is_three_times_the_typical_layer(jump, is_gap):
    # Given 0.2 mm layers with one larger step
    heights = [*steps(0.2, 0.2, 5), 1.0 + jump, 1.2 + jump, 1.4 + jump]

    # When gaps are looked for
    gaps = find_layer_gaps(heights)

    # Then a step of three layers is allowed and anything bigger is a gap
    assert bool(gaps) is is_gap


@pytest.mark.parametrize(
    ("jump", "is_gap"),
    [(0.9, False), (1.2, True)],
    ids=["exactly-three-thick-layers-is-normal", "four-thick-layers-is-a-gap"],
)
def test_the_gap_threshold_scales_with_the_layer_height(jump, is_gap):
    # Given 0.3 mm layers, where three layers (0.9 mm) is above the 0.6 mm absolute minimum, with one larger step
    heights = [*steps(0.3, 0.3, 5), 1.5 + jump, 1.8 + jump, 2.1 + jump]

    # When gaps are looked for
    gaps = find_layer_gaps(heights)

    # Then three layers is still allowed and anything bigger is a gap
    assert bool(gaps) is is_gap


def test_floating_point_error_does_not_turn_three_layers_into_a_gap():
    # Given heights built by adding up layer thicknesses, as a slicer does, so a step of exactly three layers
    # comes out as 0.6000000000000001
    heights, z = [], 0.0
    for thickness in [0.2, 0.2, 0.2, 0.2, 0.2, 0.6, 0.2, 0.2]:
        z += thickness
        heights.append(z)

    # When gaps are looked for
    gaps = find_layer_gaps(heights)

    # Then the rounding error is tolerated
    assert gaps == []


def test_a_small_absolute_step_is_never_a_gap_even_on_very_fine_layers():
    # Given 0.05 mm layers with one 0.5 mm step, which is ten layers but still only half a millimetre
    heights = [*steps(0.05, 0.05, 6), 0.8, 0.85, 0.9]

    # When gaps are looked for
    gaps = find_layer_gaps(heights)

    # Then it is not worth a warning
    assert gaps == []


def test_no_warning_when_nothing_is_missing(write_gcode):
    # Given G-code for a print with no empty stretch
    path = write_gcode(layers(*steps(0.2, 0.2, 20)))

    # When the gap warning is built
    warning = layer_gap_warning(path)

    # Then there is none
    assert warning is None


def test_the_warning_says_how_much_is_missing_and_where_it_starts(write_gcode):
    # Given G-code with two empty stretches: 0.4 to 9 mm (8.6 mm) and 9.4 to 12 mm (2.6 mm)
    path = write_gcode(layers(0.2, 0.4, 9.0, 9.2, 9.4, 12.0, 12.2, 12.4))

    # When the gap warning is built
    warning = layer_gap_warning(path)

    # Then it gives the total, the number of gaps, the first one, and what to do about it
    assert warning is not None
    assert "11.2 mm of the 12.4 mm" in warning
    assert "2 gaps" in warning
    assert "between z 0.4 and 9 mm" in warning


def test_the_warning_uses_the_singular_for_one_gap(write_gcode):
    # Given G-code with a single empty stretch
    path = write_gcode(layers(0.2, 0.4, 9.0, 9.2, 9.4))

    # When the gap warning is built
    warning = layer_gap_warning(path)

    # Then it says "1 gap", not "1 gaps"
    assert warning is not None
    assert "1 gap," in warning


def test_the_warning_suggests_changing_the_orientation_before_repairing_the_mesh(write_gcode):
    # Given G-code with an empty stretch, as a Y-up scan lying on its side produces
    path = write_gcode(layers(0.2, 0.4, 9.0, 9.2, 9.4))

    # When the gap warning is built
    warning = layer_gap_warning(path)

    # Then orientation comes first, because that was the real cause for a scan, and repair second
    assert warning is not None
    assert "Y-up" in warning
    assert warning.index("rotate") < warning.index("repair")


# --------------------------------------------------------------------------- filament per feature


def feature_filament(tmp_path, text: str) -> dict[str, float]:
    path = tmp_path / "out.gcode"
    path.write_text(text)
    return filament_by_feature(path)


def test_filament_is_summed_per_feature_with_relative_extrusion(tmp_path):
    # Given a print with perimeters and support, using relative extrusion
    text = "M83\n;TYPE:Perimeter\nG1 X10 Y0 E1.5\nG1 X10 Y10 E1.5\n;TYPE:Support material\nG1 X0 Y10 E2.0\n"

    # When the filament per feature is read
    totals = feature_filament(tmp_path, text)

    # Then each feature has what was extruded under it
    assert totals == {"Perimeter": pytest.approx(3.0), "Support material": pytest.approx(2.0)}


def test_travel_moves_and_retractions_are_not_extrusion(tmp_path):
    # Given relative extrusion with a retraction, a travel, and the un-retraction (none of which goes anywhere with E)
    text = "M83\n;TYPE:Perimeter\nG1 X10 Y0 E1.0\nG1 E-0.8 F2100\nG1 X50 Y50 F9000\nG1 E0.8 F2100\nG1 X60 Y50 E1.0\n"

    # When the filament is read
    totals = feature_filament(tmp_path, text)

    # Then only the two extruding moves count: 2.0, not 2.8
    assert totals == {"Perimeter": pytest.approx(2.0)}


def test_windows_line_endings_do_not_disturb_the_filament_count(tmp_path):
    # Given a print written with CRLF line endings, with a feature name that would keep a stray \r
    path = tmp_path / "crlf.gcode"
    path.write_bytes(b"M83\r\n;TYPE:Perimeter\r\nG1 X10 Y0 E2.5\r\n;TYPE:Support material\r\nG1 X20 Y0 E1.0\r\n")

    # When the filament is counted per feature
    totals = filament_by_feature(path)

    # Then the names are clean and the amounts right
    assert totals == {"Perimeter": 2.5, "Support material": 1.0}


def test_arcs_are_counted_as_extrusion(tmp_path):
    # Given a print whose perimeter is an arc (arc fitting writes G2 and G3)
    text = "M83\n;TYPE:External perimeter\nG2 X10 Y0 I5 J0 E3.0\nG3 X0 Y0 I-5 J0 E3.0\n"

    # When the filament is read
    totals = feature_filament(tmp_path, text)

    # Then both arcs count
    assert totals == {"External perimeter": pytest.approx(6.0)}


def test_absolute_extrusion_counts_what_the_extruder_advances_and_not_an_unretraction(tmp_path):
    # Given absolute extrusion: an extrusion, a retraction back, then the same distance forward again, then more
    text = "M82\nG92 E0\n;TYPE:Perimeter\nG1 X10 Y0 E2.0\nG1 E1.2\nG1 X30 Y0\nG1 E2.0\nG1 X40 Y0 E3.0\n"

    # When the filament is read
    totals = feature_filament(tmp_path, text)

    # Then 2.0 for the first move and 1.0 for the last: the un-retraction to 2.0 adds nothing
    assert totals == {"Perimeter": pytest.approx(3.0)}


def test_a_reset_of_the_extruder_position_starts_the_count_again(tmp_path):
    # Given absolute extrusion with the extruder position reset to zero between two layers
    text = "M82\n;TYPE:Perimeter\nG1 X10 Y0 E5.0\nG92 E0\nG1 X20 Y0 E4.0\n"

    # When the filament is read
    totals = feature_filament(tmp_path, text)

    # Then both moves count in full: 5.0 and 4.0
    assert totals == {"Perimeter": pytest.approx(9.0)}


def test_what_is_printed_before_the_first_feature_is_left_out(tmp_path):
    # Given a purge line in the start G-code, before any ;TYPE:
    text = "M83\nG1 X5 Y0 E9.0\n;TYPE:Perimeter\nG1 X10 Y0 E1.0\n"

    # When the filament is read
    totals = feature_filament(tmp_path, text)

    # Then only the print itself is counted
    assert totals == {"Perimeter": pytest.approx(1.0)}


def test_a_feature_name_is_kept_whole(tmp_path):
    # Given support and its interface layers, which have similar names
    text = "M83\n;TYPE:Support material\nG1 X1 Y0 E1.0\n;TYPE:Support material interface\nG1 X2 Y0 E2.0\n"

    # When the filament is read
    totals = feature_filament(tmp_path, text)

    # Then they stay separate
    assert totals == {"Support material": pytest.approx(1.0), "Support material interface": pytest.approx(2.0)}


def test_comments_after_a_command_are_ignored(tmp_path):
    # Given a move that ends with a comment mentioning E
    text = "M83\n;TYPE:Perimeter\nG1 X10 Y0 E1.0 ; E9 is only a comment\n"

    # When the filament is read
    totals = feature_filament(tmp_path, text)

    # Then the comment is not read as the extrusion
    assert totals == {"Perimeter": pytest.approx(1.0)}


def test_a_wipe_that_retracts_while_moving_does_not_take_filament_away(tmp_path):
    # Given a perimeter followed by a wipe: a move that travels and retracts at the same time
    text = "M83\n;TYPE:Perimeter\nG1 X10 Y0 E2.0\nG1 X12 Y0 E-0.4\nG1 X20 Y0 E2.0\n"

    # When the filament is read
    totals = feature_filament(tmp_path, text)

    # Then the wipe is not extrusion and does not subtract: 4.0
    assert totals == {"Perimeter": pytest.approx(4.0)}


def test_a_switch_back_to_absolute_extrusion_is_followed(tmp_path):
    # Given a file that starts in relative mode and switches to absolute extrusion part way
    text = "M83\n;TYPE:Perimeter\nG1 X10 Y0 E1.0\nM82\nG92 E0\nG1 X20 Y0 E2.0\nG1 X30 Y0 E5.0\n"

    # When the filament is read
    totals = feature_filament(tmp_path, text)

    # Then after the switch the extruder position is what counts: 1.0, then 2.0 and 3.0 (not 2.0 and 5.0)
    assert totals == {"Perimeter": pytest.approx(6.0)}
