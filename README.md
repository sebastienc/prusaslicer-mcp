# prusaslicer-mcp

An [MCP](https://modelcontextprotocol.io) server that lets Claude (or any MCP client) drive the
**PrusaSlicer 2.9.x command line**: discover installed printers and profiles, sanity-check a model,
slice it headlessly with your real presets, and get print time and filament use back.

It runs PrusaSlicer as a separate process, so it works while the GUI is open and does not touch it.
It does **not** control the GUI itself (PrusaSlicer 2.9.x has no remote-control API), and it targets
**2.9.x only**; PrusaSlicer 3.x is not supported yet.

**Status:** v0.1.0, early. Four tools, tested against PrusaSlicer 2.9.7 on macOS. See the [roadmap](ROADMAP.md).

## Example

Once registered with an MCP client, you can ask things like:

> "Which printers do I have installed? Check `~/models/bracket.stl` and slice it on the MINI with
> Prusament PLA at 0.20mm, 25% infill. How long will it take and how much filament does it use?"

Behind that, the client calls `list_printers` → `list_profiles` → `inspect_model` → `slice_model` and
reads back the print time and filament use. `preview_model` and `preview_gcode` let it *look* at the model and at what was sliced, and `suggest_orientation` proposes which way up to print.

## Tools

| Tool | What it does |
|---|---|
| `list_printers` | Installed printer models, exact printer profile names, nozzle variants, bed sizes |
| `list_profiles` | Print (quality) profiles and compatible filament profiles for a printer profile |
| `inspect_model` | Size, volume, watertightness, open holes (and how many are flat gaps `close_holes` can cap), part count; optional build-volume fit check (via `trimesh`), a warning when a 3MF's stored position is off the bed, and, for a 3MF saved from PrusaSlicer, the profiles and key settings (infill, brim, supports) stored in it |
| `slice_model` | Slice with `printer_profile` / `print_profile` / `material_profile` (all three, or none for a PrusaSlicer project, which then keeps its own saved settings), optional setting overrides, `center` (plain 3MF files are centred automatically), transforms (`rotate_x/y/z`, `scale`, `scale_to_fit`, `split`, `copies`), and `close_holes` to cap a flat hole such as a scan's missing base; returns G-code path, time, filament, cost, layers, whether the project's or the profiles' settings were used, whether the model was centred, and how many holes were closed |
| `suggest_orientation` | Ranks the ways to stand a model: its large flat faces, the axes and the orientation as stored, each with the `rotate_x`/`rotate_y` to reach it, its height, how much of it lies on the bed, how much overhang would need support, and whether it rests on a real base. `close_holes` lets a scan's missing base count. Geometry only (near-equal overhang is a tie), unless you also give the three profiles: then each option, at most six, is sliced with supports on and reports its real support filament, filament and print time (slow, one slice each) |
| `preview_model` | A PNG of a model from iso, front, side or top, or all four on one sheet, with its size and which way is up; shows a Y-up scan lying on its side at a glance. Takes the same `rotate_*`, `scale` and `scale_to_fit` as `slice_model`, and `close_holes`, and draws the model as PrusaSlicer will transform it, so an orientation can be checked before slicing. A pale grid is the bed, level with the model's lowest point, so it is plain which face rests on it |
| `preview_gcode` | A PNG of sliced G-code: one layer's toolpaths coloured by feature, or front and side silhouettes of everything printed, where an empty stretch shows as a blank band |

Profile names must match exactly; use `list_printers` and `list_profiles` to discover them.

**Projects.** A 3MF saved from PrusaSlicer carries its own settings (supports, brim, infill...). Slice it with no profiles to keep them; passing profiles makes PrusaSlicer ignore them and use the plain profile values ([ADR 0007](docs/decisions/0007-slice-prusaslicer-projects-with-their-own-settings.md)). `inspect_model` shows what a project saves.
G-code is always written as text (`--binary-gcode=0`) so statistics can be read back.

## Setup

Requires Python 3.12+, [uv](https://docs.astral.sh/uv/), and PrusaSlicer 2.9.x.

```bash
uv sync
cp .env.example .env     # then edit; see below
direnv allow             # optional: loads .env into your shell
uv run pytest            # integration tests are skipped if PrusaSlicer isn't found
```

In VS Code, open `prusaslicer-mcp.code-workspace` (interpreter, pytest, tasks, debug configs and recommended extensions are preconfigured).

### Configuration (`.env`)

| Variable | Purpose | Default |
|---|---|---|
| `PRUSASLICER_PATH` | PrusaSlicer executable | auto-detected (`PATH`, `/Applications/**/PrusaSlicer.app`, ...) |
| `PRUSASLICER_DATADIR` | Profile/config directory | platform default |
| `PRUSASLICER_MCP_OUTPUT_DIR` | Where G-code goes when no output path is given; created in full if missing | `./output` |
| `PRUSASLICER_MCP_TIMEOUT` | Slice timeout (seconds, must be positive) | `600` |

## Register with Claude Code

```bash
claude mcp add prusaslicer \
  -e PRUSASLICER_PATH="/path/to/PrusaSlicer" \
  -- uv --directory /path/to/prusaslicer-mcp run prusaslicer-mcp
```

`PRUSASLICER_PATH` is only needed when auto-detection fails (e.g. a nonstandard install folder; quote
paths containing spaces). `claude mcp list` should then show `prusaslicer`. Other MCP clients need the same
command and an `env` block.

### Project scope (this repo)

The repository ships a `.mcp.json` that registers the server for anyone working in this checkout
(`claude mcp add --scope project prusaslicer -- uv run prusaslicer-mcp`). It contains no paths: `uv run`
resolves the project from the working directory, and PrusaSlicer is auto-detected. If detection fails, set
`PRUSASLICER_PATH` in the environment `claude` is launched from (for example via direnv and `.env`). Claude
Code asks you to approve project-scoped servers the first time; `claude mcp list` shows the status.

## Notes

- STEP files (`.step`, `.stp`) work in every tool: `inspect_model` and `preview_model` have PrusaSlicer convert them to a temporary mesh, so their triangle count and watertightness describe PrusaSlicer's tessellation ([ADR 0016](docs/decisions/0016-read-step-files-through-prusaslicer.md)).
- Transforms use PrusaSlicer's own flags: rotations apply in the fixed order X, then Y, then Z (with one oddity, exactly +-90 about Y together with a Z rotation, so check with `preview_model(rotate_*)`, which asks PrusaSlicer itself: [ADR 0015](docs/decisions/0015-preview-transforms-by-asking-prusaslicer.md)); `scale` is a factor (0.5 is half, not 50%); `copies` is the total number of objects. Plates built from several files are not supported, because `--merge` crashes PrusaSlicer 2.9.7 ([ADR 0012](docs/decisions/0012-transform-with-prusaslicers-own-flags.md)).
- A slice that succeeds is not always printable. A scan exported Y-up slices without an error and with plausible statistics, but it lies on its side, so parts of its height print nothing. `preview_model` shows that at a glance and `preview_gcode` (view `profile`) shows the empty stretches. A scan can also have a real hole, such as a missing base, which PrusaSlicer refuses (`no extrusions in the first layer`); `inspect_model` reports it and `slice_model(close_holes=true)` caps it in a temporary copy, leaving the file alone ([ADR 0014](docs/decisions/0014-cap-flat-holes-on-request.md)), with a flat base even where the scan's rim is ragged ([ADR 0017](docs/decisions/0017-close-a-hole-with-a-flat-base.md)). A scan's base is rarely square to its axis (the statue's is 16 degrees off), so stand it on the capped base rather than on an axis, as `suggest_orientation(close_holes=true)` does: a tilted base touches the bed along one edge ([ADR 0018](docs/decisions/0018-suggest-orientations-from-geometry.md)). Only simple, nearly flat holes are capped, so look at `preview_model` first: a cup scanned open at the top would be closed too. `slice_model` returns PrusaSlicer's own warnings in full and adds a warning when layers skip a large stretch of the height, so read `warnings` before trusting the numbers.
- Plain 3MF files (exported from CAD, not saved from PrusaSlicer) keep their stored coordinates, so a part modelled around the origin sits half off the bed. `slice_model` therefore centres a plain 3MF on the bed by default (`center` omitted) and reports `centered`; pass `center=false` to keep its stored position, or `center=true` to centre a project, STL or OBJ. STL and OBJ files are placed by PrusaSlicer, and projects keep their own layout ([ADR 0013](docs/decisions/0013-centre-plain-3mf-files-automatically.md)).
- When PrusaSlicer refuses a slice, the error keeps its own message and adds advice where we know the remedy: a model larger than the bed (with its size, the bed's size, `scale_to_fit` and, if it fits across the diagonal, `rotate_z=45`), an empty first layer (`preview_model`, `rotate_x`/`rotate_y`, repair), and the wipe-tower conflict (an override).

- `--query-*` actions exit with status 1 on success in 2.9.7; the server judges them by their output file.
- `slice_model`'s `output_path` may create its last folder only; if the folder above it does not exist the call is refused, because that is almost always a typo.
- Setting overrides use PrusaSlicer config option names, e.g. `{"fill_density": "25%"}` (see `PrusaSlicer --help-fff`). Options the server sets itself (profiles, output, `binary_gcode`, `datadir`, `save`) are rejected.

## Limitations

- No live GUI control: each call runs a separate PrusaSlicer process and cannot see what is open in the GUI.
- Output is always text G-code, even where the profile prefers binary (`.bgcode`).
- FFF (filament) slicing only; single material; no transform options yet. See the [roadmap](ROADMAP.md).

## Development

Everything runs through `uv`; [Poe the Poet](https://poethepoet.natn.io/) chains the checks (uv has no task runner).

```bash
uv sync                      # install
uv run poe check             # lint, format check, type check, unit tests (what CI runs, minus integration)
uv run poe fix               # apply safe lint fixes, then format
uv run poe test-integration  # tests that need a real PrusaSlicer (skip when absent)
uv run poe                   # list every task
uv run poe dogfood run <folder>   # run every tool over a folder of real models and report (opt-in; docs/dogfooding.md)
```

`uv format`, `uv check` and `uv audit` are uv's own formatter, type checker (ty, pinned) and dependency audit.
Ruff does the linting and pyright type-checks alongside ty ([ADR 0010](docs/decisions/0010-pin-ty-and-add-pyright.md)). Commits follow [Conventional Commits](https://www.conventionalcommits.org/) (`feat: ...`, `fix: ...`):
CI checks them with commitlint, and [Release Please](https://github.com/googleapis/release-please) opens a release
pull request from them. See [ADR 0008](docs/decisions/0008-conventional-commits-and-release-please.md) and
[ADR 0009](docs/decisions/0009-quality-gate-toolchain.md).

## Documentation

- [Roadmap](ROADMAP.md): what's planned
- [Architecture](docs/architecture/README.md): how the server works
- [Decision records](docs/decisions/README.md): why it works that way (MADR)
- [`CLAUDE.md`](CLAUDE.md) and `.claude/rules/`: conventions for Claude Code sessions in this repo

## License

MIT. PrusaSlicer itself is AGPL-3.0 and is invoked as a separate program, not bundled.
