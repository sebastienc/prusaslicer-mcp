# Roadmap

Direction, not commitments. Order within a section is rough priority. Anything that involves a real
design choice gets an ADR in [`docs/decisions/`](docs/decisions/README.md) before or with the work.
When an item ships, move it to **Done** and update the README and architecture doc.

## Done

### Project

- Open source under the MIT licence and published to PyPI as `prusaslicer-mcp` through trusted publishing from the release workflow, with contributing and security policies and a CI job that builds and installs the package ([ADR 0020](docs/decisions/0020-open-source-and-publish-to-pypi.md)).

### Tools

- `preview_gcode` draws `G2`/`G3` arcs, so an arc-fitted print no longer looks empty; before, arcs were counted but not drawn, which made a full first layer look blank while checking the statue.
- The core tools `list_printers`, `list_profiles`, `inspect_model` and `slice_model`, wrapping the PrusaSlicer 2.9.x command line ([ADR 0002](docs/decisions/0002-wrap-the-prusaslicer-2-9-cli.md)), with G-code statistics: time, filament length, volume and weight summed across extruders, cost and layers.
- PrusaSlicer projects keep their own saved settings: profiles are optional for a saved project, `inspect_model` reports what it stores, and the result says which settings applied ([ADR 0007](docs/decisions/0007-slice-prusaslicer-projects-with-their-own-settings.md)).
- Transforms with PrusaSlicer's own flags: `rotate_x/y/z`, `scale`, `scale_to_fit`, `split` and `copies`, also on projects ([ADR 0012](docs/decisions/0012-transform-with-prusaslicers-own-flags.md)). Plain 3MF files are centred on the bed by default ([ADR 0013](docs/decisions/0013-centre-plain-3mf-files-automatically.md)).
- **Scans with a missing face.** `inspect_model` counts open holes and says which are flat gaps, and `slice_model(close_holes=true)` caps them in a temporary copy, with a flat base even where the scan's rim is ragged ([ADR 0014](docs/decisions/0014-cap-flat-holes-on-request.md), [ADR 0017](docs/decisions/0017-close-a-hole-with-a-flat-base.md)). Lesson recorded in ADR 0017: a slice that PrusaSlicer accepts is not proof that it prints; the first capped statue "sliced" with a first layer that was a single point.
- **Choosing the orientation.** `suggest_orientation` ranks the ways to stand a model (flat faces, axes, as stored) by bed contact, overhang and height, with the `rotate_x`/`rotate_y` for each ([ADR 0018](docs/decisions/0018-suggest-orientations-from-geometry.md)). With the three profiles it also slices each option with supports on and reports the real support filament, filament and time ([ADR 0019](docs/decisions/0019-measure-support-by-slicing-on-request.md)). On five real models the geometric winner was the measured winner on four.
- **Seeing the model.** `preview_model` draws a model on a bed grid, and takes the transforms and `close_holes`, asking PrusaSlicer itself for the transformed mesh so the picture matches the slice, quirks included ([ADR 0015](docs/decisions/0015-preview-transforms-by-asking-prusaslicer.md), [ADR 0011](docs/decisions/0011-render-previews-with-numpy-and-pillow.md)). `preview_gcode` draws a layer or the side silhouettes of what was sliced.
- STEP files work in `inspect_model`, `preview_model` and `suggest_orientation`, converted by PrusaSlicer's `--export-stl` ([ADR 0016](docs/decisions/0016-read-step-files-through-prusaslicer.md)).

### Correctness and clear errors

- Failures reach the model as readable `ToolError`s with PrusaSlicer's own message (SDK 2.x hides any other exception).
- A refused slice says how to fix it: a model bigger than the bed, an empty first layer, and the wipe-tower conflict. The remedies were verified on the real models that triggered them.
- A refused slice is never reported as a success. PrusaSlicer exits 0 for some refusals, so slices go to a scratch folder and move into place only on success.
- PrusaSlicer's whole multi-line warnings are returned, and a slice that prints nothing over part of the model's height is flagged.
- Overrides the server controls itself (`binary_gcode`, `save`, ...) are refused, everything is validated before the disk is touched, and `output_path` may create only its last folder.

### Process

- TDD as the default workflow and Given/When/Then as the test style (`.claude/rules/testing.md`). Unit-test coverage is 98% (line and branch, 95% floor in CI), and new code is mutation-checked: each logic change is mutated by hand and every survivor either gets a test or is shown to be redundant.
- Quality gates ([ADR 0009](docs/decisions/0009-quality-gate-toolchain.md), [ADR 0010](docs/decisions/0010-pin-ty-and-add-pyright.md)): `uv run poe check` (Ruff, `uv format`, `ty` pinned plus pyright, unit tests), `uv audit`, an automated stdio protocol test, and CI with lint, types, audit, unit tests on Python 3.12 and 3.14, integration tests on macOS (PrusaSlicer download cached by version) and commitlint.
- Conventional Commits and Release Please release pull requests ([ADR 0008](docs/decisions/0008-conventional-commits-and-release-please.md)). The `ci-required-main` ruleset requires the single `ci` check, and only `feat`, `fix`, `perf` and `revert` commits can trigger a release.
- An opt-in dogfood sweep, `uv run poe dogfood run <folder>`, that runs every tool over a folder of real models and reports crashes, timeouts, refusals, warnings and suspicious results ([docs/dogfooding.md](docs/dogfooding.md)). Its first run over 132 models found and fixed four problems, and it now also scores every plain model's orientation.
- Project scaffolding: uv, direnv and `.env`, Claude rules, MADR decisions, the architecture doc, a VS Code workspace.

## Next

In rough order, with the reason each is here. After a change to slicing, previewing, inspection or G-code parsing, run the dogfood sweep.

1. **Speed up the G-code parse for very large files.** `preview_gcode` reads the file in plain Python in two passes (about 2 s per million extruding moves), and an arc-fitted print now expands each arc into many short moves.
2. **Windows support.** The code has no known POSIX-only logic, and the lookups that differ (install folders, the console build, UTF-8 query output) are done and unit-tested, but nothing has run on Windows. Left: a Windows job in CI (unit tests, then integration tests against the 2.9.7 `.zip` or `-setup.exe` release asset with a throwaway data folder), a Windows-native fake slicer so the process tests there are not skipped, a README section (`%USERPROFILE%` paths, JSON backslashes, where Claude Desktop keeps its config), a safer default for the output folder than the working directory (a client on Windows may start the server somewhere unwritable), and the Windows classifier once CI is green.
3. **Make the dogfood sweep see the first layer.** The sweep reports that a slice succeeded, not that it would stick to the bed. Report each slice's first-layer filament against its second (`gcode.filament_by_feature` and the layer markers give it) and flag a first layer that is a small fraction: that would have caught the capped statue's single-point base automatically.
4. **Calibrate the orientation scores on more models.** Geometry picked the measured winner on four of five models (ADR 0019); the miss was a pipe elbow whose as-stored orientation, flagged unstable by the 5% line, cost 9.5 g less support. Recheck the 5% stability line and the 10% tie rule, add bridging, and propose a candidate at an arbitrary angle for curved models.
5. **Cover the defensive branches.** Coverage is 98%; the misses are paths that are meant to be rare: a loop that cannot be triangulated or has no area (`repair.py`), a G-code with a reset or arc in an unusual place (`gcode.py`), and a few more. Test them or delete them.
6. **Open shells and other repairs.** `close_holes` caps only a flat, simple hole. Two CAD exports are open shells with 28 to 32 non-flat loops, and ten files have non-manifold edges but no open ones; `inspect_model` counts them and nothing repairs them. First look at what PrusaSlicer does with them before choosing a remedy.

## Later

### Found by dogfooding

- **Multi-model plates.** `--merge` segfaults in PrusaSlicer 2.9.7, so a plate of several files needs our own plate builder (trimesh) or a fixed PrusaSlicer. `copies` and `split` cover several copies of one model and several parts in one file. See ADR 0012.
- **Preview improvements.** Stack the two silhouette panels for wide, low prints so they use the whole picture, and add a perspective or shaded layer-stack view. (Arcs and the parse speed are in **Next**.)
- **Failed slices leave an empty output folder.** It is created before PrusaSlicer runs. Remove it when the slice fails and the server created it.
- **Validate overrides earlier.** A bad key or value already fails with PrusaSlicer's own readable message (`Unknown option --fill-densty`, `Invalid value supplied for --fill-density`). What remains is failing before PrusaSlicer starts, and suggesting the closest valid key from `--help-fff`.
- **Orientation for projects.** `suggest_orientation` refuses a PrusaSlicer project because its own placement does not combine with the rotations as scored. (Previewing a rotation on a project works.)
- **A flatter cap.** The cap is exact but made of thin ear-clipped triangles; fine for printing, not a mesh worth exporting. A cleaner triangulation, or a `repair_model` that writes the repaired mesh, would let a capped scan be kept.

### Ideas

- **Richer G-code analysis:** silent-mode time, first-layer time, time per feature type, per-layer stats. (Filament per feature type exists now, `gcode.filament_by_feature`.)
- **Effective-settings introspection:** show the resolved value of a setting for a printer, print and filament combination, and explain what an override changed. Must not write into the user's PrusaSlicer data directory.
- **Project details:** report a project's per-object settings and plate layout, and possibly write a project back. (Slicing a project as saved is done, ADR 0007.)
- **Multi-material and multi-extruder slicing** (multiple filament profiles, tool changes). Needs a check of how the 2.9.x CLI takes several `--material-profile` values.
- **SLA (resin) support.** `list_printers` already accepts `SLA`; slicing and statistics differ (layer images, different footer).
- **Ideas from PrusaMCP** ([ADR 0004](docs/decisions/0004-build-our-own-server.md)): printability checks (thin walls, bridges). Port with attribution; it is MIT.
- **Binary G-code:** a reader or `convert_gcode` tool so output can match the printer profile again ([ADR 0005](docs/decisions/0005-always-slice-to-text-gcode.md)).
- **Packaging:** make it installable and runnable with `uvx` for easier client setup.

### Tooling

- **Type checkers.** Run one again once `ty` reaches 1.0 ([ADR 0010](docs/decisions/0010-pin-ty-and-add-pyright.md)). Related watch item: `uv format` uses the latest Ruff 0.15.x at run time, so pin it with `--version` if formatting ever drifts.
- **Linux integration tests.** Prusa no longer attaches Linux builds to its GitHub releases; the Flathub package could work, but is untried.
- **Dogfood sweep in CI.** It needs a small corpus of freely licensed models to run against, since the real library is private.

## Exploring (needs a decision first)

- **Live GUI control** via a patched PrusaSlicer exposing a local control channel. Feasible but means maintaining an AGPL fork; see [ADR 0002](docs/decisions/0002-wrap-the-prusaslicer-2-9-cli.md).
- **PrusaSlicer 3.x.** The 3.0 alpha adds sandboxed Lua plugins and a restructured CLI. Re-evaluate when it is stable and its CLI/plugin API is documented.
- **Working with the Prusa3d MCP connector** (printers, Printables, material DB, cloud slicing): complement rather than duplicate it, e.g. slice locally here, then hand the G-code to a printer through it.

## Out of scope

- Printer control and monitoring (the Prusa Connect/PrusaLink servers and the Prusa3d connector cover this).
- Bundling or redistributing PrusaSlicer.
- Print-quality "advice engines" with hardcoded material tables; prefer data that comes from the user's installed profiles.
