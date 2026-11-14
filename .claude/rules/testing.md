---
paths:
  - "tests/**/*.py"
  - "src/**/*.py"
---

# Testing

## TDD is the default workflow

- Write the **failing test first**, run it and see it fail for the right reason, then write the least code that makes it pass, then refactor with the suite green. Red, green, refactor.
- This applies to new behavior, changed behavior, and bug fixes alike. A bug fix starts with a regression test that reproduces the bug.
- One behavior per cycle: small steps, run `uv run pytest` after each. Do not write a batch of implementation and add tests afterwards.
- Do not weaken or delete a test to get to green. If a test is wrong, fix the test deliberately and say why.
- Exceptions need a stated reason: pure docs/config changes, throwaway exploration (then write the tests before keeping the code), and behavior that cannot run without the real PrusaSlicer, which gets an integration test that skips when it is missing (see below).

## Practicalities

- Run the suite with `uv run pytest`. It must pass before committing.
- Unit-test pure logic (parsing, validation) with inline samples; no PrusaSlicer needed. Example: `tests/test_gcode.py`.
- Integration tests that run the real binary go in `tests/test_server.py` and use the `prusaslicer` fixture, which **skips** when PrusaSlicer is not installed. They must never fail just because it is missing.
- Use `tmp_path` / the `cube_stl` fixture for files. Do not commit models, `.gcode`, or `.bgcode` files, and do not write into the repo tree or the user's PrusaSlicer data directory.
- Reset module state that tests touch (`server._config`) in a fixture, as `test_server.py` does.
- When a change touches the stdio protocol surface (tool names, schemas), also verify with a real MCP client over stdio, not only by calling the Python functions.
