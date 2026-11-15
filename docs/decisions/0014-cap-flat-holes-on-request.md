---
status: accepted
date: 2026-11-14
decision-makers: Sebastien Coutu
---

# Cap flat holes in a mesh on request

## Context and Problem Statement

A scan can lack a face entirely, usually its base. PrusaSlicer then has no bottom to print on: stood the right way up
it refuses the model with "object with no extrusions in the first layer", and upside down it slices but prints the
model inverted. The sweep over the user's 132 models found one such scan (687 open edges), and a second one was
refused the same way. What should the server do about holes in a mesh?

Measured on the 17 non-watertight models of that library, by joining the open edges into loops:

| Kind | Models | What the open boundary looks like |
|---|---|---|
| A missing face (a scan's base) | 2 | one simple loop of 687 or 815 edges, flat (spread 0.03 and 0.009) |
| An open shell (CAD export) | 2 | 28 to 32 loops, none flat (spread above 0.5) |
| A tiny gap | 3 | 1 to 8 open edges across 0.2 mm or less |
| No open edges, only non-manifold ones | 10 | nothing to cap |

Capping the two scans' loops made both meshes slice: the statue, refused head-up before, now slices head-up at its
full 141 mm height (61.6 g), and the other scan slices in three of the four orientations tried.

## Decision Drivers

* Turn a refusal that has one known cause into a slice, without a second tool or manual repair.
* Never change the user's file, and never invent geometry silently: a cap is a guess about the shape.
* Do not add a heavy or native dependency for a few dozen lines of geometry.
* Say what happened, so a result never hides that the sliced mesh was not the file.

## Considered Options

* Diagnose only: `inspect_model` reports the holes and the caller repairs the file elsewhere
* A `repair_model` tool that writes a repaired copy of the file
* `close_holes` on `slice_model`, with the diagnostics in `inspect_model`
* Cap holes automatically on every slice
* Depend on a mesh-repair library (`pymeshfix`, `mapbox-earcut`, `manifold3d`)

## Decision Outcome

Chosen option: "`close_holes` on `slice_model`, with the diagnostics in `inspect_model`", because it fixes the
refusal in one call and leaves the choice to the caller.

* `repair.find_holes(mesh)` joins the open edges into loops. A loop is **closable** when it is a single simple loop
  (no vertex visited twice), has between 12 and 10,000 edges, and is nearly flat (smallest over largest spread of
  its points at most 0.1). `repair.close_holes(mesh)` caps those by ear clipping in the loop's best-fit plane,
  winding each cap against the faces' edge direction so it faces outward, and returns a new mesh.
* Anything else is reported and left alone: tiny gaps (PrusaSlicer repairs those itself), bent holes, open shells
  and boundaries that touch themselves. Guessing a surface there would invent geometry.
* `inspect_model` returns `open_holes` and `closable_holes` and, when some can be capped, a warning that names
  `close_holes=true`.
* `slice_model(close_holes=true)` caps the holes in memory, writes the repaired mesh as an STL named after the model
  into its private scratch folder (the one results already go through, [ADR 0007](0007-slice-prusaslicer-projects-with-their-own-settings.md)),
  and slices that. The model file is never rewritten. The result reports `holes_closed` and always carries a warning
  saying what `close_holes` did, including when it found nothing to close.
* A PrusaSlicer project is refused: a repaired copy would drop its saved settings. A plain 3MF becomes a single
  object in the copy, and is still centred automatically ([ADR 0013](0013-centre-plain-3mf-files-automatically.md)).
* The first-layer refusal's hint now names `close_holes`.

It is opt-in because a cap is not always right. A cup scanned open at the top has a flat, simple hole too, and
capping it would make the cup solid. A person or a model looking at `preview_model` decides; the server does not.

### Consequences

* Good, because both scans in the library that PrusaSlicer refused now slice, with no dependency added.
* Good, because the file on disk is untouched and the result says a copy was sliced.
* Bad, because ear clipping makes thin triangles. They are only a flat bottom face, which slicing does not mind, but
  the cap is not a mesh worth exporting.
* Bad, because the cost grows with the square of the loop's length, hence the 10,000-edge limit (about 3 s).
* Bad, because open shells and non-manifold meshes are still not repaired. They are counted by `inspect_model`.

### Confirmation

Unit tests for finding and closing holes on constructed meshes (a missing base, a non-convex star, two holes, a tiny
gap, a bent hole, a boundary that touches itself, a flipped face, the size limit), for `inspect_model`'s counts and
warning, and for `slice_model` through the fake command line (the copy is what PrusaSlicer receives, the original is
untouched, projects are refused, a refused request creates nothing). A real-binary test slices a capped scan. The
two real scans were sliced end to end by hand.

## Pros and Cons of the Options

### Diagnose only

* Good, because it cannot do wrong.
* Bad, because the caller is left with a refusal and no tool to fix it.

### A `repair_model` tool

* Good, because the repaired file can be previewed and kept.
* Bad, because it writes next to the user's models or somewhere to be found again, and adds a second step to a
  routine fix. `slice_model` already has a private scratch folder.

### `close_holes` on `slice_model`

* Good, because it is one call and leaves nothing behind.
* Bad, because the repaired mesh cannot be previewed first (a preview with transforms is on the roadmap).

### Cap automatically

* Good, because no refusal would reach the caller.
* Bad, because it changes shape without being asked, and is wrong for a cup or a pipe.

### A repair library

* Good, because it handles more cases.
* Bad, because `pymeshfix` and `manifold3d` are native builds for a problem the data shows is mostly one flat loop,
  and `mapbox-earcut` alone would save about sixty lines.

## More Information

Found by dogfooding ([docs/dogfooding.md](../dogfooding.md)); see ADR 0012 for the rotations that stand a scan
upright once its base exists.
