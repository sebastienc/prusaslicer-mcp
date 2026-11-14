"""Integration tests against a real PrusaSlicer install (skipped when absent)."""

from types import SimpleNamespace

import pytest
import trimesh
from mcp.server.mcpserver.exceptions import ToolError

from prusaslicer_mcp import server


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
    return SimpleNamespace(printer=printer, print_profile=print_profile.name, filament=print_profile.filament_profiles[0])


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
    assert printers and all(p.variants for p in printers)


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


def test_inspect_model_reports_size_volume_and_fit_for_a_cube_on_a_large_bed(cube_stl):
    # Given a 20 mm cube and a 180 mm build volume

    # When the model is inspected against that volume
    info = server.inspect_model(str(cube_stl), bed_width=180, bed_depth=180, max_height=180)

    # Then it is watertight, fits, and has the cube's size and volume
    assert info.watertight and info.fits_bed
    assert info.size_mm == pytest.approx((20, 20, 20))
    assert info.volume_mm3 == pytest.approx(8000)


def test_inspect_model_reports_a_cube_as_not_fitting_a_tiny_bed(cube_stl):
    # Given a 20 mm cube and a 10 mm build volume

    # When the model is inspected against that volume
    info = server.inspect_model(str(cube_stl), bed_width=10, bed_depth=10, max_height=10)

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


async def test_slice_refuses_a_plain_3mf_around_the_origin_and_suggests_center(origin_cube_3mf, installed):
    # Given a plain 3MF that keeps its stored coordinates and so sits half off the bed

    # When / Then slicing it as it is fails with the remedy in the message
    with pytest.raises(ToolError, match="center=true"):
        await server.slice_model(str(origin_cube_3mf), installed.printer, installed.print_profile, installed.filament)


async def test_slice_places_a_plain_3mf_around_the_origin_when_centered(origin_cube_3mf, installed):
    # Given the same plain 3MF around the origin

    # When it is sliced with center on
    result = await server.slice_model(
        str(origin_cube_3mf), installed.printer, installed.print_profile, installed.filament, center=True
    )

    # Then it slices
    assert result.stats.layer_count
