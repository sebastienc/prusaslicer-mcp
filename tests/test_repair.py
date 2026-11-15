"""Finding and closing the open boundaries of a mesh (src/prusaslicer_mcp/repair.py, ADR 0014)."""

from __future__ import annotations

import numpy as np
import pytest
import trimesh

from prusaslicer_mcp import repair


def _without_bottom(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    """The mesh with every face that points straight down removed: a solid whose base is missing."""
    keep = mesh.face_normals[:, 2] < -0.99
    return trimesh.Trimesh(mesh.vertices, mesh.faces[~keep])


@pytest.fixture
def open_cylinder() -> trimesh.Trimesh:
    # A 20 mm wide, 30 mm tall cylinder with no bottom, like a scan whose base was never captured
    return _without_bottom(trimesh.creation.cylinder(radius=10, height=30, sections=48))


def _star_prism(points: int = 8, height: float = 4.0) -> trimesh.Trimesh:
    """A star-shaped prism with a missing base: its hole is a non-convex polygon."""
    count = 2 * points
    angles = np.linspace(0, 2 * np.pi, count, endpoint=False)
    radii = np.where(np.arange(count) % 2 == 0, 10.0, 4.0)
    ring = np.column_stack([radii * np.cos(angles), radii * np.sin(angles)])
    bottom = np.column_stack([ring, np.zeros(count)])
    top = np.column_stack([ring, np.full(count, height)])
    vertices = np.vstack([bottom, top, [[0.0, 0.0, height]]])
    faces = []
    for i in range(count):
        j = (i + 1) % count
        faces += [[i, j, count + j], [i, count + j, count + i], [count + i, count + j, 2 * count]]
    return trimesh.Trimesh(vertices, faces)


def _star_area(points: int = 8) -> float:
    count = 2 * points
    angles = np.linspace(0, 2 * np.pi, count, endpoint=False)
    radii = np.where(np.arange(count) % 2 == 0, 10.0, 4.0)
    x, y = radii * np.cos(angles), radii * np.sin(angles)
    return float(0.5 * abs(np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y)))


def test_a_closed_mesh_has_no_holes():
    # Given a watertight cylinder
    mesh = trimesh.creation.cylinder(radius=10, height=30, sections=48)

    # When its holes are looked for
    holes = repair.find_holes(mesh)

    # Then there are none
    assert holes == []


def test_a_missing_base_is_one_closable_hole(open_cylinder):
    # Given a cylinder with no bottom

    # When its holes are looked for
    holes = repair.find_holes(open_cylinder)

    # Then there is one hole, as long as the cylinder's rim, flat, and worth closing
    assert len(holes) == 1
    assert holes[0].edges == 48
    assert holes[0].flatness < 0.01
    assert holes[0].size_mm == pytest.approx(20, abs=0.1)
    assert holes[0].closable


def test_closing_a_missing_base_makes_the_mesh_watertight_and_solid(open_cylinder):
    # Given a cylinder with no bottom, and the volume the full cylinder has
    full = trimesh.creation.cylinder(radius=10, height=30, sections=48)

    # When its holes are closed
    closed = repair.close_holes(open_cylinder)

    # Then the mesh is watertight and encloses the same volume as the full cylinder, so the cap faces outward
    assert closed.closed == 1
    assert closed.left_open == 0
    assert closed.mesh.is_watertight
    assert closed.mesh.is_winding_consistent
    assert closed.mesh.volume == pytest.approx(full.volume, rel=1e-6)


def test_closing_a_non_convex_hole_fills_exactly_the_hole():
    # Given a star-shaped prism with no base, whose hole is a non-convex polygon
    mesh = _star_prism()

    # When its hole is closed
    closed = repair.close_holes(mesh)

    # Then the cap covers the star and nothing outside it, so the volume is the star's area times the height
    assert closed.closed == 1
    assert closed.mesh.is_watertight
    assert closed.mesh.volume == pytest.approx(_star_area() * 4.0, rel=1e-6)


def test_closing_leaves_the_input_mesh_alone(open_cylinder):
    # Given a mesh with a hole and its face count
    faces = len(open_cylinder.faces)

    # When the hole is closed
    repair.close_holes(open_cylinder)

    # Then the original mesh is unchanged
    assert len(open_cylinder.faces) == faces
    assert not open_cylinder.is_watertight


def test_a_watertight_mesh_is_returned_as_it_is():
    # Given a watertight mesh
    mesh = trimesh.creation.box(extents=(10, 10, 10))

    # When its holes are closed
    closed = repair.close_holes(mesh)

    # Then nothing is closed and the faces are the same
    assert (closed.closed, closed.left_open) == (0, 0)
    assert len(closed.mesh.faces) == len(mesh.faces)


def test_a_tiny_hole_is_left_for_prusaslicer_to_repair():
    # Given a sphere with a single triangle missing
    sphere = trimesh.creation.icosphere(subdivisions=3)
    mesh = trimesh.Trimesh(sphere.vertices, sphere.faces[1:])

    # When its holes are looked for and closed
    holes = repair.find_holes(mesh)
    closed = repair.close_holes(mesh)

    # Then the three-edge hole is reported but not closable, and is left open
    assert [hole.edges for hole in holes] == [3]
    assert not holes[0].closable
    assert (closed.closed, closed.left_open) == (0, 1)
    assert len(closed.mesh.faces) == len(mesh.faces)


def test_a_bent_hole_is_not_closed():
    # Given a finely divided box with its top and front faces removed, so the hole wraps round a corner
    box = trimesh.creation.box(extents=(10, 10, 10)).subdivide().subdivide()
    top_or_front = (box.face_normals[:, 2] > 0.99) | (box.face_normals[:, 1] < -0.99)
    mesh = trimesh.Trimesh(box.vertices, box.faces[~top_or_front])

    # When its holes are looked for and closed
    holes = repair.find_holes(mesh)
    closed = repair.close_holes(mesh)

    # Then the hole is too far from flat to cap, and stays open
    assert len(holes) == 1
    assert holes[0].flatness > repair.MAX_FLATNESS
    assert not holes[0].closable
    assert (closed.closed, closed.left_open) == (0, 1)


def test_a_hole_whose_edge_branches_is_not_closable():
    # Given two cylinders with no bottoms that meet at one vertex, so the open edge touches itself
    left = _without_bottom(trimesh.creation.cylinder(radius=5, height=20, sections=24))
    right = _without_bottom(trimesh.creation.cylinder(radius=5, height=20, sections=24))
    right.apply_translation([10, 0, 0])  # their rims touch at x = 5
    both = trimesh.Trimesh(
        np.vstack([left.vertices, right.vertices]), np.vstack([left.faces, right.faces + len(left.vertices)])
    )
    both.merge_vertices()

    # When its holes are looked for
    holes = repair.find_holes(both)

    # Then the touching rims form one hole that cannot be closed as a single polygon
    assert len(holes) == 1
    assert holes[0].edges == 48
    assert not holes[0].closable


def test_two_separate_holes_are_both_closed():
    # Given a cylinder with neither its bottom nor its top
    full = trimesh.creation.cylinder(radius=10, height=30, sections=48)
    keep = np.abs(full.face_normals[:, 2]) < 0.99
    mesh = trimesh.Trimesh(full.vertices, full.faces[keep])

    # When its holes are closed
    closed = repair.close_holes(mesh)

    # Then both ends are capped
    assert closed.closed == 2
    assert closed.mesh.is_watertight
    assert closed.mesh.volume == pytest.approx(full.volume, rel=1e-6)


def test_a_hole_too_large_to_cap_quickly_is_left_open(open_cylinder, monkeypatch):
    # Given a limit below the hole's size
    monkeypatch.setattr(repair, "MAX_HOLE_EDGES", 40)

    # When its holes are looked for and closed
    holes = repair.find_holes(open_cylinder)
    closed = repair.close_holes(open_cylinder)

    # Then the 48-edge hole is not closable and stays open
    assert not holes[0].closable
    assert (closed.closed, closed.left_open) == (0, 1)


def test_a_hole_bordered_by_a_flipped_face_is_not_closable(open_cylinder):
    # Given a cylinder with no bottom, in which one face along the rim is wound the wrong way
    on_rim = (open_cylinder.triangles[:, :, 2] < -14.99).sum(axis=1) == 2
    faces = open_cylinder.faces.copy()
    flipped = np.flatnonzero(on_rim)[0]
    faces[flipped] = faces[flipped][::-1]
    mesh = trimesh.Trimesh(open_cylinder.vertices, faces, process=False)

    # When its holes are looked for
    holes = repair.find_holes(mesh)

    # Then the boundary is not a consistent loop, so nothing is closable
    assert holes
    assert not any(hole.closable for hole in holes)


def test_an_open_chain_with_loose_ends_is_not_closable_and_does_not_crash(open_cylinder):
    # Given a cylinder with no bottom plus one extra face glued onto a rim edge, so that edge is no longer open
    # and the rest of the rim becomes a chain with two loose ends (as around a non-manifold edge in a real scan)
    on_rim = open_cylinder.triangles[:, :, 2] < -14.99
    face = np.flatnonzero(on_rim.sum(axis=1) == 2)[0]
    first, second = open_cylinder.faces[face][on_rim[face]]
    top = np.flatnonzero(open_cylinder.vertices[:, 2] > 14.99)[0]
    faces = np.vstack([open_cylinder.faces, [[first, second, top]]])
    mesh = trimesh.Trimesh(open_cylinder.vertices, faces, process=False)

    # When its holes are looked for and closed
    holes = repair.find_holes(mesh)
    closed = repair.close_holes(mesh)

    # Then the chain is reported but not closable, and nothing is capped
    assert holes
    assert not any(hole.closable for hole in holes)
    assert closed.closed == 0
    assert len(closed.mesh.faces) == len(mesh.faces)


# --------------------------------------------------------------------------- a ragged rim still gets a flat base


def _ragged(cylinder: trimesh.Trimesh, raised, amount: float) -> trimesh.Trimesh:
    """The open cylinder with some points of its rim raised by `amount`, like the uneven edge of a scanned base."""
    vertices = cylinder.vertices.copy()
    rim = np.flatnonzero(vertices[:, 2] < -14.99)
    vertices[rim[np.asarray(raised(len(rim)), dtype=bool)], 2] += amount
    return trimesh.Trimesh(vertices, cylinder.faces, process=False)


EVERY_OTHER = lambda count: np.arange(count) % 2 == 0  # noqa: E731  (a symmetric pattern: the base stays level)
RANDOM_70 = lambda count: np.random.default_rng(7).random(count) < 0.7  # noqa: E731  (some points stay on the plane)


@pytest.mark.parametrize("raised", [EVERY_OTHER, RANDOM_70], ids=["every other point", "random points"])
def test_a_ragged_rim_is_closed_with_a_watertight_mesh(open_cylinder, raised):
    # Given a cylinder with no bottom whose rim is uneven, with some points left on the lowest level
    scan = _ragged(open_cylinder, raised, amount=1.0)

    # When its hole is closed
    closed = repair.close_holes(scan)

    # Then the mesh is watertight and consistently wound
    assert closed.closed == 1
    assert closed.mesh.is_watertight
    assert closed.mesh.is_winding_consistent


def test_the_base_over_a_ragged_rim_is_one_flat_plane(open_cylinder):
    # Given a cylinder with no bottom whose rim has every other point raised 1 mm
    scan = _ragged(open_cylinder, EVERY_OTHER, amount=1.0)

    # When its hole is closed
    closed = repair.close_holes(scan)

    # Then every cap face lies in the plane of the outermost rim point, so the base prints flat
    lowest = closed.mesh.vertices[:, 2].min()
    in_plane = np.isclose(closed.mesh.vertices[:, 2], lowest, atol=1e-9)
    cap = closed.mesh.faces[in_plane[closed.mesh.faces].all(axis=1)]
    assert len(cap) >= 46  # a 48-point ring has at least 46 triangles
    triangles = closed.mesh.vertices[cap]
    normals = np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0])
    assert (normals[:, 2] < 0).all()  # all of them face down, outward


def test_the_rim_is_carried_down_to_the_base_and_the_distance_is_reported(open_cylinder):
    # Given a cylinder with no bottom whose rim has every other point raised 1 mm
    scan = _ragged(open_cylinder, EVERY_OTHER, amount=1.0)

    # When its hole is closed
    closed = repair.close_holes(scan)

    # Then the base was extended by the 1 mm the raised points were short of the plane
    assert closed.extended_mm == pytest.approx(1.0, abs=1e-6)


def test_closing_never_moves_an_existing_vertex(open_cylinder):
    # Given a ragged scan and its vertices
    scan = _ragged(open_cylinder, RANDOM_70, amount=1.0)
    before = scan.vertices.copy()

    # When its hole is closed
    closed = repair.close_holes(scan)

    # Then the original vertices are where they were, and only new ones were added
    assert len(closed.mesh.vertices) > len(before)
    assert np.array_equal(closed.mesh.vertices[: len(before)], before)


def test_a_level_rim_needs_no_extra_vertices(open_cylinder):
    # Given a cylinder with no bottom and a level rim

    # When its hole is closed
    closed = repair.close_holes(open_cylinder)

    # Then nothing is carried or added: the cap joins the rim directly
    assert closed.extended_mm == 0.0
    assert len(closed.mesh.vertices) == len(open_cylinder.vertices)
