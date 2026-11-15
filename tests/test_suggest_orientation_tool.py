"""suggest_orientation as a client sees it (no PrusaSlicer needed): options, warnings about holes, refusals."""

from __future__ import annotations

import math

import pytest
import trimesh
from conftest import PROJECT_CONFIG
from mcp.server.mcpserver.exceptions import ToolError

from prusaslicer_mcp import server


def cone_stl(path, with_base: bool = True, apex_up: bool = True):
    """A flat cone, 40 mm across and 10 mm tall, optionally with no base and optionally standing on its apex."""
    mesh = trimesh.creation.cone(radius=20, height=10, sections=48)
    if not with_base:
        mesh = trimesh.Trimesh(mesh.vertices, mesh.faces[mesh.face_normals[:, 2] > -0.99])
    if not apex_up:
        mesh.apply_transform(trimesh.transformations.rotation_matrix(math.pi, [1, 0, 0]))
    mesh.export(path)
    return path


async def test_options_are_ranked_and_describe_each_way_of_standing_the_model(tmp_path):
    # Given a cone exported apex down
    model = cone_stl(tmp_path / "cone.stl", apex_up=False)

    # When orientations are suggested
    advice = await server.suggest_orientation(str(model))

    # Then the best option puts the base down and says how to get there, and the as-stored one is listed
    best = advice.options[0]
    assert best.rank == 1
    assert best.height_mm == pytest.approx(10, abs=0.1)
    assert best.base_area_mm2 == pytest.approx(1253, rel=0.01)
    assert best.overhang_area_mm2 == 0
    assert best.stable is True
    assert abs(best.rotate_x) == pytest.approx(180, abs=0.1) or abs(best.rotate_y) == pytest.approx(180, abs=0.1)
    assert any(option.as_stored for option in advice.options)
    assert advice.surface_area_mm2 > 0


async def test_count_limits_how_many_options_are_returned(tmp_path):
    # Given a cube and a request for two options
    model = tmp_path / "cube.stl"
    trimesh.creation.box(extents=(20, 20, 20)).export(model)

    # When orientations are suggested
    advice = await server.suggest_orientation(str(model), count=2)

    # Then two are returned, plus the as-stored one if it was not among them
    assert 2 <= len(advice.options) <= 3


@pytest.mark.parametrize("count", [0, 13])
async def test_a_count_outside_the_allowed_range_is_refused(tmp_path, count):
    # Given a model
    model = cone_stl(tmp_path / "cone.stl")

    # When / Then a count outside 1 to 12 is refused by the tool's schema
    with pytest.raises(ToolError):
        await server.mcp.call_tool("suggest_orientation", {"model_path": str(model), "count": count})


async def test_a_missing_base_is_pointed_out_and_is_not_a_candidate_until_it_is_capped(tmp_path):
    # Given a cone with no base, standing apex up
    model = cone_stl(tmp_path / "scan.stl", with_base=False)

    # When orientations are suggested without close_holes
    advice = await server.suggest_orientation(str(model))

    # Then no option gets the missing 1253 mm2 base (the cone as stored rests on nothing, and at best it could lie on
    # one slanted triangle), and a warning names close_holes as the way to get one
    assert max(option.base_area_mm2 for option in advice.options) < 100
    assert next(option for option in advice.options if option.as_stored).base_area_mm2 == 0
    assert any("close_holes" in warning for warning in advice.warnings)


async def test_close_holes_makes_the_capped_base_the_best_orientation(tmp_path):
    # Given the same cone with no base
    model = cone_stl(tmp_path / "scan.stl", with_base=False)

    # When orientations are suggested with close_holes
    advice = await server.suggest_orientation(str(model), close_holes=True)

    # Then the capped base is the best option, and the warning says it was capped
    best = advice.options[0]
    assert best.base_area_mm2 == pytest.approx(1253, rel=0.02)
    assert best.stable is True
    assert any("capped 1" in warning and "scoring" in warning for warning in advice.warnings)


async def test_a_closed_model_gets_no_hole_warning(tmp_path):
    # Given a closed cone
    model = cone_stl(tmp_path / "cone.stl")

    # When orientations are suggested
    advice = await server.suggest_orientation(str(model))

    # Then there are no warnings
    assert advice.warnings == []


async def test_a_model_that_cannot_rest_on_a_base_in_any_orientation_says_so(tmp_path):
    # Given a sphere
    model = tmp_path / "ball.stl"
    trimesh.creation.icosphere(subdivisions=3, radius=15).export(model)

    # When orientations are suggested
    advice = await server.suggest_orientation(str(model))

    # Then a warning says nothing rests on a real base
    assert any("real base" in warning for warning in advice.warnings)


async def test_a_project_is_refused_because_it_keeps_its_own_placement(tmp_path, make_3mf):
    # Given a PrusaSlicer project
    project = make_3mf(config=PROJECT_CONFIG)

    # When orientations are suggested
    with pytest.raises(ToolError, match="project"):
        await server.suggest_orientation(str(project))


async def test_an_unreadable_model_fails_readably(tmp_path):
    # Given a file with an STL name that is not a mesh
    broken = tmp_path / "broken.stl"
    broken.write_text("not a mesh")

    # When orientations are suggested
    with pytest.raises(ToolError, match="Could not"):
        await server.suggest_orientation(str(broken))


async def test_a_tiny_gap_that_close_holes_would_leave_alone_gets_no_hole_warning(tmp_path):
    # Given a cube with one triangle missing: not watertight, but nothing close_holes would cap
    box = trimesh.creation.box(extents=(20, 20, 20))
    model = tmp_path / "gap.stl"
    trimesh.Trimesh(box.vertices, box.faces[:-1], process=False).export(model)

    # When orientations are suggested
    advice = await server.suggest_orientation(str(model))

    # Then there is no warning about holes
    assert advice.warnings == []
