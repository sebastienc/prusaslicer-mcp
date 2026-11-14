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
- Quality gates ([ADR 0009](docs/decisions/0009-quality-gate-toolchain.md)): `uv run poe check` (Ruff lint, `uv format`, `uv check`, unit tests), `uv audit`, an automated stdio protocol test, and CI with lint, types, audit, unit tests on Python 3.12 and 3.14, integration tests on macOS (PrusaSlicer download cached by version) and commitlint
- Conventional Commits and Release Please release pull requests ([ADR 0008](docs/decisions/0008-conventional-commits-and-release-please.md))
- Test gaps filled and mutation-checked: coverage 84% to 99% (line+branch), only `main()` uncovered (an automated stdio test is in Quality gates). The new tests exposed and fixed six problems: an opaque crash on an invalid `PRUSASLICER_MCP_TIMEOUT`, an opaque crash on a corrupt 3MF/STEP/AMF, overrides that could undo server guarantees (`binary_gcode=1`, `save`), folders created for refused requests, a made-up `0` seconds for an unrecognised print time, and a whole G-code file read into memory to check four bytes

## Next

1. **Finish the CI setup.** Activate the `ci-required-main` ruleset (it is `disabled`); it requires the `ci` check, which a job in `ci.yml` now provides. Merge the Release Please pull request when you want a release. Note a `docs:` commit alone triggers one; hide `docs` with `changelog-sections` in `release-please-config.json` if that is noise.
2. **Dogfood.** The server is registered for this repo through the committed `.mcp.json` (project scope). Use it on real models; note friction and fix it. Candidate gaps are tool descriptions, error messages, and defaults.
3. **Preview rendering.** Return PNGs so Claude can *see* a model and individual sliced layers (adds `matplotlib`; needs an ADR on the rendering approach, e.g. mesh silhouette vs. parsed toolpaths).
4. **Transforms and multi-model plates.** Expose `--rotate`, `--rotate-x/-y`, `--scale`, `--scale-to-fit`, `--dont-arrange`, `--split`, and `--merge` on `slice_model`. (`--center` shipped as the `center` option; it assumes a corner bed origin, so delta printers need a look.)
5. **Validate overrides.** Check setting keys against PrusaSlicer's real option list (`--help-fff`) so a typo fails early with a useful message instead of a slicer error.

## Later

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
