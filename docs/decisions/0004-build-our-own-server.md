---
status: accepted
date: 2026-11-14
decision-makers: Sebastien Coutu
---

# Build our own server instead of adopting PrusaMCP

## Context and Problem Statement

Before building, we searched GitHub for existing PrusaSlicer MCP servers. The closest is
[Noosbai/PrusaMCP](https://github.com/Noosbai/PrusaMCP) (TypeScript, MIT, 17 tools). We read its
source (without running it). Should we adopt or extend it rather than start our own?

What we found: it is mostly a print-advice engine (mesh analysis, a hardcoded recommendation engine
for materials/goals, defect diagnosis) with a thin slicing layer. Slicing runs
`--export-gcode --load <generated .ini>`; it does not use installed printer/print/filament profiles,
has no profile discovery, and does not handle `.bgcode`. It is Windows-oriented (`prusa-slicer-console.exe`,
`%APPDATA%`, PowerShell/Win32 for screenshots and window-title detection). It had 3 commits from one author.

## Decision Drivers

* Needs to work on macOS with the user's real installed profiles.
* The core capability we want (profile-aware headless slicing) is exactly its weakest part.
* We want to understand and control the code.

## Considered Options

* Build our own (`prusaslicer-mcp`)
* Use PrusaMCP as-is
* Fork or contribute upstream to PrusaMCP

## Decision Outcome

Chosen option: "Build our own", because the overlap is small, the existing server would need its
slicing core and platform support rewritten, and a small server we fully understand is preferable.

### Consequences

* Good, because the design is profile-first and cross-platform from the start.
* Bad, because we forgo its advisory features (orientation scoring, printability checks, cost estimate) unless we port them.
* Neutral, because it is MIT-licensed; ideas or code may be reused with attribution.

## Pros and Cons of the Options

### Build our own

* Good, because it fits our goals and platform.
* Bad, because it is more work than reuse.

### Use PrusaMCP as-is

* Good, because it exists today.
* Bad, because it targets Windows and ignores installed profiles.

### Fork or contribute upstream to PrusaMCP

* Good, because it avoids duplicated effort.
* Bad, because the needed changes touch its core and the codebase is small and young; coordination cost outweighs reuse.

## More Information

Reference clone (kept outside this repo): `/Users/sebastienc/src/com.github/Noosbai/PrusaMCP`.
Candidate ideas to port later: orientation scoring and printability checks.
Other servers surveyed: OrcaSlicer MCP servers (several), printer-side PrusaLink/Prusa Connect servers.
