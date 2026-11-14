"""Thin async wrapper around the PrusaSlicer command line."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from .config import Config


@dataclass
class CliResult:
    returncode: int
    stdout: str
    stderr: str


class CliTimeout(RuntimeError):
    pass


async def run(config: Config, args: list[str], timeout: float | None = None) -> CliResult:
    """Run PrusaSlicer with *args* (no shell). Always passes --datadir if one is configured."""
    full = [str(config.executable)]
    if config.datadir is not None:
        full += ["--datadir", str(config.datadir)]
    full += args

    proc = await asyncio.create_subprocess_exec(
        *full,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout or config.timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise CliTimeout(f"PrusaSlicer did not finish within {timeout or config.timeout:.0f}s") from None
    return CliResult(proc.returncode or 0, out.decode(errors="replace"), err.decode(errors="replace"))
