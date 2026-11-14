---
paths:
  - "src/prusaslicer_mcp/server.py"
---

# MCP tool conventions

- The MCP SDK is **2.x**: import `MCPServer` from `mcp.server.mcpserver` (the v1 `FastMCP` import does not exist). Check the installed API before assuming v1 behaviour.
- **Never write to stdout.** The server speaks MCP over stdio; any `print()` corrupts the protocol. Log to stderr (`logging`) only.
- Every tool parameter uses `Annotated[..., Field(description=...)]`. The descriptions are what the model sees; say where valid values come from (e.g. "exact name from `list_profiles`").
- Tool docstrings are the tool descriptions: first sentence says what it does, then anything the caller must know.
- Return **pydantic models** so clients get structured output. Do not return pre-formatted prose or markdown.
- Signal failure by raising **`ToolError`** (`from mcp.server.mcpserver.exceptions import ToolError`) with a message the model can act on. In SDK 2.x only `ToolError` text reaches the client; any other exception (`ValueError`, `RuntimeError`, ...) is treated as a crash and the client sees just `Error executing tool <name>`. Convert expected failures at the boundary (bad input, missing PrusaSlicer, timeouts, slicer errors) and include PrusaSlicer's own message. Do not return `{"error": ...}` payloads. `tests/test_tool_errors.py` checks this through `mcp.call_tool`.
- Mark side-effect-free tools with `annotations=_READ_ONLY`. Tools that write files (`slice_model`) must not carry it.
- Profile names are matched **exactly** by PrusaSlicer. Tools must not guess or fuzzy-match them; point the caller at `list_printers` / `list_profiles`.
- Adding or changing a tool: update the tool table in `README.md` and the tool section in `docs/architecture/README.md` in the same change.
