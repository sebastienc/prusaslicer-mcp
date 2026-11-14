# prusaslicer-mcp

An [MCP](https://modelcontextprotocol.io) server that lets Claude (or any MCP client) drive the
**PrusaSlicer 2.9.x command line**: discover installed printers and profiles, sanity-check a model,
slice it headlessly with your real presets, and get print time and filament use back.

It runs PrusaSlicer as a separate process, so it works while the GUI is open and does not touch it.
It does **not** control the GUI itself (PrusaSlicer 2.9.x has no remote-control API).

## Tools

| Tool | What it does |
|---|---|
| `list_printers` | Installed printer models, exact printer profile names, nozzle variants, bed sizes |
| `list_profiles` | Print (quality) profiles and compatible filament profiles for a printer profile |
| `inspect_model` | Size, volume, watertightness, part count; optional build-volume fit check (via `trimesh`) |
| `slice_model` | Slice with `printer_profile` / `print_profile` / `material_profile`, optional setting overrides; returns G-code path, time, filament, cost, layers |

Profile names must match exactly; use `list_printers` and `list_profiles` to discover them.
G-code is always written as text (`--binary-gcode=0`) so statistics can be read back.

## Setup

Requires Python 3.12+, [uv](https://docs.astral.sh/uv/), and PrusaSlicer 2.9.x.

```bash
uv sync
cp .env.example .env     # then edit; see below
direnv allow             # optional: loads .env into your shell
uv run pytest            # integration tests are skipped if PrusaSlicer isn't found
```

### Configuration (`.env`)

| Variable | Purpose | Default |
|---|---|---|
| `PRUSASLICER_PATH` | PrusaSlicer executable | auto-detected (`PATH`, `/Applications/**/PrusaSlicer.app`, ...) |
| `PRUSASLICER_DATADIR` | Profile/config directory | platform default |
| `PRUSASLICER_MCP_OUTPUT_DIR` | Where G-code goes when no output path is given | `./output` |
| `PRUSASLICER_MCP_TIMEOUT` | Slice timeout (seconds) | `600` |

## Register with Claude Code

```bash
claude mcp add prusaslicer \
  -e PRUSASLICER_PATH="/path/to/PrusaSlicer" \
  -- uv --directory /path/to/prusaslicer-mcp run prusaslicer-mcp
```

## Notes

- `--query-*` actions exit with status 1 on success in 2.9.7; the server judges them by their output file.
- Setting overrides use PrusaSlicer config option names, e.g. `{"fill_density": "25%"}` (see `PrusaSlicer --help-fff`).

## License

MIT. PrusaSlicer itself is AGPL-3.0 and is invoked as a separate program, not bundled.
