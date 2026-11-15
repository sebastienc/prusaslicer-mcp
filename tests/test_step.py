"""STEP files are read by having PrusaSlicer convert them to a mesh (ADR 0016); the command line is faked here."""

from pathlib import Path

import pytest
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import CallToolResult, ImageContent

from prusaslicer_mcp import server


@pytest.fixture(params=[".step", ".stp"])
def step_file(tmp_path, request):
    path = tmp_path / f"part{request.param}"
    path.write_text("ISO-10303-21;\nEND-ISO-10303-21;\n")
    return path


async def test_inspect_model_measures_the_mesh_prusaslicer_makes_from_a_step_file(fake_export, step_file):
    # Given a STEP file, and a PrusaSlicer that converts it to a 20 x 30 x 40 mm box

    # When it is inspected
    info = await server.inspect_model(str(step_file))

    # Then PrusaSlicer was asked to export an STL of that file, and the answer describes the box
    args = fake_export.calls[0]
    assert args[0] == "--export-stl"
    assert args[-1] == str(step_file.resolve())
    assert Path(args[args.index("--output") + 1]).suffix == ".stl"
    assert info.size_mm == pytest.approx((20, 30, 40))
    assert info.triangles == 12
    assert info.watertight is True


async def test_preview_model_draws_a_step_file(fake_export, step_file):
    # Given a STEP file

    # When it is previewed
    result = await server.mcp.call_tool("preview_model", {"model_path": str(step_file)})

    # Then a picture comes back, drawn from the converted mesh
    assert isinstance(result, CallToolResult)
    assert any(isinstance(block, ImageContent) for block in result.content)
    assert fake_export.calls[0][0] == "--export-stl"


async def test_the_conversion_leaves_nothing_behind(fake_export, step_file):
    # Given a STEP file

    # When it is inspected
    await server.inspect_model(str(step_file))

    # Then the folder PrusaSlicer wrote into is gone
    written = Path(fake_export.calls[0][fake_export.calls[0].index("--output") + 1])
    assert not written.parent.exists()


async def test_a_step_file_prusaslicer_cannot_read_fails_with_its_message(fake_export, step_file):
    # Given a PrusaSlicer that refuses the file
    fake_export.state.returncode = 1
    fake_export.state.writes_output = False
    fake_export.state.stderr = "Error: could not read the STEP file"

    # When it is inspected
    with pytest.raises(ToolError) as error:
        await server.inspect_model(str(step_file))

    # Then the file is named with PrusaSlicer's own message
    assert f"could not convert {step_file.name}" in str(error.value)
    assert "could not read the STEP file" in str(error.value)
    assert "valid STEP file" in str(
        error.value
    )  # PrusaSlicer's own words for a broken file can be as bare as "basic_string"


async def test_a_conversion_that_exits_with_an_error_is_a_failure_even_if_it_wrote_a_file(fake_export, step_file):
    # Given a PrusaSlicer that wrote a mesh but exited with an error, so the mesh may be partial
    fake_export.state.returncode = 1
    fake_export.state.stderr = "Error: something went wrong half way"

    # When it is inspected
    with pytest.raises(ToolError) as error:
        await server.inspect_model(str(step_file))

    # Then it is a failure with PrusaSlicer's message, not a model with a doubtful mesh
    assert "something went wrong half way" in str(error.value)


async def test_a_conversion_that_writes_nothing_is_a_failure_even_with_exit_zero(fake_export, step_file):
    # Given a PrusaSlicer that exits 0 without writing the mesh
    fake_export.state.writes_output = False

    # When it is inspected
    with pytest.raises(ToolError) as error:
        await server.inspect_model(str(step_file))

    # Then it is reported, not mistaken for an empty model
    assert f"could not convert {step_file.name}" in str(error.value)


async def test_an_stl_is_read_directly_without_running_prusaslicer(fake_export, cube_stl):
    # Given an STL

    # When it is inspected
    await server.inspect_model(str(cube_stl))

    # Then PrusaSlicer is not started
    assert fake_export.calls == []
