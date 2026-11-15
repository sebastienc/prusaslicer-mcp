---
status: accepted
date: 2026-11-14
decision-makers: Sebastien Coutu
---

# Close a hole with a flat base

## Context and Problem Statement

[ADR 0014](0014-cap-flat-holes-on-request.md) caps a scan's missing base by ear clipping the open loop, and its
evidence was that the capped statue, refused before, now sliced head-up at its full height. That evidence was too
weak: PrusaSlicer accepting a model does not mean it prints. Looking at the statue's first printed layers showed the
first layer was a single 0.3 x 0.2 mm move (2.8 mm of filament) and layer 5 only 4.8 x 3.5 mm. The bust would have
balanced on a point.

Two things caused it, and this decision is about the first:

1. **The cap was bumpy.** A scan's rim is ragged: the rim points of the statue deviate from their best-fit plane by
   -1.15 to +1.68 mm over 54 mm. Triangles joined straight to such a rim are not flat, so only the lowest rim points
   touch the bed and the base grows out of spikes. With the old cap, even at the correct tilt, the filament per layer
   crept up over seven layers (2.7, 3.0, 8.8, 9.3, 15.3, 24.2, 36.1 mm) instead of starting full.
2. **The base was tilted.** The statue's base plane is 16.1 degrees off its Y axis, so `rotate_x=90`, which stands
   the axis upright, stood the base on one edge. The right rotation is `rotate_x=73.9`, `rotate_y=0.2`. That is
   about choosing the orientation, not the cap (see ADR 0018).

How should a hole be closed so that the base prints flat?

## Decision Drivers

* The first layer of a capped scan must be a whole base, not a few points.
* Never move a vertex of the user's model: moving rim points folds the small triangles beside them.
* Say how far the shape was changed, so a result never hides it.

## Considered Options

* Keep ear clipping the loop as it is
* Move the rim points onto the best-fit plane
* Carry the rim outward to a plane, join it to the rim with a thin wall, and cap that flat ring

## Decision Outcome

Chosen option: "carry the rim outward to a plane". The cap's outward direction comes from the loop's own winding
(Newell's normal over the cap polygon). Each rim point is projected outward along it to the plane of the
outermost rim point, a wall of two triangles per rim edge joins the rim to the projected ring (a point already on the
plane is its own ring point and gets no wall), and the exactly planar ring is capped by ear clipping as before.

* Existing vertices never move; only new ones are added.
* The base is one plane, so it prints flat once that plane is down.
* The largest distance a rim point was carried is `Closing.extended_mm`, and the warning in `slice_model` and
  `preview_model` says "an uneven rim was extended by up to X mm so the base is flat" when it is 0.05 mm or more.

Measured on the real statue at the right tilt: the first layer is 164 mm of filament (a full base), against 2.7 mm
with the old cap.

### Consequences

* Good, because the base of a capped scan is flat and the first layer is whole.
* Good, because no existing vertex moves, so nothing folds.
* Bad, because the model gains up to a couple of millimetres of material along a ragged rim (the statue: up to
  about 2.8 mm), reported to the caller.
* Bad, because the wall can cross the model's own surface where the scan flares near the rim by more than the carried
  distance; PrusaSlicer unions such overlaps when it slices.
* Bad, because ADR 0014's test of "it slices" was too weak. Its other decisions stand.

### Confirmation

Unit tests that a ragged rim (every other point raised, and random points left on the plane) closes watertight and
consistently wound, that the cap is one plane facing outward, that the carried distance is reported, that no
existing vertex moves, and that a level rim adds no vertices. A real-binary test that a ragged scan base prints a
first layer carrying as much filament as the second, which fails against the old cap.

## Pros and Cons of the Options

### Keep ear clipping the loop

* Good, because it is simple and moves nothing.
* Bad, because the base is bumpy and prints from spikes.

### Move the rim points onto the plane

* Good, because it adds no material.
* Bad, because it moves up to 1.7 mm of a ragged rim at once, folding the scan's small neighbouring triangles.

### Carry the rim outward to a plane

* Good, because of the decision outcome above.
* Bad, because of the consequences above.

## More Information

The statue's measurements: `repair.find_holes` loop of 687 edges, deviation from its best-fit plane -1.15 to +1.68
mm, outward normal 16.1 degrees from -Y.
