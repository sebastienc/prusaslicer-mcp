"""Protocol tests: start the real server as a subprocess and talk to it over stdio like a client does.

These need no PrusaSlicer install. They check what a client actually receives (tool list, schemas,
annotations, error text), which calling the Python functions directly cannot show.
"""

import asyncio
import json
import sys
from contextlib import asynccontextmanager

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

READ_ONLY_TOOLS = {"list_printers", "list_profiles", "inspect_model"}
ALL_TOOLS = READ_ONLY_TOOLS | {"slice_model"}


@asynccontextmanager
async def connected(env: dict[str, str] | None = None):
    """Yield (initialize result, session) for a freshly started server."""
    params = StdioServerParameters(
        command=sys.executable, args=["-c", "from prusaslicer_mcp import main; main()"], env=env
    )
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        yield await session.initialize(), session


@pytest.fixture
async def tools():
    async with connected() as (_, session):
        return {tool.name: tool for tool in (await session.list_tools()).tools}


async def test_the_server_offers_exactly_the_four_tools(tools):
    # Given a freshly started server

    # When a client lists its tools (the fixture)

    # Then these are the tools, no more and no fewer
    assert set(tools) == ALL_TOOLS


async def test_read_only_tools_say_so_to_clients(tools):
    # Given the tools a client received

    # When the discovery and inspection tools are looked at
    hints = {name: tools[name].annotations for name in READ_ONLY_TOOLS}

    # Then each is marked read-only, idempotent and closed-world
    for name, annotations in hints.items():
        assert annotations is not None, name
        assert (annotations.read_only_hint, annotations.idempotent_hint, annotations.open_world_hint) == (
            True,
            True,
            False,
        ), name


async def test_slice_model_is_not_marked_read_only(tools):
    # Given the tools a client received

    # When slice_model is looked at, since it writes a G-code file
    annotations = tools["slice_model"].annotations

    # Then it does not claim to be read-only
    assert annotations is None or annotations.read_only_hint is not True


async def test_every_tool_and_every_parameter_has_a_description(tools):
    # Given the tools a client received

    # When their descriptions are collected
    missing = [t.name for t in tools.values() if not t.description]
    missing += [
        f"{t.name}.{param}"
        for t in tools.values()
        for param, schema in t.input_schema.get("properties", {}).items()
        if not schema.get("description")
    ]

    # Then nothing is undocumented, because the model reads these to decide how to call a tool
    assert missing == []


async def test_slice_model_needs_only_a_model_because_profiles_are_optional_for_projects(tools):
    # Given the tools a client received

    # When slice_model's required parameters are read
    required = tools["slice_model"].input_schema.get("required")

    # Then only the model path is required (ADR 0007)
    assert required == ["model_path"]


async def test_the_server_tells_clients_that_profile_names_must_match_exactly():
    # Given a freshly started server

    # When a client initialises
    async with connected() as (initialized, _):
        # Then the server instructions carry the rule that trips callers up most often
        assert "Profile names must match exactly" in initialized.instructions


async def test_a_failure_reaches_the_client_as_readable_error_text(tmp_path):
    # Given a client asking about a model file that does not exist
    async with connected() as (_, session):
        # When it calls inspect_model
        result = await session.call_tool("inspect_model", {"model_path": str(tmp_path / "nope.stl")})

    # Then the call is flagged as an error and says what was wrong
    assert result.is_error is True
    assert "Model file not found" in result.content[0].text


async def test_a_misconfigured_server_explains_itself_to_the_client(tmp_path):
    # Given a server whose PRUSASLICER_PATH points at nothing
    env = {"PRUSASLICER_PATH": str(tmp_path / "missing")}
    async with connected(env) as (_, session):
        # When a client calls a tool that needs PrusaSlicer
        result = await session.call_tool("list_printers", {})

    # Then the error names the setting to fix
    assert result.is_error is True
    assert "PRUSASLICER_PATH" in result.content[0].text


async def test_a_successful_call_returns_structured_content(cube_stl):
    # Given a valid 20 mm cube
    async with connected() as (_, session):
        # When a client inspects it
        result = await session.call_tool("inspect_model", {"model_path": str(cube_stl)})

    # Then the result is structured data, not formatted prose
    assert result.is_error is False
    assert result.structured_content["size_mm"] == pytest.approx([20, 20, 20])


async def test_stdout_carries_nothing_but_protocol_messages():
    # Given the server's raw standard output, which is the MCP transport: any stray print corrupts it,
    # and the SDK's own client silently skips such lines, so only the raw bytes can show it
    server = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        "from prusaslicer_mcp import main; main()",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    handshake = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "raw-test", "version": "0"},
            },
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    ]

    # When a client performs a handshake and lists the tools, then closes the connection
    stdout, _ = await asyncio.wait_for(
        server.communicate("".join(json.dumps(message) + "\n" for message in handshake).encode()), timeout=30
    )

    # Then every line the server wrote is a JSON-RPC message
    lines = stdout.decode().splitlines()
    assert lines
    for line in lines:
        assert json.loads(line)["jsonrpc"] == "2.0", line
