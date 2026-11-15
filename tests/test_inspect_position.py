"""inspect_model warns when a 3MF's stored position is off the bed (no PrusaSlicer needed).

PrusaSlicer places STL/OBJ files itself, but keeps a 3MF's stored coordinates. A part modelled around
the origin therefore fits the bed by size yet cannot be sliced without slice_model(center=true).
"""

import trimesh

from prusaslicer_mcp import server

BED = {"bed_width": 180, "bed_depth": 180, "max_height": 180}


def export_box(path, center):
    box = trimesh.creation.box(extents=(20, 20, 20))
    box.apply_translation(center)
    box.export(path)
    return path


def position_warnings(info):
    return [w for w in info.warnings if "off the bed" in w]


async def test_3mf_straddling_the_origin_warns_to_center(tmp_path):
    # Given a 20 mm cube saved in a 3MF around the origin, and a 180 mm bed
    model = export_box(tmp_path / "origin.3mf", center=(0, 0, 10))

    # When the model is inspected against the bed
    info = await server.inspect_model(str(model), **BED)

    # Then it still fits by size, and the stored position is flagged, saying slice_model centres it automatically
    assert info.fits_bed is True
    (warning,) = position_warnings(info)
    assert "centres a plain 3MF" in warning
    assert "center=false" in warning


async def test_3mf_inside_the_bed_has_no_position_warning(tmp_path):
    # Given a 20 mm cube saved in a 3MF in the middle of a 180 mm bed
    model = export_box(tmp_path / "placed.3mf", center=(90, 90, 10))

    # When the model is inspected against the bed
    info = await server.inspect_model(str(model), **BED)

    # Then there is nothing to warn about
    assert position_warnings(info) == []


async def test_stl_around_the_origin_has_no_position_warning(tmp_path):
    # Given the same off-bed placement but in an STL, which PrusaSlicer places automatically
    model = export_box(tmp_path / "origin.stl", center=(0, 0, 10))

    # When the model is inspected against the bed
    info = await server.inspect_model(str(model), **BED)

    # Then the position is not flagged
    assert position_warnings(info) == []


async def test_3mf_position_is_not_checked_without_a_bed(tmp_path):
    # Given a 3MF around the origin and no bed dimensions
    model = export_box(tmp_path / "origin.3mf", center=(0, 0, 10))

    # When the model is inspected without a bed
    info = await server.inspect_model(str(model))

    # Then no position warning is made up
    assert position_warnings(info) == []


async def test_a_project_off_the_bed_is_told_to_ask_for_centring(make_3mf):
    # Given a PrusaSlicer project whose stored position is off a 180 mm bed
    from conftest import PROJECT_CONFIG

    model = make_3mf(config=PROJECT_CONFIG, at=(0.0, 0.0, 10.0))

    # When it is inspected against the bed
    info = await server.inspect_model(str(model), **BED)

    # Then the warning says its layout is kept, and how to centre it, since it is not centred automatically
    (warning,) = position_warnings(info)
    assert "PrusaSlicer project" in warning
    assert "center=true" in warning
