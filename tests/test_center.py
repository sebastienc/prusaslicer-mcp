"""slice_model's `center` option (no PrusaSlicer needed; the CLI is faked).

Plain 3MF files keep their stored coordinates, so a model modelled around the origin lands half
off the bed and PrusaSlicer refuses to slice it. `center=True` passes --center <bed middle>.
"""

import json
from pathlib import Path

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from prusaslicer_mcp import cli, server
from prusaslicer_mcp.config import Config

PRINTERS = {
    "printer_models": [
        {
            "id": "MINIIS",
            "name": "Original Prusa MINI && MINI+ Input Shaper",
            "variants": [
                {
                    "name": "0.4",
                    "printer_profiles": [
                        {"name": "Mini", "extruders_cnt": 1, "bed": {"width": 180, "height": 180, "max_print_height": 180}}
                    ],
                },
                {
                    "name": "0.4",
                    "printer_profiles": [
                        {"name": "MK3S", "extruders_cnt": 1, "bed": {"width": 250, "height": 210, "max_print_height": 210}}
                    ],
                },
            ],
        }
    ]
}


@pytest.fixture
def slicer(tmp_path, monkeypatch):
    """Fake CLI: answers the printer query, records slice calls, writes a stub G-code file."""
    monkeypatch.setattr(
        server, "_config", Config(executable=tmp_path / "PrusaSlicer", datadir=None, output_dir=tmp_path / "out", timeout=5)
    )
    calls: list[list[str]] = []
    state = {"stderr": ""}

    async def fake_run(config, args, timeout=None):
        if "--query-printer-models" in args:
            Path(args[args.index("-o") + 1]).write_text(json.dumps(PRINTERS))
            return cli.CliResult(1, "", "")
        calls.append(args)
        if state["stderr"]:
            return cli.CliResult(0, "", state["stderr"])
        Path(args[args.index("--output") + 1]).write_text("; layer_count = 1\n")
        return cli.CliResult(0, "", "")

    monkeypatch.setattr(cli, "run", fake_run)
    return type("Slicer", (), {"calls": calls, "state": state})


@pytest.fixture
def model(tmp_path):
    p = tmp_path / "part.3mf"
    p.write_bytes(b"x")
    return p


def slice_args(model, printer="Mini", **extra):
    return {"model_path": str(model), "printer_profile": printer, "print_profile": "q", "material_profile": "m", **extra}


async def test_center_uses_the_middle_of_the_bed(slicer, model):
    await server.mcp.call_tool("slice_model", slice_args(model, center=True))
    args = slicer.calls[0]
    assert args[args.index("--center") + 1] == "90,90"


async def test_center_follows_bed_size(slicer, model):
    await server.mcp.call_tool("slice_model", slice_args(model, printer="MK3S", center=True))
    args = slicer.calls[0]
    assert args[args.index("--center") + 1] == "125,105"


async def test_default_does_not_move_the_model(slicer, model):
    await server.mcp.call_tool("slice_model", slice_args(model))
    assert "--center" not in slicer.calls[0]


async def test_center_with_unknown_printer_profile_is_readable(slicer, model):
    with pytest.raises(ToolError, match="Nope"):
        await server.mcp.call_tool("slice_model", slice_args(model, printer="Nope", center=True))
    assert slicer.calls == []


async def test_outside_print_volume_suggests_center(slicer, model):
    slicer.state["stderr"] = "All objects are outside of the print volume."
    with pytest.raises(ToolError, match="center=true"):
        await server.mcp.call_tool("slice_model", slice_args(model))
