"""Failures must reach the model as readable ToolErrors, not opaque crashes.

In MCP SDK 2.x only ToolError text is sent to the client; any other exception (ValueError,
RuntimeError, ...) is reported as a bare "Error executing tool <name>". These tests go through
`mcp.call_tool`, the same path a real client takes, and need no PrusaSlicer install.
"""

import pytest
from mcp.server.mcpserver.exceptions import ToolError, UnexpectedToolError

from prusaslicer_mcp import cli, server
from prusaslicer_mcp.config import Config, PrusaSlicerNotFound


@pytest.fixture
def fake_config(tmp_path, monkeypatch):
    cfg = Config(executable=tmp_path / "PrusaSlicer", datadir=None, output_dir=tmp_path / "out", timeout=5)
    monkeypatch.setattr(server, "_config", cfg)
    return cfg


@pytest.fixture
def model(tmp_path):
    p = tmp_path / "part.stl"
    p.write_text("solid x\nendsolid x\n")
    return p


async def tool_error(name: str, arguments: dict) -> str:
    """Call a tool the way a client does and return the message the client would see.

    It also fails the test if the error is a crash, whose text the SDK withholds from the client.
    """
    with pytest.raises(ToolError) as exc:
        await server.mcp.call_tool(name, arguments)
    assert not isinstance(exc.value, UnexpectedToolError), f"crash, message withheld from client: {exc.value}"
    return str(exc.value)


def slice_arguments(model, **extra) -> dict:
    return {"model_path": str(model), "printer_profile": "p", "print_profile": "q", "material_profile": "m", **extra}


def slicer_says(monkeypatch, stderr: str, returncode: int = 0) -> None:
    """Fake the CLI so PrusaSlicer exits with this stderr."""

    async def fake_run(config, args, timeout=None):
        return cli.CliResult(returncode, "", stderr)

    monkeypatch.setattr(cli, "run", fake_run)


async def test_unsupported_technology_error_is_readable():
    # Given a technology that is neither FFF nor SLA
    arguments = {"technology": "X"}

    # When list_printers is called
    message = await tool_error("list_printers", arguments)

    # Then the client can read what was wrong
    assert "technology must be 'FFF' or 'SLA'" in message


async def test_missing_model_error_is_readable(tmp_path):
    # Given a model path that does not exist
    arguments = {"model_path": str(tmp_path / "nope.stl")}

    # When inspect_model is called
    message = await tool_error("inspect_model", arguments)

    # Then the client can read that the file was not found
    assert "Model file not found" in message


async def test_invalid_override_key_error_is_readable(fake_config, model):
    # Given an override key that is not a valid option name
    arguments = slice_arguments(model, overrides={"bad key; rm": "1"})

    # When slice_model is called
    message = await tool_error("slice_model", arguments)

    # Then the client can read which part was invalid
    assert "Invalid override key" in message


async def test_slicer_failure_text_reaches_the_client(fake_config, model, monkeypatch):
    # Given PrusaSlicer refuses the model with its own explanation
    slicer_says(monkeypatch, "All objects are outside of the print volume.")

    # When slice_model is called
    message = await tool_error("slice_model", slice_arguments(model))

    # Then PrusaSlicer's explanation is in the message the client sees
    assert "All objects are outside of the print volume." in message


async def test_timeout_error_is_readable(fake_config, model, monkeypatch):
    # Given PrusaSlicer runs past the configured timeout
    async def fake_run(config, args, timeout=None):
        raise cli.CliTimeout("PrusaSlicer did not finish within 5s")

    monkeypatch.setattr(cli, "run", fake_run)

    # When slice_model is called
    message = await tool_error("slice_model", slice_arguments(model))

    # Then the client can read that it timed out
    assert "did not finish within 5s" in message


async def test_missing_prusaslicer_error_tells_how_to_configure_it(monkeypatch):
    # Given no PrusaSlicer executable can be found
    def boom():
        raise PrusaSlicerNotFound("PrusaSlicer not found. Install it or set PRUSASLICER_PATH to the executable.")

    monkeypatch.setattr(server, "_config", None)
    monkeypatch.setattr(server, "load_config", boom)

    # When any tool that needs it is called
    message = await tool_error("list_printers", {})

    # Then the client is told which setting fixes it
    assert "PRUSASLICER_PATH" in message


@pytest.mark.parametrize(
    "slicer_message",
    [
        "Error while loading config from profiles: \nPrint profile '0.20mm SPEED' wasn't found.",
        "Error while loading config from profiles: \nPrinter profile 'Mini' wasn't found.",
        "Error while loading config from profiles: \nFilament profile 'PLA' wasn't found.",
    ],
    ids=["print-profile", "printer-profile", "filament-profile"],
)
async def test_unknown_profile_error_points_at_the_listing_tools(fake_config, model, monkeypatch, slicer_message):
    # Given PrusaSlicer cannot find one of the profile names it was given
    slicer_says(monkeypatch, slicer_message, returncode=1)

    # When the model is sliced
    msg = await tool_error("slice_model", slice_arguments(model))

    # Then the slicer's own text is kept and the caller is told where the exact names come from
    assert "wasn't found" in msg
    assert "list_printers" in msg and "list_profiles" in msg


async def test_unrelated_slicer_error_gets_no_profile_hint(fake_config, model, monkeypatch):
    # Given PrusaSlicer fails for a reason that has nothing to do with profile names
    slicer_says(monkeypatch, "Unknown option --fill-densty", returncode=1)

    # When the model is sliced
    msg = await tool_error("slice_model", slice_arguments(model))

    # Then the message is the slicer's text without a misleading profile hint
    assert "Unknown option --fill-densty" in msg
    assert "list_profiles" not in msg
