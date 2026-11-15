"""Unit tests for locating PrusaSlicer and its data directory (no PrusaSlicer needed).

Every test runs on a fake machine: an empty home directory, an empty PATH, and install-location
globs that point into tmp_path, so the real install on the developer's machine cannot leak in.
"""

import sys
from types import SimpleNamespace

import pytest

from prusaslicer_mcp import config
from prusaslicer_mcp.config import ConfigError, PrusaSlicerNotFound, default_datadir, find_executable, load_config

ENV_VARS = (
    "PRUSASLICER_PATH",
    "PRUSASLICER_DATADIR",
    "PRUSASLICER_MCP_OUTPUT_DIR",
    "PRUSASLICER_MCP_TIMEOUT",
    "APPDATA",
    "LOCALAPPDATA",
    "ProgramFiles",
    "ProgramW6432",
    "ProgramFiles(x86)",
)


@pytest.fixture(autouse=True)
def machine(tmp_path, monkeypatch, set_home):
    """A fake machine with nothing installed: empty home, empty PATH, install globs under tmp_path."""
    for var in ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    home = tmp_path / "home"
    path_dir = tmp_path / "bin"
    home.mkdir()
    path_dir.mkdir()
    set_home(home)
    monkeypatch.setenv("PATH", str(path_dir))
    monkeypatch.setattr(
        config, "_MAC_GLOBS", [str(tmp_path / "Applications/*/PrusaSlicer.app/Contents/MacOS/PrusaSlicer")]
    )
    monkeypatch.setenv("ProgramFiles", str(tmp_path / "ProgramFiles"))
    monkeypatch.setenv("ProgramFiles(x86)", str(tmp_path / "ProgramFiles (x86)"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalAppData"))
    return SimpleNamespace(root=tmp_path, home=home, path_dir=path_dir)


def on_platform(monkeypatch, name):
    monkeypatch.setattr(config, "sys", SimpleNamespace(platform=name))


needs_posix_permissions = pytest.mark.skipif(
    sys.platform == "win32", reason="Windows reports every existing file as executable (os.access ignores the mode)"
)


def make_file(path, executable=True):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n")
    path.chmod(0o755 if executable else 0o644)
    return path


# --------------------------------------------------------------------------- find_executable


def test_executable_from_prusaslicer_path_is_used(machine, monkeypatch):
    # Given PRUSASLICER_PATH points at an executable, and a different one is on PATH
    chosen = make_file(machine.root / "custom/PrusaSlicer")
    make_file(machine.path_dir / "prusa-slicer")
    monkeypatch.setenv("PRUSASLICER_PATH", str(chosen))

    # When the executable is located
    found = find_executable()

    # Then the variable wins over PATH
    assert found == chosen


def test_tilde_in_prusaslicer_path_is_expanded(machine, monkeypatch):
    # Given PRUSASLICER_PATH written relative to the home directory
    expected = make_file(machine.home / "apps/PrusaSlicer")
    monkeypatch.setenv("PRUSASLICER_PATH", "~/apps/PrusaSlicer")

    # When the executable is located
    found = find_executable()

    # Then the home directory is substituted
    assert found == expected


@pytest.mark.parametrize("problem", [pytest.param("not-executable", marks=needs_posix_permissions), "missing"])
def test_invalid_prusaslicer_path_is_an_error_not_a_fallback(machine, monkeypatch, problem):
    # Given PRUSASLICER_PATH is set to something unusable, while a working one is on PATH
    bad = machine.root / "bad/PrusaSlicer"
    if problem == "not-executable":
        make_file(bad, executable=False)
    make_file(machine.path_dir / "prusa-slicer")
    monkeypatch.setenv("PRUSASLICER_PATH", str(bad))

    # When / Then locating it fails loudly instead of silently using the one on PATH
    with pytest.raises(PrusaSlicerNotFound, match="PRUSASLICER_PATH is set but not an executable file"):
        find_executable()


@pytest.mark.parametrize("name", ["prusa-slicer", "PrusaSlicer", "prusa-slicer-console"])
def test_executable_is_found_on_path(machine, name):
    # Given no variable is set and a known executable name is on PATH (Windows only runs files with an extension)
    expected = make_file(machine.path_dir / (name + (".exe" if sys.platform == "win32" else "")))

    # When the executable is located
    found = find_executable()

    # Then the PATH entry is used
    assert found == expected


def test_macos_install_in_a_nonstandard_folder_is_found(machine, monkeypatch):
    # Given a Mac whose PrusaSlicer.app sits in a folder with a space in its name, and nothing on PATH
    on_platform(monkeypatch, "darwin")
    expected = make_file(
        machine.root / "Applications/Original Prusa Drivers/PrusaSlicer.app/Contents/MacOS/PrusaSlicer"
    )

    # When the executable is located
    found = find_executable()

    # Then the install is found through the Applications glob
    assert found == expected


@needs_posix_permissions
def test_non_executable_file_at_an_install_location_is_skipped(machine, monkeypatch):
    # Given a Mac install location holding a file that is not executable
    on_platform(monkeypatch, "darwin")
    make_file(machine.root / "Applications/Broken/PrusaSlicer.app/Contents/MacOS/PrusaSlicer", executable=False)

    # When / Then it is not mistaken for an install
    with pytest.raises(PrusaSlicerNotFound):
        find_executable()


def test_windows_install_location_is_found(machine, monkeypatch):
    # Given a Windows machine with PrusaSlicer's console executable in its install folder
    on_platform(monkeypatch, "win32")
    expected = make_file(machine.root / "ProgramFiles/Prusa3D/PrusaSlicer/prusa-slicer-console.exe")

    # When the executable is located
    found = find_executable()

    # Then the install is found
    assert found == expected


@pytest.mark.parametrize(
    "location",
    [
        "ProgramFiles (x86)/Prusa3D/PrusaSlicer/prusa-slicer-console.exe",
        "ProgramFiles/PrusaSlicer/prusa-slicer-console.exe",
        "ProgramFiles/Prusa3D/PrusaSlicer-2.9.7/prusa-slicer-console.exe",
        "LocalAppData/Programs/PrusaSlicer/prusa-slicer-console.exe",
        "LocalAppData/Programs/PrusaSlicer-2.9.7/prusa-slicer-console.exe",
    ],
    ids=[
        "x86-program-files",
        "without-the-vendor-folder",
        "versioned-folder",
        "per-user-install",
        "per-user-versioned",
    ],
)
def test_windows_installs_in_other_usual_places_are_found(machine, monkeypatch, location):
    # Given a Windows machine whose PrusaSlicer is somewhere other than the default folder
    on_platform(monkeypatch, "win32")
    expected = make_file(machine.root / location)

    # When the executable is located
    found = find_executable()

    # Then the install is found
    assert found == expected


def test_windows_install_locations_follow_the_environment_not_the_c_drive(machine, monkeypatch):
    # Given Program Files on another drive, as the environment reports it
    on_platform(monkeypatch, "win32")
    monkeypatch.setenv("ProgramFiles", str(machine.root / "D-drive/Programmes"))
    expected = make_file(machine.root / "D-drive/Programmes/Prusa3D/PrusaSlicer/prusa-slicer-console.exe")

    # When the executable is located
    found = find_executable()

    # Then it is found there
    assert found == expected


def test_a_program_files_folder_with_glob_characters_in_its_name_is_still_searched(machine, monkeypatch):
    # Given a Program Files folder whose name contains square brackets, which a glob would read as a character set
    on_platform(monkeypatch, "win32")
    monkeypatch.setenv("ProgramFiles", str(machine.root / "Programs [work]"))
    expected = make_file(machine.root / "Programs [work]/Prusa3D/PrusaSlicer/prusa-slicer-console.exe")

    # When the executable is located
    found = find_executable()

    # Then the folder is taken literally and the install is found
    assert found == expected


def test_windows_without_the_environment_variables_finds_nothing_and_does_not_crash(machine, monkeypatch):
    # Given a Windows machine where the usual folder variables are missing
    on_platform(monkeypatch, "win32")
    for var in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
        monkeypatch.delenv(var)

    # When / Then the search ends in the normal "not found" error
    with pytest.raises(PrusaSlicerNotFound):
        find_executable()


def test_the_console_build_is_used_when_given_the_gui_build_next_to_it(machine, monkeypatch):
    # Given PRUSASLICER_PATH pointing at the Windows GUI program, which writes nothing to stdout,
    # with the console program beside it
    gui = make_file(machine.root / "PrusaSlicer/prusa-slicer.exe")
    console = make_file(machine.root / "PrusaSlicer/prusa-slicer-console.exe")
    monkeypatch.setenv("PRUSASLICER_PATH", str(gui))

    # When the executable is located
    found = find_executable()

    # Then the console build is used, so warnings and errors are not lost
    assert found == console


def test_the_console_build_is_used_when_the_gui_build_is_found_on_path(machine, monkeypatch):
    # Given the GUI program on PATH (Windows adds the extension, whatever its case), with the console program beside it
    gui = make_file(machine.root / "PrusaSlicer/prusa-slicer.EXE")
    console = make_file(machine.root / "PrusaSlicer/prusa-slicer-console.exe")
    monkeypatch.setattr(config.shutil, "which", lambda name: str(gui) if name == "prusa-slicer" else None)

    # When the executable is located
    found = find_executable()

    # Then the console build is used
    assert found == console


def test_the_gui_build_is_kept_when_there_is_no_console_build(machine, monkeypatch):
    # Given PRUSASLICER_PATH pointing at a GUI program with no console program beside it
    gui = make_file(machine.root / "PrusaSlicer/prusa-slicer.exe")
    monkeypatch.setenv("PRUSASLICER_PATH", str(gui))

    # When the executable is located
    found = find_executable()

    # Then what the user pointed at is used as it is
    assert found == gui


@pytest.mark.parametrize(
    ("platform", "foreign_location"),
    [
        ("linux", "Applications/Custom/PrusaSlicer.app/Contents/MacOS/PrusaSlicer"),
        ("linux", "ProgramFiles/Prusa3D/PrusaSlicer/prusa-slicer-console.exe"),
        ("darwin", "ProgramFiles/Prusa3D/PrusaSlicer/prusa-slicer-console.exe"),
        ("win32", "Applications/Custom/PrusaSlicer.app/Contents/MacOS/PrusaSlicer"),
    ],
    ids=["linux-ignores-mac", "linux-ignores-windows", "mac-ignores-windows", "windows-ignores-mac"],
)
def test_install_locations_are_only_searched_for_the_current_platform(machine, monkeypatch, platform, foreign_location):
    # Given a machine whose only PrusaSlicer is at another platform's install location
    on_platform(monkeypatch, platform)
    make_file(machine.root / foreign_location)

    # When / Then it is not found, because each platform searches only its own locations
    with pytest.raises(PrusaSlicerNotFound):
        find_executable()


def test_not_found_error_says_how_to_configure_it(monkeypatch):
    # Given a machine with no PrusaSlicer anywhere
    on_platform(monkeypatch, "darwin")

    # When / Then the error names the variable that fixes it
    with pytest.raises(PrusaSlicerNotFound, match="PRUSASLICER_PATH"):
        find_executable()


# --------------------------------------------------------------------------- default_datadir


def test_datadir_variable_is_returned_as_given_with_tilde_expanded(machine, monkeypatch):
    # Given PRUSASLICER_DATADIR relative to home, at a directory that does not exist yet
    monkeypatch.setenv("PRUSASLICER_DATADIR", "~/profiles")

    # When the data directory is resolved
    datadir = default_datadir()

    # Then the variable is trusted and expanded
    assert datadir == machine.home / "profiles"


@pytest.mark.parametrize(
    ("platform", "relative"),
    [("darwin", "Library/Application Support/PrusaSlicer"), ("linux", ".config/PrusaSlicer")],
)
def test_default_datadir_is_the_platform_location_when_it_exists(machine, monkeypatch, platform, relative):
    # Given a platform whose PrusaSlicer data directory exists under home
    on_platform(monkeypatch, platform)
    expected = machine.home / relative
    expected.mkdir(parents=True)

    # When the data directory is resolved
    datadir = default_datadir()

    # Then the platform location is returned
    assert datadir == expected


def test_windows_default_datadir_is_under_appdata(machine, monkeypatch):
    # Given a Windows machine whose APPDATA holds a PrusaSlicer directory
    on_platform(monkeypatch, "win32")
    appdata = machine.root / "AppData"
    (appdata / "PrusaSlicer").mkdir(parents=True)
    monkeypatch.setenv("APPDATA", str(appdata))

    # When the data directory is resolved
    datadir = default_datadir()

    # Then it is APPDATA/PrusaSlicer
    assert datadir == appdata / "PrusaSlicer"


@pytest.mark.parametrize("platform", ["darwin", "linux"])
def test_no_datadir_when_the_platform_location_is_missing(monkeypatch, platform):
    # Given a platform whose PrusaSlicer data directory has never been created
    on_platform(monkeypatch, platform)

    # When the data directory is resolved
    datadir = default_datadir()

    # Then there is none, so PrusaSlicer uses its own default
    assert datadir is None


# --------------------------------------------------------------------------- load_config


@pytest.fixture
def installed_slicer(machine, monkeypatch):
    path = make_file(machine.root / "custom/PrusaSlicer")
    monkeypatch.setenv("PRUSASLICER_PATH", str(path))
    return path


def test_config_defaults(installed_slicer, machine, monkeypatch):
    # Given only the executable is configured, and the server runs from some working directory
    work = machine.root / "work"
    work.mkdir()
    monkeypatch.chdir(work)

    # When the configuration is loaded
    cfg = load_config()

    # Then output goes to ./output, the timeout is 600 s, and there is no datadir
    assert cfg.executable == installed_slicer
    assert cfg.output_dir == (work / "output").resolve()
    assert cfg.timeout == 600
    assert cfg.datadir is None


def test_config_reads_overrides_from_the_environment(installed_slicer, machine, monkeypatch):
    # Given the output directory, timeout and data directory are all set in the environment
    monkeypatch.setenv("PRUSASLICER_MCP_OUTPUT_DIR", str(machine.root / "gcode"))
    monkeypatch.setenv("PRUSASLICER_MCP_TIMEOUT", "12.5")
    monkeypatch.setenv("PRUSASLICER_DATADIR", str(machine.root / "data"))

    # When the configuration is loaded
    cfg = load_config()

    # Then each value is taken from its variable
    assert cfg.output_dir == machine.root / "gcode"
    assert cfg.timeout == 12.5
    assert cfg.datadir == machine.root / "data"


@pytest.mark.parametrize("value", ["abc", "", "0", "-5"], ids=["not-a-number", "empty", "zero", "negative"])
def test_invalid_timeout_is_a_configuration_error_naming_the_variable(installed_slicer, monkeypatch, value):
    # Given the timeout variable holds something that is not a positive number
    monkeypatch.setenv("PRUSASLICER_MCP_TIMEOUT", value)

    # When / Then loading the configuration fails with an error that names the variable
    with pytest.raises(ConfigError, match="PRUSASLICER_MCP_TIMEOUT"):
        load_config()


def test_missing_prusaslicer_counts_as_a_configuration_error():
    # Given no PrusaSlicer anywhere

    # When / Then the not-found error can be caught as a configuration error
    with pytest.raises(ConfigError):
        find_executable()
