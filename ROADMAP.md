# Roadmap

Direction, not commitments. Order within a section is rough priority. Anything that involves a real
design choice gets an ADR in [`docs/decisions/`](docs/decisions/README.md) before or with the work.
When an item ships, move it to **Done** and update the README and architecture doc.

## Done

- Wrap the PrusaSlicer 2.9.x CLI: `list_printers`, `list_profiles`, `inspect_model`, `slice_model` (v0.1.0)
- Text G-code statistics: time, filament length/volume/weight, cost, layers
- Tool failures reach the model as readable `ToolError`s with PrusaSlicer's own message (SDK 2.x hides any other exception)
- `slice_model(center=true)` for plain 3MF files that sit off the bed
- Project scaffolding: uv, direnv/`.env`, tests, Claude rules, MADR decisions, architecture doc, VS Code workspace
- TDD as the default workflow, and Given/When/Then as the test style, both written down in `.claude/rules/testing.md`; every existing test migrated to that shape
- PrusaSlicer projects keep their own settings: profiles are optional for a saved project, `inspect_model` reports what it stores, and the result says which settings applied ([ADR 0007](docs/decisions/0007-slice-prusaslicer-projects-with-their-own-settings.md))
- G-code statistics add up every extruder's filament length and volume (multi-material footers list one value per extruder)
- Releases: the `ci-required-main` ruleset is active and requires the single `ci` check, Release Please has cut `v0.1.1`, and only `feat`, `fix`, `perf` and `revert` commits can trigger a release
- `slice_model` returns PrusaSlicer's whole multi-line warnings, and warns when a slice prints nothing over part of the model's height (found slicing a Y-up scan that lay on its side)
- `slice_model` refuses overrides the server controls itself (`binary_gcode=1` used to beat the forced text G-code, `save` could write into the user's data directory), validates everything before touching the disk, and lets a caller-supplied `output_path` create only its last folder, so a typo fails instead of building a stray folder tree
- Type checking runs `ty` pinned to a fixed version plus pyright ([ADR 0010](docs/decisions/0010-pin-ty-and-add-pyright.md))
- `preview_model` and `preview_gcode` return PNGs so Claude can see a model (iso, front, side, top or a four-view sheet) and what was sliced (one layer's toolpaths, or front and side silhouettes of everything printed), drawn with numpy and Pillow ([ADR 0011](docs/decisions/0011-render-previews-with-numpy-and-pillow.md))
- `slice_model` transforms with PrusaSlicer's own flags: `rotate_x/y/z`, `scale`, `scale_to_fit`, `split` and `copies`, also on projects ([ADR 0012](docs/decisions/0012-transform-with-prusaslicers-own-flags.md))
- A refused slice is never reported as a success: PrusaSlicer exits 0 for some refusals, so an old file at the output path used to be returned with its statistics; slices now go to a scratch folder and move into place only on success (found by slicing every model in the library)
- Quality gates ([ADR 0009](docs/decisions/0009-quality-gate-toolchain.md)): `uv run poe check` (Ruff lint, `uv format`, `uv check`, unit tests), `uv audit`, an automated stdio protocol test, and CI with lint, types, audit, unit tests on Python 3.12 and 3.14, integration tests on macOS (PrusaSlicer download cached by version) and commitlint
- Conventional Commits and Release Please release pull requests ([ADR 0008](docs/decisions/0008-conventional-commits-and-release-please.md))
- Test gaps filled and mutation-checked: coverage 84% to 99% (line+branch), only `main()` uncovered (an automated stdio test is in Quality gates). The new tests exposed and fixed six problems: an opaque crash on an invalid `PRUSASLICER_MCP_TIMEOUT`, an opaque crash on a corrupt 3MF/STEP/AMF, overrides that could undo server guarantees (`binary_gcode=1`, `save`), folders created for refused requests, a made-up `0` seconds for an unrecognised print time, and a whole G-code file read into memory to check four bytes

## Next

1. **Dogfood.** Use the server on real models (it is registered for this repo through the committed `.mcp.json`), note friction and fix it. Real models have so far exposed four problems, all fixed: a project's saved settings were ignored, warnings were cut to one line, a Y-up scan lying on its side sliced "successfully" with healthy-looking numbers, and a mistyped `output_path` built a stray folder tree. Still untried: a multi-material project that really uses several extruders, very large files, SLA, and STEP.

## Later

- **Multi-model plates.** `--merge` segfaults in PrusaSlicer 2.9.7, so a plate of several files needs our own plate builder (trimesh) or a fixed PrusaSlicer. `copies` and `split` cover several copies of one model and several parts in one file. See ADR 0012.
- **Preview with transforms:** let `preview_model` show a model after `rotate_*` and `scale`, so an orientation can be checked before slicing.
- **Close open meshes before slicing.** A scan can lack a face entirely: the statue's base has no bottom (687 open edges), so stood head-up PrusaSlicer refuses it (`object with no extrusions in the first layer`) and head-down it slices but upside down. Cap the hole, or say clearly that the mesh needs repair.
- **Preview improvements:** stack the two silhouette panels for wide, low prints so they use the whole picture, draw `G2`/`G3` arcs, and add a perspective or shaded layer-stack view. Speed up the G-code parse for very large files.
- **STEP files.** `inspect_model` cannot read STEP at all (trimesh needs `cascadio` or `gmsh`, neither installed), yet `.step`/`.stp` are accepted and PrusaSlicer slices them natively. Either skip the mesh inspection for STEP with a clear message, or add a converter.
- **Failed slices leave an empty output folder:** it is created before PrusaSlicer runs. Remove it when the slice fails and the server created it.
- **Validate overrides earlier.** A bad key or value already fails with PrusaSlicer's own readable message (`Unknown option --fill-densty`, `Invalid value supplied for --fill-density`). What remains is failing before PrusaSlicer starts, and suggesting the closest valid key from `--help-fff`.
- **Type checkers:** run one again once `ty` reaches 1.0 ([ADR 0010](docs/decisions/0010-pin-ty-and-add-pyright.md)). Related watch item: `uv format` uses the latest Ruff 0.15.x at run time, so pin it with `--version` if formatting ever drifts.
- **Linux integration tests.** Prusa no longer attaches Linux builds to its GitHub releases; the Flathub package could work, but is untried.
- **Richer G-code analysis:** silent-mode time, first-layer time, time and filament per feature type, per-layer stats.
- **Effective-settings introspection:** show the resolved value of a setting for a printer/print/filament combination, and explain what an override changed. Must not write into the user's PrusaSlicer data directory.
- **3MF projects:** read per-object settings and plate layout from 3MF; slice a project as saved in the GUI; possibly write one back.
- **Multi-material and multi-extruder slicing** (multiple filament profiles, tool changes). Needs a check of how the 2.9.x CLI takes several `--material-profile` values.
- **SLA (resin) support.** `list_printers` already accepts `SLA`; slicing and statistics differ (layer images, different footer).
- **Ideas from PrusaMCP** ([ADR 0004](docs/decisions/0004-build-our-own-server.md)): orientation scoring, printability checks (thin walls, bridges, overhangs). Port with attribution; it is MIT.
- **Binary G-code:** a reader or `convert_gcode` tool so output can match the printer profile again ([ADR 0005](docs/decisions/0005-always-slice-to-text-gcode.md)).
- **Packaging:** make it installable/runnable with `uvx` for easier client setup.

## Exploring (needs a decision first)

- **Live GUI control** via a patched PrusaSlicer exposing a local control channel. Feasible but means maintaining an AGPL fork; see [ADR 0002](docs/decisions/0002-wrap-the-prusaslicer-2-9-cli.md).
- **PrusaSlicer 3.x.** The 3.0 alpha adds sandboxed Lua plugins and a restructured CLI. Re-evaluate when it is stable and its CLI/plugin API is documented.
- **Working with the Prusa3d MCP connector** (printers, Printables, material DB, cloud slicing): complement rather than duplicate it, e.g. slice locally here, then hand the G-code to a printer through it.

## Out of scope

- Printer control and monitoring (the Prusa Connect/PrusaLink servers and the Prusa3d connector cover this).
- Bundling or redistributing PrusaSlicer.
- Print-quality "advice engines" with hardcoded material tables; prefer data that comes from the user's installed profiles.
