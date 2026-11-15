"""Unit tests for the PrusaSlicer subprocess wrapper.

Real subprocesses, on every platform, with no fake program files: the Python running the tests plays "PrusaSlicer"
(`python -c <code> <arguments>`), so process handling is exercised for real without PrusaSlicer installed. The
arguments `cli.run` puts in front (--datadir) cannot be given to Python, so those are checked at the one boundary
where they are assembled.
"""

import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from prusaslicer_mcp import cli
from prusaslicer_mcp.config import Config

# After a kill, os.kill(pid, 0) says the process is gone with ProcessLookupError on POSIX and a plain OSError on Windows.
GONE = OSError if sys.platform == "win32" else ProcessLookupError


@pytest.fixture
def python_slicer(tmp_path):
    """A Config whose "PrusaSlicer" is this Python, so `cli.run(config, ["-c", code, ...])` runs `code`."""

    def make(*, datadir=None, timeout: float = 5.0) -> Config:
        return Config(executable=Path(sys.executable), datadir=datadir, output_dir=tmp_path / "out", timeout=timeout)

    return make


def run_code(code: str, *args: str) -> list[str]:
    """The arguments that make the fake PrusaSlicer run `code` (extra arguments land in sys.argv[1:])."""
    return ["-c", code, *args]


async def test_exit_code_and_both_output_streams_are_returned(python_slicer):
    # Given a program that writes to stdout and stderr and exits with status 3
    code = "import sys; print('to-stdout'); print('to-stderr', file=sys.stderr); sys.exit(3)"

    # When it is run
    result = await cli.run(python_slicer(), run_code(code))

    # Then all three come back, with the platform's own line ending normalised by Python's text mode
    assert result.returncode == 3
    assert result.stdout.splitlines() == ["to-stdout"]
    assert result.stderr.splitlines() == ["to-stderr"]


async def test_arguments_reach_the_executable_verbatim_without_a_shell(python_slicer, tmp_path):
    # Given arguments full of characters a shell would interpret
    argv_file = tmp_path / "argv.txt"
    code = "import sys, pathlib; pathlib.Path(sys.argv[1]).write_text(chr(10).join(sys.argv[2:]), encoding='utf-8')"
    args = ["--print-profile", "0.20mm SPEED; echo hacked", "$(whoami)", "*", "it's", "100%", "a&b"]

    # When it is run
    await cli.run(python_slicer(), run_code(code, str(argv_file), *args))

    # Then the program receives exactly those arguments, unexpanded
    assert argv_file.read_text(encoding="utf-8").split("\n") == args


@pytest.fixture
def spawned(monkeypatch):
    """Replace the one place a process is started, and record what it was asked to run."""
    calls: list[tuple[str, ...]] = []

    class FakeProcess:
        returncode = 0

        async def communicate(self):
            return b"", b""

    async def fake_exec(*argv, **_kwargs):
        calls.append(argv)
        return FakeProcess()

    monkeypatch.setattr(cli.asyncio, "create_subprocess_exec", fake_exec)
    return SimpleNamespace(calls=calls)


async def test_datadir_is_passed_first_when_configured(spawned, python_slicer, tmp_path):
    # Given a configured data directory
    config = python_slicer(datadir=tmp_path / "data dir")

    # When a command is run
    await cli.run(config, ["--export-gcode"])

    # Then --datadir comes right after the executable and before the command's own arguments
    assert spawned.calls == [(sys.executable, "--datadir", str(tmp_path / "data dir"), "--export-gcode")]


async def test_no_datadir_flag_when_none_is_configured(spawned, python_slicer):
    # Given no data directory
    config = python_slicer(datadir=None)

    # When a command is run
    await cli.run(config, ["--export-gcode"])

    # Then only the command's own arguments follow the executable
    assert spawned.calls == [(sys.executable, "--export-gcode")]


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


async def test_executable_cannot_read_the_servers_own_stdin(python_slicer, open_stdin):
    # Given the server's stdin is live (it carries the MCP protocol), and a program that reads stdin to its end
    code = "import sys; sys.stdin.read(); print('finished')"

    # When it is run
    result = await cli.run(python_slicer(timeout=10), run_code(code))

    # Then it sees end-of-file at once instead of blocking on, or consuming, the server's stdin
    assert result.stdout.strip() == "finished"


async def test_undecodable_output_is_replaced_not_fatal(python_slicer):
    # Given a program that prints a byte that is not valid UTF-8
    code = "import sys; sys.stdout.buffer.write(b'bad\\xffbyte')"

    # When it is run
    result = await cli.run(python_slicer(), run_code(code))

    # Then the byte is replaced and the rest of the text survives
    assert result.stdout == "bad�byte"


SLEEP_THEN_NOTHING = (
    "import os, sys, time, pathlib; pathlib.Path(sys.argv[1]).write_text(str(os.getpid())); time.sleep(30)"
)


async def test_slow_executable_is_killed_and_reported_as_a_timeout(python_slicer, tmp_path):
    # Given a program that records its process id and then would run for 30 seconds
    pid_file = tmp_path / "pid"
    config = python_slicer(timeout=3)
    started = time.monotonic()

    # When it is run with a short timeout
    with pytest.raises(cli.CliTimeout, match="did not finish within 3s"):
        await cli.run(config, run_code(SLEEP_THEN_NOTHING, str(pid_file)))

    # Then it fails after about that long, and the process is really gone
    assert time.monotonic() - started < 15
    with pytest.raises(GONE):
        os.kill(int(pid_file.read_text()), 0)


async def test_explicit_timeout_overrides_the_configured_one(python_slicer, tmp_path):
    # Given a configured timeout of 60 seconds and a program that never finishes on its own
    config = python_slicer(timeout=60)
    started = time.monotonic()

    # When it is run with an explicit 3 second timeout
    with pytest.raises(cli.CliTimeout) as error:
        await cli.run(config, run_code(SLEEP_THEN_NOTHING, str(tmp_path / "pid")), timeout=3)

    # Then it gives up after about 3 seconds, not after the configured 60
    assert "within 3s" in str(error.value)
    assert time.monotonic() - started < 20
