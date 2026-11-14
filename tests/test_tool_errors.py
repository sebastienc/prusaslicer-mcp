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
    """Call a tool the way a client does and return the message the client would see."""
    with pytest.raises(ToolError) as exc:
        await server.mcp.call_tool(name, arguments)
    assert not isinstance(exc.value, UnexpectedToolError), f"crash, message withheld from client: {exc.value}"
    return str(exc.value)


async def test_bad_technology_is_readable():
    assert "technology must be 'FFF' or 'SLA'" in await tool_error("list_printers", {"technology": "X"})


async def test_missing_model_is_readable(tmp_path):
    assert "Model file not found" in await tool_error("inspect_model", {"model_path": str(tmp_path / "nope.stl")})


async def test_bad_override_key_is_readable(fake_config, model):
    msg = await tool_error(
        "slice_model",
        {"model_path": str(model), "printer_profile": "p", "print_profile": "q", "material_profile": "m",
         "overrides": {"bad key; rm": "1"}},
    )
    assert "Invalid override key" in msg


async def test_slicer_failure_text_reaches_client(fake_config, model, monkeypatch):
    async def fake_run(config, args, timeout=None):
        return cli.CliResult(0, "", "All objects are outside of the print volume.")

    monkeypatch.setattr(cli, "run", fake_run)
    msg = await tool_error(
        "slice_model",
        {"model_path": str(model), "printer_profile": "p", "print_profile": "q", "material_profile": "m"},
    )
    assert "All objects are outside of the print volume." in msg


async def test_timeout_is_readable(fake_config, model, monkeypatch):
    async def fake_run(config, args, timeout=None):
        raise cli.CliTimeout("PrusaSlicer did not finish within 5s")

    monkeypatch.setattr(cli, "run", fake_run)
    msg = await tool_error(
        "slice_model",
        {"model_path": str(model), "printer_profile": "p", "print_profile": "q", "material_profile": "m"},
    )
    assert "did not finish within 5s" in msg


async def test_missing_prusaslicer_is_readable(monkeypatch):
    def boom():
        raise PrusaSlicerNotFound("PrusaSlicer not found. Install it or set PRUSASLICER_PATH to the executable.")

    monkeypatch.setattr(server, "_config", None)
    monkeypatch.setattr(server, "load_config", boom)
    assert "PRUSASLICER_PATH" in await tool_error("list_printers", {})


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
    async def fake_run(config, args, timeout=None):
        return cli.CliResult(1, "", slicer_message)

    monkeypatch.setattr(cli, "run", fake_run)

    # When the model is sliced
    msg = await tool_error(
        "slice_model",
        {"model_path": str(model), "printer_profile": "p", "print_profile": "q", "material_profile": "m"},
    )

    # Then the slicer's own text is kept and the caller is told where the exact names come from
    assert "wasn't found" in msg
    assert "list_printers" in msg and "list_profiles" in msg


async def test_unrelated_slicer_error_gets_no_profile_hint(fake_config, model, monkeypatch):
    # Given PrusaSlicer fails for a reason that has nothing to do with profile names
    async def fake_run(config, args, timeout=None):
        return cli.CliResult(1, "", "Unknown option --fill-densty")

    monkeypatch.setattr(cli, "run", fake_run)

    # When the model is sliced
    msg = await tool_error(
        "slice_model",
        {"model_path": str(model), "printer_profile": "p", "print_profile": "q", "material_profile": "m"},
    )

    # Then the message is the slicer's text without a misleading profile hint
    assert "Unknown option --fill-densty" in msg
    assert "list_profiles" not in msg
