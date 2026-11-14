"""Parse slicing statistics from PrusaSlicer's text G-code."""

from __future__ import annotations

import itertools
import re
import statistics
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


def _seconds(text: str) -> int | None:
    parts = re.findall(r"(\d+)\s*([dhms])", text)
    if not parts:
        return None
    return sum(int(value) * {"d": 86400, "h": 3600, "m": 60, "s": 1}[unit] for value, unit in parts)


def _float(pattern: str, text: str) -> float | None:
    m = re.search(pattern, text, re.MULTILINE)
    return float(m.group(1)) if m else None


def _float_total(pattern: str, text: str) -> float | None:
    """Like _float, but for lines that list one value per extruder ("1292.02, 100.50, 0.00"): the sum."""
    m = re.search(pattern, text, re.MULTILINE)
    return round(sum(float(v) for v in m.group(1).split(",")), 2) if m else None


def parse_gcode_stats(path: Path) -> GcodeStats:
    with path.open("rb") as f:
        magic = f.read(4)
    if magic == b"GCDE":
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
        filament_used_mm=_float_total(r"^; filament used \[mm\] = ([\d.]+(?:,\s*[\d.]+)*)", tail),
        filament_used_cm3=_float_total(r"^; filament used \[cm3\] = ([\d.]+(?:,\s*[\d.]+)*)", tail),
        filament_used_g=_float(r"^; total filament used \[g\] = ([\d.]+)", tail),
        filament_cost=_float(r"^; total filament cost = ([\d.]+)", tail),
        layer_count=layers or None,
    )


# A step between layers counts as a gap when it is more than this many typical layers, and at least this tall in
# absolute terms, so fine layers and variable layer height do not trigger it.
_GAP_LAYERS = 3
_MIN_GAP_MM = 0.6


class LayerGap(BaseModel):
    """A stretch where the print jumps from one layer to a much higher one, so nothing is printed between."""

    from_mm: float
    to_mm: float


def read_layer_heights(path: Path) -> list[float]:
    """The height of every layer, from the `;Z:` comment PrusaSlicer writes after each `;LAYER_CHANGE`."""
    heights: list[float] = []
    with path.open("rb") as f:
        for line in f:
            if line.startswith(b";Z:"):
                try:
                    heights.append(float(line[3:]))
                except ValueError:
                    continue
    return heights


def find_layer_gaps(heights: list[float]) -> list[LayerGap]:
    """Where consecutive layers jump by far more than a layer: the model has holes, or parts that float."""
    if len(heights) < 3:
        return []
    pairs = list(itertools.pairwise(heights))
    steps = [b - a for a, b in pairs]
    upward = [step for step in steps if step > 0]  # printing objects one after another restarts at the bottom
    if not upward:
        return []
    limit = max(_GAP_LAYERS * statistics.median(upward), _MIN_GAP_MM)
    # The tolerance keeps "exactly three layers" from tripping on float noise (3 * 0.3 is 0.8999999999999999).
    return [LayerGap(from_mm=a, to_mm=b) for (a, b), step in zip(pairs, steps, strict=True) if step > limit + 1e-6]


def layer_gap_warning(path: Path) -> str | None:
    """A sentence describing the gaps in a sliced model's layers, or None when there are none."""
    heights = read_layer_heights(path)
    gaps = find_layer_gaps(heights)
    if not gaps:
        return None
    total = sum(gap.to_mm - gap.from_mm for gap in gaps)
    first = gaps[0]
    noun = "gap" if len(gaps) == 1 else "gaps"
    return (
        f"Nothing is printed across {total:.1f} mm of the {max(heights):.1f} mm height ({len(gaps)} {noun}, the first "
        f"between z {first.from_mm:g} and {first.to_mm:g} mm). The model probably has holes or floating parts: "
        "repair the mesh or change its orientation."
    )
