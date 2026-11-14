"""Unit tests for slice_model's command line, output handling and failures (CLI faked, no PrusaSlicer).

Only `cli.run` is faked, so argument building, validation, output paths, warning extraction and
failure reporting are the real code under test.
"""

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from conftest import PROJECT_CONFIG
from mcp.server.mcpserver.exceptions import ToolError

from prusaslicer_mcp import cli, server
from prusaslicer_mcp.config import Config

FOOTER = """;LAYER_CHANGE
; filament used [mm] = 100.5
; total filament used [g] = 0.31
; estimated printing time (normal mode) = 12m 5s
"""

PROFILES = ("Mini", "0.20mm SPEED", "PLA")
NO_PROFILES = (None, None, None)
PROFILE_FLAGS = ("--printer-profile", "--print-profile", "--material-profile")
MK3S = "Original Prusa i3 MK3S & MK3S+ MMU2S Single"
PRINTERS = {
    "printer_models": [
        {
            "id": "MK3S",
            "name": "MK3S",
            "variants": [
                {
                    "name": 0.4,
                    "printer_profiles": [{"name": MK3S, "bed": {"width": 250, "height": 210, "max_print_height": 210}}],
                }
            ],
        }
    ]
}


@pytest.fixture
def fake_prusaslicer(tmp_path, monkeypatch):
    """A fake slicer. `.state` chooses what it writes and says; `.calls` records every command line."""
    monkeypatch.setattr(
        server,
        "_config",
        Config(executable=tmp_path / "PrusaSlicer", datadir=None, output_dir=tmp_path / "out", timeout=5),
    )
    calls: list[list[str]] = []
    state = SimpleNamespace(gcode=FOOTER.encode(), writes_output=True, returncode=0, stdout="", stderr="")

    async def fake_run(config, args, timeout=None):
        if "--query-printer-models" in args:
            Path(args[args.index("-o") + 1]).write_text(json.dumps(PRINTERS))
            return cli.CliResult(1, "", "")
        calls.append(args)
        if state.writes_output:
            Path(args[args.index("--output") + 1]).write_bytes(state.gcode)
        return cli.CliResult(state.returncode, state.stdout, state.stderr)

    monkeypatch.setattr(cli, "run", fake_run)
    return SimpleNamespace(calls=calls, state=state, out_dir=tmp_path / "out", tmp=tmp_path)


@pytest.fixture
def model(tmp_path):
    path = tmp_path / "part.stl"
    path.write_text("solid x\nendsolid x\n")
    return path


async def slice_it(model, profiles=PROFILES, **extra):
    return await server.slice_model(str(model), *profiles, **extra)


# --------------------------------------------------------------------------- the command line


async def test_command_line_asks_for_text_gcode_with_the_given_profiles(fake_prusaslicer, model):
    # Given a model and three profile names

    # When it is sliced
    await slice_it(model)

    # Then PrusaSlicer is asked for text G-code with exactly those profiles, and the model comes last
    args = fake_prusaslicer.calls[0]
    assert args[:2] == ["--export-gcode", "--binary-gcode=0"]
    assert args[2:8] == ["--printer-profile", "Mini", "--print-profile", "0.20mm SPEED", "--material-profile", "PLA"]
    assert args[-3] == "--output"
    assert args[-1] == str(model.resolve())


async def test_overrides_become_hyphenated_equals_flags(fake_prusaslicer, model):
    # Given two setting overrides written with underscores
    overrides = {"fill_density": "25%", "top_solid_layers": "5"}

    # When the model is sliced
    await slice_it(model, overrides=overrides)

    # Then each is passed as one --name=value argument between the profiles and the output
    args = fake_prusaslicer.calls[0]
    assert args[8:10] == ["--fill-density=25%", "--top-solid-layers=5"]
    assert args[10] == "--output"


async def test_override_values_are_passed_verbatim_as_one_argument(fake_prusaslicer, model):
    # Given a value full of characters a shell would interpret
    value = "a b; echo $(whoami) *"

    # When the model is sliced
    await slice_it(model, overrides={"start_gcode": value})

    # Then it reaches PrusaSlicer unchanged, as a single argument
    assert f"--start-gcode={value}" in fake_prusaslicer.calls[0]


async def test_no_overrides_add_no_extra_arguments(fake_prusaslicer, model):
    # Given no overrides and no centring

    # When the model is sliced
    await slice_it(model)

    # Then the command line is just the fixed part plus output and model
    assert len(fake_prusaslicer.calls[0]) == 8 + 3


@pytest.mark.parametrize("value", ["a\nb", "a\rb"], ids=["newline", "carriage-return"])
async def test_override_value_with_a_line_break_is_refused(fake_prusaslicer, model, value):
    # Given an override value containing a line break
    overrides = {"start_gcode": value}

    # When / Then slicing is refused and PrusaSlicer is never started
    with pytest.raises(ToolError, match="Invalid override value for 'start_gcode'"):
        await slice_it(model, overrides=overrides)
    assert fake_prusaslicer.calls == []


@pytest.mark.parametrize("key", ["Bad", "1x", "a b", "a-b", "", "--evil", "x=y"], ids=repr)
async def test_malformed_override_key_is_refused(fake_prusaslicer, model, key):
    # Given an override key that is not a lower-case option name
    overrides = {key: "1"}

    # When / Then slicing is refused and PrusaSlicer is never started
    with pytest.raises(ToolError, match="Invalid override key"):
        await slice_it(model, overrides=overrides)
    assert fake_prusaslicer.calls == []


@pytest.mark.parametrize(
    "key",
    [
        "binary_gcode",
        "export_gcode",
        "output",
        "datadir",
        "save",
        "printer_profile",
        "print_profile",
        "material_profile",
    ],
)
async def test_override_cannot_replace_a_setting_the_server_controls(fake_prusaslicer, model, key):
    # Given an override for a flag the server sets itself, or one that writes into the user's PrusaSlicer data
    overrides = {key: "1"}

    # When / Then slicing is refused and PrusaSlicer is never started
    with pytest.raises(ToolError, match="controlled by the server"):
        await slice_it(model, overrides=overrides)
    assert fake_prusaslicer.calls == []


# --------------------------------------------------------------------------- where the G-code goes


async def test_gcode_defaults_to_the_output_directory_named_after_the_model(fake_prusaslicer, model):
    # Given no output path and an output directory that does not exist yet

    # When the model is sliced
    result = await slice_it(model)

    # Then the G-code is <output dir>/<model name>.gcode and the directory was created
    assert result.gcode_path == str(fake_prusaslicer.out_dir / "part.gcode")
    assert (fake_prusaslicer.out_dir / "part.gcode").is_file()


async def test_explicit_output_path_is_used_and_its_last_folder_is_created(fake_prusaslicer, model):
    # Given an output path whose folder does not exist yet, inside a folder that does
    target = fake_prusaslicer.tmp / "results" / "result.gcode"

    # When the model is sliced
    result = await slice_it(model, output_path=str(target))

    # Then the G-code is written exactly there, and that one folder was created for it
    assert result.gcode_path == str(target)
    assert target.is_file()


async def test_tilde_in_output_path_is_expanded(fake_prusaslicer, model, monkeypatch):
    # Given an output path written relative to a home directory that exists
    (fake_prusaslicer.tmp / "home").mkdir()
    monkeypatch.setenv("HOME", str(fake_prusaslicer.tmp / "home"))

    # When the model is sliced
    result = await slice_it(model, output_path="~/gcode/result.gcode")

    # Then it lands under the home directory
    assert result.gcode_path == str(fake_prusaslicer.tmp / "home" / "gcode" / "result.gcode")


@pytest.mark.parametrize(
    "extra",
    [
        {"overrides": {"Bad": "1"}},
        {"overrides": {"binary_gcode": "1"}},
        {"overrides": {"a": "x\ny"}},
        {"profiles": NO_PROFILES},
        {"profiles": ("Mini", None, None)},
    ],
    ids=["bad-key", "reserved-key", "bad-value", "no-profiles-for-an-stl", "partial-profiles"],
)
async def test_a_refused_request_creates_no_folders(fake_prusaslicer, model, extra):
    # Given a request that will be refused, with an output path in folders that do not exist
    target = fake_prusaslicer.tmp / "should-not-exist" / "result.gcode"

    # When / Then it is refused
    with pytest.raises(ToolError):
        await slice_it(model, output_path=str(target), **extra)

    # And nothing was created on disk for it
    assert not target.parent.exists()


async def test_centring_on_an_unknown_printer_creates_no_folders(fake_prusaslicer, model, monkeypatch):
    # Given centring is requested but the printer's bed cannot be found
    async def no_such_bed(printer_profile):
        raise ToolError("Cannot centre on the bed")

    monkeypatch.setattr(server, "_bed_center", no_such_bed)
    target = fake_prusaslicer.tmp / "should-not-exist" / "result.gcode"

    # When / Then it is refused
    with pytest.raises(ToolError, match="Cannot centre"):
        await slice_it(model, output_path=str(target), center=True)

    # And nothing was created on disk for it
    assert not target.parent.exists()


# --------------------------------------------------------------------------- results and failures


async def test_statistics_come_from_the_gcode_footer(fake_prusaslicer, model):
    # Given PrusaSlicer writes G-code with a footer

    # When the model is sliced
    result = await slice_it(model)

    # Then the statistics are read from it
    assert result.stats.estimated_time == "12m 5s"
    assert result.stats.filament_used_g == 0.31
    assert result.stats.layer_count == 1


async def test_each_single_line_slicer_warning_is_returned_trimmed(fake_prusaslicer, model):
    # Given PrusaSlicer prints progress, a warning and a differently-cased warning
    fake_prusaslicer.state.stdout = "10 => Processing\n  Warning: thin walls  \n20 => Done\nWARNING: low bridge\n"

    # When the model is sliced
    result = await slice_it(model)

    # Then only the warning lines are returned, trimmed
    assert result.warnings == ["Warning: thin walls", "WARNING: low bridge"]


async def test_nonzero_exit_fails_even_if_an_old_output_file_exists(fake_prusaslicer, model):
    # Given a G-code file left over from an earlier run, and PrusaSlicer now exits with 2
    fake_prusaslicer.out_dir.mkdir()
    (fake_prusaslicer.out_dir / "part.gcode").write_bytes(FOOTER.encode())
    fake_prusaslicer.state.writes_output = False
    fake_prusaslicer.state.returncode = 2
    fake_prusaslicer.state.stderr = "boom"

    # When / Then the stale file is not mistaken for a result
    with pytest.raises(ToolError, match=r"Slicing failed \(exit 2\): boom"):
        await slice_it(model)


async def test_clean_exit_without_an_output_file_is_a_failure(fake_prusaslicer, model):
    # Given PrusaSlicer exits 0 but writes nothing
    fake_prusaslicer.state.writes_output = False
    fake_prusaslicer.state.stdout = "nothing to do"

    # When / Then it is reported as failed, using stdout as the explanation
    with pytest.raises(ToolError, match=r"Slicing failed \(exit 0\): nothing to do"):
        await slice_it(model)


async def test_only_the_tail_of_a_very_long_error_is_kept(fake_prusaslicer, model):
    # Given PrusaSlicer fails with 5000 characters of output ending in the real reason
    fake_prusaslicer.state.returncode = 1
    fake_prusaslicer.state.writes_output = False
    fake_prusaslicer.state.stderr = "HEAD" + "x" * 5000 + "the real reason"

    # When / Then the message ends with the reason and drops the start
    with pytest.raises(ToolError) as error:
        await slice_it(model)
    assert str(error.value).endswith("the real reason")
    assert "HEAD" not in str(error.value)


async def test_binary_gcode_output_is_reported_as_a_readable_failure(fake_prusaslicer, model):
    # Given PrusaSlicer writes binary G-code anyway
    fake_prusaslicer.state.gcode = b"GCDE" + b"\0" * 32

    # When / Then the statistics cannot be read, and the tool says why
    with pytest.raises(ToolError, match="Binary G-code"):
        await slice_it(model)


# --------------------------------------------------------------------------- PrusaSlicer projects (ADR 0007)


async def test_a_project_is_sliced_with_its_own_settings_when_no_profiles_are_given(fake_prusaslicer, make_3mf):
    # Given a 3MF saved from PrusaSlicer, with its own settings embedded
    project = make_3mf(config=PROJECT_CONFIG)

    # When it is sliced without profiles
    result = await slice_it(project, profiles=NO_PROFILES)

    # Then PrusaSlicer is given no profile flags, so the project's settings apply, and text G-code is still forced
    args = fake_prusaslicer.calls[0]
    assert not any(flag in args for flag in PROFILE_FLAGS)
    assert args[:2] == ["--export-gcode", "--binary-gcode=0"]
    assert result.settings_from == "project"


async def test_profiles_given_for_a_project_replace_its_settings(fake_prusaslicer, make_3mf):
    # Given a project and explicit profiles
    project = make_3mf(config=PROJECT_CONFIG)

    # When it is sliced with them
    result = await slice_it(project)

    # Then the profile flags are passed, which makes PrusaSlicer use the profiles and not the project's settings
    args = fake_prusaslicer.calls[0]
    assert all(flag in args for flag in PROFILE_FLAGS)
    assert result.settings_from == "profiles"


async def test_a_model_that_is_not_a_project_reports_that_profiles_were_used(fake_prusaslicer, model):
    # Given an STL and profiles

    # When it is sliced
    result = await slice_it(model)

    # Then the result says profiles were used
    assert result.settings_from == "profiles"


async def test_overrides_still_apply_on_top_of_a_projects_own_settings(fake_prusaslicer, make_3mf):
    # Given a project sliced without profiles, with one override
    project = make_3mf(config=PROJECT_CONFIG)

    # When it is sliced
    await slice_it(project, profiles=NO_PROFILES, overrides={"fill_density": "10%"})

    # Then the override is passed, and no profile flags are
    args = fake_prusaslicer.calls[0]
    assert "--fill-density=10%" in args
    assert not any(flag in args for flag in PROFILE_FLAGS)


async def test_centring_a_project_uses_the_bed_of_the_printer_stored_in_it(fake_prusaslicer, make_3mf):
    # Given a project that names a 250 x 210 mm printer, and no printer_profile argument
    project = make_3mf(config=PROJECT_CONFIG)

    # When it is sliced without profiles but centred
    await slice_it(project, profiles=NO_PROFILES, center=True)

    # Then PrusaSlicer is told to centre on that bed's middle
    args = fake_prusaslicer.calls[0]
    assert args[args.index("--center") + 1] == "125,105"


async def test_centring_a_project_that_does_not_name_its_printer_asks_for_one(fake_prusaslicer, make_3mf):
    # Given a project whose configuration has no printer profile name
    project = make_3mf(config="; fill_density = 20%\n")

    # When / Then centring it without a printer_profile is refused with advice
    with pytest.raises(ToolError, match="does not name its printer"):
        await slice_it(project, profiles=NO_PROFILES, center=True)
    assert fake_prusaslicer.calls == []


@pytest.mark.parametrize("kind", ["stl", "plain-3mf"])
async def test_a_model_that_is_not_a_project_needs_profiles(fake_prusaslicer, model, make_3mf, kind):
    # Given a model without embedded PrusaSlicer settings
    target = model if kind == "stl" else make_3mf(config=None)

    # When / Then slicing it without profiles is refused, saying what is needed
    with pytest.raises(ToolError, match="required unless the model is a PrusaSlicer project"):
        await slice_it(target, profiles=NO_PROFILES)
    assert fake_prusaslicer.calls == []


@pytest.mark.parametrize(
    "profiles",
    [("Mini", None, None), (None, "0.20mm SPEED", None), (None, None, "PLA"), ("Mini", "0.20mm SPEED", None)],
    ids=["printer-only", "print-only", "material-only", "no-material"],
)
async def test_some_but_not_all_profiles_is_refused_even_for_a_project(fake_prusaslicer, make_3mf, profiles):
    # Given a project and an incomplete set of profiles
    project = make_3mf(config=PROJECT_CONFIG)

    # When / Then slicing is refused, because a partial set would mix profile values with the project's
    with pytest.raises(ToolError, match="all three"):
        await slice_it(project, profiles=profiles)
    assert fake_prusaslicer.calls == []


async def test_empty_profile_names_count_as_given_profiles_and_are_left_for_prusaslicer_to_reject(
    fake_prusaslicer, make_3mf
):
    # Given a project and profile names that are present but empty
    project = make_3mf(config=PROJECT_CONFIG)

    # When it is sliced with them
    result = await slice_it(project, profiles=("", "", ""))

    # Then they are passed on as profiles (not silently replaced by the project's settings)
    assert result.settings_from == "profiles"
    assert fake_prusaslicer.calls[0][fake_prusaslicer.calls[0].index("--printer-profile") + 1] == ""


# --------------------------------------------------------------------------- how far an output path may reach


async def test_an_output_path_two_folders_deep_is_refused_because_it_is_probably_a_typo(fake_prusaslicer, model):
    # Given an output path where neither its folder nor that folder's parent exists
    target = fake_prusaslicer.tmp / "typo" / "also-typo" / "result.gcode"

    # When / Then it is refused with a message that names the path, and PrusaSlicer is never started
    with pytest.raises(ToolError, match=r"Cannot write .*result\.gcode.*neither"):
        await slice_it(model, output_path=str(target))
    assert fake_prusaslicer.calls == []


async def test_a_refused_deep_output_path_creates_no_folders(fake_prusaslicer, model):
    # Given the same too-deep output path
    target = fake_prusaslicer.tmp / "typo" / "also-typo" / "result.gcode"

    # When it is refused
    with pytest.raises(ToolError):
        await slice_it(model, output_path=str(target))

    # Then nothing was created on disk
    assert not (fake_prusaslicer.tmp / "typo").exists()


async def test_an_output_folder_that_is_a_file_is_refused(fake_prusaslicer, model):
    # Given a path whose "folder" is actually a regular file
    blocker = fake_prusaslicer.tmp / "not-a-folder"
    blocker.write_text("x")

    # When / Then slicing is refused readably, and PrusaSlicer is never started
    with pytest.raises(ToolError, match="not a folder"):
        await slice_it(model, output_path=str(blocker / "result.gcode"))
    assert fake_prusaslicer.calls == []


@pytest.mark.skipif(hasattr(os, "geteuid") and os.geteuid() == 0, reason="root ignores folder permissions")
async def test_a_folder_that_cannot_be_created_is_a_readable_failure(fake_prusaslicer, model):
    # Given a read-only folder, so creating a folder inside it is not allowed
    locked = fake_prusaslicer.tmp / "locked"
    locked.mkdir()
    locked.chmod(0o500)

    # When / Then slicing fails with a message naming the folder, not an opaque crash
    try:
        with pytest.raises(ToolError, match="Cannot create the output folder"):
            await slice_it(model, output_path=str(locked / "new" / "result.gcode"))
    finally:
        locked.chmod(0o700)
    assert fake_prusaslicer.calls == []


async def test_the_configured_output_directory_is_created_however_deep_it_is(fake_prusaslicer, model, monkeypatch):
    # Given an output directory set in the configuration that is several levels below an existing folder
    deep = fake_prusaslicer.tmp / "a" / "b" / "c"
    monkeypatch.setattr(
        server,
        "_config",
        server.get_config().__class__(
            executable=server.get_config().executable, datadir=None, output_dir=deep, timeout=5
        ),
    )

    # When the model is sliced without an output path
    result = await slice_it(model)

    # Then the whole configured directory is created, because that path is the user's own setting
    assert result.gcode_path == str(deep / "part.gcode")


async def test_a_multi_line_slicer_warning_is_returned_whole(fake_prusaslicer, model):
    # Given PrusaSlicer reports gaps in the model as a warning followed by detail and advice
    fake_prusaslicer.state.stdout = (
        "90 => Exporting G-code to /tmp/x.gcode\n"
        "print warning: Empty layer between 0.4 and 9.\n"
        "Empty layer between 9.2 and 11.4.\n"
        "\n"
        "Make sure the object is printable. Try to repair the model.\n"
        "Slicing result exported to /tmp/x.gcode\n"
    )

    # When the model is sliced
    result = await slice_it(model)

    # Then the caller gets one warning with every gap and the advice
    assert len(result.warnings) == 1
    assert "between 9.2 and 11.4" in result.warnings[0]
    assert "Try to repair the model." in result.warnings[0]
