---
status: accepted
date: 2026-11-14
decision-makers: Sebastien Coutu
---

# Suggest orientations from geometry

## Context and Problem Statement

Choosing which way up to print a model was the weakest part of working with this server. The statue was misdiagnosed
twice, and a corrected diagnosis still left its base tilted 16 degrees, so it would have stood on one edge
([ADR 0017](0017-close-a-hole-with-a-flat-base.md)). Previews let an orientation be looked at
([ADR 0015](0015-preview-transforms-by-asking-prusaslicer.md)), but something still had to propose it. What should the
server offer?

## Decision Drivers

* Replace guessing with measurements: bed contact, support needed, height.
* The rotations returned must work in PrusaSlicer exactly as given, including its quirks (ADR 0015).
* Say plainly what the numbers do not know.
* No dependency beyond numpy (scipy is not installed, so no convex hull).
* No hard-coded print advice for materials.

## Considered Options

* Do nothing: callers keep trying rotations and previewing them
* Score only the six axis-aligned orientations
* Score the large flat faces of the mesh, the axes and the orientation as stored
* Search the whole sphere of orientations and optimise

## Decision Outcome

Chosen option: "score the large flat faces, the axes and the orientation as stored", as `orientation.py` and the
read-only tool `suggest_orientation`.

* **Candidates.** Face normals are grouped by direction and ranked by their total area (a base made of many small
  triangles must beat a few large slanted ones, which a first version got wrong), the 14 largest groups become
  candidates, and the six axes and the identity are always added.
* **Rotations.** Each candidate is turned to point down with `rotate_x` and then `rotate_y` only, the smaller of the
  two possible turns. No Z rotation is ever needed, so PrusaSlicer's odd case (exactly +-90 about Y with a Z
  rotation) cannot occur. Real-binary tests export the model through PrusaSlicer with the returned angles and check
  that the base is level at the bed, for a cone at six odd angles including +-90 about X and Y.
* **Scores.** `base_area_mm2` is the downward-facing surface within 0.3 mm of the lowest point;
  `overhang_area_mm2` is surface off the bed that leans past 45 degrees (PrusaSlicer's default threshold); `height_mm`
  is the height. An orientation is `stable` when its base is at least 5% of the model's silhouette seen from above;
  below that it stands on a point or an edge, which is also what PrusaSlicer refuses as "no extrusions in the first
  layer".
* **Ranking.** Stable before unstable, then least overhang, then largest base, then lowest. The as-stored orientation
  is always listed with its true rank.
* **Holes.** An open base is not a base, so `close_holes=true` scores the model with its flat holes capped
  ([ADR 0014](0014-cap-flat-holes-on-request.md)); without it a warning says the capped scan would be better.
  PrusaSlicer projects are refused, since their own placement does not combine with these rotations as scored.

### How well the score tracks reality

Checked against PrusaSlicer on the statue (capped), slicing three orientations with automatic supports:

| Orientation | Predicted overhang | Real support filament |
|---|---|---|
| best (`rotate_x` 73.9) | 2,163 mm2 | 15.0 g |
| head down (`rotate_x` -90) | 3,797 mm2 | 21.6 g |
| as stored | 4,114 mm2 | 18.0 g |

The best option really is the cheapest, which is what the tool is for. The second and third are in the wrong order
(8% apart in area, 20% apart in filament), so overhang area is a rough guide and not a measure, and the tool says
orientations within about 10% are effectively tied. A column-volume estimate (area times height above the bed) was
tried and picked the as-stored orientation, which is worse, so it was not adopted. This rests on one model and should
be rechecked on others.

Over the user's library (71 plain models; the 61 PrusaSlicer projects are skipped): no errors, median under 0.1 s,
slowest 9.8 s (a 2M-triangle OBJ). In 33 a different orientation scored better than as stored, and in 9 the model as
stored rests on no real base (for example two planters exported lying on their side, 8 mm2 of base, which the tool
stands up on 1,845 and 1,907 mm2).

### Consequences

* Good, because an orientation is now one call with measured trade-offs, and it found the statue's 16 degree tilt.
* Good, because the angles are verified through the real PrusaSlicer, and avoid its known quirk.
* Bad, because the scores are geometry only: nothing about strength, appearance, layer lines, bridging or material,
  and a faceted scan's many small faces make overhang area noisy.
* Bad, because candidates come from flat faces and axes, so an orientation that is good only at an arbitrary angle
  (a vase leaning on a curved side) is not proposed.
* Bad, because `FLAT_DEGREES` (8) is a heuristic that the on-bed height test mostly makes redundant; it only matters
  for faces under about 17 mm across.
* Bad, because the 5% stability line and the 14 candidates are judgement calls, kept as named constants.

### Confirmation

Unit tests for the rotation maths (any direction ends pointing down; angles within half a turn), for finding the
flat faces of a turned box and the axes of a sphere, for ranking with hand-made options, and for the scores on cones,
boxes, a sphere and a tilted cone. Tool tests for holes, counts, refusals and warnings, and stdio tests for the
schema and the description's caveats. Real-binary tests that the returned angles level the base in PrusaSlicer and
that a tilted cone is refused as stored but prints a whole first layer when levelled. The dogfood sweep has an
`orientation` step that records the verdict per file.

## Pros and Cons of the Options

### Do nothing

* Good, because there is nothing to maintain.
* Bad, because orientation stays a guess, which is where this project kept going wrong.

### Score only the axis-aligned orientations

* Good, because it is simple.
* Bad, because it cannot see a tilted base: the statue's 16 degrees, the very case that motivated this.

### Score flat faces, axes and as stored

* Good, because of the decision outcome above.
* Bad, because of the consequences above.

### Search all orientations and optimise

* Good, because it could find non-obvious angles.
* Bad, because the score is too rough to justify the optimisation, and it costs far more time per call.

## More Information

PrusaMCP, the server examined in [ADR 0004](0004-build-our-own-server.md), has orientation scoring too; it was not
copied here and its approach was not read for this work.
