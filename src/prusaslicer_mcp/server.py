"""MCP server exposing the PrusaSlicer 2.9.x command line to Claude."""

from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path
from typing import Annotated, Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from . import cli
from .config import Config, ConfigError, load_config
from .gcode import GcodeStats, layer_gap_warning, parse_gcode_stats
from .project import ProjectInfo, read_project
from .slicer_output import parse_warnings

mcp = MCPServer(
    "prusaslicer",
    instructions=(
        "Headless PrusaSlicer 2.9.x. Discover exact profile names with list_printers and list_profiles, "
        "check a model with inspect_model, then slice_model. Profile names must match exactly."
    ),
)

_READ_ONLY = ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=False)

_MODEL_SUFFIXES = {".stl", ".3mf", ".obj", ".amf", ".step", ".stp"}
_OVERRIDE_KEY = re.compile(r"^[a-z][a-z0-9_]*$")
# Flags the server sets itself, plus `save`, which would write into the user's PrusaSlicer data directory.
# An override with one of these names would silently undo a guarantee (e.g. binary_gcode=1 beats our text G-code).
_RESERVED_OVERRIDES = frozenset(
    {
        "export_gcode",
        "binary_gcode",
        "printer_profile",
        "print_profile",
        "material_profile",
        "output",
        "datadir",
        "save",
        "center",
    }
)
_PROFILE_NOT_FOUND = re.compile(r"profile '.*' wasn't found", re.IGNORECASE)
_PROFILE_HINT = " (hint: profile names must match exactly; get them from list_printers and list_profiles)"

_config: Config | None = None


def get_config() -> Config:
    global _config
    if _config is None:
        try:
            _config = load_config()
        except ConfigError as e:
            raise ToolError(str(e)) from e
    return _config


async def _run(cfg: Config, args: list[str], timeout: float | None = None) -> cli.CliResult:
    try:
        return await cli.run(cfg, args, timeout=timeout)
    except cli.CliTimeout as e:
        raise ToolError(str(e)) from e


def _with_profile_hint(detail: str) -> str:
    return detail + _PROFILE_HINT if _PROFILE_NOT_FOUND.search(detail) else detail


def _chosen_profiles(
    printer: str | None, print_: str | None, material: str | None, project: ProjectInfo | None
) -> tuple[str, str, str] | None:
    """The three profile names to slice with, or None to use the project's own saved settings (ADR 0007).

    All three or none: a partial set would mix profile values with the project's. None is only for a project.
    """
    if printer is not None and print_ is not None and material is not None:
        return printer, print_, material
    if printer is None and print_ is None and material is None:
        if project is None:
            raise ToolError(
                "printer_profile, print_profile and material_profile are required unless the model is a PrusaSlicer "
                "project (a .3mf saved from PrusaSlicer), which is sliced with its own settings"
            )
        return None
    raise ToolError("Give all three profiles (printer_profile, print_profile, material_profile) or none")


def _model_path(path: str) -> Path:
    p = Path(path).expanduser().resolve()
    if not p.is_file():
        raise ToolError(f"Model file not found: {p}")
    if p.suffix.lower() not in _MODEL_SUFFIXES:
        raise ToolError(f"Unsupported model type '{p.suffix}'. Supported: {sorted(_MODEL_SUFFIXES)}")
    return p


async def _query_json(args: list[str]) -> dict[str, Any]:
    """Run a --query-* action and return the JSON it writes with -o."""
    cfg = get_config()
    with tempfile.TemporaryDirectory(prefix="prusaslicer-mcp-") as tmp:
        out = Path(tmp) / "result.json"
        result = await _run(cfg, [*args, "-o", str(out)], timeout=60)
        # PrusaSlicer 2.9.x exits with status 1 even when a --query-* action succeeds,
        # so success is judged by the output file, not the exit code.
        if not out.is_file() or out.stat().st_size == 0:
            detail = _with_profile_hint(result.stderr.strip() or result.stdout.strip())
            raise ToolError(f"PrusaSlicer query failed (exit {result.returncode}): {detail}")
        try:
            return json.loads(out.read_text())
        except json.JSONDecodeError as e:
            raise ToolError(f"PrusaSlicer produced invalid JSON: {e}") from e


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


async def _bed_center(printer_profile: str) -> tuple[float, float]:
    """Middle of the bed for a known FFF printer profile (assumes the bed origin is a corner)."""
    data = await _query_json(["--query-printer-models", "--printer-technology", "FFF"])
    for m in data.get("printer_models", []):
        for v in m.get("variants", []):
            for p in v.get("printer_profiles", []):
                bed = p.get("bed", {})
                if p.get("name") == printer_profile and bed.get("width") and bed.get("height"):
                    return bed["width"] / 2, bed["height"] / 2
    raise ToolError(
        f"Cannot centre on the bed: printer profile {printer_profile!r} was not found with a bed size. "
        "Use the exact name from list_printers."
    )


@mcp.tool(annotations=_READ_ONLY)
async def list_printers(
    technology: Annotated[str, Field(description="'FFF' (filament) or 'SLA' (resin)")] = "FFF",
) -> list[PrinterModel]:
    """List the printer models installed in PrusaSlicer, with the exact printer profile
    names (use these as `printer_profile` elsewhere) and bed sizes."""
    if technology not in ("FFF", "SLA"):
        raise ToolError("technology must be 'FFF' or 'SLA'")
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
        models.append(
            PrinterModel(
                id=m["id"], name=_display_name(m["name"]), technology=m.get("technology", technology), variants=variants
            )
        )
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
    project: ProjectInfo | None = None
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
    try:
        mesh = trimesh.load(path, force="mesh")
    except (
        Exception
    ) as e:  # trimesh's parsers raise assorted types on bad input (BadZipFile, ValueError, ImportError, ...)
        raise ToolError(f"Could not read {path.name} as a {path.suffix.lower()} model: {e}") from e
    if not isinstance(mesh, trimesh.Trimesh) or len(mesh.faces) == 0:
        raise ToolError("Could not load a triangle mesh from this file.")

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
    if bed_width is not None and bed_depth is not None and max_height is not None:
        fits = size[0] <= bed_width and size[1] <= bed_depth and size[2] <= max_height
        if not fits:
            warnings.append(
                f"Model ({size[0]:.1f}x{size[1]:.1f}x{size[2]:.1f} mm) exceeds the build volume in at least one axis (rotation not considered)."
            )

    # PrusaSlicer places STL/OBJ itself but keeps a 3MF's stored coordinates, so a 3MF that fits by size
    # can still sit off the bed (e.g. modelled around the origin) and fail to slice.
    if path.suffix.lower() == ".3mf" and bed_width is not None and bed_depth is not None:
        lo, hi = mesh.bounds
        if lo[0] < 0 or lo[1] < 0 or hi[0] > bed_width or hi[1] > bed_depth:
            warnings.append(
                f"Stored position is off the bed (x {lo[0]:.1f}..{hi[0]:.1f}, y {lo[1]:.1f}..{hi[1]:.1f} mm; "
                f"bed is 0..{bed_width:g} by 0..{bed_depth:g}). PrusaSlicer keeps a 3MF's position, so slice "
                "it with slice_model center=true."
            )

    return ModelInfo(
        path=str(path),
        triangles=len(mesh.faces),
        size_mm=size,  # type: ignore[arg-type]
        bounds_min=tuple(float(x) for x in mesh.bounds[0]),  # type: ignore[arg-type]
        bounds_max=tuple(float(x) for x in mesh.bounds[1]),  # type: ignore[arg-type]
        volume_mm3=float(mesh.volume) if mesh.is_watertight else None,
        surface_area_mm2=float(mesh.area),
        watertight=bool(mesh.is_watertight),
        connected_parts=parts,
        fits_bed=fits,
        project=read_project(path),
        warnings=warnings,
    )


# --------------------------------------------------------------------------- slicing


class SliceResult(BaseModel):
    gcode_path: str
    stats: GcodeStats
    settings_from: Literal["profiles", "project"]
    warnings: list[str]


@mcp.tool()
async def slice_model(
    model_path: Annotated[str, Field(description="Absolute path to an STL/3MF/OBJ file")],
    printer_profile: Annotated[
        str | None,
        Field(
            description="Exact printer profile name, from list_printers. Give all three profiles, or none for a PrusaSlicer "
            "project (a .3mf saved from PrusaSlicer, see inspect_model's `project`), which is then sliced with its own saved "
            "settings (supports, brim, infill...). Giving profiles makes PrusaSlicer ignore those saved settings."
        ),
    ] = None,
    print_profile: Annotated[
        str | None, Field(description="Exact print profile name, from list_profiles. All three profiles or none.")
    ] = None,
    material_profile: Annotated[
        str | None, Field(description="Exact filament profile name, from list_profiles. All three profiles or none.")
    ] = None,
    overrides: Annotated[
        dict[str, str] | None,
        Field(
            description="Optional PrusaSlicer settings, e.g. {'fill_density': '25%', 'perimeters': '3'}. Keys are config option names (see PrusaSlicer --help-fff); options the server sets itself (profiles, output, binary_gcode, datadir, save) are rejected."
        ),
    ] = None,
    output_path: Annotated[
        str | None,
        Field(
            description="Where to write the G-code (default: <output dir>/<model>.gcode). Its folder is created if missing, but only that one level: the folder above it must already exist."
        ),
    ] = None,
    center: Annotated[
        bool,
        Field(
            description="Move the model to the middle of the bed. Needed for plain 3MF files modelled around "
            "the origin ('All objects are outside of the print volume'); STL/OBJ are placed automatically. "
            "Leave false for 3MF projects saved from PrusaSlicer, which already hold their layout."
        ),
    ] = False,
) -> SliceResult:
    """Slice a model headlessly and return the G-code path plus print time, filament use and layer count.
    Uses the given installed profiles, or, for a PrusaSlicer project 3MF with no profiles given, the settings
    saved in the project. G-code is always written as text (not .bgcode)."""
    cfg = get_config()
    model = _model_path(model_path)
    project = read_project(model)
    profiles = _chosen_profiles(printer_profile, print_profile, material_profile, project)

    if output_path:
        out = Path(output_path).expanduser().resolve()
        # A caller-supplied path may create only its last folder: reaching further is almost always a typo, and
        # silently building a tree for it hides the mistake. The configured output directory is the user's own
        # setting, so that one is created in full.
        if out.parent.exists() and not out.parent.is_dir():
            raise ToolError(f"Cannot write {out}: {out.parent} is not a folder")
        if not out.parent.is_dir() and not out.parent.parent.is_dir():
            raise ToolError(
                f"Cannot write {out}: neither its folder nor that folder's parent exists. "
                "Use an existing folder, or one level below it."
            )
        create_all_parents = False
    else:
        out = cfg.output_dir / f"{model.stem}.gcode"
        create_all_parents = True

    args = ["--export-gcode", "--binary-gcode=0"]
    if profiles is not None:
        printer, print_, material = profiles
        args += ["--printer-profile", printer, "--print-profile", print_, "--material-profile", material]
    for key, value in (overrides or {}).items():
        if not _OVERRIDE_KEY.match(key):
            raise ToolError(f"Invalid override key: {key!r}")
        if key in _RESERVED_OVERRIDES:
            raise ToolError(f"Override {key!r} is controlled by the server and cannot be set")
        if "\n" in value or "\r" in value:
            raise ToolError(f"Invalid override value for {key!r}")
        args.append(f"--{key.replace('_', '-')}={value}")
    if center:
        bed_printer = profiles[0] if profiles is not None else (project.printer_profile if project else None)
        if bed_printer is None:
            raise ToolError("Cannot centre on the bed: the project does not name its printer, so pass printer_profile")
        x, y = await _bed_center(bed_printer)
        args += ["--center", f"{x:g},{y:g}"]
    args += ["--output", str(out), str(model)]

    # Everything is validated by now, so a refused request leaves nothing behind on disk.
    try:
        out.parent.mkdir(parents=create_all_parents, exist_ok=True)
    except OSError as e:
        raise ToolError(f"Cannot create the output folder {out.parent}: {e}") from e
    result = await _run(cfg, args)
    if result.returncode != 0 or not out.is_file():
        detail = _with_profile_hint((result.stderr.strip() or result.stdout.strip())[-2000:])
        if "outside of the print volume" in detail and not center:
            detail += " (hint: retry with center=true to place the model in the middle of the bed)"
        raise ToolError(f"Slicing failed (exit {result.returncode}): {detail}")

    warnings = parse_warnings(result.stdout)
    try:
        stats = parse_gcode_stats(out)
    except ValueError as e:
        raise ToolError(str(e)) from e
    # PrusaSlicer does not always say when layers are missing, and the statistics look normal either way.
    gap_warning = layer_gap_warning(out)
    if gap_warning:
        warnings.append(gap_warning)
    return SliceResult(
        gcode_path=str(out),
        stats=stats,
        settings_from="profiles" if profiles is not None else "project",
        warnings=warnings,
    )


def main() -> None:
    mcp.run()
