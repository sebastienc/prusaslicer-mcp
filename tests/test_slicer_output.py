"""Unit tests for turning PrusaSlicer's stdout into warnings (no PrusaSlicer needed).

PrusaSlicer reports a problem as a block: a line containing "warning", then a variable number of plain lines
(more detail, the object name, advice), up to the next numbered progress line or the final export message.
"""

import pytest

from prusaslicer_mcp.slicer_output import parse_warnings

# What PrusaSlicer 2.9.7 printed for a scanned mesh with holes in it (paths shortened).
REAL_OUTPUT = """\
10 => Processing triangulated mesh
20 => Generating perimeters
90 => Exporting G-code to /tmp/statue.gcode
print warning: Empty layer between 0.4 and 9.
Empty layer between 9.2 and 11.4.
Empty layer between 12 and 19.2.
(Some lines not shown)

Object name: StatueDemo_mesh.stl

Make sure the object is printable. This is usually caused by negligibly small extrusions or by a faulty model.
Slicing result exported to /tmp/statue.gcode
"""


def test_a_warning_block_is_kept_whole_as_one_warning():
    # Given PrusaSlicer's real output for a mesh with holes
    stdout = REAL_OUTPUT

    # When the warnings are read from it
    warnings = parse_warnings(stdout)

    # Then there is one warning, with every gap, the object name and the advice
    assert len(warnings) == 1
    assert "print warning: Empty layer between 0.4 and 9." in warnings[0]
    assert "Empty layer between 12 and 19.2." in warnings[0]
    assert "Object name: StatueDemo_mesh.stl" in warnings[0]
    assert "Make sure the object is printable." in warnings[0]


def test_the_warning_stops_before_the_final_export_message():
    # Given the same real output

    # When the warnings are read from it
    (warning,) = parse_warnings(REAL_OUTPUT)

    # Then the success line that follows is not swallowed into the warning
    assert "Slicing result exported" not in warning


def test_blank_lines_inside_a_warning_are_dropped_and_lines_are_trimmed():
    # Given a warning whose lines are padded and separated by blank lines
    stdout = "  warning: first  \n\n   second line   \n10 => next\n"

    # When the warnings are read from it
    warnings = parse_warnings(stdout)

    # Then the lines are joined one per line with no blanks
    assert warnings == ["warning: first\nsecond line"]


def test_a_single_line_warning_ends_at_the_next_progress_line():
    # Given a one-line warning between progress lines
    stdout = "10 => Processing\nWarning: thin walls\n20 => Done\n"

    # When the warnings are read from it
    warnings = parse_warnings(stdout)

    # Then only that line is the warning
    assert warnings == ["Warning: thin walls"]


def test_each_warning_block_is_reported_separately():
    # Given two warning blocks with progress between them
    stdout = "warning: one\ndetail of one\n20 => Working\nWARNING: two\n"

    # When the warnings are read from it
    warnings = parse_warnings(stdout)

    # Then they are two warnings, and the match is case-insensitive
    assert warnings == ["warning: one\ndetail of one", "WARNING: two"]


@pytest.mark.parametrize(
    "stdout",
    ["", "\n\n", "10 => Processing\n20 => Done\nSlicing result exported to /tmp/x.gcode\n"],
    ids=["empty", "blank", "clean-run"],
)
def test_output_without_a_warning_gives_none(stdout):
    # Given PrusaSlicer output that mentions no warning

    # When the warnings are read from it
    warnings = parse_warnings(stdout)

    # Then there are none
    assert warnings == []


def test_two_warnings_printed_back_to_back_stay_separate():
    # Given two warnings with nothing but their own detail lines between them
    stdout = "warning: one\ndetail of one\nwarning: two\ndetail of two\n"

    # When the warnings are read from it
    warnings = parse_warnings(stdout)

    # Then each keeps its own detail
    assert warnings == ["warning: one\ndetail of one", "warning: two\ndetail of two"]
