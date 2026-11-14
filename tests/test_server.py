"""Integration tests against a real PrusaSlicer install (skipped when absent)."""

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from prusaslicer_mcp import server


@pytest.fixture(autouse=True)
def _reset_config(prusaslicer, tmp_path, monkeypatch):
    monkeypatch.setenv("PRUSASLICER_MCP_OUTPUT_DIR", str(tmp_path / "out"))
    server._config = None
    yield
    server._config = None


async def test_list_printers_and_profiles():
    printers = await server.list_printers()
    assert printers and all(p.variants for p in printers)
    assert all("&&" not in p.name for p in printers)
    profile = printers[0].variants[0].printer_profile
    profiles = await server.list_profiles(profile)
    assert profiles.print_profiles


def test_inspect_model(cube_stl):
    info = server.inspect_model(str(cube_stl), bed_width=180, bed_depth=180, max_height=180)
    assert info.watertight and info.fits_bed
    assert info.size_mm == pytest.approx((20, 20, 20))
    assert info.volume_mm3 == pytest.approx(8000)


def test_inspect_model_too_big(cube_stl):
    assert server.inspect_model(str(cube_stl), bed_width=10, bed_depth=10, max_height=10).fits_bed is False


async def test_slice_rejects_bad_override(cube_stl):
    with pytest.raises(ToolError, match="Invalid override key"):
        await server.slice_model(str(cube_stl), "x", "y", "z", overrides={"bad key; rm": "1"})


async def test_slice_model(cube_stl):
    printers = await server.list_printers()
    printer = next(v.printer_profile for p in printers for v in p.variants)
    profiles = await server.list_profiles(printer)
    pp = profiles.print_profiles[0]
    result = await server.slice_model(str(cube_stl), printer, pp.name, pp.filament_profiles[0], overrides={"fill_density": "10%"})
    assert result.stats.estimated_time_seconds
    assert result.stats.filament_used_g
    assert result.stats.layer_count


async def test_slice_plain_3mf_needs_center(tmp_path):
    """A 3MF modelled around the origin keeps its coordinates and starts half off the bed."""
    import trimesh

    model = tmp_path / "origin_cube.3mf"
    trimesh.creation.box(extents=(20, 20, 20)).export(model)
    printers = await server.list_printers()
    printer = next(v.printer_profile for p in printers for v in p.variants)
    pp = (await server.list_profiles(printer)).print_profiles[0]
    args = (str(model), printer, pp.name, pp.filament_profiles[0])

    with pytest.raises(ToolError, match="center=true"):
        await server.slice_model(*args)
    result = await server.slice_model(*args, center=True)
    assert result.stats.layer_count
