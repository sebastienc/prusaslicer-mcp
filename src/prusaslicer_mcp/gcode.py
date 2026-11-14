"""Parse slicing statistics from PrusaSlicer's text G-code."""

from __future__ import annotations

import re
from pathlib import Path

from pydantic import BaseModel

_TAIL_BYTES = 512 * 1024  # statistics live in the footer, before the config dump


class GcodeStats(BaseModel):
    estimated_time: str | None = None
    estimated_time_seconds: int | None = None
    filament_used_mm: float | None = None
    filament_used_cm3: float | None = None
    filament_used_g: float | None = None
    filament_cost: float | None = None
    layer_count: int | None = None


def _seconds(text: str) -> int:
    total = 0
    for value, unit in re.findall(r"(\d+)\s*([dhms])", text):
        total += int(value) * {"d": 86400, "h": 3600, "m": 60, "s": 1}[unit]
    return total


def _float(pattern: str, text: str) -> float | None:
    m = re.search(pattern, text, re.MULTILINE)
    return float(m.group(1)) if m else None


def parse_gcode_stats(path: Path) -> GcodeStats:
    if path.read_bytes()[:4] == b"GCDE":
        raise ValueError("Binary G-code (.bgcode) cannot be parsed; slice with binary G-code disabled.")

    with path.open("rb") as f:
        f.seek(0, 2)
        f.seek(max(0, f.tell() - _TAIL_BYTES))
        tail = f.read().decode(errors="replace")

    time_m = re.search(r"^; estimated printing time \(normal mode\) = (.+)$", tail, re.MULTILINE)
    layers = 0
    with path.open("rb") as f:
        for line in f:
            if line.startswith(b";LAYER_CHANGE"):
                layers += 1

    return GcodeStats(
        estimated_time=time_m.group(1).strip() if time_m else None,
        estimated_time_seconds=_seconds(time_m.group(1)) if time_m else None,
        filament_used_mm=_float(r"^; filament used \[mm\] = ([\d.]+)", tail),
        filament_used_cm3=_float(r"^; filament used \[cm3\] = ([\d.]+)", tail),
        filament_used_g=_float(r"^; total filament used \[g\] = ([\d.]+)", tail),
        filament_cost=_float(r"^; total filament cost = ([\d.]+)", tail),
        layer_count=layers or None,
    )
