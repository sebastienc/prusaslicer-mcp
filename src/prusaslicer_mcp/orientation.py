"""Suggest which way up to print a model: candidate orientations and how each scores (ADR 0018).

A model is printed resting on one face, so the candidates are the large flat faces of the mesh (found by grouping
face normals by area), the six axis directions, and the orientation as stored. Each is scored by the surface it
puts on the bed, the overhang that would need support, and its height. The numbers are geometry only: they know
nothing about strength, appearance or material, so they inform a choice and do not make it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    import trimesh
    from numpy.typing import NDArray

# Face normals within this many degrees of each other are one flat face.
CLUSTER_DEGREES = 5.0
# A face counts as lying on the bed when it points down to within this many degrees.
FLAT_DEGREES = 8.0
# PrusaSlicer's default support threshold: a surface leaning more than this far past vertical needs support.
OVERHANG_DEGREES = 45.0
# Faces whose highest point is within this height of the lowest point are on the bed (a first layer is 0.2 mm).
BED_TOLERANCE_MM = 0.3
# A base smaller than this share of the model's silhouette seen from above is a point or an edge, not a base.
MIN_BASE_SHARE = 0.05
# Only this many of the largest flat faces become candidates.
MAX_FLAT_CANDIDATES = 14
_CELLS_PER_UNIT = 16  # face directions are grouped in cells about 3.6 degrees across before being merged


@dataclass(frozen=True)
class Orientation:
    """One way to stand a model: the rotations that reach it, and what it costs."""

    rank: int
    rotate_x: float  # degrees, for slice_model and preview_model, applied about X first and then about Y
    rotate_y: float
    height_mm: float
    base_area_mm2: float  # surface lying on the bed
    base_share: float  # of the model's silhouette seen from above
    overhang_area_mm2: float  # surface off the bed that leans past 45 degrees and would need support
    overhang_share: float  # of the whole surface
    stable: bool
    as_stored: bool


def _rotation(rotate_x: float, rotate_y: float) -> NDArray[np.float64]:
    """The matrix PrusaSlicer applies for these two angles: about X, then about the fixed Y axis."""
    ax, ay = math.radians(rotate_x), math.radians(rotate_y)
    about_x = np.array([[1, 0, 0], [0, math.cos(ax), -math.sin(ax)], [0, math.sin(ax), math.cos(ax)]])
    about_y = np.array([[math.cos(ay), 0, math.sin(ay)], [0, 1, 0], [-math.sin(ay), 0, math.cos(ay)]])
    return about_y @ about_x


def face_down(direction: NDArray[np.float64]) -> tuple[float, float]:
    """The `rotate_x` and `rotate_y` (degrees) that turn a unit vector to point straight down.

    Only these two axes are used, in PrusaSlicer's order, so no Z rotation is needed (rotating +-90 about Y together
    with Z is where PrusaSlicer is odd, ADR 0015). The smaller of the two possible turns is returned.
    """
    x, y, z = (float(v) for v in direction)
    options = []
    for turn in (math.atan2(y, z), math.atan2(-y, -z)):  # the second is half a turn about X from the first
        lifted = y * math.sin(turn) + z * math.cos(turn)  # z after the X rotation; y is zero by construction
        about_y = math.atan2(x, -lifted)
        options.append((abs(turn) + abs(about_y), turn, about_y))
    _, turn, about_y = min(options)
    return _half_turns(math.degrees(turn)), _half_turns(math.degrees(about_y))


def _half_turns(degrees: float) -> float:
    """The angle within -180 to 180 (180 itself allowed), with no negative zero."""
    wrapped = (degrees + 180) % 360 - 180
    return 180.0 if wrapped == -180 else wrapped + 0.0


def _flat_faces(normals: NDArray[np.float64], areas: NDArray[np.float64]) -> list[NDArray[np.float64]]:
    """The mean direction of each of the largest groups of faces that point the same way, largest first.

    Groups are seeded from cells of similar direction ranked by their total area, not from the largest single face:
    a base made of many small triangles must beat a few big slanted ones.
    """
    cosine = math.cos(math.radians(CLUSTER_DEGREES))
    cells, owner = np.unique(np.round(normals * _CELLS_PER_UNIT).astype(int), axis=0, return_inverse=True)
    owner = owner.ravel()
    weight = np.bincount(owner, weights=areas, minlength=len(cells))
    direction = np.zeros((len(cells), 3))
    np.add.at(direction, owner, normals * areas[:, None])
    free = np.ones(len(areas), dtype=bool)
    found: list[NDArray[np.float64]] = []
    for cell in np.argsort(-weight):
        if len(found) >= MAX_FLAT_CANDIDATES:
            break
        length = float(np.linalg.norm(direction[cell]))
        if length == 0 or not free[owner == cell].any():
            continue
        seed = direction[cell] / length
        group = free & (normals @ seed >= cosine)
        mean = (normals[group] * areas[group, None]).sum(axis=0)
        found.append(mean / float(np.linalg.norm(mean)))
        free &= ~group
    return found


def _candidate_directions(normals: NDArray[np.float64], areas: NDArray[np.float64]) -> list[NDArray[np.float64]]:
    directions = _flat_faces(normals, areas)
    near = math.cos(math.radians(3))
    for axis in np.vstack([np.eye(3), -np.eye(3)]):
        if not any(float(axis @ direction) >= near for direction in directions):
            directions.append(axis)
    return directions


def _score(
    mesh: trimesh.Trimesh, rotate_x: float, rotate_y: float, as_stored: bool
) -> Orientation:  # rank is filled in once all are scored
    rotation = _rotation(rotate_x, rotate_y)
    faces = np.asarray(mesh.faces)
    areas = np.asarray(mesh.area_faces)
    vertices = np.asarray(mesh.vertices) @ rotation.T
    normals = np.asarray(mesh.face_normals) @ rotation.T
    heights = vertices[:, 2][faces]
    lowest = float(heights.min())
    on_bed = heights.max(axis=1) <= lowest + BED_TOLERANCE_MM
    base = float(areas[on_bed & (normals[:, 2] <= -math.cos(math.radians(FLAT_DEGREES)))].sum())
    overhang = float(areas[~on_bed & (normals[:, 2] < -math.sin(math.radians(OVERHANG_DEGREES)))].sum())
    silhouette = 0.5 * float((areas * np.abs(normals[:, 2])).sum())  # the area seen from above
    share = base / silhouette if silhouette > 0 else 0.0
    return Orientation(
        rank=0,
        rotate_x=rotate_x,
        rotate_y=rotate_y,
        height_mm=float(heights.max()) - lowest,
        base_area_mm2=base,
        base_share=share,
        overhang_area_mm2=overhang,
        overhang_share=overhang / float(areas.sum()),
        stable=share >= MIN_BASE_SHARE,
        as_stored=as_stored,
    )


def _ranked(options: list[Orientation]) -> list[Orientation]:
    """Best first, numbered from 1: stable before unstable, then least overhang, largest base, lowest height."""
    ordered = sorted(options, key=lambda o: (not o.stable, o.overhang_area_mm2, -o.base_area_mm2, o.height_mm))
    return [replace(option, rank=position) for position, option in enumerate(ordered, start=1)]


def suggest(mesh: trimesh.Trimesh, count: int = 5) -> list[Orientation]:
    """The best `count` orientations, best first, plus the one as stored (always listed, with its true rank).

    Stable orientations come before unstable ones, then the least overhang, then the largest base, then the lowest.
    """
    if len(mesh.faces) == 0:
        raise ValueError("This model has no faces to orient.")
    normals = np.asarray(mesh.face_normals)
    areas = np.asarray(mesh.area_faces)
    angles: dict[tuple[float, float], bool] = {(0.0, 0.0): True}  # the as-stored orientation, always scored
    for direction in _candidate_directions(normals, areas):
        rotate_x, rotate_y = face_down(direction)
        angles.setdefault((round(rotate_x, 2) + 0.0, round(rotate_y, 2) + 0.0), False)
    ranked = _ranked([_score(mesh, x, y, stored) for (x, y), stored in angles.items()])
    chosen = ranked[:count]
    if not any(option.as_stored for option in chosen):
        chosen.append(next(option for option in ranked if option.as_stored))
    return chosen
