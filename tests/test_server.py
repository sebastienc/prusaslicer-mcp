"""Integration tests against a real PrusaSlicer install (skipped when absent)."""

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import trimesh
from conftest import PROJECT_CONFIG
from mcp.server.mcpserver import Image
from mcp.server.mcpserver.exceptions import ToolError
from step_builders import step_cube

from prusaslicer_mcp import server
from prusaslicer_mcp.preview_gcode import iter_extrusions, scan_gcode


@pytest.fixture(autouse=True)
def _reset_config(prusaslicer, tmp_path, monkeypatch):
    monkeypatch.setenv("PRUSASLICER_MCP_OUTPUT_DIR", str(tmp_path / "out"))
    server._config = None
    yield
    server._config = None


@pytest.fixture
async def installed():
    """The first installed printer profile with its first print profile and a compatible filament."""
    printers = await server.list_printers()
    printer = next(v.printer_profile for p in printers for v in p.variants)
    print_profile = (await server.list_profiles(printer)).print_profiles[0]
    return SimpleNamespace(
        printer=printer, print_profile=print_profile.name, filament=print_profile.filament_profiles[0]
    )


@pytest.fixture
def origin_cube_3mf(tmp_path):
    """A 20 mm cube saved in a plain 3MF around the origin, so half of it is off the bed."""
    path = tmp_path / "origin_cube.3mf"
    trimesh.creation.box(extents=(20, 20, 20)).export(path)
    return path


async def test_list_printers_returns_models_with_variants():
    # Given a PrusaSlicer install with printer profiles (the prusaslicer fixture)

    # When the installed printers are listed
    printers = await server.list_printers()

    # Then there are models and each one has at least one variant
    assert printers
    assert all(p.variants for p in printers)


async def test_list_printers_shows_model_names_without_doubled_ampersands():
    # Given vendor bundles that store model names GUI-escaped ("&&")

    # When the installed printers are listed
    printers = await server.list_printers()

    # Then no displayed model name still contains "&&"
    assert all("&&" not in p.name for p in printers)


async def test_list_profiles_returns_print_profiles_for_a_listed_printer(installed):
    # Given a printer profile name taken from list_printers

    # When its profiles are listed
    profiles = await server.list_profiles(installed.printer)

    # Then there are print profiles to choose from
    assert profiles.print_profiles


async def test_inspect_model_reports_size_volume_and_fit_for_a_cube_on_a_large_bed(cube_stl):
    # Given a 20 mm cube and a 180 mm build volume

    # When the model is inspected against that volume
    info = await server.inspect_model(str(cube_stl), bed_width=180, bed_depth=180, max_height=180)

    # Then it is watertight, fits, and has the cube's size and volume
    assert info.watertight
    assert info.fits_bed
    assert info.size_mm == pytest.approx((20, 20, 20))
    assert info.volume_mm3 == pytest.approx(8000)


async def test_inspect_model_reports_a_cube_as_not_fitting_a_tiny_bed(cube_stl):
    # Given a 20 mm cube and a 10 mm build volume

    # When the model is inspected against that volume
    info = await server.inspect_model(str(cube_stl), bed_width=10, bed_depth=10, max_height=10)

    # Then it is reported as not fitting
    assert info.fits_bed is False


async def test_slice_rejects_an_invalid_override_key(cube_stl):
    # Given an override key that is not a valid PrusaSlicer option name

    # When / Then slicing is refused with a readable message
    with pytest.raises(ToolError, match="Invalid override key"):
        await server.slice_model(str(cube_stl), "x", "y", "z", overrides={"bad key; rm": "1"})


async def test_slice_returns_time_filament_and_layers_for_a_cube_with_an_override(cube_stl, installed):
    # Given a cube, real installed profiles, and a fill density override

    # When the cube is sliced
    result = await server.slice_model(
        str(cube_stl), installed.printer, installed.print_profile, installed.filament, overrides={"fill_density": "10%"}
    )

    # Then the statistics are filled in
    assert result.stats.estimated_time_seconds
    assert result.stats.filament_used_g
    assert result.stats.layer_count


async def test_a_plain_3mf_around_the_origin_is_centred_automatically(origin_cube_3mf, installed):
    # Given a plain 3MF that keeps its stored coordinates and so sits half off the bed

    # When it is sliced with no center option
    result = await server.slice_model(
        str(origin_cube_3mf), installed.printer, installed.print_profile, installed.filament
    )

    # Then it is centred for the caller and slices, and the result says so (ADR 0013)
    assert result.centered is True
    assert result.stats.layer_count


async def test_slice_refuses_a_plain_3mf_around_the_origin_when_centring_is_off(origin_cube_3mf, installed):
    # Given a plain 3MF that keeps its stored coordinates and so sits half off the bed

    # When / Then slicing it with centring switched off fails with the remedy in the message
    with pytest.raises(ToolError, match="center=true"):
        await server.slice_model(
            str(origin_cube_3mf), installed.printer, installed.print_profile, installed.filament, center=False
        )


async def test_slice_places_a_plain_3mf_around_the_origin_when_centered(origin_cube_3mf, installed):
    # Given the same plain 3MF around the origin

    # When it is sliced with center on
    result = await server.slice_model(
        str(origin_cube_3mf), installed.printer, installed.print_profile, installed.filament, center=True
    )

    # Then it slices
    assert result.stats.layer_count


async def test_a_scan_with_no_base_slices_to_its_full_height_once_the_hole_is_closed(tmp_path, installed):
    # Given a 30 mm tall cylinder with no bottom, the shape of a scan whose underside was never captured
    full = trimesh.creation.cylinder(radius=10, height=30, sections=48)
    scan = tmp_path / "scan.stl"
    trimesh.Trimesh(full.vertices, full.faces[full.face_normals[:, 2] > -0.99]).export(scan)
    before = scan.read_bytes()

    # When it is sliced with close_holes
    result = await server.slice_model(
        str(scan), installed.printer, installed.print_profile, installed.filament, close_holes=True
    )

    # Then PrusaSlicer accepts the capped copy, prints all 30 mm, and the result says a hole was closed
    assert result.holes_closed == 1
    assert max(scan_gcode(Path(result.gcode_path)).layer_heights) == pytest.approx(30, abs=0.3)
    assert scan.read_bytes() == before  # the model file itself is not rewritten


@pytest.fixture
def step_cube_file(tmp_path):
    """A 20 mm cube as a STEP file, which trimesh cannot read."""
    path = tmp_path / "cube.step"
    path.write_text(step_cube(20))
    return path


async def test_inspect_model_measures_a_step_file_through_prusaslicer(step_cube_file):
    # Given a STEP cube, a format trimesh cannot read

    # When it is inspected
    info = await server.inspect_model(str(step_cube_file))

    # Then PrusaSlicer's conversion gives its real size and volume
    assert info.size_mm == pytest.approx((20, 20, 20), abs=0.01)
    assert info.volume_mm3 == pytest.approx(8000, rel=1e-3)
    assert info.watertight is True


async def test_preview_model_draws_a_step_file(step_cube_file):
    # Given a STEP cube

    # When it is previewed
    content = await server.preview_model(str(step_cube_file), "iso", 256)

    # Then there is a picture, and the caption gives the converted size
    assert any(isinstance(item, Image) and item.data for item in content)
    assert any(isinstance(item, str) and "20.0 x 20.0 x 20.0" in item for item in content)


async def test_a_step_file_slices(step_cube_file, installed):
    # Given a STEP cube and installed profiles

    # When it is sliced
    result = await server.slice_model(
        str(step_cube_file), installed.printer, installed.print_profile, installed.filament
    )

    # Then it prints
    assert result.stats.layer_count


async def test_a_broken_step_file_fails_with_a_message_that_says_what_to_check(tmp_path):
    # Given a file with a STEP name and no STEP content
    broken = tmp_path / "broken.step"
    broken.write_text("this is not a STEP file")

    # When it is inspected
    with pytest.raises(ToolError) as error:
        await server.inspect_model(str(broken))

    # Then the message names the file and the likely cause
    assert "could not convert broken.step" in str(error.value)
    assert "valid STEP file" in str(error.value)


def recorded_setting(result, key: str) -> str:
    """The value PrusaSlicer wrote for `key` in the config dump at the end of the G-code."""
    for line in reversed(Path(result.gcode_path).read_text().splitlines()):
        if line.startswith(f"; {key} = "):
            return line.split(" = ", 1)[1]
    raise AssertionError(f"{key} not found in the G-code")


async def test_slice_applies_a_projects_saved_settings_when_no_profiles_are_given(make_3mf):
    # Given a project 3MF that saves a 5 mm brim and supports
    project = make_3mf(config=PROJECT_CONFIG)

    # When it is sliced without profiles
    result = await server.slice_model(str(project))

    # Then PrusaSlicer recorded the project's settings in the G-code
    assert result.settings_from == "project"
    assert recorded_setting(result, "brim_width") == "5"
    assert recorded_setting(result, "support_material") == "1"


async def test_slice_with_profiles_ignores_a_projects_saved_settings(make_3mf, installed):
    # Given the same project, and an installed print profile that sets no brim
    project = make_3mf(config=PROJECT_CONFIG)

    # When it is sliced with profiles
    result = await server.slice_model(str(project), installed.printer, installed.print_profile, installed.filament)

    # Then the profile's values win over the project's saved brim
    assert result.settings_from == "profiles"
    assert recorded_setting(result, "brim_width") != "5"


async def test_slice_flags_a_model_that_has_an_empty_stretch_in_its_height(tmp_path, installed):
    # Given an STL of two cubes with 10 mm of air between them, so the upper one floats
    lower = trimesh.creation.box(extents=(20, 20, 10))
    lower.apply_translation((0, 0, 5))
    upper = trimesh.creation.box(extents=(20, 20, 10))
    upper.apply_translation((0, 0, 25))
    model = tmp_path / "floating.stl"
    trimesh.util.concatenate([lower, upper]).export(model)

    # When it is sliced with real profiles
    result = await server.slice_model(str(model), installed.printer, installed.print_profile, installed.filament)

    # Then the caller is told layers are missing, and where, from the real G-code's layer markers
    gap_warnings = [w for w in result.warnings if w.startswith("Nothing is printed across")]
    assert len(gap_warnings) == 1
    assert "between z 10" in gap_warnings[0]


async def test_slice_of_a_plain_cube_reports_no_empty_stretch(cube_stl, installed):
    # Given a solid cube

    # When it is sliced with real profiles
    result = await server.slice_model(str(cube_stl), installed.printer, installed.print_profile, installed.filament)

    # Then no layers are reported missing
    assert not any(w.startswith("Nothing is printed across") for w in result.warnings)


# --------------------------------------------------------------------------- transforms on real PrusaSlicer output


@pytest.fixture
def bar_stl(tmp_path):
    """A 10 x 20 x 30 mm box, so rotating or scaling it changes the number of layers in a predictable way."""
    path = tmp_path / "bar.stl"
    trimesh.creation.box(extents=(10, 20, 30)).export(path)
    return path


def ratio(numerator: float | None, denominator: float | None) -> float:
    """numerator / denominator, failing clearly if a statistic was not reported."""
    assert numerator is not None
    assert denominator is not None
    return numerator / denominator


async def slice_bar(model, installed, **extra):
    return await server.slice_model(str(model), installed.printer, installed.print_profile, installed.filament, **extra)


async def test_rotating_about_x_stands_the_box_on_its_side(bar_stl, installed):
    # Given a box 30 mm tall and 20 mm deep, sliced as it is and rotated 90 degrees about X
    plain = await slice_bar(bar_stl, installed)

    # When it is rotated 90 degrees about X
    rotated = await slice_bar(bar_stl, installed, rotate_x=90)

    # Then it is now 20 mm tall, so it has two thirds of the layers
    assert ratio(rotated.stats.layer_count, plain.stats.layer_count) == pytest.approx(20 / 30, abs=0.03)


def caption_of(content) -> str:
    return next(item for item in content if isinstance(item, str))


async def test_a_preview_with_a_rotation_shows_the_height_the_slice_prints(bar_stl, installed):
    # Given a 10 x 20 x 30 mm box rotated 90 degrees about X

    # When it is previewed and sliced with that rotation
    caption = caption_of(await server.preview_model(str(bar_stl), rotate_x=90.0))
    sliced = await slice_bar(bar_stl, installed, rotate_x=90)

    # Then the preview's size is the print's size: 10 x 30 wide, 20 tall
    assert "Size 10.0 x 30.0 x 20.0" in caption
    assert max(scan_gcode(Path(sliced.gcode_path)).layer_heights) == pytest.approx(20, abs=0.25)


@pytest.mark.parametrize(
    ("arguments", "size"),
    [
        ({"scale": 2.0}, "20.0 x 40.0 x 60.0"),
        ({"scale_to_fit": [100.0, 100.0, 15.0]}, "5.0 x 10.0 x 15.0"),
        ({"rotate_z": 90.0}, "20.0 x 10.0 x 30.0"),
    ],
    ids=["scale", "scale to fit", "rotate z"],
)
async def test_a_preview_applies_the_transforms_prusaslicer_applies(bar_stl, installed, arguments, size):
    # Given a 10 x 20 x 30 mm box

    # When it is previewed with a transform
    caption = caption_of(await server.preview_model(str(bar_stl), **arguments))

    # Then the size is what PrusaSlicer makes of it
    assert f"Size {size}" in caption


def tripod_stl(tmp_path):
    """Three arms of different lengths meeting at a corner, so every orientation looks different."""
    arms = [trimesh.creation.box(extents=e) for e in ((40, 8, 8), (8, 25, 8), (8, 8, 15))]
    for arm, shift in zip(arms, ([16, 0, 0], [0, 8.5, 0], [0, 0, 3.5]), strict=True):
        arm.apply_translation(shift)
    faces = np.vstack([arm.faces + sum(len(a.vertices) for a in arms[:i]) for i, arm in enumerate(arms)])
    path = tmp_path / "tripod.stl"
    trimesh.Trimesh(np.vstack([arm.vertices for arm in arms]), faces).export(path)
    return path


@pytest.mark.parametrize(
    "rotation",
    [{"rotate_x": 90.0}, {"rotate_y": 90.0, "rotate_z": -90.0}],
    ids=["plain rotation", "y 90 with z -90"],
)
async def test_a_previews_base_is_the_slices_first_layer_even_where_prusaslicer_is_odd(tmp_path, installed, rotation):
    # Given an asymmetric model. Rotating +-90 about Y and then about Z turns it a different way up from the
    # fixed X, Y, Z order that the other cases follow (measured on PrusaSlicer 2.9.7), which is why the preview asks
    # PrusaSlicer instead of working the rotation out itself.
    model = tripod_stl(tmp_path)

    # When it is previewed as PrusaSlicer transforms it, and sliced the same way
    flags = server._transform_args(
        rotation.get("rotate_x"), rotation.get("rotate_y"), rotation.get("rotate_z"), None, None, False, None
    )
    mesh = await server._export_mesh(model, flags)
    sliced = await slice_bar(model, installed, **rotation)

    # Then the footprint on the bed in the preview is the footprint of the first printed layer
    on_bed = mesh.vertices[:, 2] <= mesh.bounds[0][2] + 0.05
    previewed = np.ptp(mesh.vertices[on_bed][:, :2], axis=0)
    first_layer = [m for m in iter_extrusions(Path(sliced.gcode_path)) if m.layer == 0 and m.feature != "Skirt/Brim"]
    printed = (
        max(max(m.x0, m.x1) for m in first_layer) - min(min(m.x0, m.x1) for m in first_layer),
        max(max(m.y0, m.y1) for m in first_layer) - min(min(m.y0, m.y1) for m in first_layer),
    )
    assert printed == pytest.approx(tuple(previewed), abs=1.0)


async def test_scale_doubles_the_height(bar_stl, installed):
    # Given a box sliced at its own size
    plain = await slice_bar(bar_stl, installed)

    # When it is scaled by a factor of 2
    scaled = await slice_bar(bar_stl, installed, scale=2)

    # Then it is twice as tall, so it has twice the layers
    assert ratio(scaled.stats.layer_count, plain.stats.layer_count) == pytest.approx(2.0, abs=0.05)


async def test_scale_to_fit_shrinks_the_box_into_the_given_volume(bar_stl, installed):
    # Given a box 30 mm tall

    # When it is scaled to fit a 15 mm cube
    plain = await slice_bar(bar_stl, installed)
    fitted = await slice_bar(bar_stl, installed, scale_to_fit=[15, 15, 15])

    # Then the tallest side is halved, so it has half the layers
    assert ratio(fitted.stats.layer_count, plain.stats.layer_count) == pytest.approx(0.5, abs=0.03)


async def test_copies_print_that_many_objects(bar_stl, installed):
    # Given a box sliced once
    one = await slice_bar(bar_stl, installed)

    # When three copies are requested
    three = await slice_bar(bar_stl, installed, copies=3)

    # Then about three times the filament is used, and the layers are unchanged
    assert ratio(three.stats.filament_used_g, one.stats.filament_used_g) == pytest.approx(3.0, rel=0.1)
    assert three.stats.layer_count == one.stats.layer_count


async def test_split_brings_separate_solids_together_on_the_bed(tmp_path, installed):
    # Given one STL holding two solids 60 mm apart
    left = trimesh.creation.box(extents=(20, 20, 10))
    right = trimesh.creation.box(extents=(10, 10, 30))
    right.apply_translation((60, 0, 0))
    both = trimesh.util.concatenate([left, right])
    model = tmp_path / "two.stl"
    both.export(model)

    # When it is sliced as one object and then split (each width is measured before the next slice, because both
    # write the same default file)
    def printed_width(result) -> float:
        extent = scan_gcode(Path(result.gcode_path)).x_range
        return extent[1] - extent[0]

    plain_width = printed_width(await slice_bar(model, installed))
    split_width = printed_width(await slice_bar(model, installed, split=True))

    # Then PrusaSlicer re-arranges the separated solids, so the printed width shrinks
    assert split_width < plain_width * 0.7


async def test_a_projects_saved_settings_survive_a_rotation(make_3mf):
    # Given a project that saves a 5 mm brim, sliced as saved
    project = make_3mf(config=PROJECT_CONFIG)
    plain = await server.slice_model(str(project))

    # When it is sliced rotated about X with no profiles
    rotated = await server.slice_model(str(project), rotate_x=45)

    # Then it still uses the project's settings, and the model really was rotated
    assert rotated.settings_from == "project"
    assert recorded_setting(rotated, "brim_width") == "5"
    assert rotated.stats.layer_count != plain.stats.layer_count


async def test_a_plain_3mf_can_be_rotated_and_centred_together(origin_cube_3mf, installed):
    # Given a plain 3MF modelled around the origin, which only slices once it is centred on the bed

    # When it is rotated and centred
    result = await server.slice_model(
        str(origin_cube_3mf), installed.printer, installed.print_profile, installed.filament, rotate_x=90, center=True
    )

    # Then it slices
    assert result.stats.layer_count


async def test_a_refused_slice_does_not_reuse_the_file_from_an_earlier_slice(origin_cube_3mf, installed, tmp_path):
    # Given a good slice already written to a path (centred, so PrusaSlicer accepts it)
    target = tmp_path / "same.gcode"
    args = (str(origin_cube_3mf), installed.printer, installed.print_profile, installed.filament)
    await server.slice_model(*args, center=True, output_path=str(target))
    earlier = target.read_bytes()

    # When the same model is sliced to the same path with centring off, which PrusaSlicer refuses with exit code 0
    with pytest.raises(ToolError, match="outside of the print volume"):
        await server.slice_model(*args, center=False, output_path=str(target))

    # Then it is reported as a failure and the earlier file is left exactly as it was
    assert target.read_bytes() == earlier


async def test_a_refused_oversized_model_says_how_big_it_is_and_what_to_do(tmp_path, installed):
    # Given a model a metre long, far larger than any bed
    model = tmp_path / "huge.stl"
    trimesh.creation.box(extents=(1000, 20, 20)).export(model)

    # When it is sliced with real profiles
    with pytest.raises(ToolError) as error:
        await server.slice_model(str(model), installed.printer, installed.print_profile, installed.filament)

    # Then PrusaSlicer's refusal comes with the model's size and a scale_to_fit remedy, not a pointless recentre
    message = str(error.value)
    assert "outside of the print volume" in message
    assert "1000.0 x 20.0 x 20.0 mm" in message
    assert "scale_to_fit=[" in message
    assert "center=true" not in message
