"""Candidate orientations for a model and how each scores (src/prusaslicer_mcp/orientation.py, ADR 0018)."""

from __future__ import annotations

import math

import numpy as np
import pytest
import trimesh

from prusaslicer_mcp import orientation


def rotation(rotate_x: float, rotate_y: float) -> np.ndarray:
    """PrusaSlicer's order for these two axes: about X first, then about the fixed Y axis."""
    ax, ay = math.radians(rotate_x), math.radians(rotate_y)
    about_x = np.array([[1, 0, 0], [0, math.cos(ax), -math.sin(ax)], [0, math.sin(ax), math.cos(ax)]])
    about_y = np.array([[math.cos(ay), 0, math.sin(ay)], [0, 1, 0], [-math.sin(ay), 0, math.cos(ay)]])
    return about_y @ about_x


def cone(apex_up: bool = True) -> trimesh.Trimesh:
    """A flat cone, 40 mm across and 10 mm tall: it needs no support on its base, and a lot on its apex."""
    mesh = trimesh.creation.cone(radius=20, height=10, sections=48)
    if not apex_up:
        mesh.apply_transform(trimesh.transformations.rotation_matrix(math.pi, [1, 0, 0]))
    return mesh


def turned(mesh: trimesh.Trimesh, x: float, y: float, z: float) -> trimesh.Trimesh:
    """The mesh rotated about fixed X, then Y, then Z, in degrees: a model that was exported at some odd angle."""
    result = mesh.copy()
    for axis, degrees in (([1, 0, 0], x), ([0, 1, 0], y), ([0, 0, 1], z)):
        result.apply_transform(trimesh.transformations.rotation_matrix(math.radians(degrees), axis))
    return result


# --------------------------------------------------------------------------- the rotation that puts a face down


@pytest.mark.parametrize(
    "direction",
    [
        (0, 0, -1),
        (0, 0, 1),
        (1, 0, 0),
        (-1, 0, 0),
        (0, 1, 0),
        (0, -1, 0),
        (0.3, 0.5, -0.8),
        (-0.7, 0.2, 0.4),
        (0.004, -0.961, -0.277),  # the base of a scanned statue, 16 degrees off its Y axis
    ],
)
def test_the_rotation_for_a_face_turns_it_to_point_straight_down(direction):
    # Given the outward direction of a face, as a unit vector
    unit = np.array(direction, dtype=float)
    unit /= np.linalg.norm(unit)

    # When the rotate_x and rotate_y that put it down are worked out and applied in PrusaSlicer's order
    rotate_x, rotate_y = orientation.face_down(unit)
    result = rotation(rotate_x, rotate_y) @ unit

    # Then the face points to -z
    assert result == pytest.approx((0, 0, -1), abs=1e-9)


@pytest.mark.parametrize("direction", [(0.3, 0.5, -0.8), (-0.7, 0.2, 0.4), (0, 1, 0), (1, 0, 0), (0, 0, 1)])
def test_the_angles_are_within_half_a_turn_either_way(direction):
    # Given a direction

    # When the angles are worked out
    rotate_x, rotate_y = orientation.face_down(np.array(direction, dtype=float) / np.linalg.norm(direction))

    # Then each is within -180 to 180 degrees
    assert -180 < rotate_x <= 180
    assert -180 < rotate_y <= 180


def test_a_face_that_already_points_down_needs_no_rotation():
    # Given a face pointing straight down

    # When the rotation is worked out
    rotate_x, rotate_y = orientation.face_down(np.array([0.0, 0.0, -1.0]))

    # Then none is needed
    assert (rotate_x, rotate_y) == (0.0, 0.0)


# --------------------------------------------------------------------------- scoring orientations


def test_a_cone_is_best_on_its_base_and_worst_on_its_apex():
    # Given a cone standing on its base

    # When orientations are suggested
    options = orientation.suggest(cone(), count=10)

    # Then the first is the cone as it stands, with a full base and no overhang
    best = options[0]
    assert (best.rotate_x, best.rotate_y) == (0.0, 0.0)
    assert best.height_mm == pytest.approx(10)
    assert best.base_area_mm2 == pytest.approx(1253, rel=0.01)
    assert best.overhang_area_mm2 == 0
    assert best.stable is True


def test_a_cone_on_its_apex_is_unstable_and_all_overhang():
    # Given a cone that was exported apex down

    # When orientations are suggested
    options = orientation.suggest(cone(apex_up=False), count=10)
    as_stored = next(option for option in options if option.as_stored)

    # Then as stored it rests on a point and its whole side is overhang
    assert as_stored.base_area_mm2 == pytest.approx(0, abs=1)
    assert as_stored.stable is False
    assert as_stored.overhang_area_mm2 > 1000


def test_a_cone_exported_apex_down_is_turned_base_down_by_the_best_option():
    # Given a cone exported apex down
    mesh = cone(apex_up=False)

    # When the best orientation is applied to it
    best = orientation.suggest(mesh)[0]
    vertices = mesh.vertices @ rotation(best.rotate_x, best.rotate_y).T

    # Then its base is the lowest thing: 48 rim points and the centre all sit at the bottom, and the apex is on top
    low = vertices[:, 2].min()
    assert (vertices[:, 2] <= low + 1e-6).sum() >= 48
    assert vertices[:, 2].max() - low == pytest.approx(10)
    assert best.overhang_area_mm2 == 0


@pytest.mark.parametrize("angles", [(37, -20, 110), (90, 0, 0), (0, 90, 0), (-135, 25, 60)])
def test_a_cone_at_any_angle_is_stood_on_its_base(angles):
    # Given a cone exported at an odd angle
    mesh = turned(cone(), *angles)

    # When the best orientation is applied to it
    best = orientation.suggest(mesh)[0]
    vertices = mesh.vertices @ rotation(best.rotate_x, best.rotate_y).T

    # Then it is level on its base, so the whole 40 mm base is at the bottom, 10 mm tall (angles are given to 0.01
    # degrees, which leaves a 40 mm base within about 0.004 mm of level)
    assert (vertices[:, 2] <= vertices[:, 2].min() + 1e-2).sum() >= 48
    assert best.height_mm == pytest.approx(10, abs=0.01)
    assert best.base_area_mm2 == pytest.approx(1253, rel=0.01)


def test_a_cone_whose_base_is_tilted_is_levelled():
    # Given a cone standing on its base but tilted 16 degrees, like a scan whose base is not square to its axis
    mesh = turned(cone(), 16, 0, 0)

    # When the best orientation is applied to it
    best = orientation.suggest(mesh)[0]

    # Then a correction of 16 degrees is suggested, not "as stored", and the base is whole
    assert abs(best.rotate_x) == pytest.approx(16, abs=0.5)
    assert best.as_stored is False
    assert best.base_area_mm2 == pytest.approx(1253, rel=0.01)


def test_a_box_lies_on_its_largest_face_when_nothing_overhangs():
    # Given a 10 x 20 x 30 mm box, which has no overhang in any orientation
    mesh = trimesh.creation.box(extents=(10, 20, 30))

    # When orientations are suggested
    options = orientation.suggest(mesh, count=6)

    # Then the largest base comes first, and the tallest orientation, on the smallest face, comes last
    assert options[0].base_area_mm2 == pytest.approx(20 * 30)
    assert options[0].height_mm == pytest.approx(10)
    assert options[-1].base_area_mm2 == pytest.approx(10 * 20)
    assert [option.overhang_area_mm2 for option in options] == [0] * len(options)


def test_the_orientation_as_stored_is_always_listed_with_its_rank():
    # Given a model whose as-stored orientation is not the best
    mesh = cone(apex_up=False)

    # When only the single best option is asked for
    options = orientation.suggest(mesh, count=1)

    # Then the as-stored one is added after it, with its true rank
    assert [option.as_stored for option in options] == [False, True]
    assert options[0].rank == 1
    assert options[1].rank > 1


def test_the_as_stored_orientation_is_not_listed_twice_when_it_is_the_best():
    # Given a cone standing on its base

    # When orientations are suggested
    options = orientation.suggest(cone(), count=3)

    # Then exactly one option is the as-stored one
    assert sum(option.as_stored for option in options) == 1


def test_a_tall_thin_post_standing_on_its_end_is_stable_because_it_rests_on_its_whole_silhouette():
    # Given a 4 x 4 x 60 mm post
    mesh = trimesh.creation.box(extents=(4, 4, 60))

    # When orientations are suggested
    options = orientation.suggest(mesh, count=6)
    standing = next(option for option in options if option.height_mm == pytest.approx(60))

    # Then upright it rests on all of its footprint, so it is not flagged
    assert standing.base_share == pytest.approx(1.0)
    assert standing.stable is True


def test_a_sphere_rests_on_a_point_in_every_orientation():
    # Given a sphere
    mesh = trimesh.creation.icosphere(subdivisions=3, radius=15)

    # When orientations are suggested
    options = orientation.suggest(mesh, count=8)

    # Then none of them has a real base
    assert not any(option.stable for option in options)
    assert all(option.base_share < 0.05 for option in options)


def test_a_model_with_no_faces_is_refused_clearly():
    # Given an empty mesh
    mesh = trimesh.Trimesh()

    # When / Then orientations cannot be suggested
    with pytest.raises(ValueError, match="no faces"):
        orientation.suggest(mesh)


# --------------------------------------------------------------------------- finding the candidates


def test_every_face_of_a_turned_box_is_a_candidate_largest_first():
    # Given a 10 x 20 x 30 mm box exported at an odd angle
    mesh = turned(trimesh.creation.box(extents=(10, 20, 30)), 37, -20, 110)

    # When its flat faces are looked for
    faces = orientation._flat_faces(np.asarray(mesh.face_normals), np.asarray(mesh.area_faces))

    # Then all six are found, the two 20 x 30 faces first
    assert len(faces) == 6
    areas = [float(np.asarray(mesh.area_faces)[np.asarray(mesh.face_normals) @ face > 0.99].sum()) for face in faces]
    assert areas == pytest.approx([600, 600, 300, 300, 200, 200])


def test_the_six_axis_directions_are_candidates_for_a_smooth_shape():
    # Given a sphere, which has no flat faces for them to coincide with
    mesh = trimesh.creation.icosphere(subdivisions=3, radius=15)

    # When the candidate directions are worked out
    directions = orientation._candidate_directions(np.asarray(mesh.face_normals), np.asarray(mesh.area_faces))

    # Then every axis, both ways, is within 3 degrees of one of them
    for axis in np.vstack([np.eye(3), -np.eye(3)]):
        assert max(float(axis @ direction) for direction in directions) >= math.cos(math.radians(3))


# --------------------------------------------------------------------------- ranking


def option(
    *,
    rank: int = 0,
    height_mm: float = 10.0,
    base_area_mm2: float = 100.0,
    overhang_area_mm2: float = 0.0,
    stable: bool = True,
) -> orientation.Orientation:
    """An orientation with sensible values for everything a test does not care about."""
    return orientation.Orientation(
        rank=rank,
        rotate_x=0.0,
        rotate_y=0.0,
        height_mm=height_mm,
        base_area_mm2=base_area_mm2,
        base_share=0.5,
        overhang_area_mm2=overhang_area_mm2,
        overhang_share=0.0,
        stable=stable,
        as_stored=False,
    )


def test_a_stable_orientation_beats_an_unstable_one_even_with_more_overhang():
    # Given an unstable orientation with no overhang and a stable one with plenty
    unstable = option(stable=False, overhang_area_mm2=0.0, base_area_mm2=0.0)
    stable = option(stable=True, overhang_area_mm2=500.0)

    # When they are ranked
    ranked = orientation._ranked([unstable, stable])

    # Then the stable one is first
    assert [o.stable for o in ranked] == [True, False]
    assert [o.rank for o in ranked] == [1, 2]


def test_less_overhang_beats_a_larger_base():
    # Given two stable orientations, one with a small base and no overhang, one with a big base and some
    clean = option(base_area_mm2=50.0, overhang_area_mm2=0.0)
    overhanging = option(base_area_mm2=900.0, overhang_area_mm2=10.0)

    # When they are ranked
    ranked = orientation._ranked([overhanging, clean])

    # Then the one without overhang is first
    assert ranked[0] == option(rank=1, base_area_mm2=50.0, overhang_area_mm2=0.0)


def test_with_equal_overhang_the_larger_base_wins_and_then_the_lower_one():
    # Given three stable orientations with no overhang: a big base, and two small ones of different heights
    big = option(base_area_mm2=900.0, height_mm=30.0)
    low = option(base_area_mm2=100.0, height_mm=10.0)
    tall = option(base_area_mm2=100.0, height_mm=40.0)

    # When they are ranked
    ranked = orientation._ranked([tall, low, big])

    # Then the big base is first, then the lower of the two equal bases
    assert [(o.base_area_mm2, o.height_mm) for o in ranked] == [(900.0, 30.0), (100.0, 10.0), (100.0, 40.0)]
