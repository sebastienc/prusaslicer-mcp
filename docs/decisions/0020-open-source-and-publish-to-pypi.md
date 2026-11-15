---
status: accepted
date: 2026-11-15
decision-makers: Sebastien Coutu
---

# Open-source the project and publish it to PyPI

## Context and Problem Statement

The repository was private and [ADR 0008](0008-conventional-commits-and-release-please.md) deliberately stopped at a
GitHub release: nothing went to a package index. The project is now useful enough to share, and the natural way to
install an MCP server is `uvx prusaslicer-mcp`, which needs a package on PyPI. How do we publish it, and how do we
keep a published package from becoming a liability?

## Decision Drivers

* A release must not need a long-lived secret that can leak.
* A bad release cannot be taken back: PyPI never lets a version number be reused, and a yanked version stays visible.
* The existing release flow (Release Please, Conventional Commits) should stay the single way a version is made.
* Publishing was previously ruled out "without being asked"; it must stay a deliberate act, not a side effect.

## Considered Options

* Trusted publishing from the Release Please workflow, through a protected `pypi` environment
* A separate workflow triggered by the GitHub release
* A manual `uv publish` with an API token from a laptop

## Decision Outcome

Chosen option: "Trusted publishing from the Release Please workflow", because it needs no stored token and keeps one
path from commit to release.

* The repository is public under the MIT licence; the PyPI project is `prusaslicer-mcp`.
* Merging the Release Please pull request is the deliberate act. That creates the tag, and the `build` and `publish`
  jobs of `.github/workflows/release-please.yml` upload to PyPI. Nothing else publishes.
* Publishing is a job of the Release Please workflow, not an `on: release` workflow, because a release created with
  the default `GITHUB_TOKEN` does not trigger other workflows.
* `build` runs with read-only permissions; only `publish` has `id-token: write`, and only inside the `pypi`
  environment, which can require a reviewer.
* The `package` job in CI builds the wheel and sdist on every pull request, installs the wheel in a clean
  environment and runs `twine check --strict`, so a broken package fails before release day.
* The dependency on `mcp` is `>=2.1.0`: the code imports `mcp.server.mcpserver`, which does not exist in 1.x and fails to build
  its tool schemas in 2.0.0 (found by running the unit tests against the lowest allowed versions), so the
  earlier `>=1.2` would have installed a server that fails on import.

### Consequences

* Good, because a release is one merge, with no secret to rotate or leak.
* Good, because the wheel and its metadata are exercised on every pull request.
* Bad, because the first publish needs a one-off manual step on PyPI: a pending trusted publisher must be registered
  for the repository, the workflow `release-please.yml` and the environment `pypi` (see `CONTRIBUTING.md`).
* Bad, because a released version is permanent. A mistake costs a new patch release, not a correction.
* Bad, because the project now has users. The name `PrusaSlicer` appears in the package name, so the README states
  that this is an independent project and not affiliated with or endorsed by Prusa Research.

### Confirmation

The `package` job in `.github/workflows/ci.yml`; the `publish` job and the project page on PyPI.
