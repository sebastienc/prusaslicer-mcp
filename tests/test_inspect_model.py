"""Unit tests for inspect_model (real meshes built with trimesh; no PrusaSlicer needed)."""

import pytest
import trimesh
from mcp.server.mcpserver.exceptions import ToolError

from prusaslicer_mcp import server

from conftest import PROJECT_CONFIG

BED = {"bed_width": 180, "bed_depth": 180, "max_height": 180}


def cube(size=20.0, at=(0.0, 0.0, 0.0)):
    mesh = trimesh.creation.box(extents=(size, size, size))
    mesh.apply_translation(at)
    return mesh


def save(mesh, path):
    mesh.export(path)
    return path


# --------------------------------------------------------------------------- what a healthy model reports


def test_a_clean_cube_is_reported_in_full(tmp_path):
    # Given a closed 20 mm cube in an STL
    model = save(cube(20, at=(10, 10, 10)), tmp_path / "cube.stl")

    # When it is inspected
    info = server.inspect_model(str(model))

    # Then size, bounds, volume, area and counts are all reported, with no warnings
    assert info.triangles == 12
    assert info.size_mm == pytest.approx((20, 20, 20))
    assert info.bounds_min == pytest.approx((0, 0, 0))
    assert info.bounds_max == pytest.approx((20, 20, 20))
    assert info.volume_mm3 == pytest.approx(8000)
    assert info.surface_area_mm2 == pytest.approx(2400)
    assert (info.watertight, info.connected_parts) == (True, 1)
    assert info.warnings == []


def test_fit_is_not_judged_without_a_bed(tmp_path):
    # Given a cube and no bed dimensions
    model = save(cube(), tmp_path / "cube.stl")

    # When it is inspected
    info = server.inspect_model(str(model))

    # Then fits_bed stays undecided
    assert info.fits_bed is None


@pytest.mark.parametrize("given", [{"bed_width": 180}, {"bed_width": 180, "bed_depth": 180}], ids=["width-only", "no-height"])
def test_fit_is_not_judged_with_an_incomplete_bed(tmp_path, given):
    # Given a cube and only some of the three bed dimensions
    model = save(cube(), tmp_path / "cube.stl")

    # When it is inspected
    info = server.inspect_model(str(model), **given)

    # Then fits_bed stays undecided instead of guessing
    assert info.fits_bed is None


def test_a_model_exactly_the_size_of_the_bed_fits(tmp_path):
    # Given a 20 mm cube and a 20 mm build volume
    model = save(cube(20), tmp_path / "cube.stl")

    # When it is inspected against that volume
    info = server.inspect_model(str(model), bed_width=20, bed_depth=20, max_height=20)

    # Then the boundary case fits
    assert info.fits_bed is True


@pytest.mark.parametrize(
    "bed",
    [
        {"bed_width": 10, "bed_depth": 180, "max_height": 180},
        {"bed_width": 180, "bed_depth": 10, "max_height": 180},
        {"bed_width": 180, "bed_depth": 180, "max_height": 10},
    ],
    ids=["too-wide", "too-deep", "too-tall"],
)
def test_a_model_too_large_in_one_axis_does_not_fit_and_is_explained(tmp_path, bed):
    # Given a 20 mm cube and a build volume that is too small in exactly one axis
    model = save(cube(20), tmp_path / "cube.stl")

    # When it is inspected against that volume
    info = server.inspect_model(str(model), **bed)

    # Then it does not fit, and a warning says so
    assert info.fits_bed is False
    assert any("exceeds the build volume" in w for w in info.warnings)


def test_fit_check_does_not_try_rotating_the_model(tmp_path):
    # Given a 30 x 10 x 10 mm bar and a 20 x 40 x 40 mm build volume it would fit if turned
    bar = trimesh.creation.box(extents=(30, 10, 10))
    model = save(bar, tmp_path / "bar.stl")

    # When it is inspected against that volume
    info = server.inspect_model(str(model), bed_width=20, bed_depth=40, max_height=40)

    # Then it is reported as not fitting, and the warning says rotation was not considered
    assert info.fits_bed is False
    assert any("rotation not considered" in w for w in info.warnings)


# --------------------------------------------------------------------------- mesh health warnings


def test_an_open_mesh_has_no_volume_and_warns_it_may_need_repair(tmp_path):
    # Given a cube with one triangle missing, so the surface has a hole
    box = cube()
    holed = trimesh.Trimesh(vertices=box.vertices, faces=box.faces[:-1], process=False)
    model = save(holed, tmp_path / "holed.stl")

    # When it is inspected
    info = server.inspect_model(str(model))

    # Then it is not watertight, volume is unknown, and the warning mentions repair
    assert info.watertight is False
    assert info.volume_mm3 is None
    assert any("not watertight" in w for w in info.warnings)


def test_a_closed_mesh_with_a_flipped_face_warns_about_winding(tmp_path):
    # Given a closed cube where one triangle is wound the wrong way
    box = cube()
    faces = box.faces.copy()
    faces[0] = faces[0][::-1]
    flipped = trimesh.Trimesh(vertices=box.vertices, faces=faces, process=False)
    model = save(flipped, tmp_path / "flipped.stl")

    # When it is inspected
    info = server.inspect_model(str(model))

    # Then only the winding problem is reported, not a hole
    assert info.watertight is True
    assert any("winding is inconsistent" in w for w in info.warnings)
    assert not any("not watertight" in w for w in info.warnings)


def test_two_separate_solids_are_counted_as_two_parts(tmp_path):
    # Given two cubes far apart in one STL
    both = trimesh.util.concatenate([cube(at=(0, 0, 0)), cube(at=(100, 0, 0))])
    model = save(both, tmp_path / "two.stl")

    # When it is inspected
    info = server.inspect_model(str(model))

    # Then two parts are counted and the warning says so
    assert info.connected_parts == 2
    assert any("2 disconnected parts" in w for w in info.warnings)


def test_a_3mf_with_several_objects_is_inspected_as_one_model(tmp_path):
    # Given a 3MF holding two cubes as separate objects
    scene = trimesh.Scene({"a": cube(at=(0, 0, 0)), "b": cube(at=(100, 0, 0))})
    model = tmp_path / "two.3mf"
    scene.export(model)

    # When it is inspected
    info = server.inspect_model(str(model))

    # Then both objects are counted together
    assert info.triangles == 24
    assert info.connected_parts == 2


# --------------------------------------------------------------------------- files that cannot be inspected


def test_an_unsupported_file_type_is_refused_naming_the_supported_ones(tmp_path):
    # Given a text file
    model = tmp_path / "notes.txt"
    model.write_text("hello")

    # When / Then it is refused, listing what is supported
    with pytest.raises(ToolError, match=r"Unsupported model type '\.txt'.*\.stl"):
        server.inspect_model(str(model))


def test_file_type_is_matched_case_insensitively(tmp_path):
    # Given a valid STL whose extension is upper case
    model = save(cube(), tmp_path / "cube.stl")
    upper = model.rename(tmp_path / "CUBE.STL")

    # When it is inspected
    info = server.inspect_model(str(upper))

    # Then it is accepted
    assert info.triangles == 12


def test_a_directory_is_not_a_model_file(tmp_path):
    # Given a path that is a directory

    # When / Then it is reported as not found
    with pytest.raises(ToolError, match="Model file not found"):
        server.inspect_model(str(tmp_path))


def test_a_model_path_may_start_with_a_tilde(tmp_path, monkeypatch):
    # Given a model in the home directory and a path written with "~"
    monkeypatch.setenv("HOME", str(tmp_path))
    save(cube(), tmp_path / "cube.stl")

    # When it is inspected
    info = server.inspect_model("~/cube.stl")

    # Then the home directory is substituted
    assert info.triangles == 12


@pytest.mark.parametrize("suffix", [".stl", ".3mf", ".obj", ".step", ".stp", ".amf"])
@pytest.mark.parametrize("content", [b"", b"this is not a mesh"], ids=["empty", "garbage"])
def test_an_unreadable_model_of_any_supported_type_fails_readably(tmp_path, suffix, content):
    # Given a file with a supported extension whose content is empty or garbage
    model = tmp_path / f"broken{suffix}"
    model.write_bytes(content)

    # When / Then the tool fails with a message the client can read, not an opaque crash
    with pytest.raises(ToolError, match="Could not"):
        server.inspect_model(str(model))


# --------------------------------------------------------------------------- PrusaSlicer projects


def test_a_project_3mf_reports_the_profiles_and_settings_saved_in_it(make_3mf):
    # Given a 3MF saved from PrusaSlicer with supports and a brim switched on
    model = make_3mf(config=PROJECT_CONFIG)

    # When it is inspected
    info = server.inspect_model(str(model))

    # Then the stored profile names and the settings that shape a print are reported
    assert info.project.printer_profile == "Original Prusa i3 MK3S & MK3S+ MMU2S Single"
    assert info.project.print_profile == "0.20mm QUALITY @MK3"
    assert info.project.material_profile == "Prusament PLA"
    assert info.project.settings["support_material"] == "1"
    assert info.project.settings["brim_width"] == "5"


@pytest.mark.parametrize("kind", ["plain-3mf", "stl"])
def test_a_model_that_is_not_a_project_reports_no_project(make_3mf, tmp_path, kind):
    # Given a plain 3MF, or an STL
    model = make_3mf(config=None) if kind == "plain-3mf" else save(cube(), tmp_path / "cube.stl")

    # When it is inspected
    info = server.inspect_model(str(model))

    # Then no project settings are reported
    assert info.project is None
