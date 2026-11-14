---
status: accepted
date: 2026-11-14
decision-makers: Sebastien Coutu
---

# Configure through environment variables loaded by direnv

## Context and Problem Statement

The server needs machine-specific settings, chiefly the PrusaSlicer executable path (the user's
install is in a nonstandard folder, `/Applications/Original Prusa Drivers/...`), plus optional data
directory, output directory and timeout. How should these be supplied and kept out of source control?

## Decision Drivers

* Different machines have different install locations.
* Local settings must not be committed.
* Works for MCP clients that pass an `env` block, and for local development.

## Considered Options

* Environment variables, loaded locally by direnv from a git-ignored `.env`
* A config file in the repo or in the user's home directory
* Command-line arguments only

## Decision Outcome

Chosen option: "Environment variables, loaded locally by direnv from a git-ignored `.env`", because
environment variables are what MCP clients pass natively, direnv gives automatic loading in the
project directory, and `.env.example` documents every variable.

Resolution order for the executable: `PRUSASLICER_PATH` → `PATH` lookup → known install locations
for the platform. Everything has a sensible default except where no install can be found, in which
case the server fails with a clear message.

### Consequences

* Good, because secrets/paths stay out of git and setup is one `cp .env.example .env`.
* Good, because auto-detection means the env var is only needed for unusual installs.
* Bad, because direnv is an extra tool; MCP clients that do not use it must supply `env` themselves (documented in the README).

## Pros and Cons of the Options

### Environment variables with direnv

* Good, because standard, scriptable, client-friendly.
* Bad, because requires direnv for the local convenience.

### A config file

* Good, because structured.
* Bad, because it adds a format and a location to define, and risks committing machine paths.

### Command-line arguments only

* Good, because explicit.
* Bad, because awkward to set per machine in MCP client configs and in development.

## More Information

Variables: `PRUSASLICER_PATH`, `PRUSASLICER_DATADIR`, `PRUSASLICER_MCP_OUTPUT_DIR`,
`PRUSASLICER_MCP_TIMEOUT` (see `.env.example`).
