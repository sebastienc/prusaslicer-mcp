"""Unit tests for the PrusaSlicer subprocess wrapper (real subprocesses, fake executables).

Each test writes a tiny shell script and uses it as "PrusaSlicer", so process handling is exercised
for real without needing PrusaSlicer installed.
"""

import os
import time

import pytest

from prusaslicer_mcp import cli
from prusaslicer_mcp.config import Config


@pytest.fixture
def fake_slicer(tmp_path):
    """Factory: write a shell script and return a Config that runs it as the PrusaSlicer executable."""

    def make(body: str, *, datadir=None, timeout: float = 5.0) -> Config:
        script = tmp_path / "PrusaSlicer"
        script.write_text(f"#!/bin/sh\n{body}\n")
        script.chmod(0o755)
        return Config(executable=script, datadir=datadir, output_dir=tmp_path / "out", timeout=timeout)

    return make


@pytest.fixture
def argv_file(tmp_path):
    return tmp_path / "argv.txt"


def recorded_argv(argv_file) -> list[str]:
    return argv_file.read_text().splitlines()


RECORD_ARGV = 'printf "%s\\n" "$@" > "{}"'


async def test_exit_code_and_both_output_streams_are_returned(fake_slicer):
    # Given an executable that writes to stdout and stderr and exits with status 3
    config = fake_slicer("echo to-stdout; echo to-stderr >&2; exit 3")

    # When it is run
    result = await cli.run(config, [])

    # Then all three come back
    assert result == cli.CliResult(returncode=3, stdout="to-stdout\n", stderr="to-stderr\n")


async def test_arguments_reach_the_executable_verbatim_without_a_shell(fake_slicer, argv_file):
    # Given arguments full of characters a shell would interpret
    config = fake_slicer(RECORD_ARGV.format(argv_file))
    args = ["--print-profile", "0.20mm SPEED; echo hacked", "$(whoami)", "*", "it's"]

    # When it is run
    await cli.run(config, args)

    # Then the executable receives exactly those arguments, unexpanded
    assert recorded_argv(argv_file) == args


async def test_datadir_is_passed_first_when_configured(fake_slicer, argv_file, tmp_path):
    # Given a configured data directory
    config = fake_slicer(RECORD_ARGV.format(argv_file), datadir=tmp_path / "data dir")

    # When a command is run
    await cli.run(config, ["--export-gcode"])

    # Then --datadir comes before the command's own arguments
    assert recorded_argv(argv_file) == ["--datadir", str(tmp_path / "data dir"), "--export-gcode"]


async def test_no_datadir_flag_when_none_is_configured(fake_slicer, argv_file):
    # Given no data directory
    config = fake_slicer(RECORD_ARGV.format(argv_file), datadir=None)

    # When a command is run
    await cli.run(config, ["--export-gcode"])

    # Then only the command's own arguments are passed
    assert recorded_argv(argv_file) == ["--export-gcode"]


@pytest.fixture
def open_stdin():
    """Make this process's stdin an open pipe nobody writes to, like the MCP transport on stdio."""
    reader, writer = os.pipe()
    saved = os.dup(0)
    os.dup2(reader, 0)
    yield
    os.dup2(saved, 0)
    for fd in (reader, writer, saved):
        os.close(fd)


async def test_executable_cannot_read_the_servers_own_stdin(fake_slicer, open_stdin):
    # Given the server's stdin is live (it carries the MCP protocol), and an executable that reads stdin to its end
    config = fake_slicer("cat; echo finished", timeout=3)

    # When it is run
    result = await cli.run(config, [])

    # Then it sees end-of-file at once instead of blocking on, or consuming, the server's stdin
    assert result.stdout == "finished\n"


async def test_undecodable_output_is_replaced_not_fatal(fake_slicer):
    # Given an executable that prints a byte that is not valid UTF-8
    config = fake_slicer(r"printf 'bad\377byte'")

    # When it is run
    result = await cli.run(config, [])

    # Then the byte is replaced and the rest of the text survives
    assert result.stdout == "bad�byte"


async def test_slow_executable_is_killed_and_reported_as_a_timeout(fake_slicer, tmp_path):
    # Given an executable that records its process id and then would run for 30 seconds
    pid_file = tmp_path / "pid"
    config = fake_slicer(f'echo $$ > "{pid_file}"; exec sleep 30', timeout=1)
    started = time.monotonic()

    # When it is run with a 1 second timeout
    with pytest.raises(cli.CliTimeout, match="did not finish within 1s"):
        await cli.run(config, [])

    # Then it fails after about a second, and the process is really gone
    assert time.monotonic() - started < 10
    with pytest.raises(ProcessLookupError):
        os.kill(int(pid_file.read_text()), 0)


async def test_explicit_timeout_overrides_the_configured_one(fake_slicer):
    # Given a configured timeout of 30 seconds and an executable that never finishes on its own
    config = fake_slicer("exec sleep 30", timeout=30)
    started = time.monotonic()

    # When it is run with an explicit 1 second timeout
    with pytest.raises(cli.CliTimeout) as error:
        await cli.run(config, [], timeout=1)

    # Then it gives up after about a second, not after the configured 30
    assert "within 1s" in str(error.value)
    assert time.monotonic() - started < 10
