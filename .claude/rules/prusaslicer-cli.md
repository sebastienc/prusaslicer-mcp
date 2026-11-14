---
paths:
  - "src/prusaslicer_mcp/cli.py"
  - "src/prusaslicer_mcp/config.py"
  - "src/prusaslicer_mcp/gcode.py"
  - "src/prusaslicer_mcp/server.py"
---

# Talking to PrusaSlicer

This project wraps the **PrusaSlicer 2.9.x command line** and nothing else (see ADR 0002). It does not control the GUI and must work while the GUI is running.

- All invocations go through `cli.run()`. It uses `asyncio.create_subprocess_exec` with an argument list. **Never use a shell**, `shell=True`, or string-built commands.
- Never interpolate user input into a flag name. Setting overrides are validated against `^[a-z][a-z0-9_]*$` and passed as a single `--key=value` argument.
- Profile flags beat a project 3MF's embedded settings (ADR 0007). For a PrusaSlicer project with no profiles given, do not pass them, so the project's saved settings apply. Never mix some profile flags with the project's.
- Always slice with `--binary-gcode=0`. Binary G-code (`.bgcode`, magic `GCDE`) cannot be parsed for statistics (ADR 0005).
- `--query-*` actions exit with status **1 even on success** in 2.9.7. Judge them by the output file (exists, non-empty, valid JSON), never by exit code.
- Read-only discovery must not modify the user's PrusaSlicer data directory. Do not use `--save` or other options that write into it. Generated files go to the configured output directory or a temp dir.
- Executable and data-directory lookup lives in `config.py` only. Do not hard-code install paths elsewhere. Respect `PRUSASLICER_PATH` / `PRUSASLICER_DATADIR` first.
- G-code statistics come from comments PrusaSlicer writes in the footer. If a new stat is needed, extend `gcode.py` and add a case to `tests/test_gcode.py` with a realistic sample.
- Anything specific to PrusaSlicer **3.x** (Lua plugins, new CLI layout) is out of scope until a new ADR says otherwise.
