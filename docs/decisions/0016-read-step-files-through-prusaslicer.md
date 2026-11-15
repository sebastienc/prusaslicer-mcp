---
status: accepted
date: 2026-11-14
decision-makers: Sebastien Coutu
---

# Read STEP files through PrusaSlicer

## Context and Problem Statement

`.step` and `.stp` files were accepted by every tool, and PrusaSlicer slices them natively, but `inspect_model` and
`preview_model` failed on them: they load meshes with `trimesh`, which reads STEP only through `cascadio` or `gmsh`,
neither installed (`No module named 'cascadio'`). A STEP model could be sliced blind but not looked at or measured.
How should the two tools read STEP?

## Decision Drivers

* A STEP file should be inspectable and previewable like any other model.
* No heavy or native dependency (OpenCASCADE is large).
* Measure what PrusaSlicer will actually slice, not what another converter makes of the file.

## Considered Options

* Skip the mesh inspection for STEP with a clear message
* Add `cascadio` (OpenCASCADE bindings) as a dependency
* Have PrusaSlicer convert the file with `--export-stl`

## Decision Outcome

Chosen option: "have PrusaSlicer convert the file", because PrusaSlicer already contains the converter that slices
the file, so the mesh the tools describe is the mesh that will be printed, with nothing new to install.

Tried on the Open CASCADE sample assembly `as1-oc-214.stp` (a 442 kB file with 18 parts): `--export-stl` took 0.2 s
and gave 15,624 triangles, 200 x 150 x 84 mm, watertight. A generated STEP cube converts to a 20 mm, watertight,
outward-facing cube.

* `_load_model_mesh` converts a STEP file by running `prusaslicer --export-stl --output <temp>/<name>.stl <file>` and
  loading the STL; every other format is loaded directly. Both run off the event loop, so `inspect_model` and
  `preview_model` are now async.
* The STL lives in a temporary folder that is removed afterwards.
* A non-zero exit, or no file written, is a failure even if the exit code was 0 or a file exists, and says so with
  PrusaSlicer's own words plus a hint ("is it a valid STEP file?"), because for a broken file those words can be as
  bare as `basic_string`.
* `slice_model` is unchanged: it still hands the STEP file to PrusaSlicer. The size hint for a model outside the
  print volume and `close_holes` use the same converted mesh.

### Consequences

* Good, because STEP files work in `inspect_model`, `preview_model` and the transformed previews of ADR 0015.
* Good, because no dependency was added.
* Bad, because triangle counts and watertightness describe PrusaSlicer's tessellation, not the CAD solid.
* Bad, because STEP now needs PrusaSlicer for inspection too (other formats still do not).
* Bad, because a large assembly costs a subprocess and a tessellation every call.

### Confirmation

Unit tests with a faked `--export-stl` for the command line, both extensions, cleanup, failures and an STL that must
not start PrusaSlicer. Real-binary tests with a STEP cube built by `tests/step_builders.py` (so no model is
committed): inspect, preview, slice, and a broken file.

## Pros and Cons of the Options

### Skip the inspection

* Good, because it is one line.
* Bad, because the model stays unseen, and the size, fit and orientation checks are the point of the tools.

### Add `cascadio`

* Good, because it needs no PrusaSlicer.
* Bad, because it is a large native dependency and tessellates differently from the slicer.

### Convert through PrusaSlicer

* Good, because of the decision outcome above.
* Bad, because of the consequences above.

## More Information

Found by the dogfood sweep, which accepted STEP in its file list but had no STEP file to run on. See
[ADR 0002](0002-wrap-the-prusaslicer-2-9-cli.md) for why the project wraps PrusaSlicer's command line.
