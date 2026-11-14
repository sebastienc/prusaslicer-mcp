"""MCP server exposing the PrusaSlicer 2.9.x command line to Claude."""

from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path
from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from . import cli
from .config import Config, load_config
from .gcode import GcodeStats, parse_gcode_stats

mcp = MCPServer(
    "prusaslicer",
    instructions=(
        "Headless PrusaSlicer 2.9.x. Discover exact profile names with list_printers and list_profiles, "
        "check a model with inspect_model, then slice_model. Profile names must match exactly."
    ),
)

_READ_ONLY = ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False)

_MODEL_SUFFIXES = {".stl", ".3mf", ".obj", ".amf", ".step", ".stp"}
_OVERRIDE_KEY = re.compile(r"^[a-z][a-z0-9_]*$")

_config: Config | None = None


def get_config() -> Config:
    global _config
    if _config is None:
        _config = load_config()
    return _config


def _model_path(path: str) -> Path:
    p = Path(path).expanduser().resolve()
    if not p.is_file():
        raise ValueError(f"Model file not found: {p}")
    if p.suffix.lower() not in _MODEL_SUFFIXES:
        raise ValueError(f"Unsupported model type '{p.suffix}'. Supported: {sorted(_MODEL_SUFFIXES)}")
    return p


async def _query_json(args: list[str]) -> dict[str, Any]:
    """Run a --query-* action and return the JSON it writes with -o."""
    cfg = get_config()
    with tempfile.TemporaryDirectory(prefix="prusaslicer-mcp-") as tmp:
        out = Path(tmp) / "result.json"
        result = await cli.run(cfg, [*args, "-o", str(out)], timeout=60)
        # PrusaSlicer 2.9.x exits with status 1 even when a --query-* action succeeds,
        # so success is judged by the output file, not the exit code.
        if not out.is_file() or out.stat().st_size == 0:
            raise RuntimeError(f"PrusaSlicer query failed (exit {result.returncode}): {result.stderr.strip() or result.stdout.strip()}")
        try:
            return json.loads(out.read_text())
        except json.JSONDecodeError as e:
            raise RuntimeError(f"PrusaSlicer produced invalid JSON: {e}") from e


# --------------------------------------------------------------------------- printers / profiles


class PrinterVariant(BaseModel):
    nozzle_diameter: float | str
    printer_profile: str
    extruders: int | None = None
    bed_width: float | None = None
    bed_depth: float | None = None
    max_print_height: float | None = None


class PrinterModel(BaseModel):
    id: str
    name: str
    technology: str
    variants: list[PrinterVariant]


def _display_name(name: str) -> str:
    # Vendor bundles store model names wx-escaped ("&&" renders as "&" in the GUI). Unescape so the
    # name reads naturally and matches the real profile names, which use a single "&".
    return name.replace("&&", "&")


@mcp.tool(annotations=_READ_ONLY)
async def list_printers(
    technology: Annotated[str, Field(description="'FFF' (filament) or 'SLA' (resin)")] = "FFF",
) -> list[PrinterModel]:
    """List the printer models installed in PrusaSlicer, with the exact printer profile
    names (use these as `printer_profile` elsewhere) and bed sizes."""
    if technology not in ("FFF", "SLA"):
        raise ValueError("technology must be 'FFF' or 'SLA'")
    data = await _query_json(["--query-printer-models", "--printer-technology", technology])
    models: list[PrinterModel] = []
    for m in data.get("printer_models", []):
        variants = []
        for v in m.get("variants", []):
            for p in v.get("printer_profiles", []):
                bed = p.get("bed", {})
                variants.append(
                    PrinterVariant(
                        nozzle_diameter=v.get("name"),
                        printer_profile=p["name"],
                        extruders=p.get("extruders_cnt"),
                        bed_width=bed.get("width"),
                        bed_depth=bed.get("height"),
                        max_print_height=bed.get("max_print_height"),
                    )
                )
        models.append(PrinterModel(id=m["id"], name=_display_name(m["name"]), technology=m.get("technology", technology), variants=variants))
    return models


class PrintProfile(BaseModel):
    name: str
    filament_profiles: list[str]


class ProfileList(BaseModel):
    printer_profile: str
    print_profiles: list[PrintProfile]


@mcp.tool(annotations=_READ_ONLY)
async def list_profiles(
    printer_profile: Annotated[str, Field(description="Exact printer profile name, from list_printers")],
) -> ProfileList:
    """List the print (quality) profiles and compatible filament profiles for a printer profile."""
    data = await _query_json(["--query-print-filament-profiles", "--printer-profile", printer_profile])
    return ProfileList(
        printer_profile=data.get("printer_profile", printer_profile),
        print_profiles=[
            PrintProfile(name=p["name"], filament_profiles=p.get("filament_profiles", []))
            for p in data.get("print_profiles", [])
        ],
    )


# --------------------------------------------------------------------------- model inspection


class ModelInfo(BaseModel):
    path: str
    triangles: int
    size_mm: tuple[float, float, float]
    bounds_min: tuple[float, float, float]
    bounds_max: tuple[float, float, float]
    volume_mm3: float | None
    surface_area_mm2: float
    watertight: bool
    connected_parts: int
    fits_bed: bool | None = None
    warnings: list[str]


@mcp.tool(annotations=_READ_ONLY)
def inspect_model(
    model_path: Annotated[str, Field(description="Absolute path to an STL/3MF/OBJ file")],
    bed_width: Annotated[float | None, Field(description="Bed X size in mm, to check fit")] = None,
    bed_depth: Annotated[float | None, Field(description="Bed Y size in mm, to check fit")] = None,
    max_height: Annotated[float | None, Field(description="Max print height in mm, to check fit")] = None,
) -> ModelInfo:
    """Check a model before slicing: size, volume, watertightness, number of separate parts,
    and (optionally) whether it fits a given build volume."""
    import trimesh

    path = _model_path(model_path)
    mesh = trimesh.load(path, force="mesh")
    if not isinstance(mesh, trimesh.Trimesh) or len(mesh.faces) == 0:
        raise ValueError("Could not load a triangle mesh from this file.")

    size = tuple(float(x) for x in mesh.extents)
    warnings: list[str] = []
    if not mesh.is_watertight:
        warnings.append("Mesh is not watertight (holes or non-manifold edges); PrusaSlicer may need to repair it.")
    elif not mesh.is_winding_consistent:
        warnings.append("Face winding is inconsistent.")
    parts = len(mesh.split(only_watertight=False))
    if parts > 1:
        warnings.append(f"Model has {parts} disconnected parts.")

    fits = None
    if None not in (bed_width, bed_depth, max_height):
        fits = size[0] <= bed_width and size[1] <= bed_depth and size[2] <= max_height  # type: ignore[operator]
        if not fits:
            warnings.append(f"Model ({size[0]:.1f}x{size[1]:.1f}x{size[2]:.1f} mm) exceeds the build volume in at least one axis (rotation not considered).")

    return ModelInfo(
        path=str(path),
        triangles=int(len(mesh.faces)),
        size_mm=size,  # type: ignore[arg-type]
        bounds_min=tuple(float(x) for x in mesh.bounds[0]),  # type: ignore[arg-type]
        bounds_max=tuple(float(x) for x in mesh.bounds[1]),  # type: ignore[arg-type]
        volume_mm3=float(mesh.volume) if mesh.is_watertight else None,
        surface_area_mm2=float(mesh.area),
        watertight=bool(mesh.is_watertight),
        connected_parts=parts,
        fits_bed=fits,
        warnings=warnings,
    )


# --------------------------------------------------------------------------- slicing


class SliceResult(BaseModel):
    gcode_path: str
    stats: GcodeStats
    warnings: list[str]


@mcp.tool()
async def slice_model(
    model_path: Annotated[str, Field(description="Absolute path to an STL/3MF/OBJ file")],
    printer_profile: Annotated[str, Field(description="Exact printer profile name, from list_printers")],
    print_profile: Annotated[str, Field(description="Exact print profile name, from list_profiles")],
    material_profile: Annotated[str, Field(description="Exact filament profile name, from list_profiles")],
    overrides: Annotated[
        dict[str, str] | None,
        Field(description="Optional PrusaSlicer settings, e.g. {'fill_density': '25%', 'perimeters': '3'}. Keys are config option names (see PrusaSlicer --help-fff)."),
    ] = None,
    output_path: Annotated[str | None, Field(description="Where to write the G-code (default: <output dir>/<model>.gcode)")] = None,
) -> SliceResult:
    """Slice a model headlessly using installed PrusaSlicer profiles and return the G-code path
    plus print time, filament use and layer count. G-code is always written as text (not .bgcode)."""
    cfg = get_config()
    model = _model_path(model_path)

    if output_path:
        out = Path(output_path).expanduser().resolve()
    else:
        cfg.output_dir.mkdir(parents=True, exist_ok=True)
        out = cfg.output_dir / f"{model.stem}.gcode"
    out.parent.mkdir(parents=True, exist_ok=True)

    args = [
        "--export-gcode",
        "--binary-gcode=0",
        "--printer-profile", printer_profile,
        "--print-profile", print_profile,
        "--material-profile", material_profile,
    ]
    for key, value in (overrides or {}).items():
        if not _OVERRIDE_KEY.match(key):
            raise ValueError(f"Invalid override key: {key!r}")
        if "\n" in value or "\r" in value:
            raise ValueError(f"Invalid override value for {key!r}")
        args.append(f"--{key.replace('_', '-')}={value}")
    args += ["--output", str(out), str(model)]

    result = await cli.run(cfg, args)
    if result.returncode != 0 or not out.is_file():
        detail = (result.stderr.strip() or result.stdout.strip())[-2000:]
        raise RuntimeError(f"Slicing failed (exit {result.returncode}): {detail}")

    warnings = [line.strip() for line in result.stdout.splitlines() if "warning" in line.lower()]
    return SliceResult(gcode_path=str(out), stats=parse_gcode_stats(out), warnings=warnings)


def main() -> None:
    mcp.run()
