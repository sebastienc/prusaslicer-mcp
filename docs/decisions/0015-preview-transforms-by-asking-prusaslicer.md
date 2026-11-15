---
status: accepted
date: 2026-11-14
decision-makers: Sebastien Coutu
---

# Preview transforms by asking PrusaSlicer

## Context and Problem Statement

`slice_model` can rotate and scale a model ([ADR 0012](0012-transform-with-prusaslicers-own-flags.md)) and cap its
holes ([ADR 0014](0014-cap-flat-holes-on-request.md)), but `preview_model` drew a model only as stored. Choosing an
orientation therefore meant a full slice to find out whether it was right, and the session that found the statue's
open base got its diagnosis wrong twice for want of a picture of the rotated model. How should a preview show a
model after its transforms?

## Decision Drivers

* The picture must show what PrusaSlicer will print, not what we think it will.
* An orientation should cost a second to check, not a slice.
* Do not re-implement behaviour PrusaSlicer already has, including its quirks (ADR 0012's own driver).

## Considered Options

* Apply the rotation and scale ourselves with trimesh and draw that
* Ask PrusaSlicer to export the transformed mesh (`--export-stl` with the same flags) and draw that
* Keep the preview as stored

## Decision Outcome

Chosen option: "ask PrusaSlicer to export the transformed mesh", because the straightforward maths turned out to
differ from PrusaSlicer in one case, and a preview that disagrees with the slice is worse than none.

The rotation was measured by exporting an asymmetric three-armed model with `--export-stl` and fitting the matrix
PrusaSlicer applied (exact, with no slicing noise):

* For a rotation about all three axes at generic angles (30, 45, 60 and -20, 70, 15 degrees) the result is exactly
  the fixed-axis order X, then Y, then Z, right-handed, as ADR 0012 recorded.
* `--rotate-y 90` together with `--rotate -90` is not: the model comes out upside down relative to that order (the
  matrix is the expected one turned 180 degrees about X). The earlier `--rotate-y 90 --rotate 90` and
  `--rotate-y -90 --rotate 90` match. Slicing confirms it: the first printed layer is the large end that the maths
  puts on top. This looks like PrusaSlicer's handling of exactly +-90 degrees about Y (gimbal lock), but the cause
  was not investigated.

So `preview_model` takes `rotate_x`, `rotate_y`, `rotate_z`, `scale` and `scale_to_fit`, validates them with the same
code as `slice_model`, and when any is given runs PrusaSlicer's `--export-stl` with the same flags into a temporary
folder and draws the result. Without transforms nothing is run and the file is drawn as stored. `close_holes` works
here too: the model is capped in memory first and PrusaSlicer is given the capped copy, so the picture shows the
repaired scan. The caption says which transforms were applied and what `close_holes` did.

The rotate descriptions, shared by both tools, warn about the +-90 case and point to the preview.

### Consequences

* Good, because the preview and the slice agree by construction, including where PrusaSlicer is odd.
* Good, because a statue's orientation and its capped base can be checked before slicing, in about a second.
* Bad, because a transformed preview needs PrusaSlicer installed (an untransformed one still does not).
* Bad, because the export tessellates and rewrites the whole mesh, so a transformed preview of a very large model
  costs a few seconds.
* Bad, because the +-90 quirk is PrusaSlicer's, so it is documented rather than fixed.

### Confirmation

Unit tests with a faked `--export-stl` for the flags, the caption, validation before anything runs, failures, and
`close_holes` alone and with a transform. Real-binary tests that the preview's size matches the slice's printed
height for a rotation, scale, scale to fit and rotate Z, and that the base of an asymmetric model in the preview is
its first printed layer both for an ordinary rotation and for the +-90 case.

## Pros and Cons of the Options

### Apply the transforms ourselves

* Good, because it needs no subprocess and works without PrusaSlicer.
* Bad, because it was wrong for `rotate_y=90` with `rotate_z=-90`, and any other quirk we have not met.

### Ask PrusaSlicer

* Good, because it cannot disagree with the slice.
* Bad, because of the consequences above.

### Keep the preview as stored

* Good, because it is simple.
* Bad, because it leaves the slice-and-see loop that this decision removes.

## More Information

Found while planning the work that followed the dogfood sweep; see ADR 0012 for the transforms themselves.
