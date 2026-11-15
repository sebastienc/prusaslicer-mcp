"""MCP server exposing the PrusaSlicer 2.9.x command line to Claude."""

from __future__ import annotations

import asyncio
import json
import math
import os
import re
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, Literal

from mcp.server.mcpserver import Image, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from . import cli, repair
from .config import Config, ConfigError, load_config
from .gcode import GcodeStats, layer_gap_warning, parse_gcode_stats
from .preview_gcode import render_layer, render_profile, scan_gcode
from .preview_model import SHEET_ORDER, render_model, to_png
from .project import ProjectInfo, read_project
from .slicer_output import parse_warnings

if TYPE_CHECKING:
    import trimesh

mcp = MCPServer(
    "prusaslicer",
    instructions=(
        "Headless PrusaSlicer 2.9.x. Discover exact profile names with list_printers and list_profiles, "
        "check a model with inspect_model, then slice_model. Profile names must match exactly."
    ),
)

_READ_ONLY = ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=False)

_MODEL_SUFFIXES = {".stl", ".3mf", ".obj", ".amf", ".step", ".stp"}
_GCODE_SUFFIXES = {".gcode", ".gco"}
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
_SHEET_CORNERS = ("top left", "top right", "bottom left", "bottom right")
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


# Refusals PrusaSlicer words tersely, with what to try. Each was met slicing real models and the remedy was verified.
_STATIC_HINTS = (
    (
        re.compile(r"no extrusions in the first layer", re.IGNORECASE),
        " (hint: the model's lowest layer has nothing to print, usually because its underside is open, as in many "
        "scans, or it rests on a point. Look at it with preview_model, then try rotate_x or rotate_y to put a flat, "
        "closed face down. If inspect_model reports a hole that can be closed, repair the mesh with "
        "close_holes=true)",
    ),
    (
        re.compile(r"wipe tower is currently not supported for multimaterial sequential", re.IGNORECASE),
        " (hint: this is a conflict in the project's own settings. Change one with overrides, for example "
        '{"wipe_tower": "0"} or {"complete_objects": "0"})',
    ),
)


async def _outside_volume_hint(model: Path, printer_profile: str | None, centred: bool) -> str:
    """Say why a model is outside the print volume when we can tell: too big for the bed, or just off it."""
    centre_hint = " (hint: retry with center=true to place the model in the middle of the bed)"
    if printer_profile is not None:
        try:
            x, y, z = (float(v) for v in _load_mesh(model).extents)
            width, depth, height = await _bed_size(printer_profile)
        except ToolError:
            return "" if centred else centre_hint  # sizes unknown: the position is the likeliest cause
        too_big = z > height or not ((x <= width and y <= depth) or (x <= depth and y <= width))
        if too_big:
            fits_diagonally = z <= height and (x + y) / math.sqrt(2) <= min(width, depth)
            limit_z = height if math.isfinite(height) else z  # no height limit known: leave the height alone
            bed = f"{width:g} x {depth:g}" + (f" x {height:g}" if math.isfinite(height) else "")
            fit = f"scale_to_fit=[{width:g}, {depth:g}, {limit_z:g}]"
            rotate = " or rotate_z=45 to lay it across the bed's diagonal" if fits_diagonally else ""
            return (
                f" (hint: the model is {x:.1f} x {y:.1f} x {z:.1f} mm but the bed is {bed} mm. "
                f"Use {fit} to shrink it{rotate})"
            )
    return "" if centred else centre_hint


async def _explain_failure(detail: str, model: Path, printer_profile: str | None, centred: bool) -> str:
    """PrusaSlicer's own message plus advice for the refusals we know how to resolve."""
    detail = _with_profile_hint(detail)
    for pattern, hint in _STATIC_HINTS:
        if pattern.search(detail):
            detail += hint
    if "outside of the print volume" in detail:
        detail += await _outside_volume_hint(model, printer_profile, centred)
    return detail


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


def _load_mesh(path: Path) -> trimesh.Trimesh:
    """Load a model file as one mesh, or raise a ToolError a client can read."""
    import trimesh

    try:
        mesh = trimesh.load(path, force="mesh")
    except (
        Exception
    ) as e:  # trimesh's parsers raise assorted types on bad input (BadZipFile, ValueError, ImportError, ...)
        raise ToolError(f"Could not read {path.name} as a {path.suffix.lower()} model: {e}") from e
    if not isinstance(mesh, trimesh.Trimesh) or len(mesh.faces) == 0:
        raise ToolError("Could not load a triangle mesh from this file.")
    return mesh


def _close_holes_of(path: Path) -> repair.Closing:
    return repair.close_holes(_load_mesh(path))


def _closing_warning(closing: repair.Closing) -> str:
    """What close_holes did, so a result never hides that the sliced mesh was not the file."""
    if closing.closed:
        rest = f"; {closing.left_open} other open hole(s) were left as they are" if closing.left_open else ""
        return f"close_holes capped {closing.closed} flat hole(s) in a copy of the model before slicing{rest}."
    if closing.left_open:
        return (
            f"close_holes could not close any of the {closing.left_open} open hole(s): they are tiny, bent or touch "
            "themselves. The model was sliced as it is."
        )
    return "close_holes found no open holes, so the model was sliced as it is."


def _transform_args(
    rotate_x: float | None,
    rotate_y: float | None,
    rotate_z: float | None,
    scale: float | None,
    scale_to_fit: list[float] | None,
    split: bool,
    copies: int | None,
) -> list[str]:
    """PrusaSlicer's transform flags for the requested changes, validated (ADR 0012).

    PrusaSlicer applies them in its own fixed order whatever order they are passed: rotate about X, then Y, then
    Z, then scale. `--scale` takes a factor, and a bare `50` would mean fifty times, so only factors are accepted.
    """
    args: list[str] = []
    for name, flag, degrees in (
        ("rotate_x", "--rotate-x", rotate_x),
        ("rotate_y", "--rotate-y", rotate_y),
        ("rotate_z", "--rotate", rotate_z),
    ):
        if degrees is None:
            continue
        if not math.isfinite(degrees):
            raise ToolError(f"{name} must be a finite number of degrees")
        args += [flag, f"{degrees:g}"]
    if scale is not None and scale_to_fit is not None:
        raise ToolError("Use either scale or scale_to_fit, not both")
    if scale is not None:
        if not math.isfinite(scale) or scale <= 0:
            raise ToolError("scale must be a factor greater than 0 (0.5 is half size, 2 is double)")
        args += ["--scale", f"{scale:g}"]
    if scale_to_fit is not None:
        if len(scale_to_fit) != 3:
            raise ToolError("scale_to_fit needs exactly 3 sizes in millimetres: [x, y, z]")
        if not all(math.isfinite(size) and size > 0 for size in scale_to_fit):
            raise ToolError("scale_to_fit sizes must all be positive")
        args += ["--scale-to-fit", ",".join(f"{size:g}" for size in scale_to_fit)]
    if split:
        args.append("--split")
    if copies is not None:
        if not 1 <= copies <= 100:
            raise ToolError("copies must be between 1 and 100")
        args += ["--duplicate", str(copies)]
    return args


def _model_path(path: str) -> Path:
    p = Path(path).expanduser().resolve()
    if not p.is_file():
        raise ToolError(f"Model file not found: {p}")
    if p.suffix.lower() not in _MODEL_SUFFIXES:
        raise ToolError(f"Unsupported model type '{p.suffix}'. Supported: {sorted(_MODEL_SUFFIXES)}")
    return p


def _gcode_path(path: str) -> Path:
    p = Path(path).expanduser().resolve()
    if not p.is_file():
        raise ToolError(f"G-code file not found: {p}")
    if p.suffix.lower() not in _GCODE_SUFFIXES:
        raise ToolError(f"Unsupported G-code type '{p.suffix}'. Supported: {sorted(_GCODE_SUFFIXES)}")
    with p.open("rb") as f:
        if f.read(4) == b"GCDE":
            raise ToolError("Binary G-code (.bgcode) cannot be drawn; slice_model always writes text G-code.")
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


async def _bed_size(printer_profile: str) -> tuple[float, float, float]:
    """Width, depth and maximum print height of a known FFF printer profile's bed, in mm."""
    data = await _query_json(["--query-printer-models", "--printer-technology", "FFF"])
    for m in data.get("printer_models", []):
        for v in m.get("variants", []):
            for p in v.get("printer_profiles", []):
                bed = p.get("bed", {})
                if p.get("name") == printer_profile and bed.get("width") and bed.get("height"):
                    return bed["width"], bed["height"], bed.get("max_print_height") or float("inf")
    raise ToolError(
        f"printer profile {printer_profile!r} was not found with a bed size; use the exact name from list_printers"
    )


async def _bed_center(printer_profile: str) -> tuple[float, float]:
    """Middle of the bed for a known FFF printer profile (assumes the bed origin is a corner)."""
    try:
        width, depth, _ = await _bed_size(printer_profile)
    except ToolError as e:
        raise ToolError(f"Cannot centre on the bed: {e}") from e
    return width / 2, depth / 2


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
    open_holes: int
    closable_holes: int
    connected_parts: int
    fits_bed: bool | None = None
    project: ProjectInfo | None = None
    warnings: list[str]


@mcp.tool(annotations=_READ_ONLY)
async def inspect_model(
    model_path: Annotated[str, Field(description="Absolute path to an STL/3MF/OBJ file")],
    bed_width: Annotated[float | None, Field(description="Bed X size in mm, to check fit")] = None,
    bed_depth: Annotated[float | None, Field(description="Bed Y size in mm, to check fit")] = None,
    max_height: Annotated[float | None, Field(description="Max print height in mm, to check fit")] = None,
) -> ModelInfo:
    """Check a model before slicing: size, volume, watertightness, number of separate parts,
    and (optionally) whether it fits a given build volume."""
    path = _model_path(model_path)
    mesh = _load_mesh(path)

    size = tuple(float(x) for x in mesh.extents)
    warnings: list[str] = []
    holes = [] if mesh.is_watertight else repair.find_holes(mesh)
    closable = sum(hole.closable for hole in holes)
    if not mesh.is_watertight:
        warnings.append("Mesh is not watertight (holes or non-manifold edges); PrusaSlicer may need to repair it.")
    if closable:
        stay = (
            f" The other {len(holes) - closable} (small, bent or part of an open shell) would stay open."
            if closable < len(holes)
            else ""
        )
        warnings.append(
            f"{closable} of the {len(holes)} open hole(s) are flat gaps, such as a missing base: slice_model can "
            f"cap them with close_holes=true.{stay}"
        )
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
    project = read_project(path)
    if path.suffix.lower() == ".3mf" and bed_width is not None and bed_depth is not None:
        lo, hi = mesh.bounds
        if lo[0] < 0 or lo[1] < 0 or hi[0] > bed_width or hi[1] > bed_depth:
            where = (
                f"Stored position is off the bed (x {lo[0]:.1f}..{hi[0]:.1f}, y {lo[1]:.1f}..{hi[1]:.1f} mm; "
                f"bed is 0..{bed_width:g} by 0..{bed_depth:g}). PrusaSlicer keeps a 3MF's position. "
            )
            remedy = (
                "slice_model centres a plain 3MF on the bed automatically (center=false keeps this position)."
                if project is None
                else "This is a PrusaSlicer project, so slice_model keeps its layout; pass center=true to centre it."
            )
            warnings.append(where + remedy)

    return ModelInfo(
        path=str(path),
        triangles=len(mesh.faces),
        size_mm=size,  # type: ignore[arg-type]
        bounds_min=tuple(float(x) for x in mesh.bounds[0]),  # type: ignore[arg-type]
        bounds_max=tuple(float(x) for x in mesh.bounds[1]),  # type: ignore[arg-type]
        volume_mm3=float(mesh.volume) if mesh.is_watertight else None,
        surface_area_mm2=float(mesh.area),
        watertight=bool(mesh.is_watertight),
        open_holes=len(holes),
        closable_holes=closable,
        connected_parts=parts,
        fits_bed=fits,
        project=project,
        warnings=warnings,
    )


PreviewView = Literal["iso", "front", "side", "top", "sheet"]


@mcp.tool(annotations=_READ_ONLY)
async def preview_model(
    model_path: Annotated[str, Field(description="Absolute path to an STL/3MF/OBJ file")],
    view: Annotated[
        PreviewView,
        Field(
            description="iso (default), front, side or top; sheet puts all four in one picture. Z is up, and the model "
            "is drawn as stored, centred."
        ),
    ] = "iso",
    size: Annotated[int, Field(description="Picture width and height in pixels", ge=128, le=1024)] = 640,
) -> list[Image | str]:
    """Draw a picture of a model, to check its shape and which way up it is before slicing.

    Returns a PNG and a caption with its size. PrusaSlicer prints with z up too, so a model that looks to be
    lying on its side will be printed that way (scans are often Y-up)."""
    path = _model_path(model_path)
    mesh = _load_mesh(path)
    try:
        picture = render_model(mesh, view, size)
    except ValueError as e:
        raise ToolError(str(e)) from e
    x, y, z = (float(v) for v in mesh.extents)
    where = (
        "sheet: " + ", ".join(f"{name} ({corner})" for name, corner in zip(SHEET_ORDER, _SHEET_CORNERS, strict=True))
        if view == "sheet"
        else f"{view} view"
    )
    caption = (
        f"{path.name}, {where}. Size {x:.1f} x {y:.1f} x {z:.1f} mm (x, y, z). Z is up and the model is drawn as "
        "stored, centred. PrusaSlicer also prints with z up, so a model that looks to be lying on its side would be "
        "printed that way."
    )
    return [Image(data=to_png(picture), format="png"), caption]


GcodeView = Literal["layer", "profile"]


@mcp.tool(annotations=_READ_ONLY)
def preview_gcode(
    gcode_path: Annotated[
        str, Field(description="Absolute path to a text G-code file, such as the gcode_path slice_model returns")
    ],
    view: Annotated[
        GcodeView,
        Field(
            description="layer (default): one layer's toolpaths coloured by feature, with the layer below as a faint "
            "ghost. profile: front and side silhouettes of everything printed, where a stretch of height with nothing "
            "printed shows as a blank band."
        ),
    ] = "layer",
    layer: Annotated[
        int | None,
        Field(description="Layer number for view=layer, from 1 (the first layer); default the middle layer", ge=1),
    ] = None,
    size: Annotated[int, Field(description="Picture width and height in pixels", ge=128, le=1024)] = 640,
) -> list[Image | str]:
    """Draw a picture of sliced G-code, to check what will really be printed before trusting the statistics.

    Use view=profile after slice_model: it shows at a glance if parts of the print float or whole stretches of the
    height are empty. Use view=layer to inspect one layer's perimeters, infill and supports."""
    path = _gcode_path(gcode_path)
    if view == "profile" and layer is not None:
        raise ToolError("layer is only used with view=layer")
    try:
        scan = scan_gcode(path)
        total = len(scan.layer_heights)
        number = layer if layer is not None else (total + 1) // 2
        picture = render_layer(path, scan, number, size) if view == "layer" else render_profile(path, scan, size)
    except ValueError as e:
        raise ToolError(str(e)) from e
    if view == "layer":
        caption = (
            f"{path.name}, layer {number} of {total} (z {scan.layer_heights[number - 1]:g} mm). The legend names this "
            "layer's features; the faint grey is the layer below. Every layer is drawn on the same scale."
        )
    else:
        caption = (
            f"{path.name}: front (x) and side (y) silhouettes of everything printed, {total} layers, "
            f"{max(scan.layer_heights):.1f} mm tall, on a 10 mm grid. A blank band across both panels means nothing "
            "was printed at that height."
        )
        gap_warning = layer_gap_warning(path)
        if gap_warning:
            caption += " " + gap_warning
    if scan.arcs_skipped:
        noun = "move" if scan.arcs_skipped == 1 else "moves"
        caption += f" {scan.arcs_skipped} arc {noun} (G2/G3) {'is' if scan.arcs_skipped == 1 else 'are'} not drawn."
    return [Image(data=to_png(picture), format="png"), caption]


# --------------------------------------------------------------------------- slicing


class SliceResult(BaseModel):
    gcode_path: str
    stats: GcodeStats
    settings_from: Literal["profiles", "project"]
    centered: bool
    holes_closed: int = 0
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
        bool | None,
        Field(
            description="Move the model to the middle of the bed. Omit it to centre plain 3MF files, which are usually "
            "modelled around the origin and otherwise fail with 'All objects are outside of the print volume', and to "
            "leave PrusaSlicer projects (which hold their own layout) and STL/OBJ (which PrusaSlicer places itself) "
            "alone. true centres any model; false keeps a plain 3MF where it is stored. The result says whether it was "
            "centred."
        ),
    ] = None,
    rotate_x: Annotated[
        float | None,
        Field(
            description="Degrees to rotate about the X axis. PrusaSlicer applies rotations in the fixed order X, then Y, "
            "then Z, whatever order you think of them. 90 or -90 stands a model that lies along Y upright, e.g. a Y-up "
            "scan (check with preview_model first)."
        ),
    ] = None,
    rotate_y: Annotated[
        float | None, Field(description="Degrees to rotate about the Y axis (applied after rotate_x).")
    ] = None,
    rotate_z: Annotated[
        float | None, Field(description="Degrees to rotate about the vertical Z axis (applied last).")
    ] = None,
    scale: Annotated[
        float | None,
        Field(
            gt=0, description="Scale factor: 0.5 is half size, 2 is double. Not a percentage. Not with scale_to_fit."
        ),
    ] = None,
    scale_to_fit: Annotated[
        list[float] | None,
        Field(
            min_length=3,
            max_length=3,
            description="[x, y, z] in mm: scale the model uniformly to fit inside this box, e.g. the bed size. Not with scale.",
        ),
    ] = None,
    split: Annotated[
        bool,
        Field(
            description="Separate unconnected solids into their own objects, which PrusaSlicer then arranges "
            "compactly on the bed."
        ),
    ] = False,
    copies: Annotated[
        int | None,
        Field(
            ge=1,
            le=100,
            description="Total number of objects to print, arranged automatically on the bed (3 prints three of this model).",
        ),
    ] = None,
    close_holes: Annotated[
        bool,
        Field(
            description="Cap flat holes in the mesh before slicing, such as the missing base of a scan, which "
            "PrusaSlicer otherwise refuses with 'no extrusions in the first layer'. inspect_model says whether a model "
            "has such holes. Only simple, nearly flat holes are closed; bent holes, tiny gaps and open shells are left "
            "alone. PrusaSlicer slices a repaired copy in a temporary folder, so the model file is never changed. Not "
            "for PrusaSlicer projects, which would lose their saved settings."
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

    closing: repair.Closing | None = None
    if close_holes:
        if project is not None:
            raise ToolError(
                "close_holes cannot be used with a PrusaSlicer project: slicing a repaired copy would drop its saved "
                "settings. Repair the mesh in PrusaSlicer, or slice the model as a plain STL with profiles."
            )
        # A large scan takes seconds to load and cap, so keep that off the event loop.
        closing = await asyncio.to_thread(_close_holes_of, model)

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
    args += _transform_args(rotate_x, rotate_y, rotate_z, scale, scale_to_fit, split, copies)
    bed_printer = profiles[0] if profiles is not None else (project.printer_profile if project else None)
    # Omitted means automatic: centre a plain 3MF (ADR 0013), leave projects, STL and OBJ alone.
    automatic = center is None
    centre = (model.suffix.lower() == ".3mf" and project is None) if automatic else center
    centered = False
    if centre:
        if bed_printer is None:
            raise ToolError("Cannot centre on the bed: the project does not name its printer, so pass printer_profile")
        try:
            x, y = await _bed_center(bed_printer)
            args += ["--center", f"{x:g},{y:g}"]
            centered = True
        except ToolError:
            if not automatic:
                raise  # centring was asked for, so say it cannot be done; automatic centring is best effort
    # Everything is validated by now, so a refused request leaves nothing behind on disk.
    try:
        out.parent.mkdir(parents=create_all_parents, exist_ok=True)
        scratch = tempfile.TemporaryDirectory(prefix=".prusaslicer-mcp-", dir=out.parent)
    except OSError as e:
        raise ToolError(f"Cannot create the output folder {out.parent}: {e}") from e

    # Slice into a private scratch folder and move the result into place only on success. PrusaSlicer exits 0 for
    # some refusals ("outside of the print volume"), so a file already sitting at the output path would otherwise
    # be reported as this slice's result, and a failed slice must not destroy the previous file either.
    with scratch as scratch_dir:
        scratch_out = Path(scratch_dir) / out.name
        slicing = model
        if closing is not None and closing.closed:
            slicing = Path(scratch_dir) / f"{model.stem}.stl"  # named like the model, so PrusaSlicer's messages are
            try:
                await asyncio.to_thread(closing.mesh.export, slicing)
            except OSError as e:
                raise ToolError(f"Cannot write the repaired copy of the model: {e}") from e
        result = await _run(cfg, [*args, "--output", str(scratch_out), str(slicing)])
        if result.returncode != 0 or not scratch_out.is_file():
            detail = (result.stderr.strip() or result.stdout.strip())[-2000:]
            bed_printer = profiles[0] if profiles is not None else (project.printer_profile if project else None)
            detail = await _explain_failure(detail, model, bed_printer, centered)
            raise ToolError(f"Slicing failed (exit {result.returncode}): {detail}")
        try:
            os.replace(scratch_out, out)
        except OSError as e:
            raise ToolError(f"Cannot write {out}: {e}") from e

    warnings = ([_closing_warning(closing)] if closing is not None else []) + parse_warnings(result.stdout)
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
        centered=centered,
        holes_closed=closing.closed if closing is not None else 0,
        warnings=warnings,
    )


def main() -> None:
    mcp.run()
