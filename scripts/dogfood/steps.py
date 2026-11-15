"""The per-file steps of the dogfood sweep. Each runs in its own process (see sweep.py) and returns one result row."""

from __future__ import annotations

import asyncio
import time
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any

from mcp.server.mcpserver import Image
from mcp.server.mcpserver.exceptions import ToolError

from prusaslicer_mcp import server
from prusaslicer_mcp.preview_gcode import scan_gcode
from prusaslicer_mcp.project import read_project

if TYPE_CHECKING:
    from pathlib import Path

STEPS = ("inspect", "preview_model", "slice")
_PICTURE_SIZE = 640
_NOTE_LIMIT = 400


@dataclass(frozen=True)
class Setup:
    """The printer and profiles every non-project model is sliced with, and the bed inspections compare against."""

    printer_profile: str
    print_profile: str
    material_profile: str
    bed_width: float
    bed_depth: float
    max_height: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


async def choose_setup(
    printer_profile: str | None = None, print_profile: str | None = None, material_profile: str | None = None
) -> Setup:
    """Use the named profiles, or the first installed printer with its first print profile and filament."""
    variants = [variant for model in await server.list_printers() for variant in model.variants]
    if not variants:
        raise RuntimeError("PrusaSlicer reports no installed printers; run it once and pick one in the setup wizard")
    variant = (
        next((v for v in variants if v.printer_profile == printer_profile), None) if printer_profile else variants[0]
    )
    if variant is None:
        raise RuntimeError(f"printer profile {printer_profile!r} is not installed")
    profiles = await server.list_profiles(variant.printer_profile)
    chosen = next((p for p in profiles.print_profiles if p.name == print_profile), None) if print_profile else None
    chosen = chosen or profiles.print_profiles[0]
    return Setup(
        printer_profile=variant.printer_profile,
        print_profile=chosen.name,
        material_profile=material_profile or chosen.filament_profiles[0],
        bed_width=variant.bed_width or 180,
        bed_depth=variant.bed_depth or 180,
        max_height=variant.max_print_height or 180,
    )


def _picture(content: list[Image | str]) -> bytes:
    image = next(item for item in content if isinstance(item, Image))
    assert image.data is not None
    return image.data


def _inspect(path: Path, setup: Setup) -> dict[str, Any]:
    info = server.inspect_model(str(path), setup.bed_width, setup.bed_depth, setup.max_height)
    return {
        "triangles": info.triangles,
        "size": [round(value, 1) for value in info.size_mm],
        "watertight": info.watertight,
        "parts": info.connected_parts,
        "fits": info.fits_bed,
        "warnings": info.warnings,
        "project": info.project.model_dump() if info.project else None,
    }


def _preview_model(path: Path, out_dir: Path) -> dict[str, Any]:
    (out_dir / "model.png").write_bytes(_picture(server.preview_model(str(path), "sheet", _PICTURE_SIZE)))
    return {}


def _slice(path: Path, setup: Setup, out_dir: Path) -> dict[str, Any]:
    gcode = out_dir / "print.gcode"
    gcode.unlink(missing_ok=True)
    try:
        if read_project(path):  # a PrusaSlicer project is sliced with its own saved settings
            result = asyncio.run(server.slice_model(str(path), output_path=str(gcode)))
        else:
            result = asyncio.run(
                server.slice_model(
                    str(path),
                    setup.printer_profile,
                    setup.print_profile,
                    setup.material_profile,
                    output_path=str(gcode),
                )
            )
        row: dict[str, Any] = {
            "settings_from": result.settings_from,
            "centered": result.centered,
            "estimated_time": result.stats.estimated_time,
            "grams": result.stats.filament_used_g,
            "layers": result.stats.layer_count,
            "warnings": [warning[:_NOTE_LIMIT] for warning in result.warnings],
        }
        try:
            row["printed_height"] = max(scan_gcode(gcode).layer_heights)
            (out_dir / "print.png").write_bytes(
                _picture(server.preview_gcode(str(gcode), "profile", None, _PICTURE_SIZE))
            )
        except ToolError as error:
            row["profile_preview_error"] = str(error)[:_NOTE_LIMIT]
        return row
    finally:
        gcode.unlink(missing_ok=True)  # G-code can be hundreds of MB and is not needed once it has been read


def run_step(step: str, path: Path, setup: Setup, out_dir: Path) -> dict[str, Any]:
    """Run one step on one file. A refusal is recorded with its message; any other exception is recorded as a crash."""
    out_dir.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    row: dict[str, Any] = {"step": step}
    try:
        if step == "inspect":
            row.update(_inspect(path, setup))
        elif step == "preview_model":
            row.update(_preview_model(path, out_dir))
        elif step == "slice":
            row.update(_slice(path, setup, out_dir))
        else:
            raise ValueError(f"unknown step {step!r}")
        row["ok"] = True
    except ToolError as error:
        row.update(ok=False, error=str(error)[:600])
    except Exception as error:
        row.update(ok=False, crash=f"{type(error).__name__}: {str(error)[:300]}")
    row["seconds"] = round(time.perf_counter() - started, 1)
    return row
