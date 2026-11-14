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
    return [w for w in info.warnings if "center=true" in w]


def test_3mf_straddling_the_origin_warns_to_center(tmp_path):
    # Given a 20 mm cube saved in a 3MF around the origin, and a 180 mm bed
    model = export_box(tmp_path / "origin.3mf", center=(0, 0, 10))

    # When the model is inspected against the bed
    info = server.inspect_model(str(model), **BED)

    # Then it still fits by size, but the stored position is flagged with the remedy
    assert info.fits_bed is True
    assert len(position_warnings(info)) == 1


def test_3mf_inside_the_bed_has_no_position_warning(tmp_path):
    # Given a 20 mm cube saved in a 3MF in the middle of a 180 mm bed
    model = export_box(tmp_path / "placed.3mf", center=(90, 90, 10))

    # When the model is inspected against the bed
    info = server.inspect_model(str(model), **BED)

    # Then there is nothing to warn about
    assert position_warnings(info) == []


def test_stl_around_the_origin_has_no_position_warning(tmp_path):
    # Given the same off-bed placement but in an STL, which PrusaSlicer places automatically
    model = export_box(tmp_path / "origin.stl", center=(0, 0, 10))

    # When the model is inspected against the bed
    info = server.inspect_model(str(model), **BED)

    # Then the position is not flagged
    assert position_warnings(info) == []


def test_3mf_position_is_not_checked_without_a_bed(tmp_path):
    # Given a 3MF around the origin and no bed dimensions
    model = export_box(tmp_path / "origin.3mf", center=(0, 0, 10))

    # When the model is inspected without a bed
    info = server.inspect_model(str(model))

    # Then no position warning is made up
    assert position_warnings(info) == []
