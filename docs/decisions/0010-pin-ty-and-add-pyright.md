---
status: accepted
date: 2026-11-14
decision-makers: Sebastien Coutu
---

# Pin ty and add pyright as a second type checker

## Context and Problem Statement

[ADR 0009](0009-quality-gate-toolchain.md) chose `uv check` as the type checker. It runs Astral's `ty`, which is
pre-1.0 (0.0.x). Using it showed three problems:

* `ty` is not in `uv.lock`. `uv check` resolves "the latest 0.0.x" every time, so a new `ty` release can turn CI red
  with no change in our code.
* It gave a false alarm (it said the tool annotations were discarded by Pydantic, which was untrue).
* It missed real findings: pyright reports 9 errors in `tests/test_stdio.py` that `ty` did not, such as reading
  `result.content[0].text` when the first block could be an image, and `in initialized.instructions` when that can
  be `None`.

The source passes pyright's strictest mode with no errors, so the extra checker costs little to adopt.

## Decision Drivers

* A new tool release must not break CI on its own.
* A mature checker should back up the pre-release one.
* Prefer uv's own commands, as in ADR 0009.

## Considered Options

* Keep `uv check` alone, unpinned
* Pin `ty` and keep it alone
* Pin `ty` and add pyright
* Replace `ty` with pyright (or mypy)

## Decision Outcome

Chosen option: "Pin `ty` and add pyright". `uv check --ty-version 0.0.104` keeps `ty` on the uv path with a fixed
version, and `pyright` (a locked dev dependency, basic mode, over `src` and `tests`) runs after it. Both are in the
`typecheck` Poe task, so `uv run poe check` and the CI `type check` job run them together.

* The `ty` pin lives in `[tool.poe.tasks]`; bump it on purpose, like the pinned uv version in CI.
* pyright uses the interpreter `uv run` puts on `PATH`, so no virtual environment is configured.
* Basic mode, not strict: the source is strict-clean, but strict mode is noisy on tests and on the untyped `trimesh`.

### Consequences

* Good, because `ty` can no longer change under us, and a mature checker caught what it missed.
* Bad, because two checkers can disagree, and an issue may need a fix that satisfies both.
* Bad, because pyright adds a dev dependency (it downloads Node on first use) and about 20 seconds to CI.
* Revisit when `ty` reaches 1.0: running one checker may then be enough.

### Confirmation

`uv run poe typecheck`, the `type check` job in `.github/workflows/ci.yml`. Both gates were shown to exit non-zero
on a planted type error.

## Pros and Cons of the Options

### Keep `uv check` alone, unpinned

* Good, because it adds nothing.
* Bad, because CI can break on a `ty` release, and real errors were missed.

### Pin `ty` and keep it alone

* Good, because it fixes reproducibility cheaply.
* Bad, because it keeps the missed findings.

### Pin `ty` and add pyright

* Good, because it fixes both problems and the source already passes.
* Bad, because of the consequences above.

### Replace `ty` with pyright (or mypy)

* Good, because there is one stable checker.
* Bad, because it drops the uv-native path preferred in ADR 0009 for a tool that will mature.

## More Information

Amends [ADR 0009](0009-quality-gate-toolchain.md) (its type-checking part); the rest of ADR 0009 stands.
