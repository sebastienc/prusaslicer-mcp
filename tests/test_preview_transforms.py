"""preview_model with rotate/scale/close_holes: the picture shows what PrusaSlicer will make of the model (ADR 0015).

PrusaSlicer is faked at `--export-stl`; the real flags and the real renderer are under test.
"""

import io
from pathlib import Path

import pytest
import trimesh
from conftest import PROJECT_CONFIG
from mcp.server.mcpserver import Image
from mcp.server.mcpserver.exceptions import ToolError

from prusaslicer_mcp import server


async def preview(model, **arguments):
    """The picture and the caption of a preview, called as a tool function."""
    content = await server.preview_model(str(model), **arguments)
    picture = next(item for item in content if isinstance(item, Image))
    caption = next(item for item in content if isinstance(item, str))
    return picture, caption


@pytest.fixture
def open_scan(tmp_path):
    """A cylinder with no bottom, like a scan whose underside was never captured."""
    full = trimesh.creation.cylinder(radius=10, height=30, sections=48)
    path = tmp_path / "scan.stl"
    trimesh.Trimesh(full.vertices, full.faces[full.face_normals[:, 2] > -0.99]).export(path)
    return path


def flags_before_output(fake):
    args = fake.calls[0]
    return args[1 : args.index("--output")]


async def test_transforms_are_handed_to_prusaslicer_as_slice_model_would(fake_export, cube_stl):
    # Given a model and a rotation about two axes plus a scale

    # When it is previewed
    await preview(cube_stl, rotate_x=90.0, rotate_y=-30.0, scale=2.0)

    # Then PrusaSlicer is asked to export the model with those same flags, and the model comes last
    assert fake_export.calls[0][0] == "--export-stl"
    assert flags_before_output(fake_export) == ["--rotate-x", "90", "--rotate-y", "-30", "--scale", "2"]
    assert fake_export.calls[0][-1] == str(cube_stl.resolve())


async def test_scale_to_fit_and_rotate_z_are_handed_over_too(fake_export, cube_stl):
    # Given a rotation about z and a box to fit

    # When it is previewed
    await preview(cube_stl, rotate_z=45.0, scale_to_fit=[100.0, 80.0, 60.0])

    # Then both reach PrusaSlicer in its own flag names
    assert flags_before_output(fake_export) == ["--rotate", "45", "--scale-to-fit", "100,80,60"]


async def test_the_caption_describes_the_mesh_prusaslicer_returned(fake_export, cube_stl):
    # Given a 20 mm cube, and a PrusaSlicer whose transformed result is a 20 x 30 x 40 mm box
    # When it is previewed with a rotation
    _, caption = await preview(cube_stl, rotate_x=90.0)

    # Then the size is the transformed one, and the caption says what was applied instead of "as stored"
    assert "Size 20.0 x 30.0 x 40.0" in caption
    assert "rotate_x=90" in caption
    assert "as stored" not in caption


async def test_the_picture_is_drawn_from_the_transformed_mesh(fake_export, cube_stl):
    # Given a PrusaSlicer that returns a tall thin bar, and the same preview without transforms for comparison
    fake_export.state.mesh = trimesh.creation.box(extents=(5, 5, 40))
    plain, _ = await preview(cube_stl, view="front")

    # When it is previewed with a transform
    rotated, _ = await preview(cube_stl, view="front", rotate_x=90.0)

    # Then the pictures differ: the second shows the bar
    assert plain.data != rotated.data


async def test_without_transforms_prusaslicer_is_not_started_and_the_caption_says_as_stored(fake_export, cube_stl):
    # Given an STL and no transform

    # When it is previewed
    _, caption = await preview(cube_stl)

    # Then nothing is exported, and the picture is of the file as it is stored
    assert fake_export.calls == []
    assert "as stored" in caption


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        ({"scale": 2.0, "scale_to_fit": [10.0, 10.0, 10.0]}, "either scale or scale_to_fit"),
        ({"scale": 0.0}, "greater than 0"),
        ({"rotate_x": float("inf")}, "finite"),
        ({"scale_to_fit": [10.0, 10.0]}, "exactly 3"),
    ],
    ids=["both scales", "zero scale", "infinite angle", "short box"],
)
async def test_an_invalid_transform_is_refused_before_prusaslicer_runs(fake_export, cube_stl, arguments, message):
    # Given a transform that slice_model would refuse

    # When it is previewed
    with pytest.raises(ToolError, match=message):
        await preview(cube_stl, **arguments)

    # Then it is refused with the same message and nothing is run
    assert fake_export.calls == []


async def test_a_transform_that_prusaslicer_cannot_apply_fails_with_its_message(fake_export, cube_stl):
    # Given a PrusaSlicer that fails
    fake_export.state.returncode = 1
    fake_export.state.writes_output = False
    fake_export.state.stderr = "Error: something broke"

    # When it is previewed with a rotation
    with pytest.raises(ToolError) as error:
        await preview(cube_stl, rotate_x=90.0)

    # Then the message carries PrusaSlicer's words, and does not blame a STEP file for an STL
    assert "something broke" in str(error.value)
    assert "STEP" not in str(error.value)


# --------------------------------------------------------------------------- close_holes in a preview


async def test_close_holes_alone_draws_the_capped_mesh(fake_export, open_scan, monkeypatch):
    # Given a scan with no base, and a renderer that records the mesh it is given
    drawn: list[trimesh.Trimesh] = []
    draw = server.render_model

    def recording(mesh, view, size):
        drawn.append(mesh)
        return draw(mesh, view, size)

    monkeypatch.setattr(server, "render_model", recording)

    # When it is previewed with close_holes
    await preview(open_scan, close_holes=True)

    # Then the mesh that was drawn is the capped one
    assert drawn[0].is_watertight


async def test_close_holes_alone_draws_the_capped_model_without_running_prusaslicer(fake_export, open_scan):
    # Given a scan with no base

    # When it is previewed with close_holes and no transform
    _, caption = await preview(open_scan, close_holes=True)

    # Then the caption says a hole was capped, and nothing was exported
    assert "capped 1" in caption
    assert "before drawing" in caption
    assert fake_export.calls == []


async def test_close_holes_with_a_transform_hands_prusaslicer_the_capped_copy(fake_export, open_scan):
    # Given a scan with no base

    # When it is previewed with close_holes and a rotation
    _, caption = await preview(open_scan, close_holes=True, rotate_x=90.0)

    # Then PrusaSlicer is given a watertight copy named like the scan, with the rotation flags
    given = Path(fake_export.calls[0][-1])
    assert given != open_scan.resolve()
    assert given.name == "scan.stl"
    loaded = trimesh.load(io.BytesIO(fake_export.inputs[0]), file_type="stl")
    assert isinstance(loaded, trimesh.Trimesh)
    assert loaded.is_watertight
    assert flags_before_output(fake_export) == ["--rotate-x", "90"]
    assert "capped 1" in caption


async def test_close_holes_on_a_closed_model_says_there_was_nothing_to_close(fake_export, cube_stl):
    # Given a closed cube

    # When it is previewed with close_holes
    _, caption = await preview(cube_stl, close_holes=True)

    # Then the caption says so
    assert "no open holes" in caption
    assert "drawn as it is" in caption


async def test_close_holes_is_refused_for_a_project(fake_export, make_3mf):
    # Given a PrusaSlicer project
    project = make_3mf(config=PROJECT_CONFIG)

    # When it is previewed with close_holes
    with pytest.raises(ToolError, match="project"):
        await preview(project, close_holes=True)

    # Then nothing is run
    assert fake_export.calls == []
