"""Render a mesh to a picture with numpy and Pillow only (no OpenGL, no plotting library), see ADR 0011.

Method: sample points on the surface (area-weighted), project them orthographically, keep the nearest point per
pixel (a z-buffer) and shade by the surface normal. Sampling densely and then filling the few pixels left empty
inside a surface gives a clean picture of meshes from a 12-triangle cube to a 200,000-triangle scan.
"""

from __future__ import annotations

import io
from typing import TYPE_CHECKING

import numpy as np
from PIL import Image, ImageDraw

if TYPE_CHECKING:
    import trimesh

BACKGROUND = (245, 245, 245)
BED_FILL = (228, 231, 238)  # the bed plane under the model
BED_LINE = (186, 193, 207)  # its outline and its 10 mm grid
_BASE_COLOR = np.array((120, 170, 220), dtype=np.float64)
_SAMPLES_PER_PIXEL = 6
_MARGIN = 0.9  # the model fills this fraction of the picture, leaving a border
_BED_MARGIN = 0.12  # the bed reaches this fraction of the footprint (plus 1 mm) past the model on every side
_BED_GRID_MM = 10.0
_BED_MAX_GRID_LINES = 40

# (azimuth, elevation) in degrees. Z is up; "front" looks along +y, "side" along -x, "top" straight down.
VIEWS = {"iso": (-40.0, 28.0), "front": (0.0, 0.0), "side": (-90.0, 0.0), "top": (0.0, 90.0)}
SHEET_ORDER = ("iso", "front", "side", "top")
ALL_VIEWS = (*SHEET_ORDER, "sheet")


def _rotation(azimuth: float, elevation: float) -> np.ndarray:
    """World to view: view x is screen right, view y is depth (away from the camera), view z is screen up."""
    a, e = np.radians(azimuth), np.radians(elevation)
    about_z = np.array([[np.cos(a), -np.sin(a), 0], [np.sin(a), np.cos(a), 0], [0, 0, 1]])
    about_x = np.array([[1, 0, 0], [0, np.cos(e), -np.sin(e)], [0, np.sin(e), np.cos(e)]])
    return about_x @ about_z


def _fill_gaps(pixels: np.ndarray, filled: np.ndarray, passes: int = 2) -> None:
    """Fill empty pixels that are surrounded by painted ones (sampling gaps), averaging their neighbours."""
    for _ in range(passes):
        padded_mask = np.pad(filled, 1)
        padded_color = np.pad(pixels.astype(np.float64), ((1, 1), (1, 1), (0, 0)))
        count = np.zeros(filled.shape, dtype=np.int64)
        total = np.zeros(pixels.shape, dtype=np.float64)
        height, width = filled.shape
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if dy == 0 and dx == 0:
                    continue
                neighbour = padded_mask[1 + dy : 1 + dy + height, 1 + dx : 1 + dx + width]
                count += neighbour
                total += padded_color[1 + dy : 1 + dy + height, 1 + dx : 1 + dx + width] * neighbour[..., None]
        hole = ~filled & (count >= 5)
        if not hole.any():
            return
        pixels[hole] = (total[hole] / count[hole, None]).astype(np.uint8)
        filled |= hole


def _bed_layer(vertices: np.ndarray, rotation: np.ndarray, scale: float, size: int) -> np.ndarray:
    """The bed as a picture: a plane at the model's lowest point, a little wider than its footprint, with a grid.

    Drawn with Pillow's polygon and line primitives, which clip to the picture and are exact, so a bed that spills
    over the edge is cut off and not smeared. Seen edge-on it is a single line.
    """
    low, high = vertices.min(axis=0), vertices.max(axis=0)
    margin = _BED_MARGIN * max(high[0] - low[0], high[1] - low[1]) + 1.0
    x0, x1, y0, y1, z = low[0] - margin, high[0] + margin, low[1] - margin, high[1] + margin, low[2]

    def screen(x: float, y: float) -> tuple[float, float]:
        view = rotation @ np.array([x, y, z])
        return float(view[0] * scale + size / 2), float(size / 2 - view[2] * scale)

    layer = Image.new("RGB", (size, size), BACKGROUND)
    draw = ImageDraw.Draw(layer)
    corners = [screen(x0, y0), screen(x1, y0), screen(x1, y1), screen(x0, y1)]
    draw.polygon(corners, fill=BED_FILL)
    spacing = _BED_GRID_MM
    while max(x1 - x0, y1 - y0) / spacing > _BED_MAX_GRID_LINES:
        spacing *= 2
    for offset in np.arange(spacing, x1 - x0, spacing):
        draw.line([screen(x0 + offset, y0), screen(x0 + offset, y1)], fill=BED_LINE)
    for offset in np.arange(spacing, y1 - y0, spacing):
        draw.line([screen(x0, y0 + offset), screen(x1, y0 + offset)], fill=BED_LINE)
    draw.line([*corners, corners[0]], fill=BED_LINE)
    return np.asarray(layer)


def _render_view(mesh: trimesh.Trimesh, azimuth: float, elevation: float, size: int, bed: bool = False) -> Image.Image:
    rotation = _rotation(azimuth, elevation)
    centred = mesh.vertices - mesh.bounds.mean(axis=0)
    extent = np.abs(centred @ rotation.T).max() * 2.0
    scale = size * _MARGIN / extent

    import trimesh as _trimesh  # imported late: trimesh is slow to import and the server may never preview

    sampled = _trimesh.sample.sample_surface(
        _trimesh.Trimesh(vertices=centred, faces=mesh.faces, process=False),
        _SAMPLES_PER_PIXEL * size * size,
        seed=0,
    )
    points, faces = sampled[0], sampled[1]  # the tuple is longer when colours are requested
    normals = mesh.face_normals[faces] @ rotation.T
    view = points @ rotation.T

    columns = np.clip((view[:, 0] * scale + size / 2).astype(int), 0, size - 1)
    rows = np.clip((size / 2 - view[:, 2] * scale).astype(int), 0, size - 1)
    depth = view[:, 1]

    light = np.array([-0.4, -0.7, 0.6])
    light /= np.linalg.norm(light)
    brightness = 0.35 + 0.65 * np.abs(normals @ light)  # two-sided, so open or badly wound meshes still read

    pixels = np.empty((size, size, 3), dtype=np.uint8)
    if bed:  # the bed is under the model, so it goes down first and the model is painted over it
        pixels[:] = _bed_layer(centred, rotation, scale, size)
    else:
        pixels[:] = BACKGROUND
    order = np.argsort(-depth, kind="stable")  # far first, so the nearest point is written last and wins
    pixels[rows[order], columns[order]] = (_BASE_COLOR[None, :] * brightness[order, None]).astype(np.uint8)

    filled = np.zeros((size, size), dtype=bool)
    filled[rows, columns] = True
    _fill_gaps(pixels, filled)
    return Image.fromarray(pixels)


def render_model(mesh: trimesh.Trimesh, view: str = "iso", size: int = 640, bed: bool = False) -> Image.Image:
    """A size x size picture of a mesh: one of iso, front, side, top, or `sheet` (all four in one picture).

    The mesh is drawn as stored (z up), centred, whatever its position. With `bed` a pale grid plane is drawn at its
    lowest point, which is where it rests on PrusaSlicer's bed. Raises ValueError for an unknown view or a mesh with
    no surface.
    """
    if view not in ALL_VIEWS:
        raise ValueError(f"Unknown view {view!r}. Choose one of: {', '.join(ALL_VIEWS)}")
    if not mesh.area > 0:
        raise ValueError("This mesh has no surface to draw (every triangle is degenerate).")
    if view != "sheet":
        return _render_view(mesh, *VIEWS[view], size, bed)

    half = size // 2
    sheet = Image.new("RGB", (size, size), BACKGROUND)
    for index, name in enumerate(SHEET_ORDER):
        sheet.paste(_render_view(mesh, *VIEWS[name], half, bed), ((index % 2) * half, (index // 2) * half))
    return sheet


def to_png(image: Image.Image) -> bytes:
    """The picture as PNG bytes. Deterministic, so identical pictures give identical bytes."""
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=False, compress_level=6)
    return buffer.getvalue()
