"""Draw sliced G-code with numpy and Pillow: one layer's toolpaths, or a side silhouette of everything printed.

Reads the text G-code PrusaSlicer writes: the extruding `G1` moves and arcs (`G2`/`G3`, which arc fitting writes), and
the `;LAYER_CHANGE`, `;Z:` and `;TYPE:` comments that say which layer and feature each move belongs to (ADR 0011).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np
from PIL import Image, ImageDraw, ImageFont

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

BACKGROUND = (250, 250, 250)
GHOST = (222, 222, 222)  # the layer below, for context
INK = (50, 90, 160)  # what was printed, in the side silhouette
_GRID = (232, 232, 232)
_AXIS = (170, 170, 170)
_TEXT = (70, 70, 70)
UNKNOWN_COLOR = (90, 90, 90)

FEATURE_COLORS = {
    "External perimeter": (255, 140, 0),
    "Perimeter": (255, 200, 60),
    "Overhang perimeter": (200, 60, 60),
    "Internal infill": (60, 120, 220),
    "Solid infill": (200, 80, 200),
    "Top solid infill": (230, 60, 60),
    "Bridge infill": (40, 200, 200),
    "Gap fill": (120, 220, 120),
    "Skirt/Brim": (150, 150, 150),
    "Support material": (60, 180, 90),
    "Support material interface": (120, 220, 160),
}

_GRID_MM = 10
_LINE_MM = 0.45  # a typical extrusion width, so lines look as thick as the plastic is
_ARC_TOLERANCE_MM = 0.02  # how far a drawn arc may sit from the true one; far below a pixel at any zoom we draw


@dataclass(frozen=True)
class Extrusion:
    """One extruding move: its end points, its layer (from 0), that layer's height, and its feature."""

    x0: float
    y0: float
    x1: float
    y1: float
    z: float
    layer: int
    feature: str


@dataclass
class GcodeScan:
    layer_heights: list[float]
    features: list[str]
    x_range: tuple[float, float]
    y_range: tuple[float, float]
    arcs_skipped: int


def _arc_points(
    x: float, y: float, nx: float, ny: float, i: float, j: float, clockwise: bool
) -> list[tuple[float, float]]:
    """The points along an arc from (x, y) to (nx, ny) around the centre (x + i, y + j), the end point last and exact.

    An arc that ends where it starts is a full circle, as G-code defines it.
    """
    cx, cy = x + i, y + j
    radius = math.hypot(i, j)
    start = math.atan2(y - cy, x - cx)
    sweep = math.atan2(ny - cy, nx - cx) - start
    if clockwise and sweep >= 0:
        sweep -= 2 * math.pi
    elif not clockwise and sweep <= 0:
        sweep += 2 * math.pi
    # A chord of this angle sags from its arc by the tolerance; a tiny radius is a single straight piece.
    step = 2 * math.acos(max(0.0, 1 - _ARC_TOLERANCE_MM / radius)) if radius > _ARC_TOLERANCE_MM else math.pi
    pieces = max(1, math.ceil(abs(sweep) / max(step, 1e-3)))
    points = [
        (cx + radius * math.cos(start + sweep * k / pieces), cy + radius * math.sin(start + sweep * k / pieces))
        for k in range(1, pieces)
    ]
    return [*points, (nx, ny)]


@dataclass
class _Reader:
    """Walks a G-code file once, tracking position, extrusion mode, layer and feature."""

    path: Path
    layer_heights: list[float] = field(default_factory=list)
    arcs_skipped: int = 0

    def extrusions(self) -> Iterator[Extrusion]:
        x = y = 0.0
        last_e = 0.0
        relative = False  # Marlin's default is absolute; PrusaSlicer's start G-code switches with M83
        layer = -1
        z = 0.0
        feature = ""
        with self.path.open("rb") as f:
            for raw in f:
                line = raw.decode("latin-1")
                if line.startswith(";"):
                    if line.startswith(";LAYER_CHANGE"):
                        layer += 1
                    elif line.startswith(";Z:"):
                        z = float(line[3:])
                        self.layer_heights.append(z)
                    elif line.startswith(";TYPE:"):
                        feature = line[6:].strip()
                    continue
                code = line.split(";", 1)[0].split()
                if not code:
                    continue
                command = code[0]
                if command == "M83":
                    relative = True
                elif command == "M82":
                    relative = False
                elif command == "G92":
                    for token in code[1:]:
                        if token[0] == "E":
                            last_e = float(token[1:])
                elif command in ("G0", "G1", "G2", "G3"):
                    nx, ny, e = x, y, None
                    centre: dict[str, float] = {}
                    moved = False
                    for token in code[1:]:
                        letter = token[0]
                        if letter == "X":
                            nx, moved = float(token[1:]), True
                        elif letter == "Y":
                            ny, moved = float(token[1:]), True
                        elif letter == "E":
                            e = float(token[1:])
                        elif letter in "IJ":
                            centre[letter] = float(token[1:])
                    extruding = False
                    if e is not None:
                        extruding = e > 0 if relative else e > last_e + 1e-9
                        if not relative:
                            last_e = e
                    if extruding and moved and layer >= 0:
                        if command in ("G2", "G3") and not centre:
                            self.arcs_skipped += 1  # the radius form (R) names no centre, so there is nothing to draw
                        elif command in ("G2", "G3"):
                            # An omitted I or J is 0, as in any G-code.
                            ends = _arc_points(
                                x, y, nx, ny, centre.get("I", 0.0), centre.get("J", 0.0), command == "G2"
                            )
                            for ex, ey in ends:
                                yield Extrusion(x, y, ex, ey, z, layer, feature)
                                x, y = ex, ey
                        else:
                            yield Extrusion(x, y, nx, ny, z, layer, feature)
                    x, y = nx, ny


def iter_extrusions(path: Path) -> Iterator[Extrusion]:
    """Every extruding move of the print itself (not the start G-code), in file order."""
    return _Reader(path).extrusions()


def scan_gcode(path: Path) -> GcodeScan:
    """One pass over the file: the layers and their heights, the features used, and the printed extent."""
    reader = _Reader(path)
    features: dict[str, None] = {}
    x_low = y_low = float("inf")
    x_high = y_high = float("-inf")
    seen = False
    for move in reader.extrusions():
        seen = True
        features.setdefault(move.feature)
        x_low, x_high = min(x_low, move.x0, move.x1), max(x_high, move.x0, move.x1)
        y_low, y_high = min(y_low, move.y0, move.y1), max(y_high, move.y0, move.y1)
    if not seen:
        raise ValueError("This G-code has no extruding moves to draw. Is it text G-code sliced by PrusaSlicer?")
    return GcodeScan(reader.layer_heights, list(features), (x_low, x_high), (y_low, y_high), reader.arcs_skipped)


def _text_size(image_size: int) -> int:
    return max(11, image_size // 45)


def render_layer(path: Path, scan: GcodeScan, layer: int, size: int = 640) -> Image.Image:
    """One layer's toolpaths coloured by feature, with the layer below as a faint ghost. `layer` counts from 1."""
    total = len(scan.layer_heights)
    if not 1 <= layer <= total:
        raise ValueError(f"layer must be between 1 and {total} for this file, got {layer}")
    index = layer - 1

    span_x = scan.x_range[1] - scan.x_range[0]
    span_y = scan.y_range[1] - scan.y_range[0]
    pad = size * 0.04
    scale = (size - 2 * pad) / max(span_x, span_y, 1e-6)  # one scale for every layer, so layers compare
    offset_x = (size - span_x * scale) / 2
    offset_y = (size - span_y * scale) / 2

    def point(px: float, py: float) -> tuple[float, float]:
        return offset_x + (px - scan.x_range[0]) * scale, size - (offset_y + (py - scan.y_range[0]) * scale)

    below: list[Extrusion] = []
    current: list[Extrusion] = []
    for move in iter_extrusions(path):
        if move.layer == index - 1:
            below.append(move)
        elif move.layer == index:
            current.append(move)
        elif move.layer > index:
            break

    image = Image.new("RGB", (size, size), BACKGROUND)
    draw = ImageDraw.Draw(image)
    width = max(1, round(_LINE_MM * scale))
    for move in below:
        draw.line([point(move.x0, move.y0), point(move.x1, move.y1)], fill=GHOST, width=width)
    for move in current:
        colour = FEATURE_COLORS.get(move.feature, UNKNOWN_COLOR)
        draw.line([point(move.x0, move.y0), point(move.x1, move.y1)], fill=colour, width=width)

    text = _text_size(size)
    font = ImageFont.load_default(size=text)
    row = pad
    for feature in dict.fromkeys(move.feature for move in current):
        draw.rectangle([pad, row, pad + text * 0.9, row + text * 0.9], fill=FEATURE_COLORS.get(feature, UNKNOWN_COLOR))
        draw.text((pad + text * 1.2, row - 1), feature or "(untyped)", fill=_TEXT, font=font)
        row += text * 1.4
    return image


def render_profile(path: Path, scan: GcodeScan, size: int = 640) -> Image.Image:
    """Front (x against z) and side (y against z) silhouettes of everything printed, on a 10 mm grid.

    A stretch of height where nothing was printed shows as a blank band across both panels.
    """
    panel_width = size // 2
    height = max(scan.layer_heights)
    span_x = scan.x_range[1] - scan.x_range[0]
    span_y = scan.y_range[1] - scan.y_range[0]
    pad = size * 0.03
    scale = min((panel_width - 2 * pad) / max(span_x, span_y, 1e-6), (size - 2 * pad) / max(height, 1e-6))
    floor = size - pad

    pixels = np.empty((size, size, 3), dtype=np.uint8)
    pixels[:] = BACKGROUND
    for left in (0, panel_width):
        for grid in range(int(height // _GRID_MM) + 2):
            row = round(floor - grid * _GRID_MM * scale)
            if 0 <= row < size:
                pixels[row, left : left + panel_width] = _AXIS if grid == 0 else _GRID

    panels = ((0, scan.x_range[0], span_x), (panel_width, scan.y_range[0], span_y))
    moves = iter_extrusions(path)
    while True:
        chunk = [m for _, m in zip(range(200_000), moves, strict=False)]
        if not chunk:
            break
        z = np.array([m.z for m in chunk])
        rows = np.clip((floor - z * scale).astype(int), 0, size - 1)
        for (left, low, span), (a0, a1) in zip(panels, (("x0", "x1"), ("y0", "y1")), strict=True):
            start = np.array([getattr(m, a0) for m in chunk])
            end = np.array([getattr(m, a1) for m in chunk])
            count = np.maximum(2, np.ceil(np.abs(end - start) * scale).astype(int) + 1)
            index = np.repeat(np.arange(len(chunk)), count)
            along = (np.arange(len(index)) - np.repeat(np.cumsum(count) - count, count)) / np.repeat(count - 1, count)
            coordinate = start[index] + (end[index] - start[index]) * along
            origin = left + (panel_width - span * scale) / 2
            columns = np.clip((origin + (coordinate - low) * scale).astype(int), left, left + panel_width - 1)
            pixels[rows[index], columns] = INK

    image = Image.fromarray(pixels)
    draw = ImageDraw.Draw(image)
    draw.line([(panel_width, 0), (panel_width, size)], fill=_AXIS)
    text = _text_size(size)
    font = ImageFont.load_default(size=text)
    draw.text((pad, pad), "front (x)", fill=_TEXT, font=font)
    draw.text((panel_width + pad, pad), "side (y)", fill=_TEXT, font=font)
    draw.text((pad, floor - text * 1.4), f"{_GRID_MM} mm grid", fill=_TEXT, font=font)
    return image
