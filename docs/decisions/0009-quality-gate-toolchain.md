---
status: accepted
date: 2026-11-14
decision-makers: Sebastien Coutu
---

# Quality gates: uv first, Ruff for linting, Poe to chain them

## Context and Problem Statement

We want automatic gates: formatting, linting, type checking, dependency auditing and tests, run the same way locally
and in CI, with unit tests separated from the integration tests that need a real PrusaSlicer. Which tools, and how
are they run?

## Decision Drivers

* Prefer what `uv` already provides over adding tools.
* Local and CI runs must not drift apart.
* Integration tests need PrusaSlicer, which a CI runner does not have.
* The tools must fail (non-zero exit) when something is wrong.

## Considered Options

* uv's built-in `format`, `check` and `audit`, Ruff for linting, Poe as the task runner
* Ruff and mypy (or pyright) installed as dev dependencies, plus a Makefile or `just`
* tox or nox

## Decision Outcome

Chosen option: "uv built-ins first, Ruff for linting, Poe as the task runner". uv 0.12 provides `uv format`
(Ruff's formatter), `uv check` (type checking) and `uv audit` (vulnerability audit) but has no linter and no task
runner, so the gaps are Ruff (`ruff check`) and Poe the Poet. Tasks live in `[tool.poe.tasks]`; CI calls the same
tasks, so local and CI checks cannot diverge. `uv run poe check` runs everything except integration tests.

* **Ruff version.** `uv format` uses Ruff `>=0.15,<0.16`, so the dev dependency is constrained to that range to keep
  the linter and formatter in agreement.
* **Test split.** Any test that uses the `prusaslicer` fixture is marked `integration` automatically
  (`tests/conftest.py`); `--strict-markers` is on. CI runs the unit tests on Python 3.12 and 3.14 with a 95% coverage
  floor, and the integration tests separately.
* **Integration on macOS.** Prusa stopped attaching Linux builds to its GitHub releases after 2.8.x, so the
  integration job runs on a macOS runner with the official 2.9.7 `.dmg` (`.github/scripts/setup-prusaslicer-macos.sh`).
  The installer is cached by version. A throwaway data directory is built from the profiles inside the app, so Prusa's
  AGPL profile data is never committed here.
* **Protocol test.** `tests/test_stdio.py` starts the real server and checks tools, annotations, schemas,
  descriptions, error text and that stdout carries only protocol messages. It replaces the manual client script.
* **Pinned uv.** CI pins `UV_VERSION` and sets `UV_LOCKED`.

### Consequences

* Good, because there is one place that defines every check, and CI reuses it.
* Good, because the type checker found real narrowing gaps in the first run.
* Bad, because `uv format`, `uv check` and `uv audit` are marked experimental and may change; pinning uv in CI makes
  that a deliberate upgrade.
* Bad, because the type checker does not understand Pydantic's camelCase aliases (it warned that the tool annotations
  were discarded, which was false); the code uses the snake_case names instead.
* Bad, because the integration job uses macOS runner minutes, which cost more than Linux, and Linux is not covered.
* Bad, because Poe is one more dev dependency.

### Confirmation

`.github/workflows/ci.yml`, and `uv run poe check` locally. Each gate was shown to exit non-zero on a planted problem.

## Pros and Cons of the Options

### uv built-ins, Ruff, Poe

* Good, because it adds the fewest tools and keeps the formatter and type checker on the uv path.
* Bad, because of the experimental commands noted above.

### Ruff and mypy plus a Makefile

* Good, because mypy and Make are mature and stable.
* Bad, because it duplicates what uv now provides and adds a second way to run things.

### tox or nox

* Good, because they isolate environments per task.
* Bad, because `uv run` already gives a locked environment, which makes them redundant here.

## More Information

Related: [ADR 0008](0008-conventional-commits-and-release-please.md), [ADR 0003](0003-python-uv-and-official-mcp-sdk.md).
