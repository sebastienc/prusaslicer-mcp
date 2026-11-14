"""preview_gcode as a client sees it: a PNG plus a caption, or a readable error (no PrusaSlicer needed)."""

import base64
import io
import typing

import numpy as np
import pytest
from gcode_builders import layer, square
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import CallToolResult, ImageContent, TextContent
from PIL import Image

from prusaslicer_mcp import server
from prusaslicer_mcp.preview_gcode import FEATURE_COLORS, INK


async def preview(**arguments) -> CallToolResult:
    result = await server.mcp.call_tool("preview_gcode", arguments)
    assert isinstance(result, CallToolResult)
    return result


def decode(result: CallToolResult) -> Image.Image:
    image = next(block for block in result.content if isinstance(block, ImageContent))
    assert image.mime_type == "image/png"
    return Image.open(io.BytesIO(base64.b64decode(image.data)))


def caption(result: CallToolResult) -> str:
    return next(block for block in result.content if isinstance(block, TextContent)).text


@pytest.fixture
def five_layers(tmp_path):
    """A print of five layers, 0.2 to 1.0 mm, each a perimeter square."""
    path = tmp_path / "print.gcode"
    path.write_text("M83\n" + "".join(layer(round(0.2 * i, 1), ("Perimeter", square(50, 50, 20))) for i in range(1, 6)))
    return path


@pytest.fixture
def gapped(tmp_path):
    """A print that stops at 0.4 mm and carries on at 9 mm."""
    path = tmp_path / "gapped.gcode"
    path.write_text("M83\n" + "".join(layer(z, ("Perimeter", square(50, 50, 20))) for z in (0.2, 0.4, 9.0, 9.2, 9.4)))
    return path


async def test_the_result_is_a_png_with_a_caption(five_layers):
    # Given a sliced print

    # When a client asks for a preview with the defaults
    result = await preview(gcode_path=str(five_layers))

    # Then it receives one PNG image and one text block, with no error
    assert result.is_error is False
    assert [type(block).__name__ for block in result.content] == ["ImageContent", "TextContent"]
    assert decode(result).format == "PNG"
    assert decode(result).size == (640, 640)


async def test_the_middle_layer_is_drawn_by_default(five_layers):
    # Given a print of five layers and no layer chosen

    # When a client asks for a preview
    result = await preview(gcode_path=str(five_layers))

    # Then the caption says it is layer 3 of 5, at 0.6 mm
    assert "layer 3 of 5 (z 0.6 mm)" in caption(result)


async def test_a_chosen_layer_is_the_one_drawn(five_layers):
    # Given a print of five layers

    # When a client asks for the second layer
    result = await preview(gcode_path=str(five_layers), layer=2)

    # Then the caption says so
    assert "layer 2 of 5 (z 0.4 mm)" in caption(result)


@pytest.mark.parametrize("size", [128, 500, 1024])
async def test_the_picture_has_the_requested_size(five_layers, size):
    # Given a print and a size within the allowed range

    # When a client asks for a preview
    result = await preview(gcode_path=str(five_layers), size=size)

    # Then the picture is that many pixels square
    assert decode(result).size == (size, size)


async def test_the_profile_caption_describes_what_the_picture_shows(five_layers):
    # Given a continuous print

    # When a client asks for the side silhouette
    result = await preview(gcode_path=str(five_layers), view="profile")

    # Then the caption explains the panels, the height and the layer count, and reports no gaps
    text = caption(result)
    assert "front (x)" in text
    assert "side (y)" in text
    assert "5 layers" in text
    assert "1.0 mm tall" in text
    assert "Nothing is printed across" not in text


async def test_the_profile_caption_warns_about_an_empty_stretch(gapped):
    # Given a print with an empty stretch in its height

    # When a client asks for the side silhouette
    result = await preview(gcode_path=str(gapped), view="profile")

    # Then the caption carries the same warning slice_model gives, with where the gap starts
    text = caption(result)
    assert "Nothing is printed across" in text
    assert "between z 0.4 and 9 mm" in text


async def test_arc_moves_that_were_not_drawn_are_mentioned(tmp_path):
    # Given G-code whose printer profile used arc fitting
    path = tmp_path / "arcs.gcode"
    path.write_text(
        "M83\n;LAYER_CHANGE\n;Z:0.2\n;TYPE:Perimeter\nG1 X0 Y0 F9000\nG1 X10 Y0 E0.5\nG2 X20 Y10 I10 J0 E0.8\n"
    )

    # When a client asks for a preview
    result = await preview(gcode_path=str(path))

    # Then the caption says that one arc move is missing from the picture
    assert "1 arc move" in caption(result)


async def test_a_layer_with_the_silhouette_view_is_refused(five_layers):
    # Given a request that names a layer for the silhouette, which has none
    arguments = {"gcode_path": str(five_layers), "view": "profile", "layer": 2}

    # When / Then it is refused and says what the layer is for
    with pytest.raises(ToolError, match="view=layer"):
        await preview(**arguments)


@pytest.mark.parametrize("layer_number", [6, 99])
async def test_a_layer_beyond_the_print_is_refused_with_the_valid_range(five_layers, layer_number):
    # Given a print of five layers

    # When / Then asking for a layer that does not exist says how many there are
    with pytest.raises(ToolError, match="between 1 and 5"):
        await preview(gcode_path=str(five_layers), layer=layer_number)


async def test_layer_zero_is_refused(five_layers):
    # Given layers count from 1

    # When / Then asking for layer 0 is refused
    with pytest.raises(ToolError, match="greater than or equal to 1"):
        await preview(gcode_path=str(five_layers), layer=0)


@pytest.mark.parametrize("size", [64, 1025])
async def test_a_size_outside_the_allowed_range_is_refused(five_layers, size):
    # Given a size below 128 or above 1024 pixels

    # When / Then the call is refused
    with pytest.raises(ToolError, match=r"128|1024"):
        await preview(gcode_path=str(five_layers), size=size)


async def test_a_missing_file_is_a_readable_error(tmp_path):
    # Given a path that does not exist

    # When / Then the client is told the file was not found
    with pytest.raises(ToolError, match="G-code file not found"):
        await preview(gcode_path=str(tmp_path / "nope.gcode"))


async def test_binary_gcode_is_refused_readably(tmp_path):
    # Given a binary G-code file, which starts with the magic bytes GCDE
    path = tmp_path / "print.gcode"
    path.write_bytes(b"GCDE" + b"\0" * 32)

    # When / Then the client is told it cannot be drawn and why
    with pytest.raises(ToolError, match="Binary G-code"):
        await preview(gcode_path=str(path))


async def test_a_file_that_is_not_gcode_is_refused(tmp_path):
    # Given a text file with another extension
    path = tmp_path / "notes.txt"
    path.write_text("hello")

    # When / Then the client is told the type is not supported
    with pytest.raises(ToolError, match="Unsupported"):
        await preview(gcode_path=str(path))


async def test_gcode_with_nothing_printed_is_refused_readably(tmp_path):
    # Given G-code with a layer but no extruding move
    path = tmp_path / "empty.gcode"
    path.write_text("M83\n;LAYER_CHANGE\n;Z:0.2\nG1 X10 Y10 F9000\n")

    # When / Then the client is told there was nothing to draw
    with pytest.raises(ToolError, match="no extruding moves"):
        await preview(gcode_path=str(path))


def test_the_views_offered_for_gcode_are_the_two_the_renderer_draws():
    # Given the views declared on the tool

    # When they are read
    offered = typing.get_args(server.GcodeView)

    # Then they are layer and profile, the two pictures the renderer can make
    assert set(offered) == {"layer", "profile"}


def pixels_of(picture: Image.Image, colour: tuple[int, int, int]) -> int:
    return int(np.all(np.asarray(picture) == np.array(colour, dtype=np.uint8), axis=2).sum())


async def test_each_view_draws_its_own_kind_of_picture(five_layers):
    # Given a print of five layers

    # When a client asks for each view
    layer_picture = decode(await preview(gcode_path=str(five_layers), view="layer"))
    profile_picture = decode(await preview(gcode_path=str(five_layers), view="profile"))

    # Then the layer view is drawn in feature colours only, and the silhouette in its own ink only
    assert pixels_of(layer_picture, FEATURE_COLORS["Perimeter"]) > 300
    assert pixels_of(layer_picture, INK) == 0
    assert pixels_of(profile_picture, INK) > 300
    assert pixels_of(profile_picture, FEATURE_COLORS["Perimeter"]) == 0
