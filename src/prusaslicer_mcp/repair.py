"""Find the open boundaries of a mesh and cap the ones that are a missing flat face (ADR 0014).

A scan often lacks its base entirely. PrusaSlicer then has no bottom to print on and refuses the model, and
`trimesh` has no hole filler that works without extra dependencies, so a hole that is one simple, nearly flat loop
is triangulated here by ear clipping. Anything else (a shell with many openings, a bent hole, a boundary that
touches itself) is reported and left alone: guessing a surface there would invent geometry.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    import trimesh
    from numpy.typing import NDArray

# PrusaSlicer closes a gap of a few edges by itself, so only a hole with at least this many edges is worth capping.
MIN_HOLE_EDGES = 12
# Ear clipping rechecks the whole polygon for every ear, so the cost grows with the square of the loop's length.
MAX_HOLE_EDGES = 10_000
# Smallest over largest spread of the loop's points: 0 is perfectly flat. Real scans measured 0.01 and 0.03; the open
# shells that must not be capped measured above 0.5.
MAX_FLATNESS = 0.1


@dataclass(frozen=True)
class Hole:
    """One open boundary: the edges that belong to a single face, joined into a connected set."""

    edges: int
    vertices: tuple[int, ...] | None  # the loop in order, along the faces' own edge direction; None if it branches
    flatness: float
    size_mm: float

    @property
    def closable(self) -> bool:
        """A simple loop of a useful length that lies close to a plane."""
        return (
            self.vertices is not None
            and MIN_HOLE_EDGES <= self.edges <= MAX_HOLE_EDGES
            and self.flatness <= MAX_FLATNESS
        )


@dataclass(frozen=True)
class Closing:
    """The mesh after capping, how many holes were capped and how many remain open."""

    mesh: trimesh.Trimesh
    closed: int
    left_open: int
    extended_mm: float = 0.0  # how far the ragged rim was carried to reach a flat base, at most


def _boundary_edges(mesh: trimesh.Trimesh) -> NDArray[np.int64]:
    """The directed edges that belong to exactly one face (so they border a hole)."""
    faces = np.asarray(mesh.faces, dtype=np.int64)
    directed = np.concatenate([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]])
    _, inverse, counts = np.unique(np.sort(directed, axis=1), axis=0, return_inverse=True, return_counts=True)
    return directed[counts[inverse.ravel()] == 1]


def _components(edges: NDArray[np.int64]) -> list[list[int]]:
    """Group the boundary edges into connected sets: for each, the indices of its edges."""
    parent: dict[int, int] = {}

    def find(vertex: int) -> int:
        parent.setdefault(vertex, vertex)
        while parent[vertex] != vertex:
            parent[vertex] = parent[parent[vertex]]
            vertex = parent[vertex]
        return vertex

    for a, b in edges.tolist():
        parent[find(a)] = find(b)
    groups: dict[int, list[int]] = {}
    for index, (a, _) in enumerate(edges.tolist()):
        groups.setdefault(find(a), []).append(index)
    return list(groups.values())


def _ordered_loop(edges: NDArray[np.int64]) -> tuple[int, ...] | None:
    """The vertices in order if the edges form one simple loop, or None if they branch or leave a loose end."""
    following = dict(edges.tolist())
    # Every vertex must start exactly one open edge and end exactly one; then the edges are a single loop. Otherwise
    # the boundary branches (a vertex starts two edges), or a chain stops where a non-manifold edge was dropped.
    if len(following) != len(edges) or set(following.values()) != set(following):
        return None
    start = int(edges[0][0])
    loop = [start]
    current = following[start]
    while current != start:
        loop.append(current)
        current = following[current]
    return tuple(loop)


def _flatness(points: NDArray[np.float64]) -> float:
    if len(points) < 3:
        return 0.0
    spread = np.linalg.svd(points - points.mean(axis=0), compute_uv=False)
    return float(spread[2] / spread[0]) if spread[0] > 0 else 0.0


def find_holes(mesh: trimesh.Trimesh) -> list[Hole]:
    """Every open boundary of the mesh, largest first. Empty for a mesh with no open edges."""
    edges = _boundary_edges(mesh)
    holes = []
    for group in _components(edges):
        part = edges[group]
        points = np.asarray(mesh.vertices)[np.unique(part)]
        holes.append(
            Hole(
                edges=len(part),
                vertices=_ordered_loop(part),
                flatness=_flatness(points),
                size_mm=float(np.ptp(points, axis=0).max()),
            )
        )
    return sorted(holes, key=lambda hole: -hole.edges)


def _triangulate(points: NDArray[np.float64]) -> list[tuple[int, int, int]] | None:
    """Ear clipping: triangles over a simple polygon's points, wound the way the polygon runs. None if it fails."""
    x, y = points[:, 0], points[:, 1]
    area = 0.5 * float(np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y))
    if area == 0:
        return None
    sign = 1.0 if area > 0 else -1.0
    tolerance = 1e-12 * float(np.ptp(points, axis=0).max()) ** 2
    order = np.arange(len(points))
    triangles: list[tuple[int, int, int]] = []
    while len(order) > 3:
        a, b, c = points[np.roll(order, 1)], points[order], points[np.roll(order, -1)]
        turn = sign * ((b[:, 0] - a[:, 0]) * (c[:, 1] - a[:, 1]) - (b[:, 1] - a[:, 1]) * (c[:, 0] - a[:, 0]))
        for k in np.flatnonzero(turn > tolerance):  # convex corners only
            others = np.ones(len(order), dtype=bool)
            others[[k - 1, k, (k + 1) % len(order)]] = False
            p = points[order[others]]
            inside = np.ones(len(p), dtype=bool)
            for start, end in ((a[k], b[k]), (b[k], c[k]), (c[k], a[k])):
                side = (end[0] - start[0]) * (p[:, 1] - start[1]) - (end[1] - start[1]) * (p[:, 0] - start[0])
                inside &= side * sign >= 0
            if not inside.any():  # an ear: no other corner of the polygon lies in it
                triangles.append((int(order[k - 1]), int(order[k]), int(order[(k + 1) % len(order)])))
                order = np.delete(order, k)
                break
        else:
            return None  # no ear found: the loop crosses itself in this projection
    triangles.append((int(order[0]), int(order[1]), int(order[2])))
    return triangles


def _flat_cap(
    vertices: NDArray[np.float64], loop: tuple[int, ...], first_new: int
) -> tuple[NDArray[np.float64], list[list[int]], float] | None:
    """New points, faces and the largest drop, closing a loop with a perfectly flat base; None if it cannot.

    A scan's rim is ragged, so a cap joined straight to it is bumpy and the print would start from a point. Every
    existing vertex stays where it is: each rim point is carried outward to the plane of the outermost one, a thin
    wall joins it to the rim, and the flat ring of carried points is what gets capped.
    """
    rim = vertices[list(loop)]  # in the faces' edge direction
    centre = rim.mean(axis=0)
    cap_order = (rim - centre)[::-1]  # the cap runs against the faces' edge direction, so it faces outward
    normal = np.cross(cap_order, np.roll(cap_order, -1, axis=0)).sum(axis=0)
    length = float(np.linalg.norm(normal))
    if length == 0:
        return None
    normal /= length
    height = (rim - centre) @ normal
    drop = height.max() - height
    flat = rim + drop[:, None] * normal
    moved = drop > 1e-9 * max(float(np.ptp(rim, axis=0).max()), 1.0)
    ids = np.array(loop)
    ids[moved] = first_new + np.arange(int(moved.sum()))  # a rim point already on the plane is its own ring point

    axis = np.eye(3)[int(np.argmin(np.abs(normal)))]
    u = np.cross(normal, axis)
    u /= np.linalg.norm(u)
    plane = np.asarray(np.vstack([u, np.cross(normal, u)]), dtype=np.float64)
    triangles = _triangulate((flat - flat.mean(axis=0))[::-1] @ plane.T)
    if triangles is None:
        return None

    faces: list[list[int]] = []
    count = len(loop)
    for i in range(count):
        a, b = loop[i], loop[(i + 1) % count]
        flat_a, flat_b = int(ids[i]), int(ids[(i + 1) % count])
        if flat_a != a:
            faces.append([b, a, flat_a])
        if flat_b != b:
            faces.append([b, flat_a, flat_b])
    ring = ids[::-1]
    faces += [[int(ring[a]), int(ring[b]), int(ring[c])] for a, b, c in triangles]
    return flat[moved], faces, float(drop.max())


def close_holes(mesh: trimesh.Trimesh) -> Closing:
    """Cap every closable hole with a flat base. Returns a new mesh and leaves the input alone."""
    holes = find_holes(mesh)
    vertices = np.asarray(mesh.vertices, dtype=np.float64)
    extra: list[NDArray[np.float64]] = []
    new_faces: list[list[int]] = []
    left_open = 0
    extended = 0.0
    for hole in holes:
        first_new = len(vertices) + sum(len(points) for points in extra)
        capped = _flat_cap(vertices, hole.vertices, first_new) if hole.closable and hole.vertices is not None else None
        if capped is None:
            left_open += 1
            continue
        points, faces, drop = capped
        extra.append(points)
        new_faces += faces
        extended = max(extended, drop)
    if not new_faces:
        return Closing(mesh, 0, left_open)
    import trimesh  # imported here so that starting the server does not pay for it

    capped_mesh = trimesh.Trimesh(
        np.vstack([vertices, *extra]), np.vstack([mesh.faces, np.array(new_faces)]), process=False
    )
    return Closing(capped_mesh, len(holes) - left_open, left_open, extended)
