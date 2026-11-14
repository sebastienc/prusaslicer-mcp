---
status: accepted
date: 2026-11-14
decision-makers: Sebastien Coutu
---

# Implement in Python with uv and the official MCP SDK

## Context and Problem Statement

The server needs an implementation language and toolchain. Beyond wrapping the CLI, we want mesh
analysis (watertightness, volume, parts) and, later, rendered previews that Claude can look at.

## Decision Drivers

* Quality of mesh and image libraries for model checks and previews.
* Official MCP SDK support and low boilerplate.
* Familiar, reproducible tooling.

## Considered Options

* Python with uv and the official `mcp` SDK
* TypeScript with the official `@modelcontextprotocol/sdk`

## Decision Outcome

Chosen option: "Python with uv and the official `mcp` SDK", because `trimesh` provides mesh analysis
we would otherwise hand-write, and `numpy`/`matplotlib` make server-side preview images practical.

### Consequences

* Good, because mesh validation is a few library calls, and previews are feasible later.
* Good, because `uv` gives a locked, reproducible environment.
* Bad, because dependencies are heavier than a pure-Node server (`numpy`, `trimesh`, `networkx`, `lxml`).
* Bad, because the SDK is **2.x**, where `FastMCP` became `MCPServer`; v1-era examples and training data are misleading (recorded in `.claude/rules/mcp-tools.md`).

## Pros and Cons of the Options

### Python with uv and the official `mcp` SDK

* Good, because the mesh/plotting ecosystem is strong.
* Good, because tools are plain typed functions with generated schemas.
* Bad, because of the heavier install.

### TypeScript with the official SDK

* Good, because it is light and `zod` validation is solid.
* Bad, because mesh analysis and server-side rendering would be mostly DIY.

## More Information

Minimum Python is 3.12 because current NumPy requires it.
