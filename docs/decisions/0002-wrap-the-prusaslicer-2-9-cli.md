---
status: accepted
date: 2026-11-14
decision-makers: Sebastien Coutu
---

# Integrate by wrapping the PrusaSlicer 2.9.x CLI

## Context and Problem Statement

The goal is for Claude to control PrusaSlicer. We surveyed what PrusaSlicer offers for programmatic
access, in both the 2.9.7 release tag and the 3.0.0-alpha14 source on `master`. Which integration
mechanism should the MCP server build on?

Findings (source inspection plus running the installed 2.9.7 binary):

* **2.9.7** has no plugin system, scripting engine, or inbound API. It has a headless CLI, G-code
  post-processing scripts, outbound-only print-host uploads, and a single-instance handoff that can
  only forward a file to open to a running GUI.
* **3.0.0-alpha** adds a sandboxed Lua plugin system with a deliberately minimal API (create objects,
  custom G-code per layer). Plugins are user-triggered from a menu, and the sandbox removes `io` and
  `os`, so a plugin cannot open sockets or be driven from outside.
* Neither version has an inbound control channel for the running GUI.

## Decision Drivers

* Must work on stock, released PrusaSlicer on macOS without patching it.
* Must keep working while the user has the GUI open.
* Should use the user's real installed profiles.
* Prefer a stable, documented surface over alpha features.

## Considered Options

* Wrap the PrusaSlicer 2.9.x command line
* Build on the 3.0 Lua plugin system
* Fork PrusaSlicer and add an IPC/HTTP control server
* Generate 3MF/ini files and hand them to the user to open

## Decision Outcome

Chosen option: "Wrap the PrusaSlicer 2.9.x command line", because it is the only option that works
on the released app today, uses real profiles (`--printer-profile`, `--print-profile`,
`--material-profile`, `--query-*`), and does not interfere with a running GUI.

### Consequences

* Good, because no fork or patching is needed; the server is a small, understandable program.
* Good, because profile discovery and slicing are first-class (verified against 2.9.7).
* Bad, because it cannot see or change what is open in the GUI; each call is a separate one-shot process.
* Bad, because behaviour is tied to 2.9.x CLI details (see ADR 0005 and the exit-code quirk in `docs/architecture/README.md`).

### Confirmation

`tests/test_server.py` slices a model with a real install and checks the statistics.

## Pros and Cons of the Options

### Wrap the PrusaSlicer 2.9.x CLI

* Good, because it works today on the stable release and the CLI is a supported interface.
* Bad, because there is no live GUI control.

### Build on the 3.0 Lua plugin system

* Good, because it is the sanctioned extension point going forward.
* Bad, because it is alpha, the API is minimal, and the sandbox forbids network/file access, so it cannot bridge to an MCP server.

### Fork PrusaSlicer and add an IPC/HTTP control server

* Good, because it is the only route to true live GUI control.
* Bad, because it means maintaining a fork (AGPL, source must be published) and building PrusaSlicer.
* Neutral, because another project has done this for OrcaSlicer, so it is feasible.

### Generate 3MF/ini files and hand them to the user to open

* Good, because it is trivial.
* Bad, because it is not control; the user does all the work.

## More Information

Revisit if a later PrusaSlicer release adds an inbound API, or if live GUI control becomes a goal
(then evaluate the fork option in a new ADR). Source references: `src/CLI/` and
`src/slic3r/GUI/InstanceCheck.cpp` in the 2.9.7 tag; `doc/Plugin_API.md` on `master`.
