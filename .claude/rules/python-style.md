---
paths:
  - "src/**/*.py"
  - "tests/**/*.py"
---

# Python style

- Target **Python 3.12+** (`requires-python` in `pyproject.toml`). Use modern syntax: `X | None`, built-in generics (`list[str]`), `from __future__ import annotations`.
- **src layout**: package code lives in `src/prusaslicer_mcp/`. One responsibility per module (see `docs/architecture/README.md`); do not grow `server.py` into a catch-all.
- Type-hint every function signature. Structured data crossing a tool boundary is a **pydantic `BaseModel`**, not a bare `dict`.
- Use `pathlib.Path` for paths. Resolve and validate user-supplied paths before use.
- Prefer `async def` for anything that waits on a subprocess; keep pure computation synchronous.
- Dependencies are managed with **uv** only: `uv add <pkg>` / `uv add --dev <pkg>`. Never hand-edit `uv.lock`, never use `pip install`.
- Formatting and linting are automatic: run `uv run poe fix`. Do not silence the type checker with `# type: ignore`; narrow the type so the code is correct (see `_chosen_profiles`).
- Keep comments for the *why* (quirks, constraints). Do not restate what the code does.
- No broad `except Exception: pass`. Catch the specific error and either handle it or re-raise with context.
