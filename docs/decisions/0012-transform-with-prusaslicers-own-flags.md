---
status: accepted
date: 2026-11-14
decision-makers: Sebastien Coutu
---

# Transform models with PrusaSlicer's own flags, and do not expose --merge

## Context and Problem Statement

`slice_model` could not change a model. Dogfooding showed why that matters: a scanned statue is Y-up and needs a
90 degree turn about X before it can be printed head-up. Callers also want to scale a model, print several copies,
and put several parts on one plate. PrusaSlicer's command line has flags for all of this. Which should the tool
expose, and how?

## Decision Drivers

* Transforms must work for PrusaSlicer projects without losing their saved settings (ADR 0007).
* The tool must be hard to misuse, and must not hide PrusaSlicer's surprises from the caller.
* Prefer PrusaSlicer's own behaviour over re-implementing it.
* A flag that crashes PrusaSlicer must not be offered.

## Considered Options

* Pass PrusaSlicer's transform flags through (rotate, scale, scale to fit, split, duplicate)
* Transform the mesh ourselves with trimesh and slice the result
* Also expose `--merge` and `--dont-arrange` for plates of several files

## Decision Outcome

Chosen option: "Pass PrusaSlicer's transform flags through", and not `--merge` or `--dont-arrange`. These were
measured against PrusaSlicer 2.9.7, not assumed:

| Flag | Measured behaviour | Exposed as |
|---|---|---|
| `--rotate-x`, `--rotate-y`, `--rotate` | Real rotations about those axes. Applied in a fixed order, X then Y then Z, whatever order the flags are given. Negative and non-right angles work. | `rotate_x`, `rotate_y`, `rotate_z` (degrees) |
| `--scale N` | A factor: `2` doubles and `0.5` halves, but a bare `50` means fifty times and puts the model off the bed. A percentage needs a `%` sign. | `scale`, a factor greater than 0; percentages are not offered |
| `--scale-to-fit X,Y,Z` | Uniform scaling into the box. | `scale_to_fit` as `[x, y, z]` in mm; not combinable with `scale` |
| `--duplicate N` | N objects in total, arranged compactly. | `copies`, 1 to 100 |
| `--split` | Separates unconnected solids into objects and re-arranges them compactly. | `split` |
| `--merge` | **Segfaults** (exit 139) in every case tried, even with `--info`, which does not slice. It works only with `--dont-arrange`. | not exposed |
| `--dont-arrange` | Keeps the original coordinates, so a model centred on the origin falls off the bed. Only useful together with `--merge`. | not exposed |

Transforms work on PrusaSlicer projects (with no profiles the project's saved settings still apply) and together
with `center`, which is applied after them. All of them are validated before anything is written to disk.

### Consequences

* Good, because the statue case, scaling, several copies, and multi-part STLs are all one call away.
* Good, because the traps (the scale factor versus percentage, the fixed axis order) are removed or documented in
  the tool descriptions instead of discovered by a failed print.
* Bad, because plates built from several files are not supported: `--merge` crashes PrusaSlicer 2.9.7. `copies` and
  `split` cover several copies of one model and several parts in one file. Revisit when PrusaSlicer fixes it, or
  build the plate ourselves with trimesh.
* Bad, because rotations cannot be previewed yet: `preview_model` draws a model as stored.

### Confirmation

Unit tests with a faked command line for every flag and validation, and real-binary tests that compare each
transform with an unmodified slice of the same model (layer counts, filament, printed width, project settings).

## Pros and Cons of the Options

### Pass PrusaSlicer's flags through

* Good, because it keeps PrusaSlicer's own behaviour, including for projects.
* Bad, because it inherits its quirks and crashes, which is why `--merge` is left out.

### Transform the mesh ourselves

* Good, because it would not depend on PrusaSlicer's flags or bugs.
* Bad, because it re-implements rotation and scaling, and cannot apply to a project 3MF without breaking it.

### Also expose `--merge` and `--dont-arrange`

* Good, because it would allow plates of several files.
* Bad, because `--merge` segfaults, and `--dont-arrange` alone makes models fall off the bed.

## More Information

Found while dogfooding on the scanned statue; see [ADR 0011](0011-render-previews-with-numpy-and-pillow.md) for the
previews that showed the orientation problem. Related: [ADR 0007](0007-slice-prusaslicer-projects-with-their-own-settings.md).
