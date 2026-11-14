"""Read what PrusaSlicer prints on stdout while slicing."""

from __future__ import annotations

import re

_PROGRESS = re.compile(r"^\d+ => ")
_EXPORT_DONE = re.compile(r"^Slicing result exported to ")


def parse_warnings(stdout: str) -> list[str]:
    """Return each warning PrusaSlicer printed, one string per warning, lines joined with newlines.

    A warning is a block: a line containing "warning" followed by plain lines (more detail, the object name,
    advice) up to the next numbered progress line or the final export message. Keeping only the first line,
    as an earlier version did, lost most of what PrusaSlicer said.
    """
    blocks: list[list[str]] = []
    current: list[str] | None = None
    for raw in stdout.splitlines():
        line = raw.strip()
        if _PROGRESS.match(line) or _EXPORT_DONE.match(line):
            current = None
        elif "warning" in line.lower():
            current = [line]
            blocks.append(current)
        elif current is not None and line:
            current.append(line)
    return ["\n".join(block) for block in blocks]
