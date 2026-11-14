"""Unit tests for the software mesh renderer (numpy and Pillow; no OpenGL, no PrusaSlicer needed)."""

import numpy as np
import pytest
import trimesh
from PIL import Image

from prusaslicer_mcp.preview_model import BACKGROUND, render_model, to_png

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
