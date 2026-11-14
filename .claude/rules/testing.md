---
paths:
  - "tests/**/*.py"
  - "src/**/*.py"
---

# Testing

- Run the suite with `uv run pytest`. It must pass before committing.
- Unit-test pure logic (parsing, validation) with inline samples; no PrusaSlicer needed. Example: `tests/test_gcode.py`.
- Integration tests that run the real binary go in `tests/test_server.py` and use the `prusaslicer` fixture, which **skips** when PrusaSlicer is not installed. They must never fail just because it is missing.
- Use `tmp_path` / the `cube_stl` fixture for files. Do not commit models, `.gcode`, or `.bgcode` files, and do not write into the repo tree or the user's PrusaSlicer data directory.
- Reset module state that tests touch (`server._config`) in a fixture, as `test_server.py` does.
- Fix bugs test-first where practical: a regression test that fails, then the fix.
- When a change touches the stdio protocol surface (tool names, schemas), also verify with a real MCP client over stdio, not only by calling the Python functions.
