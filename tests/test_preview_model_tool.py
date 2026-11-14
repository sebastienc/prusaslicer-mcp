"""preview_model as a client sees it: a PNG plus a caption, or a readable error (no PrusaSlicer needed)."""

import base64
import io
import typing

import numpy as np
import pytest
import trimesh
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import CallToolResult, ImageContent, TextContent
from PIL import Image

from prusaslicer_mcp import server
from prusaslicer_mcp.preview_model import ALL_VIEWS


async def preview(**arguments) -> CallToolResult:
    result = await server.mcp.call_tool("preview_model", arguments)
    assert isinstance(result, CallToolResult)
    return result


def decode(result) -> Image.Image:
    image = next(block for block in result.content if isinstance(block, ImageContent))
    assert image.mime_type == "image/png"
    return Image.open(io.BytesIO(base64.b64decode(image.data)))


def caption(result) -> str:
    return next(block for block in result.content if isinstance(block, TextContent)).text


async def test_the_result_is_a_png_with_a_caption(cube_stl):
    # Given a 20 mm cube
    arguments = {"model_path": str(cube_stl)}

    # When a client asks for a preview with the defaults
    result = await preview(**arguments)

    # Then it receives one PNG image and one text block, with no error
    assert result.is_error is False
    assert [type(block).__name__ for block in result.content] == ["ImageContent", "TextContent"]
    assert decode(result).format == "PNG"


@pytest.mark.parametrize("size", [128, 400, 1024])
async def test_the_picture_has_the_requested_size(cube_stl, size):
    # Given a cube and a size within the allowed range
    arguments = {"model_path": str(cube_stl), "size": size}

    # When a client asks for a preview
    result = await preview(**arguments)

    # Then the picture is that many pixels square
    assert decode(result).size == (size, size)


async def test_the_default_picture_is_640_pixels(cube_stl):
    # Given a cube and no size

    # When a client asks for a preview
    result = await preview(model_path=str(cube_stl))

    # Then the picture is 640 pixels square
    assert decode(result).size == (640, 640)


async def test_the_caption_gives_the_size_and_says_z_is_up(cube_stl):
    # Given a 20 mm cube

    # When a client asks for an iso preview
    result = await preview(model_path=str(cube_stl), view="iso")

    # Then the caption names the file and view, gives the size, and says which axis is up
    text = caption(result)
    assert "cube.stl" in text
    assert "iso" in text
    assert "20.0 x 20.0 x 20.0 mm" in text
    assert "Z is up" in text


async def test_the_sheet_caption_says_where_each_view_is(cube_stl):
    # Given a cube

    # When a client asks for the sheet
    result = await preview(model_path=str(cube_stl), view="sheet")

    # Then the caption says which view is in which corner
    text = caption(result)
    for corner in ("iso (top left)", "front (top right)", "side (bottom left)", "top (bottom right)"):
        assert corner in text


@pytest.mark.parametrize("view", ["iso", "front", "side", "top", "sheet"])
async def test_every_view_can_be_requested(cube_stl, view):
    # Given a cube

    # When a client asks for each view
    result = await preview(model_path=str(cube_stl), view=view, size=256)

    # Then each gives a picture
    assert decode(result).size == (256, 256)


async def test_an_unknown_view_is_refused_naming_the_valid_ones(cube_stl):
    # Given a view that does not exist
    arguments = {"model_path": str(cube_stl), "view": "diagonal"}

    # When / Then the call fails and says what is allowed
    with pytest.raises(ToolError, match="iso"):
        await preview(**arguments)


@pytest.mark.parametrize("size", [64, 127, 1025, 4000])
async def test_a_size_outside_the_allowed_range_is_refused(cube_stl, size):
    # Given a size below 128 or above 1024 pixels
    arguments = {"model_path": str(cube_stl), "size": size}

    # When / Then the call is refused
    with pytest.raises(ToolError, match=r"128|1024"):
        await preview(**arguments)


async def test_a_missing_model_is_a_readable_error(tmp_path):
    # Given a path that does not exist
    arguments = {"model_path": str(tmp_path / "nope.stl")}

    # When / Then the client is told the file was not found
    with pytest.raises(ToolError, match="Model file not found"):
        await preview(**arguments)


async def test_an_unreadable_model_is_a_readable_error(tmp_path):
    # Given a file with a model extension and garbage inside
    model = tmp_path / "broken.stl"
    model.write_bytes(b"this is not a mesh")

    # When / Then the client is told it could not be read
    with pytest.raises(ToolError, match="Could not"):
        await preview(model_path=str(model))


async def test_a_mesh_with_nothing_to_draw_is_a_readable_error(tmp_path):
    # Given an STL whose only triangle has collapsed to a point
    model = tmp_path / "point.stl"
    model.write_text(
        "solid p\nfacet normal 0 0 0\nouter loop\nvertex 1 1 1\nvertex 1 1 1\nvertex 1 1 1\nendloop\nendfacet\nendsolid p\n"
    )

    # When / Then the client is told there is no surface
    with pytest.raises(ToolError, match="no surface"):
        await preview(model_path=str(model))


def test_the_views_a_client_can_ask_for_are_the_views_the_renderer_supports():
    # Given the views declared on the tool and the views the renderer implements

    # When they are compared
    offered = typing.get_args(server.PreviewView)

    # Then they are the same set, so neither can be added without the other
    assert set(offered) == set(ALL_VIEWS)


@pytest.fixture
def bar_stl(tmp_path):
    """A 20 x 30 x 40 mm box, so every axis is different and every view looks different."""
    path = tmp_path / "bar.stl"
    trimesh.creation.box(extents=(20, 30, 40)).export(path)
    return path


def silhouette_aspect(picture: Image.Image) -> float:
    """Width over height of everything drawn that is not the light background."""
    pixels = np.asarray(picture)
    drawn = np.any(pixels != pixels[0, 0], axis=2)
    ys, xs = np.nonzero(drawn)
    return (xs.max() - xs.min() + 1) / (ys.max() - ys.min() + 1)


async def test_the_caption_lists_the_dimensions_in_x_y_z_order(bar_stl):
    # Given a box 20 mm in x, 30 mm in y and 40 mm in z

    # When a client asks for a preview
    result = await preview(model_path=str(bar_stl))

    # Then the caption gives them in that order
    assert "20.0 x 30.0 x 40.0 mm (x, y, z)" in caption(result)


@pytest.mark.parametrize(
    ("view", "width_mm", "height_mm"),
    [("front", 20, 40), ("side", 30, 40), ("top", 20, 30)],
    ids=["front-is-x-by-z", "side-is-y-by-z", "top-is-x-by-y"],
)
async def test_the_requested_view_is_the_one_drawn(bar_stl, view, width_mm, height_mm):
    # Given a box whose three faces have different proportions

    # When a client asks for one view
    picture = decode(await preview(model_path=str(bar_stl), view=view, size=400))

    # Then the silhouette has the proportions of the axes that view should show
    assert silhouette_aspect(picture) == pytest.approx(width_mm / height_mm, rel=0.04)
