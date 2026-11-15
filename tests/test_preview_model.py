"""Unit tests for the software mesh renderer (numpy and Pillow; no OpenGL, no PrusaSlicer needed)."""

import numpy as np
import pytest
import trimesh
from PIL import Image

from prusaslicer_mcp.preview_model import BACKGROUND, BED_FILL, BED_LINE, render_model, to_png

SIZE = 400


def box(x=20.0, y=10.0, z=30.0, at=(0.0, 0.0, 0.0)):
    mesh = trimesh.creation.box(extents=(x, y, z))
    mesh.apply_translation(at)
    return mesh


def combine(*meshes: trimesh.Trimesh) -> trimesh.Trimesh:
    """Several meshes as one (trimesh types the result as a mesh or a scene)."""
    combined = trimesh.util.concatenate(list(meshes))
    assert isinstance(combined, trimesh.Trimesh)
    return combined


def content_mask(image: Image.Image) -> np.ndarray:
    return np.any(np.asarray(image) != np.array(BACKGROUND, dtype=np.uint8), axis=2)


def content_box(image: Image.Image) -> tuple[int, int, int, int]:
    """(left, top, right, bottom) of everything that is not background."""
    ys, xs = np.nonzero(content_mask(image))
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def test_an_image_of_the_requested_size_is_returned():
    # Given a box and a requested size
    mesh = box()

    # When it is rendered
    image = render_model(mesh, "front", SIZE)

    # Then the image is a square RGB picture of that size
    assert image.size == (SIZE, SIZE)
    assert image.mode == "RGB"


@pytest.mark.parametrize(
    ("view", "width_mm", "height_mm"),
    [("front", 20, 30), ("side", 10, 30), ("top", 20, 10)],
    ids=["front-shows-x-and-z", "side-shows-y-and-z", "top-shows-x-and-y"],
)
def test_each_view_shows_the_right_two_axes(view, width_mm, height_mm):
    # Given a box 20 mm wide (x), 10 mm deep (y) and 30 mm tall (z)
    mesh = box(20, 10, 30)

    # When it is rendered from one side
    left, top, right, bottom = content_box(render_model(mesh, view, SIZE))

    # Then the silhouette has the proportions of the two axes that face the camera
    assert (right - left) / (bottom - top) == pytest.approx(width_mm / height_mm, rel=0.03)


def test_the_front_view_puts_z_up_on_the_screen():
    # Given a model with a small box sitting on top of a large one (z is up)
    mesh = combine(box(30, 10, 10, at=(0, 0, 0)), box(10, 10, 10, at=(0, 0, 10)))

    # When it is rendered from the front
    _, top, _, bottom = content_box(render_model(mesh, "front", SIZE))
    mask = content_mask(render_model(mesh, "front", SIZE))

    # Then the narrow part is at the top of the picture and the wide part at the bottom
    top_width = mask[top + 3].sum()
    bottom_width = mask[bottom - 4].sum()
    assert top_width < bottom_width / 2


def test_a_solid_face_has_no_gaps_in_it():
    # Given a box seen straight on, so its silhouette is a plain rectangle
    mesh = box(20, 10, 30)

    # When it is rendered
    image = render_model(mesh, "front", SIZE)

    # Then almost every pixel inside the silhouette is filled in (no speckle)
    left, top, right, bottom = content_box(image)
    inside = content_mask(image)[top:bottom, left:right]
    assert inside.mean() > 0.999


def test_the_model_is_centred_and_fully_visible_wherever_it_is_stored():
    # Given a model stored far from the origin, like a scan exported 300 mm below it
    mesh = box(20, 10, 30, at=(-90.0, -60.0, -330.0))

    # When it is rendered
    left, top, right, bottom = content_box(render_model(mesh, "iso", SIZE))

    # Then it is centred and has a margin all round
    assert abs((left + right) / 2 - SIZE / 2) < SIZE * 0.03
    assert abs((top + bottom) / 2 - SIZE / 2) < SIZE * 0.03
    assert left >= SIZE * 0.02
    assert top >= SIZE * 0.02
    assert right <= SIZE * 0.98
    assert bottom <= SIZE * 0.98


def test_the_iso_view_shows_three_faces_with_different_shading():
    # Given a box
    mesh = box(20, 20, 20)

    # When it is rendered from a corner
    image = np.asarray(render_model(mesh, "iso", SIZE))

    # Then the three visible faces have clearly different brightness
    pixels = image[content_mask(Image.fromarray(image))]
    brightness = np.round(pixels.mean(axis=1) / 8).astype(int)
    values, counts = np.unique(brightness, return_counts=True)
    big = values[counts > 0.1 * counts.sum()]
    assert len(big) >= 3


def test_a_surface_is_shaded_the_same_whichever_way_its_normals_point():
    # Given a single square and the same square wound the other way, as in an open or badly exported scan
    square = trimesh.Trimesh(vertices=[(0, 0, 0), (10, 0, 0), (10, 0, 10), (0, 0, 10)], faces=[(0, 1, 2), (0, 2, 3)])
    flipped = trimesh.Trimesh(vertices=square.vertices, faces=square.faces[:, ::-1])

    # When both are rendered
    a = render_model(square, "iso", SIZE)
    b = render_model(flipped, "iso", SIZE)

    # Then they cover the same area with the same brightness (the sample points differ, so not pixel for pixel)
    def mean_brightness(image):
        return np.asarray(image)[content_mask(image)].mean()

    assert mean_brightness(a) == pytest.approx(mean_brightness(b), abs=1.0)
    assert content_box(a) == pytest.approx(content_box(b), abs=2)


def test_the_model_fills_most_of_the_picture():
    # Given a box
    mesh = box(20, 10, 30)

    # When it is rendered
    left, top, right, bottom = content_box(render_model(mesh, "front", SIZE))

    # Then its longer side takes up most of the picture, so the detail is as large as it can be
    assert max(right - left, bottom - top) >= SIZE * 0.8


def test_the_top_view_looks_down_from_above():
    # Given a four-sided pyramid with its apex at the top, so only the view from above sees the sloped sides
    pyramid = trimesh.creation.cone(radius=10, height=20, sections=4)

    # When it is rendered from the top
    image = render_model(pyramid, "top", SIZE)
    pixels = np.asarray(image)[content_mask(image)]

    # Then the four sloped sides show several different brightness levels, not a single flat underside
    levels = np.unique(np.round(pixels.mean(axis=1) / 6).astype(int), return_counts=True)
    big_levels = levels[0][levels[1] > 0.1 * levels[1].sum()]
    assert len(big_levels) >= 2


def test_the_nearest_surface_hides_what_is_behind_it():
    # Given a large wall facing the camera, with a smaller square tilted 45 degrees in front of its middle
    wall = trimesh.Trimesh(
        vertices=[(-20, 5, -20), (20, 5, -20), (20, 5, 20), (-20, 5, 20)], faces=[(0, 1, 2), (0, 2, 3)]
    )
    tilted = trimesh.Trimesh(
        vertices=[(-8, -5, -8), (8, -5, -8), (8, -5 + 16, 8), (-8, -5 + 16, 8)], faces=[(0, 1, 2), (0, 2, 3)]
    )
    both = combine(wall, tilted)

    # When the three pictures (wall alone, tilted square alone, both) are rendered from the front
    centre = (SIZE // 2, SIZE // 2)
    wall_colour = np.asarray(render_model(wall, "front", SIZE))[centre]
    tilted_colour = np.asarray(render_model(tilted, "front", SIZE))[centre]
    both_colour = np.asarray(render_model(both, "front", SIZE))[centre]

    # Then the two surfaces look different, and in the combined picture the tilted one is seen, not the wall
    assert abs(int(wall_colour.sum()) - int(tilted_colour.sum())) > 30
    assert np.abs(both_colour.astype(int) - tilted_colour.astype(int)).max() < 8


def test_the_same_model_always_gives_the_same_picture():
    # Given a model
    mesh = box()

    # When it is rendered twice
    first = to_png(render_model(mesh, "iso", SIZE))
    second = to_png(render_model(mesh, "iso", SIZE))

    # Then the PNG bytes are identical, so tests and callers can rely on it
    assert first == second


def test_the_sheet_shows_four_views_in_one_picture():
    # Given a box
    mesh = box()

    # When the sheet is rendered
    image = render_model(mesh, "sheet", SIZE)
    mask = content_mask(image)
    half = SIZE // 2

    # Then it is the requested size and every quarter has something in it
    assert image.size == (SIZE, SIZE)
    for rows, cols in (
        (slice(0, half), slice(0, half)),
        (slice(0, half), slice(half, SIZE)),
        (slice(half, SIZE), slice(0, half)),
        (slice(half, SIZE), slice(half, SIZE)),
    ):
        assert mask[rows, cols].any()


def test_an_unknown_view_is_refused():
    # Given a box and a view that does not exist
    mesh = box()

    # When / Then rendering it is refused naming the views that do
    with pytest.raises(ValueError, match="iso"):
        render_model(mesh, "diagonal", SIZE)


def test_a_mesh_with_no_surface_is_refused():
    # Given triangles that all collapse to a point, so there is nothing to draw
    mesh = trimesh.Trimesh(vertices=[(1, 1, 1)] * 3, faces=[(0, 1, 2)], process=False)

    # When / Then rendering it is refused readably
    with pytest.raises(ValueError, match="no surface"):
        render_model(mesh, "iso", SIZE)


def test_to_png_produces_a_png_file():
    # Given a rendered picture
    image = render_model(box(), "iso", SIZE)

    # When it is encoded
    data = to_png(image)

    # Then it starts with the PNG signature
    assert data[:8] == b"\x89PNG\r\n\x1a\n"


# --------------------------------------------------------------------------- the bed


def colour_mask(image: Image.Image, colour: tuple[int, int, int]) -> np.ndarray:
    return np.all(np.asarray(image) == np.array(colour, dtype=np.uint8), axis=2)


def model_mask(image: Image.Image) -> np.ndarray:
    """Pixels that belong to the model: not background and not the bed."""
    pixels = np.asarray(image)
    other = np.zeros(pixels.shape[:2], dtype=bool)
    for colour in (BACKGROUND, BED_FILL, BED_LINE):
        other |= np.all(pixels == np.array(colour, dtype=np.uint8), axis=2)
    return ~other


def test_no_bed_is_drawn_unless_asked_for():
    # Given a box

    # When it is rendered with the default options
    image = render_model(box(), "iso", SIZE)

    # Then there are no bed pixels
    assert not colour_mask(image, BED_FILL).any()
    assert not colour_mask(image, BED_LINE).any()


def test_the_bed_is_a_line_under_the_model_in_a_side_view_and_wider_than_it():
    # Given a box seen from the front
    mesh = box(20, 10, 30)

    # When it is rendered with the bed
    image = render_model(mesh, "front", SIZE, bed=True)

    # Then the bed is one row of line colour at the model's lowest row, reaching past both sides of the model
    rows = np.flatnonzero(colour_mask(image, BED_LINE).any(axis=1))
    mask = model_mask(image)
    ys, xs = np.nonzero(mask)
    assert abs(int(rows.min()) - int(ys.max())) <= 2
    line_columns = np.flatnonzero(colour_mask(image, BED_LINE)[rows].any(axis=0))
    assert line_columns.min() < xs.min() - 3
    assert line_columns.max() > xs.max() + 3


def test_the_bed_is_at_the_models_lowest_point_wherever_the_model_is_stored():
    # Given a model stored 330 mm below the origin
    mesh = box(20, 10, 30, at=(-90.0, -60.0, -330.0))

    # When it is rendered from the front with the bed
    image = render_model(mesh, "front", SIZE, bed=True)

    # Then the bed line is still at the model's lowest row
    rows = np.flatnonzero(colour_mask(image, BED_LINE).any(axis=1))
    ys, _ = np.nonzero(model_mask(image))
    assert abs(int(rows.min()) - int(ys.max())) <= 2


def test_the_bed_never_changes_how_the_model_itself_is_drawn():
    # Given a model drawn without and with the bed in the iso view
    mesh = combine(box(30, 10, 10), box(10, 10, 10, at=(0, 0, 10)))
    plain = render_model(mesh, "iso", SIZE)
    with_bed = render_model(mesh, "iso", SIZE, bed=True)

    # When the pixels that belong to the model are compared
    where = model_mask(plain)

    # Then they are the same, and the bed is only in what the model leaves free
    assert np.array_equal(np.asarray(plain)[where], np.asarray(with_bed)[where])
    assert colour_mask(with_bed, BED_FILL).any()
    assert not (colour_mask(with_bed, BED_FILL) & where).any()


def test_the_bed_is_drawn_behind_the_model_not_over_it():
    # Given a wide flat box, whose top face hides most of the bed in the iso view
    mesh = box(60, 60, 4)

    # When it is rendered with the bed
    image = render_model(mesh, "iso", SIZE, bed=True)

    # Then the middle of the picture, where the model is, is model colour and not bed
    centre = np.asarray(image)[SIZE // 2, SIZE // 2]
    assert tuple(centre) not in (BACKGROUND, BED_FILL, BED_LINE)


def test_the_bed_reaches_past_the_models_footprint_in_the_top_view():
    # Given a box seen from above
    mesh = box(20, 10, 30)

    # When it is rendered with the bed
    image = render_model(mesh, "top", SIZE, bed=True)

    # Then the bed's outline surrounds the model on every side
    ys, xs = np.nonzero(model_mask(image))
    bed_ys, bed_xs = np.nonzero(colour_mask(image, BED_LINE) | colour_mask(image, BED_FILL))
    assert bed_xs.min() < xs.min()
    assert bed_xs.max() > xs.max()
    assert bed_ys.min() < ys.min()
    assert bed_ys.max() > ys.max()


def test_a_bed_larger_than_the_picture_is_cut_off_without_smearing_the_edge():
    # Given a long thin model whose bed spills out of the picture in the front view
    mesh = box(200, 4, 4)

    # When it is rendered with the bed
    image = render_model(mesh, "front", SIZE, bed=True)

    # Then the picture is the right size and its top and bottom rows are untouched (no clamped points)
    assert image.size == (SIZE, SIZE)
    pixels = np.asarray(image)
    assert (pixels[0] == np.array(BACKGROUND)).all()
    assert (pixels[-1] == np.array(BACKGROUND)).all()


def test_every_view_of_the_sheet_has_its_bed():
    # Given a box rendered as a sheet with the bed
    image = render_model(box(), "sheet", SIZE, bed=True)

    # When each quarter is looked at
    half = SIZE // 2
    quarters = [np.asarray(image)[y : y + half, x : x + half] for y in (0, half) for x in (0, half)]

    # Then each has bed pixels
    for quarter in quarters:
        has_bed = np.all(quarter == np.array(BED_LINE, dtype=np.uint8), axis=2).any()
        assert has_bed


def test_a_very_large_model_still_gets_a_readable_grid():
    # Given a model 4 m across, which would need 400 grid lines at 10 mm
    mesh = box(4000, 4000, 10)

    # When it is rendered from above with the bed
    image = render_model(mesh, "top", SIZE, bed=True)

    # Then it renders (the grid spacing grows with the model) and has bed pixels
    assert colour_mask(image, BED_LINE).any()


def test_the_picture_with_the_bed_is_still_deterministic():
    # Given a model
    mesh = box()

    # When it is rendered twice with the bed
    first = to_png(render_model(mesh, "iso", SIZE, bed=True))
    second = to_png(render_model(mesh, "iso", SIZE, bed=True))

    # Then the pictures are identical
    assert first == second


def bed_from_above(extent_mm: float = 100.0, size: int = 400) -> np.ndarray:
    """The bed layer for a flat square model seen from straight above."""
    from prusaslicer_mcp import preview_model

    vertices = box(extent_mm, extent_mm, 2).vertices
    rotation = preview_model._rotation(*preview_model.VIEWS["top"])
    return np.asarray(preview_model._bed_layer(vertices, rotation, scale=size * 0.9 / extent_mm / 1.3, size=size))


def test_the_bed_has_a_grid_across_it_in_both_directions():
    # Given the bed under a 100 mm square model, seen from above
    layer = bed_from_above()

    # When the full lines across the bed are counted
    drawn = np.any(layer != np.array(BACKGROUND, dtype=np.uint8), axis=2)
    ys, xs = np.nonzero(drawn)
    line = np.all(layer == np.array(BED_LINE, dtype=np.uint8), axis=2)[ys.min() : ys.max() + 1, xs.min() : xs.max() + 1]
    vertical = int((line.mean(axis=0) > 0.9).sum())
    horizontal = int((line.mean(axis=1) > 0.9).sum())

    # Then there are lines every 10 mm both ways: about 12 inside the ~124 mm bed, plus its two edges
    assert vertical >= 12
    assert horizontal >= 12


def test_the_bed_has_a_solid_outline_round_its_fill():
    # Given the bed under a square model, seen from above
    layer = bed_from_above()

    # When the extent of everything drawn as bed is found
    bed = np.any(layer != np.array(BACKGROUND, dtype=np.uint8), axis=2)
    ys, xs = np.nonzero(bed)
    line = np.all(layer == np.array(BED_LINE, dtype=np.uint8), axis=2)

    # Then its four outermost rows and columns are line colour, not fill
    assert line[ys.min(), xs.min() : xs.max() + 1].mean() > 0.95
    assert line[ys.max(), xs.min() : xs.max() + 1].mean() > 0.95
    assert line[ys.min() : ys.max() + 1, xs.min()].mean() > 0.95
    assert line[ys.min() : ys.max() + 1, xs.max()].mean() > 0.95
