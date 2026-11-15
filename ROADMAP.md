# Roadmap

Direction, not commitments. Order within a section is rough priority. Anything that involves a real
design choice gets an ADR in [`docs/decisions/`](docs/decisions/README.md) before or with the work.
When an item ships, move it to **Done** and update the README and architecture doc.

## Done

### Tools

- The core tools `list_printers`, `list_profiles`, `inspect_model` and `slice_model`, wrapping the PrusaSlicer 2.9.x command line ([ADR 0002](docs/decisions/0002-wrap-the-prusaslicer-2-9-cli.md)), with G-code statistics: time, filament length, volume and weight summed across extruders, cost and layers.
- PrusaSlicer projects keep their own saved settings: profiles are optional for a saved project, `inspect_model` reports what it stores, and the result says which settings applied ([ADR 0007](docs/decisions/0007-slice-prusaslicer-projects-with-their-own-settings.md)).
- Transforms with PrusaSlicer's own flags: `rotate_x/y/z`, `scale`, `scale_to_fit`, `split` and `copies`, also on projects ([ADR 0012](docs/decisions/0012-transform-with-prusaslicers-own-flags.md)).
- Scans with a missing face: `inspect_model` counts open holes and says which are flat gaps, and `slice_model(close_holes=true)` caps them in a temporary copy so a base-less scan slices ([ADR 0014](docs/decisions/0014-cap-flat-holes-on-request.md)). The two scans in the library that PrusaSlicer refused (the statue stood head-up, and `grimpeux-scan-1` rotated) now slice.
- Plain 3MF files are centred on the bed by default, with `center` as an override and `centered` in the result ([ADR 0013](docs/decisions/0013-centre-plain-3mf-files-automatically.md)).
- `preview_model` and `preview_gcode` return PNGs so Claude can see a model and what was sliced, drawn with numpy and Pillow ([ADR 0011](docs/decisions/0011-render-previews-with-numpy-and-pillow.md)).

### Correctness and clear errors

- Failures reach the model as readable `ToolError`s with PrusaSlicer's own message (SDK 2.x hides any other exception).
- A refused slice says how to fix it: a model bigger than the bed, an empty first layer, and the wipe-tower conflict. The remedies were verified on the real models that triggered them.
- A refused slice is never reported as a success. PrusaSlicer exits 0 for some refusals, so slices go to a scratch folder and move into place only on success.
- PrusaSlicer's whole multi-line warnings are returned, and a slice that prints nothing over part of the model's height is flagged.
- Overrides the server controls itself (`binary_gcode`, `save`, ...) are refused, everything is validated before the disk is touched, and `output_path` may create only its last folder.

### Process

- TDD as the default workflow and Given/When/Then as the test style (`.claude/rules/testing.md`). Coverage is 99% (line and branch), and the code and tests are mutation-checked.
- Quality gates ([ADR 0009](docs/decisions/0009-quality-gate-toolchain.md), [ADR 0010](docs/decisions/0010-pin-ty-and-add-pyright.md)): `uv run poe check` (Ruff, `uv format`, `ty` pinned plus pyright, unit tests), `uv audit`, an automated stdio protocol test, and CI with lint, types, audit, unit tests on Python 3.12 and 3.14, integration tests on macOS (PrusaSlicer download cached by version) and commitlint.
- Conventional Commits and Release Please release pull requests ([ADR 0008](docs/decisions/0008-conventional-commits-and-release-please.md)). The `ci-required-main` ruleset requires the single `ci` check, and only `feat`, `fix`, `perf` and `revert` commits can trigger a release.
- An opt-in dogfood sweep, `uv run poe dogfood run <folder>`, that runs every tool over a folder of real models and reports crashes, timeouts, refusals, warnings and suspicious results ([docs/dogfooding.md](docs/dogfooding.md)). Its first run over 132 models found and fixed four problems.
- Project scaffolding: uv, direnv and `.env`, Claude rules, MADR decisions, the architecture doc, a VS Code workspace.

## Next

Nothing is queued. Pick from **Later**. After a change to slicing, previewing, inspection or G-code parsing, run the dogfood sweep.

## Later

### Found by dogfooding

- **Multi-model plates.** `--merge` segfaults in PrusaSlicer 2.9.7, so a plate of several files needs our own plate builder (trimesh) or a fixed PrusaSlicer. `copies` and `split` cover several copies of one model and several parts in one file. See ADR 0012.
- **Open shells and other repairs.** `close_holes` caps only a flat, simple hole. Two CAD exports are open shells with 28 to 32 non-flat loops, and ten files have non-manifold edges but no open ones; `inspect_model` counts them and nothing repairs them. Needs a look at what PrusaSlicer does with them before choosing a remedy.
- **STEP files.** `inspect_model` cannot read STEP at all (trimesh needs `cascadio` or `gmsh`, neither installed), yet `.step`/`.stp` are accepted and PrusaSlicer slices them natively. Either skip the mesh inspection for STEP with a clear message, or add a converter.
- **Preview with transforms.** Let `preview_model` show a model after `rotate_*` and `scale`, so an orientation can be checked before slicing.
- **Preview improvements.** Stack the two silhouette panels for wide, low prints so they use the whole picture, draw `G2`/`G3` arcs, add a perspective or shaded layer-stack view, and speed up the G-code parse for very large files.
- **Failed slices leave an empty output folder.** It is created before PrusaSlicer runs. Remove it when the slice fails and the server created it.
- **Validate overrides earlier.** A bad key or value already fails with PrusaSlicer's own readable message (`Unknown option --fill-densty`, `Invalid value supplied for --fill-density`). What remains is failing before PrusaSlicer starts, and suggesting the closest valid key from `--help-fff`.

### Ideas

- **Richer G-code analysis:** silent-mode time, first-layer time, time and filament per feature type, per-layer stats.
- **Effective-settings introspection:** show the resolved value of a setting for a printer, print and filament combination, and explain what an override changed. Must not write into the user's PrusaSlicer data directory.
- **Project details:** report a project's per-object settings and plate layout, and possibly write a project back. (Slicing a project as saved is done, ADR 0007.)
- **Multi-material and multi-extruder slicing** (multiple filament profiles, tool changes). Needs a check of how the 2.9.x CLI takes several `--material-profile` values.
- **SLA (resin) support.** `list_printers` already accepts `SLA`; slicing and statistics differ (layer images, different footer).
- **Ideas from PrusaMCP** ([ADR 0004](docs/decisions/0004-build-our-own-server.md)): orientation scoring, printability checks (thin walls, bridges, overhangs). Port with attribution; it is MIT.
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
