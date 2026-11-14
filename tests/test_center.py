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
                        {
                            "name": "Mini",
                            "extruders_cnt": 1,
                            "bed": {"width": 180, "height": 180, "max_print_height": 180},
                        }
                    ],
                },
                {
                    "name": "0.4",
                    "printer_profiles": [
                        {
                            "name": "MK3S",
                            "extruders_cnt": 1,
                            "bed": {"width": 250, "height": 210, "max_print_height": 210},
                        }
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
        server,
        "_config",
        Config(executable=tmp_path / "PrusaSlicer", datadir=None, output_dir=tmp_path / "out", timeout=5),
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
    return {
        "model_path": str(model),
        "printer_profile": printer,
        "print_profile": "q",
        "material_profile": "m",
        **extra,
    }


def centre_passed_to_prusaslicer(slicer) -> str:
    args = slicer.calls[0]
    return args[args.index("--center") + 1]


async def test_center_uses_the_middle_of_a_180_mm_bed(slicer, model):
    # Given a printer profile whose bed is 180 x 180 mm and a model file
    arguments = slice_args(model, printer="Mini", center=True)

    # When the model is sliced with center on
    await server.mcp.call_tool("slice_model", arguments)

    # Then PrusaSlicer is told to centre on 90,90
    assert centre_passed_to_prusaslicer(slicer) == "90,90"


async def test_center_follows_the_bed_size_of_the_printer_profile(slicer, model):
    # Given a printer profile whose bed is 250 x 210 mm
    arguments = slice_args(model, printer="MK3S", center=True)

    # When the model is sliced with center on
    await server.mcp.call_tool("slice_model", arguments)

    # Then PrusaSlicer is told to centre on 125,105
    assert centre_passed_to_prusaslicer(slicer) == "125,105"


async def test_a_plain_3mf_is_not_moved_when_center_is_false(slicer, model):
    # Given a plain 3MF and an explicit request not to move it (the default would now centre it, ADR 0013)
    arguments = slice_args(model, center=False)

    # When the model is sliced
    await server.mcp.call_tool("slice_model", arguments)

    # Then no --center flag reaches PrusaSlicer
    assert "--center" not in slicer.calls[0]


async def test_center_with_an_unknown_printer_profile_is_refused_before_slicing(slicer, model):
    # Given a printer profile that is not among the installed ones
    arguments = slice_args(model, printer="Nope", center=True)

    # When / Then slicing is refused naming the profile, and PrusaSlicer is never asked to slice
    with pytest.raises(ToolError, match="Nope"):
        await server.mcp.call_tool("slice_model", arguments)
    assert slicer.calls == []


async def test_outside_print_volume_failure_suggests_center(slicer, model):
    # Given PrusaSlicer reports that the model is off the bed
    slicer.state["stderr"] = "All objects are outside of the print volume."

    # When / Then slicing without centring (switched off, since a plain 3MF is centred by default) fails with the remedy
    with pytest.raises(ToolError, match="center=true"):
        await server.mcp.call_tool("slice_model", slice_args(model, center=False))
