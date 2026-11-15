# prusaslicer-mcp

MCP server (Python, stdio) that lets Claude drive the **PrusaSlicer 2.9.x command line**: list
printers/profiles, check and preview a model, suggest which way up to print it, slice headlessly with the
user's real profiles, return print stats. It does not control the GUI. Private repo, MIT.

## Where things are

- Conventions: `.claude/rules/*.md` (auto-loaded; read them before changing code in the area they cover)
- How it works now: `docs/architecture/README.md`
- Why it works that way: `docs/decisions/` (MADR ADRs, index in its README)
- What's next: `ROADMAP.md`
- User-facing setup and usage: `README.md`

## Commands

```bash
uv sync                      # install (Python 3.12+)
uv run poe check             # everything CI checks except integration tests: lint, format, types, unit tests
uv run poe fix               # apply safe lint fixes, then format
uv run poe test              # unit tests (no PrusaSlicer needed)
uv run poe test-integration  # tests that need a real PrusaSlicer (skip when absent)
uv run poe                   # list every task
uv run poe dogfood run <dir> # run every tool over a folder of real models and report (opt-in, docs/dogfooding.md)
uv run prusaslicer-mcp       # run the server on stdio
```

Local config lives in `.env` (git-ignored, loaded by direnv); `.env.example` is the template.
Do not run `direnv allow` for the user.

## Critical gotchas (details in the rules)

- **Never print to stdout**: it is the MCP transport. Log to stderr.
- MCP SDK is **2.x** (`from mcp.server.mcpserver import MCPServer`), not the v1 `FastMCP` API.
- PrusaSlicer's `--query-*` actions **exit 1 on success**; check the output file instead.
- Profile names must match exactly; slice with `--binary-gcode=0`; no shell, ever.
- **A slice that succeeds is not proof that it prints.** Look at the first layers (filament per layer), not only at the exit code (ADR 0017). Prefer asking PrusaSlicer to do a transform over redoing it (ADR 0015).

## Working here

- **TDD**: write the failing test first, then the code (see `.claude/rules/testing.md`). `uv run poe check` must pass before committing.
- **Commits are Conventional Commits** (`feat: add x`, lower-case subject, header <= 72 characters); CI rejects anything else and Release Please builds releases from them.
- Tool added/changed → update `README.md` tool table and `docs/architecture/README.md`.
- Hard-to-reverse choice → write an ADR. Finished or newly planned work → update `ROADMAP.md`.
- Commit/push only when asked.

## Reference material (outside this repo, if present on this machine)

- `../../Noosbai/PrusaMCP`: another PrusaSlicer MCP server, read-only reference (see ADR 0004). Do not run its code.
- `../../prusa3d/PrusaSlicer`: PrusaSlicer source, may be checked out at the `version_2.9.7` tag. The installed
  app's path is in `.env` (`PRUSASLICER_PATH`).
