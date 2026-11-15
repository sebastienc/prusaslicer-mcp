# Architecture Decision Records

Decisions are recorded in [MADR 4.0](https://adr.github.io/madr/) format. Copy
[`adr-template.md`](adr-template.md) for a new one. Numbers are sequential and never reused.
ADRs are append-only history: to change a decision, write a new ADR and mark the old one
`superseded by ADR-NNNN`. See `.claude/rules/docs-and-decisions.md`.

| ADR | Title | Status |
|---|---|---|
| [0001](0001-record-architecture-decisions.md) | Record architecture decisions | accepted |
| [0002](0002-wrap-the-prusaslicer-2-9-cli.md) | Integrate by wrapping the PrusaSlicer 2.9.x CLI | accepted |
| [0003](0003-python-uv-and-official-mcp-sdk.md) | Implement in Python with uv and the official MCP SDK | accepted |
| [0004](0004-build-our-own-server.md) | Build our own server instead of adopting PrusaMCP | accepted |
| [0005](0005-always-slice-to-text-gcode.md) | Always slice to text G-code | accepted |
| [0006](0006-configuration-via-environment-and-direnv.md) | Configure through environment variables loaded by direnv | accepted |
| [0007](0007-slice-prusaslicer-projects-with-their-own-settings.md) | Slice PrusaSlicer projects with their own settings | accepted |
| [0008](0008-conventional-commits-and-release-please.md) | Conventional Commits, enforced by commitlint, drive releases with Release Please | accepted |
| [0009](0009-quality-gate-toolchain.md) | Quality gates: uv first, Ruff for linting, Poe to chain them | accepted |
| [0010](0010-pin-ty-and-add-pyright.md) | Pin ty and add pyright as a second type checker | accepted |
| [0011](0011-render-previews-with-numpy-and-pillow.md) | Render previews ourselves with numpy and Pillow | accepted |
| [0012](0012-transform-with-prusaslicers-own-flags.md) | Transform models with PrusaSlicer's own flags, and do not expose --merge | accepted |
| [0013](0013-centre-plain-3mf-files-automatically.md) | Centre plain 3MF files on the bed automatically | accepted |
| [0014](0014-cap-flat-holes-on-request.md) | Cap flat holes in a mesh on request | accepted |
| [0015](0015-preview-transforms-by-asking-prusaslicer.md) | Preview transforms by asking PrusaSlicer | accepted |
| [0016](0016-read-step-files-through-prusaslicer.md) | Read STEP files through PrusaSlicer | accepted |
