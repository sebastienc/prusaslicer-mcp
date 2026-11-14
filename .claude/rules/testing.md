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

## Given / When / Then

Every test is written as **Given / When / Then** (the same shape as a BDD scenario, in plain pytest; no extra framework).

- **Name** the test after the behavior, not the function: `test_<behavior>_when_<condition>` or a short sentence like `test_center_uses_the_middle_of_the_bed`. A failing name should say what broke.
- **Body** has three parts, each marked with a comment, in this order:
  - `# Given`: the state and inputs. Fixtures, fakes, sample data. Setup that every test shares goes in a fixture; setup that explains this scenario stays visible in the test.
  - `# When`: **one** action under test. If you need two, it is two tests.
  - `# Then`: the observable outcome. Assert on results and on what the client sees, not on private internals.
- Keep a part that is a single line on the same comment, e.g. `# When / Then` for `with pytest.raises(...)` blocks where the action and the assertion are one statement. Never drop `# Given` just because it is short.
- Prefer several narrow tests over one long scenario. Parametrize (`pytest.mark.parametrize`) when only the data changes, and give the cases ids that read like scenarios.
- Test through the same path a client uses where it matters (`mcp.call_tool` for tool behavior and errors), and fake only the boundary (`cli.run`), never the logic being tested.
- Example:

  ```python
  async def test_center_uses_the_middle_of_the_bed(slicer, model):
      # Given a 180 x 180 mm printer profile and a model file
      arguments = {"model_path": str(model), "printer_profile": "Mini", "center": True, ...}

      # When the model is sliced with center on
      await server.mcp.call_tool("slice_model", arguments)

      # Then PrusaSlicer is told to centre on 90,90
      args = slicer.calls[0]
      assert args[args.index("--center") + 1] == "90,90"
  ```

- Tests written before this rule are being migrated (see `ROADMAP.md`). When you touch an old test for any reason, convert it to this shape in the same change.

## Practicalities

- Run the suite with `uv run pytest`. It must pass before committing.
- Unit-test pure logic (parsing, validation) with inline samples; no PrusaSlicer needed. Example: `tests/test_gcode.py`.
- Integration tests that run the real binary go in `tests/test_server.py` and use the `prusaslicer` fixture, which **skips** when PrusaSlicer is not installed. They must never fail just because it is missing.
- Use `tmp_path` / the `cube_stl` fixture for files. Do not commit models, `.gcode`, or `.bgcode` files, and do not write into the repo tree or the user's PrusaSlicer data directory.
- Reset module state that tests touch (`server._config`) in a fixture, as `test_server.py` does.
- When a change touches the stdio protocol surface (tool names, schemas), also verify with a real MCP client over stdio, not only by calling the Python functions.
