"""Unit tests for reading toolpaths from G-code and drawing them (synthetic G-code; no PrusaSlicer needed)."""

from itertools import pairwise

import numpy as np
import pytest
from gcode_builders import layer, square
from PIL import Image

from prusaslicer_mcp.preview_gcode import (
    FEATURE_COLORS,
    INK,
    UNKNOWN_COLOR,
    iter_extrusions,
    render_layer,
    render_profile,
    scan_gcode,
)

SIZE = 400


@pytest.fixture
def write(tmp_path):
    def make(text: str):
        path = tmp_path / "print.gcode"
        path.write_text(text)
        return path

    return make


def colour_mask(image: Image.Image, colour: tuple[int, int, int]) -> np.ndarray:
    return np.all(np.asarray(image) == np.array(colour, dtype=np.uint8), axis=2)


def ink_rows(image: Image.Image, columns: slice) -> np.ndarray:
    """Rows containing printed ink (not grid lines or labels) within some columns."""
    return np.nonzero(colour_mask(image, INK)[:, columns].any(axis=1))[0]


def has_colour(image: Image.Image, colour: tuple[int, int, int]) -> bool:
    """True when the colour covers a real stretch of toolpath, not just a small legend swatch."""
    return int(colour_mask(image, colour).sum()) > 300


# --------------------------------------------------------------------------- reading extruding moves


def test_only_moves_that_extrude_are_returned(write):
    # Given a layer with a travel move, an extruding move, a retraction and an unretraction
    text = "M83\n;LAYER_CHANGE\n;Z:0.2\n;TYPE:Perimeter\nG1 X0 Y0 F9000\nG1 X10 Y0 E0.5\nG1 E-0.8\nG1 X20 Y0 F9000\nG1 E0.8\n"

    # When the extruding moves are read
    moves = list(iter_extrusions(write(text)))

    # Then only the one move that extrudes while moving remains
    assert len(moves) == 1
    assert (moves[0].x0, moves[0].y0, moves[0].x1, moves[0].y1) == (0, 0, 10, 0)


def test_a_move_carries_its_layer_height_and_feature(write):
    # Given two layers with different features
    text = (
        "M83\n" + layer(0.2, ("External perimeter", [(0, 0, 10, 0)])) + layer(0.4, ("Internal infill", [(0, 0, 0, 10)]))
    )

    # When the moves are read
    first, second = list(iter_extrusions(write(text)))

    # Then each knows its layer number (from 0), height and feature
    assert (first.layer, first.z, first.feature) == (0, 0.2, "External perimeter")
    assert (second.layer, second.z, second.feature) == (1, 0.4, "Internal infill")


def test_the_purge_line_before_the_first_layer_is_not_part_of_the_print(write):
    # Given an extruding line in the start G-code, before any layer change
    text = "M83\nG1 X0 Y0 F9000\nG1 X100 Y0 E5\n" + layer(0.2, ("Perimeter", [(10, 10, 20, 10)]))

    # When the moves are read
    moves = list(iter_extrusions(write(text)))

    # Then only the print's own move is returned
    assert [(m.x0, m.x1) for m in moves] == [(10, 20)]


def test_absolute_extrusion_counts_a_move_when_the_extruder_advances(write):
    # Given absolute extrusion (M82): E is the total fed so far, and G92 resets it
    text = (
        "M82\n;LAYER_CHANGE\n;Z:0.2\n;TYPE:Perimeter\n"
        "G92 E0\nG1 X0 Y0 F9000\nG1 X10 Y0 E1.0\nG1 X20 Y0 E2.0\nG1 X30 Y0 E1.2\nG1 X40 Y0 F9000\n"
        "G92 E0\nG1 X50 Y0 E0.5\n"
    )

    # When the moves are read
    moves = list(iter_extrusions(write(text)))

    # Then the two advancing moves and the one after the reset count; the retraction and the travel do not
    assert [(m.x0, m.x1) for m in moves] == [(0, 10), (10, 20), (40, 50)]


ARC_HEAD = "M83\n;LAYER_CHANGE\n;Z:0.2\n;TYPE:Perimeter\n"


def points_of(moves):
    """Every end point of a run of moves, the first move's start included; the moves must join up end to end."""
    for before, after in pairwise(moves):
        assert (after.x0, after.y0) == (before.x1, before.y1)
    return [(moves[0].x0, moves[0].y0), *[(m.x1, m.y1) for m in moves]]


def longest_piece(points):
    return max(np.hypot(x1 - x0, y1 - y0) for (x0, y0), (x1, y1) in pairwise(points))


def length_of(points):
    return sum(np.hypot(x1 - x0, y1 - y0) for (x0, y0), (x1, y1) in pairwise(points))


@pytest.mark.parametrize(
    ("arc", "start"),
    [
        pytest.param("G3 X0 Y10 I-10 J0 E1.5", "G1 X10 Y0 F9000", id="counter-clockwise from the right to the top"),
        pytest.param("G2 X10 Y0 I0 J-10 E1.5", "G1 X0 Y10 F9000", id="clockwise from the top to the right"),
    ],
)
def test_an_arc_is_drawn_as_the_short_way_round_a_quarter_circle(write, arc, start):
    # Given a quarter circle of radius 10 around the origin, printed as one arc move
    text = ARC_HEAD + f"{start}\n{arc}\n"

    # When the extruding moves are read
    points = points_of(list(iter_extrusions(write(text))))

    # Then the path runs between the arc's end points through the middle of the quarter, never off the circle
    assert points[0] == pytest.approx((10, 0) if "G3" in arc else (0, 10))
    assert points[-1] == pytest.approx((0, 10) if "G3" in arc else (10, 0))
    assert len(points) > 4
    assert all(np.hypot(x, y) == pytest.approx(10, abs=0.01) for x, y in points)
    assert any(np.hypot(x - 7.07, y - 7.07) < 1 for x, y in points)  # the pieces are about 1.8 mm long
    assert all(x > -0.01 and y > -0.01 for x, y in points)
    assert longest_piece(points) < 1.5  # a coarse arc would show as a polygon
    assert length_of(points) == pytest.approx(10 * np.pi / 2, abs=0.1)  # a quarter of the circumference, not a lap more


@pytest.mark.parametrize(
    ("start", "arc", "opposite"),
    [
        pytest.param(
            "G1 X10 Y0 F9000", "G2 X0 Y10 I-10 J0 E4.5", (-7.07, -7.07), id="clockwise from the right to the top"
        ),
        pytest.param(
            "G1 X0 Y10 F9000",
            "G3 X10 Y0 I0 J-10 E4.5",
            (-7.07, -7.07),
            id="counter-clockwise from the top to the right",
        ),
    ],
)
def test_an_arc_goes_the_long_way_round_when_its_direction_says_so(write, start, arc, opposite):
    # Given the same quarter-circle end points as before, but travelled in the other direction (three quarters)
    text = ARC_HEAD + f"{start}\n{arc}\n"

    # When the extruding moves are read
    points = points_of(list(iter_extrusions(write(text))))

    # Then the path swings round the far side of the circle instead of cutting across the short way
    assert any(np.hypot(x - opposite[0], y - opposite[1]) < 1 for x, y in points)
    assert any(x < -9 for x, _ in points)
    assert length_of(points) == pytest.approx(10 * np.pi * 1.5, abs=0.3)  # three quarters of the circumference
    assert all(np.hypot(x, y) == pytest.approx(10, abs=0.01) for x, y in points)


@pytest.mark.parametrize(
    ("start", "arc", "passes_through"),
    [
        pytest.param("G1 X10 Y0 F9000", "G3 X-10 Y0 I-10 E3.0", (0, 10), id="J left out"),
        pytest.param("G1 X0 Y10 F9000", "G2 X0 Y-10 J-10 E3.0", (10, 0), id="I left out"),
    ],
)
def test_a_centre_offset_that_is_left_out_is_zero(write, start, arc, passes_through):
    # Given a half circle of radius 10 around the origin whose arc names only one of I and J
    text = ARC_HEAD + f"{start}\n{arc}\n"

    # When the extruding moves are read
    points = points_of(list(iter_extrusions(write(text))))

    # Then the missing offset counts as 0: the path stays on the circle and passes through the expected side
    assert all(np.hypot(x, y) == pytest.approx(10, abs=0.01) for x, y in points)
    assert any(np.hypot(x - passes_through[0], y - passes_through[1]) < 1 for x, y in points)


@pytest.mark.parametrize("command", ["G2", "G3"])
def test_an_arc_that_ends_where_it_starts_is_a_full_circle(write, command):
    # Given a circle of radius 5 around (20, 20), printed as one arc from its rightmost point back to itself
    text = ARC_HEAD + f"G1 X25 Y20 F9000\n{command} X25 Y20 I-5 J0 E3.0\n"

    # When the file is scanned
    scan = scan_gcode(write(text))

    # Then the printed extent covers the whole circle, not nothing
    assert scan.x_range == pytest.approx((15, 25), abs=0.01)
    assert scan.y_range == pytest.approx((15, 25), abs=0.01)
    assert scan.arcs_skipped == 0


def test_an_arc_keeps_its_layer_and_feature(write):
    # Given an arc printed as an external perimeter on the second layer
    text = (
        ARC_HEAD
        + "G1 X0 Y0 F9000\nG1 X10 Y0 E0.5\n"
        + ";LAYER_CHANGE\n;Z:0.4\n;TYPE:External perimeter\nG1 X10 Y0 F9000\nG3 X0 Y10 I-10 J0 E1.5\n"
    )

    # When the extruding moves are read
    moves = list(iter_extrusions(write(text)))

    # Then every piece of the arc belongs to that layer and feature, and the move after it starts at the arc's end
    arc = moves[1:]
    assert {(m.layer, m.z, m.feature) for m in arc} == {(1, 0.4, "External perimeter")}
    assert (arc[-1].x1, arc[-1].y1) == (0, 10)


def test_a_layer_printed_as_arcs_is_drawn(write):
    # Given a layer whose perimeter is two half circles of radius 15 (arc fitting), and nothing else
    text = (
        "M83\n;LAYER_CHANGE\n;Z:0.2\n;TYPE:External perimeter\nG1 X65 Y50 F9000\n"
        "G3 X35 Y50 I-15 J0 E5.0\nG3 X65 Y50 I15 J0 E5.0\n"
    )
    path = write(text)

    # When the layer is drawn
    image = render_layer(path, scan_gcode(path), 1, SIZE)

    # Then the perimeter is on the picture instead of a blank layer
    assert has_colour(image, FEATURE_COLORS["External perimeter"])


def test_an_arc_given_by_radius_is_counted_but_not_drawn(write):
    # Given an extruding arc written in the radius form (R), which does not say where its centre is
    text = ARC_HEAD + "G1 X0 Y0 F9000\nG1 X10 Y0 E0.5\nG2 X20 Y10 R10 E0.8\n"

    # When the file is scanned
    scan = scan_gcode(write(text))

    # Then it is reported as skipped, and the straight move before it is still there
    assert scan.arcs_skipped == 1
    assert scan.x_range == (0, 10)


# --------------------------------------------------------------------------- scanning a whole file


def test_a_scan_reports_layers_heights_features_and_extent(write):
    # Given three layers: a square 20 mm wide, then two layers with another feature further along x
    text = (
        "M83\n"
        + layer(0.2, ("External perimeter", square(10, 10, 10)))
        + layer(0.4, ("Internal infill", [(30, 10, 40, 10)]))
        + layer(0.6, ("External perimeter", [(0, 0, 5, 0)]))
    )

    # When the file is scanned
    scan = scan_gcode(write(text))

    # Then it knows the layers and heights, the features in order of appearance, and the printed extent
    assert scan.layer_heights == [0.2, 0.4, 0.6]
    assert scan.features == ["External perimeter", "Internal infill"]
    assert scan.x_range == (0, 40)
    assert scan.y_range == (0, 20)


def test_a_file_with_no_extruding_moves_is_refused(write):
    # Given G-code with layers but nothing printed
    text = "M83\n;LAYER_CHANGE\n;Z:0.2\nG1 X10 Y10 F9000\n"

    # When / Then scanning it fails saying what was missing
    with pytest.raises(ValueError, match="no extruding moves"):
        scan_gcode(write(text))


# --------------------------------------------------------------------------- one layer's toolpaths


def test_a_layer_is_drawn_in_the_colour_of_its_feature(write):
    # Given a layer printed as an external perimeter
    path = write("M83\n" + layer(0.2, ("External perimeter", square(50, 50, 20))))

    # When the layer is drawn
    image = render_layer(path, scan_gcode(path), 1, SIZE)

    # Then the picture contains that feature's colour
    assert image.size == (SIZE, SIZE)
    assert has_colour(image, FEATURE_COLORS["External perimeter"])


def test_the_layer_below_is_drawn_faintly_for_context(write):
    # Given a first layer of one feature and a second of another
    path = write(
        "M83\n" + layer(0.2, ("Solid infill", square(50, 50, 20))) + layer(0.4, ("Perimeter", square(50, 50, 10)))
    )

    # When the second layer is drawn
    image = render_layer(path, scan_gcode(path), 2, SIZE)

    # Then its own colour is strong and the layer below is not drawn in its feature colour
    assert has_colour(image, FEATURE_COLORS["Perimeter"])
    assert not has_colour(image, FEATURE_COLORS["Solid infill"])
    assert has_colour(image, (222, 222, 222))


def test_every_layer_is_framed_the_same_way(write):
    # Given a first layer with a small square and a second with a large one, so the print is 80 mm wide
    path = write("M83\n" + layer(0.2, ("Perimeter", square(50, 50, 5))) + layer(0.4, ("Perimeter", square(50, 50, 40))))
    scan = scan_gcode(path)

    # When both layers are drawn
    small = np.asarray(render_layer(path, scan, 1, SIZE))
    large = np.asarray(render_layer(path, scan, 2, SIZE))

    # Then the large square fills most of the picture and the small one is proportionally small, on the same scale
    def extent(pixels):
        drawn = np.all(pixels == np.array(FEATURE_COLORS["Perimeter"], dtype=np.uint8), axis=2)
        xs = np.nonzero(drawn[SIZE // 10 :].any(axis=0))[0]  # below the legend in the corner
        return xs.max() - xs.min()

    assert extent(large) > SIZE * 0.7
    assert extent(small) == pytest.approx(extent(large) / 8, rel=0.25)


def test_a_feature_type_the_palette_does_not_know_is_drawn_in_grey(write):
    # Given a layer printed with a feature type that is not in the colour palette
    path = write("M83\n" + layer(0.2, ("Mystery feature", square(50, 50, 20))))

    # When the layer is drawn
    image = render_layer(path, scan_gcode(path), 1, SIZE)

    # Then it still draws, in the neutral colour
    assert has_colour(image, UNKNOWN_COLOR)


def test_moves_with_no_feature_comment_are_drawn_too(write):
    # Given G-code that never says which feature it is printing
    text = "M83\n;LAYER_CHANGE\n;Z:0.2\n" + "".join(
        f"G1 X{a} Y{b} F9000\nG1 X{c} Y{d} E0.5\n" for a, b, c, d in square(50, 50, 20)
    )
    path = write(text)

    # When the layer is drawn
    image = render_layer(path, scan_gcode(path), 1, SIZE)

    # Then the moves are drawn in the neutral colour
    assert has_colour(image, UNKNOWN_COLOR)


@pytest.mark.parametrize("layer_number", [0, 4, 99])
def test_a_layer_outside_the_print_is_refused_with_the_valid_range(write, layer_number):
    # Given a print of three layers
    path = write("M83\n" + "".join(layer(0.2 * i, ("Perimeter", square(50, 50, 10))) for i in (1, 2, 3)))

    # When / Then asking for a layer that does not exist says how many there are
    with pytest.raises(ValueError, match="between 1 and 3"):
        render_layer(path, scan_gcode(path), layer_number, SIZE)


# --------------------------------------------------------------------------- side silhouette


def test_an_empty_stretch_in_the_height_shows_as_a_blank_band(write):
    # Given a print that stops at 0.4 mm and carries on at 9 mm
    path = write("M83\n" + "".join(layer(z, ("Perimeter", square(50, 50, 20))) for z in (0.2, 0.4, 9.0, 9.2)))

    # When the side silhouette is drawn
    image = render_profile(path, scan_gcode(path), SIZE)
    rows = ink_rows(image, slice(0, SIZE // 2))

    # Then there is a long blank run between the ink of the first layers and the ink of the later ones
    span = rows.max() - rows.min()
    longest_blank = np.diff(rows).max()
    assert longest_blank > span * 0.8


def test_a_continuous_print_has_no_blank_band(write):
    # Given a print with evenly stacked layers
    zs = [round(0.2 * i, 1) for i in range(1, 41)]
    path = write("M83\n" + "".join(layer(z, ("Perimeter", square(50, 50, 20))) for z in zs))

    # When the side silhouette is drawn
    image = render_profile(path, scan_gcode(path), SIZE)
    rows = ink_rows(image, slice(0, SIZE // 2))

    # Then the ink is continuous from the first layer to the last
    assert np.diff(rows).max() <= 2


def test_the_two_panels_show_different_sides(write):
    # Given a print 60 mm wide in x but only 10 mm deep in y
    path = write("M83\n" + "".join(layer(z, ("Perimeter", [(0, 0, 60, 0), (60, 0, 60, 10)])) for z in (0.2, 0.4, 0.6)))

    # When the side silhouette is drawn
    image = render_profile(path, scan_gcode(path), SIZE)
    drawn = colour_mask(image, INK)
    front_width = np.ptp(np.nonzero(drawn[:, : SIZE // 2].any(axis=0))[0])
    side_width = np.ptp(np.nonzero(drawn[:, SIZE // 2 :].any(axis=0))[0])

    # Then the front panel (x) is several times wider than the side panel (y)
    assert front_width > side_width * 3
