"""Unit tests for reading the settings stored in a PrusaSlicer project 3MF (no PrusaSlicer needed)."""

import pytest

from prusaslicer_mcp.project import read_project

from conftest import PROJECT_CONFIG


@pytest.mark.parametrize("name", ["part.3mf", "PART.3MF", "Part.3mf"])
def test_a_3mf_saved_from_prusaslicer_is_a_project(make_3mf, name):
    # Given a 3MF that embeds PrusaSlicer's configuration, whatever the case of its extension
    model = make_3mf(name=name, config=PROJECT_CONFIG)

    # When it is read as a project
    project = read_project(model)

    # Then it is recognised
    assert project is not None


def test_the_profile_names_stored_in_the_project_are_reported(make_3mf):
    # Given a project whose configuration names its printer, print and filament profiles
    model = make_3mf(config=PROJECT_CONFIG)

    # When it is read as a project
    project = read_project(model)

    # Then the three names are reported, without the quotes around the filament name
    assert project.printer_profile == "Original Prusa i3 MK3S & MK3S+ MMU2S Single"
    assert project.print_profile == "0.20mm QUALITY @MK3"
    assert project.material_profile == "Prusament PLA"


def test_several_filaments_are_listed_together(make_3mf):
    # Given a multi-material project that stores one quoted filament name per extruder
    config = PROJECT_CONFIG.replace('"Prusament PLA"', '"Prusament PLA";"Prusament PETG"')
    model = make_3mf(config=config)

    # When it is read as a project
    project = read_project(model)

    # Then all of them are reported
    assert project.material_profile == "Prusament PLA; Prusament PETG"


def test_the_settings_that_decide_a_print_are_reported(make_3mf):
    # Given a project with infill, shells, brim and supports configured
    model = make_3mf(config=PROJECT_CONFIG)

    # When it is read as a project
    project = read_project(model)

    # Then those settings are reported as the project stores them
    assert project.settings == {
        "layer_height": "0.2",
        "perimeters": "2",
        "fill_density": "20%",
        "fill_pattern": "gyroid",
        "top_solid_layers": "6",
        "bottom_solid_layers": "4",
        "brim_width": "5",
        "support_material": "1",
        "support_material_auto": "1",
    }


def test_settings_missing_from_the_project_are_left_out(make_3mf):
    # Given a project whose configuration only sets the infill
    model = make_3mf(config="; fill_density = 35%\n")

    # When it is read as a project
    project = read_project(model)

    # Then only that setting is reported, and the profile names are unknown
    assert project.settings == {"fill_density": "35%"}
    assert (project.printer_profile, project.print_profile, project.material_profile) == (None, None, None)


def test_a_3mf_without_embedded_configuration_is_not_a_project(make_3mf):
    # Given a plain 3MF, such as one exported from CAD
    model = make_3mf(config=None)

    # When it is read as a project
    project = read_project(model)

    # Then it is not one
    assert project is None


def test_a_file_that_is_not_a_3mf_is_not_a_project(tmp_path):
    # Given an STL
    model = tmp_path / "part.stl"
    model.write_text("solid x\nendsolid x\n")

    # When it is read as a project
    project = read_project(model)

    # Then it is not one
    assert project is None


def test_a_damaged_3mf_is_not_a_project(tmp_path):
    # Given a file named .3mf that is not a zip archive
    model = tmp_path / "broken.3mf"
    model.write_bytes(b"this is not a zip file")

    # When it is read as a project
    project = read_project(model)

    # Then it is not one, instead of an error
    assert project is None


def test_a_zip_with_a_project_configuration_under_another_extension_is_not_a_project(make_3mf, tmp_path):
    # Given a real project archive that has been given an STL extension
    renamed = make_3mf(config=PROJECT_CONFIG).rename(tmp_path / "part.stl")

    # When it is read as a project
    project = read_project(renamed)

    # Then only .3mf files count as projects
    assert project is None
