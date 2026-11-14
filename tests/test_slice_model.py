"""Unit tests for slice_model's command line, output handling and failures (CLI faked, no PrusaSlicer).

Only `cli.run` is faked, so argument building, validation, output paths, warning extraction and
failure reporting are the real code under test.
"""

from pathlib import Path
from types import SimpleNamespace

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from prusaslicer_mcp import cli, server
from prusaslicer_mcp.config import Config

FOOTER = """;LAYER_CHANGE
; filament used [mm] = 100.5
; total filament used [g] = 0.31
; estimated printing time (normal mode) = 12m 5s
"""

PROFILES = ("Mini", "0.20mm SPEED", "PLA")


@pytest.fixture
def prusaslicer(tmp_path, monkeypatch):
    """A fake slicer. `.state` chooses what it writes and says; `.calls` records every command line."""
    monkeypatch.setattr(
        server, "_config", Config(executable=tmp_path / "PrusaSlicer", datadir=None, output_dir=tmp_path / "out", timeout=5)
    )
    calls: list[list[str]] = []
    state = SimpleNamespace(gcode=FOOTER.encode(), writes_output=True, returncode=0, stdout="", stderr="")

    async def fake_run(config, args, timeout=None):
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


async def slice_it(model, **extra):
    return await server.slice_model(str(model), *PROFILES, **extra)


# --------------------------------------------------------------------------- the command line


async def test_command_line_asks_for_text_gcode_with_the_given_profiles(prusaslicer, model):
    # Given a model and three profile names

    # When it is sliced
    await slice_it(model)

    # Then PrusaSlicer is asked for text G-code with exactly those profiles, and the model comes last
    args = prusaslicer.calls[0]
    assert args[:2] == ["--export-gcode", "--binary-gcode=0"]
    assert args[2:8] == ["--printer-profile", "Mini", "--print-profile", "0.20mm SPEED", "--material-profile", "PLA"]
    assert args[-3] == "--output" and args[-1] == str(model.resolve())


async def test_overrides_become_hyphenated_equals_flags(prusaslicer, model):
    # Given two setting overrides written with underscores
    overrides = {"fill_density": "25%", "top_solid_layers": "5"}

    # When the model is sliced
    await slice_it(model, overrides=overrides)

    # Then each is passed as one --name=value argument between the profiles and the output
    args = prusaslicer.calls[0]
    assert args[8:10] == ["--fill-density=25%", "--top-solid-layers=5"]
    assert args[10] == "--output"


async def test_override_values_are_passed_verbatim_as_one_argument(prusaslicer, model):
    # Given a value full of characters a shell would interpret
    value = "a b; echo $(whoami) *"

    # When the model is sliced
    await slice_it(model, overrides={"start_gcode": value})

    # Then it reaches PrusaSlicer unchanged, as a single argument
    assert f"--start-gcode={value}" in prusaslicer.calls[0]


async def test_no_overrides_add_no_extra_arguments(prusaslicer, model):
    # Given no overrides and no centring

    # When the model is sliced
    await slice_it(model)

    # Then the command line is just the fixed part plus output and model
    assert len(prusaslicer.calls[0]) == 8 + 3


@pytest.mark.parametrize("value", ["a\nb", "a\rb"], ids=["newline", "carriage-return"])
async def test_override_value_with_a_line_break_is_refused(prusaslicer, model, value):
    # Given an override value containing a line break
    overrides = {"start_gcode": value}

    # When / Then slicing is refused and PrusaSlicer is never started
    with pytest.raises(ToolError, match="Invalid override value for 'start_gcode'"):
        await slice_it(model, overrides=overrides)
    assert prusaslicer.calls == []


@pytest.mark.parametrize("key", ["Bad", "1x", "a b", "a-b", "", "--evil", "x=y"], ids=repr)
async def test_malformed_override_key_is_refused(prusaslicer, model, key):
    # Given an override key that is not a lower-case option name
    overrides = {key: "1"}

    # When / Then slicing is refused and PrusaSlicer is never started
    with pytest.raises(ToolError, match="Invalid override key"):
        await slice_it(model, overrides=overrides)
    assert prusaslicer.calls == []


@pytest.mark.parametrize(
    "key", ["binary_gcode", "export_gcode", "output", "datadir", "save", "printer_profile", "print_profile", "material_profile"]
)
async def test_override_cannot_replace_a_setting_the_server_controls(prusaslicer, model, key):
    # Given an override for a flag the server sets itself, or one that writes into the user's PrusaSlicer data
    overrides = {key: "1"}

    # When / Then slicing is refused and PrusaSlicer is never started
    with pytest.raises(ToolError, match="controlled by the server"):
        await slice_it(model, overrides=overrides)
    assert prusaslicer.calls == []


# --------------------------------------------------------------------------- where the G-code goes


async def test_gcode_defaults_to_the_output_directory_named_after_the_model(prusaslicer, model):
    # Given no output path and an output directory that does not exist yet

    # When the model is sliced
    result = await slice_it(model)

    # Then the G-code is <output dir>/<model name>.gcode and the directory was created
    assert result.gcode_path == str(prusaslicer.out_dir / "part.gcode")
    assert (prusaslicer.out_dir / "part.gcode").is_file()


async def test_explicit_output_path_is_used_and_its_folders_are_created(prusaslicer, model):
    # Given an output path inside folders that do not exist yet
    target = prusaslicer.tmp / "deep" / "er" / "result.gcode"

    # When the model is sliced
    result = await slice_it(model, output_path=str(target))

    # Then the G-code is written exactly there
    assert result.gcode_path == str(target)
    assert target.is_file()


async def test_tilde_in_output_path_is_expanded(prusaslicer, model, monkeypatch):
    # Given an output path written relative to the home directory
    monkeypatch.setenv("HOME", str(prusaslicer.tmp / "home"))

    # When the model is sliced
    result = await slice_it(model, output_path="~/gcode/result.gcode")

    # Then it lands under the home directory
    assert result.gcode_path == str(prusaslicer.tmp / "home" / "gcode" / "result.gcode")


@pytest.mark.parametrize(
    "extra",
    [{"overrides": {"Bad": "1"}}, {"overrides": {"binary_gcode": "1"}}, {"overrides": {"a": "x\ny"}}],
    ids=["bad-key", "reserved-key", "bad-value"],
)
async def test_a_refused_request_creates_no_folders(prusaslicer, model, extra):
    # Given a request that will be refused, with an output path in folders that do not exist
    target = prusaslicer.tmp / "should-not-exist" / "result.gcode"

    # When / Then it is refused
    with pytest.raises(ToolError):
        await slice_it(model, output_path=str(target), **extra)

    # And nothing was created on disk for it
    assert not target.parent.exists()


async def test_centring_on_an_unknown_printer_creates_no_folders(prusaslicer, model, monkeypatch):
    # Given centring is requested but the printer's bed cannot be found
    async def no_such_bed(printer_profile):
        raise ToolError("Cannot centre on the bed")

    monkeypatch.setattr(server, "_bed_center", no_such_bed)
    target = prusaslicer.tmp / "should-not-exist" / "result.gcode"

    # When / Then it is refused
    with pytest.raises(ToolError, match="Cannot centre"):
        await slice_it(model, output_path=str(target), center=True)

    # And nothing was created on disk for it
    assert not target.parent.exists()


# --------------------------------------------------------------------------- results and failures


async def test_statistics_come_from_the_gcode_footer(prusaslicer, model):
    # Given PrusaSlicer writes G-code with a footer

    # When the model is sliced
    result = await slice_it(model)

    # Then the statistics are read from it
    assert result.stats.estimated_time == "12m 5s"
    assert result.stats.filament_used_g == 0.31
    assert result.stats.layer_count == 1


async def test_warnings_are_the_slicers_stdout_lines_mentioning_warning(prusaslicer, model):
    # Given PrusaSlicer prints progress, a warning and a differently-cased warning
    prusaslicer.state.stdout = "10 => Processing\n  Warning: thin walls  \n20 => Done\nWARNING: low bridge\n"

    # When the model is sliced
    result = await slice_it(model)

    # Then only the warning lines are returned, trimmed
    assert result.warnings == ["Warning: thin walls", "WARNING: low bridge"]


async def test_nonzero_exit_fails_even_if_an_old_output_file_exists(prusaslicer, model):
    # Given a G-code file left over from an earlier run, and PrusaSlicer now exits with 2
    prusaslicer.out_dir.mkdir()
    (prusaslicer.out_dir / "part.gcode").write_bytes(FOOTER.encode())
    prusaslicer.state.writes_output = False
    prusaslicer.state.returncode = 2
    prusaslicer.state.stderr = "boom"

    # When / Then the stale file is not mistaken for a result
    with pytest.raises(ToolError, match=r"Slicing failed \(exit 2\): boom"):
        await slice_it(model)


async def test_clean_exit_without_an_output_file_is_a_failure(prusaslicer, model):
    # Given PrusaSlicer exits 0 but writes nothing
    prusaslicer.state.writes_output = False
    prusaslicer.state.stdout = "nothing to do"

    # When / Then it is reported as failed, using stdout as the explanation
    with pytest.raises(ToolError, match=r"Slicing failed \(exit 0\): nothing to do"):
        await slice_it(model)


async def test_only_the_tail_of_a_very_long_error_is_kept(prusaslicer, model):
    # Given PrusaSlicer fails with 5000 characters of output ending in the real reason
    prusaslicer.state.returncode = 1
    prusaslicer.state.writes_output = False
    prusaslicer.state.stderr = "HEAD" + "x" * 5000 + "the real reason"

    # When / Then the message ends with the reason and drops the start
    with pytest.raises(ToolError) as error:
        await slice_it(model)
    assert str(error.value).endswith("the real reason")
    assert "HEAD" not in str(error.value)


async def test_binary_gcode_output_is_reported_as_a_readable_failure(prusaslicer, model):
    # Given PrusaSlicer writes binary G-code anyway
    prusaslicer.state.gcode = b"GCDE" + b"\0" * 32

    # When / Then the statistics cannot be read, and the tool says why
    with pytest.raises(ToolError, match="Binary G-code"):
        await slice_it(model)
