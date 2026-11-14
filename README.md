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
reads back the print time and filament use.

## Tools

| Tool | What it does |
|---|---|
| `list_printers` | Installed printer models, exact printer profile names, nozzle variants, bed sizes |
| `list_profiles` | Print (quality) profiles and compatible filament profiles for a printer profile |
| `inspect_model` | Size, volume, watertightness, part count; optional build-volume fit check (via `trimesh`), a warning when a 3MF's stored position is off the bed, and, for a 3MF saved from PrusaSlicer, the profiles and key settings (infill, brim, supports) stored in it |
| `slice_model` | Slice with `printer_profile` / `print_profile` / `material_profile` (all three, or none for a PrusaSlicer project, which then keeps its own saved settings), optional setting overrides and `center`; returns G-code path, time, filament, cost, layers, and whether the project's or the profiles' settings were used |

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

- A slice that succeeds is not always printable. A scan exported Y-up slices without an error and with plausible statistics, but it lies on its side, so parts of its height print nothing (it needs rotating, not repairing). `slice_model` returns PrusaSlicer's own warnings in full and adds a warning when layers skip a large stretch of the height, so read `warnings` before trusting the numbers.
- Plain 3MF files (exported from CAD, not saved from PrusaSlicer) keep their stored coordinates, so a part modelled around the origin sits half off the bed and slicing fails with "All objects are outside of the print volume". Pass `center=true` to `slice_model` to place it in the middle of the bed. STL/OBJ files are placed automatically, and 3MF projects saved from PrusaSlicer should be sliced with `center=false` to keep their layout.

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
