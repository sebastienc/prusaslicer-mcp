"""Summarise the results of a dogfood sweep: what ran, what was refused, what was warned, how long it took."""

from __future__ import annotations

import json
import re
import statistics
from collections import Counter, defaultdict
from typing import TYPE_CHECKING, Any

import numpy as np
from PIL import Image

from prusaslicer_mcp.preview_gcode import INK
from prusaslicer_mcp.preview_model import BACKGROUND, BED_FILL, BED_LINE

if TYPE_CHECKING:
    from pathlib import Path

Row = dict[str, Any]

# A printed height this far from the model's own height means layers are missing, extra, or the model changed shape.
HEIGHT_TOLERANCE = (0.9, 1.1)


def load_rows(path: Path) -> list[Row]:
    """The result rows, one JSON object per line."""
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def status(row: Row) -> str:
    """ok, refused (the tool said no, readably), timeout, or crash (an unexpected failure: a bug in the server)."""
    if row.get("ok"):
        return "ok"
    if "timeout" in row:
        return "timeout"
    if "crash" in row:
        return "crash"
    return "refused"


def outcome_counts(rows: list[Row]) -> Counter[tuple[str, str]]:
    return Counter((row["step"], status(row)) for row in rows)


def refusals(rows: list[Row]) -> list[tuple[str, str]]:
    """Slices the tool refused, as (file, first line of the reason)."""
    return [
        (row["path"], (row.get("error") or "").splitlines()[0] if row.get("error") else "")
        for row in rows
        if row["step"] == "slice" and status(row) == "refused"
    ]


def warning_groups(rows: list[Row]) -> dict[str, tuple[int, str]]:
    """Warnings from successful slices, grouped with their numbers ignored: {text: (count, first file)}."""
    groups: dict[str, tuple[int, str]] = {}
    for row in rows:
        if row["step"] != "slice" or not row.get("ok"):
            continue
        for warning in row.get("warnings", []):
            key = re.sub(r"\d+(?:\.\d+)?", "N", warning.splitlines()[0])[:90]
            count, example = groups.get(key, (0, row["path"]))
            groups[key] = (count + 1, example)
    return dict(sorted(groups.items(), key=lambda item: -item[1][0]))


def timing_stats(rows: list[Row]) -> dict[str, tuple[float, float, float]]:
    """Per step: (median, 90th percentile, maximum) seconds."""
    seconds: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        if "seconds" in row:
            seconds[row["step"]].append(row["seconds"])
    stats = {}
    for step, values in seconds.items():
        ordered = sorted(values)
        stats[step] = (statistics.median(ordered), ordered[min(len(ordered) - 1, int(len(ordered) * 0.9))], ordered[-1])
    return stats


def inspect_counts(rows: list[Row]) -> dict[str, int]:
    """How many inspected files have each notable property."""
    counts = {
        "not watertight": 0,
        "more than one part": 0,
        "larger than the bed": 0,
        "3MF stored off the bed": 0,
        "PrusaSlicer project": 0,
    }
    for row in rows:
        if row["step"] != "inspect" or not row.get("ok"):
            continue
        counts["not watertight"] += not row["watertight"]
        counts["more than one part"] += row["parts"] > 1
        counts["larger than the bed"] += row["fits"] is False
        counts["3MF stored off the bed"] += any("off the bed" in w for w in row.get("warnings", []))
        counts["PrusaSlicer project"] += bool(row.get("project"))
    return counts


def orientation_counts(rows: list[Row]) -> dict[str, int]:
    """What suggest_orientation found: how many scored files, and how many show a problem as stored."""
    scored = [row for row in rows if row["step"] == "orientation" and row.get("ok") and "skipped" not in row]
    return {
        "scored": len(scored),
        "as stored is not the best orientation": sum(not row["best_is_stored"] for row in scored),
        "as stored rests on no real base": sum(not row["stored_stable"] for row in scored),
        "no orientation has a real base": sum(not row["any_stable"] for row in scored),
        "skipped (PrusaSlicer projects)": sum(
            1 for row in rows if row["step"] == "orientation" and row.get("ok") and "skipped" in row
        ),
    }


def height_mismatches(rows: list[Row]) -> list[tuple[str, float]]:
    """Files whose printed height is not about the model's height: (file, printed / model)."""
    inspected = {row["id"]: row for row in rows if row["step"] == "inspect" and row.get("ok")}
    found = []
    for row in rows:
        if row["step"] != "slice" or not row.get("ok") or not row.get("printed_height"):
            continue
        model = inspected.get(row["id"])
        if model is None or model["size"][2] <= 0:
            continue
        ratio = row["printed_height"] / model["size"][2]
        if not HEIGHT_TOLERANCE[0] <= ratio <= HEIGHT_TOLERANCE[1]:
            found.append((row["path"], round(ratio, 2)))
    return found


def image_outliers(out_dir: Path, rows: list[Row], count: int = 3) -> dict[str, list[tuple[str, float]]]:
    """The pictures with the least in them: a blank render usually means something went wrong."""
    path_of = {row["id"]: row["path"] for row in rows}
    fill: list[tuple[str, float]] = []
    ink: list[tuple[str, float]] = []
    for folder in sorted(out_dir.glob("[0-9][0-9][0-9]*")):
        if not folder.is_dir():
            continue
        name = path_of.get(int(folder.name))
        if name is None:
            continue
        if (folder / "model.png").exists():
            pixels = np.asarray(Image.open(folder / "model.png").convert("RGB"))
            empty = np.zeros(pixels.shape[:2], dtype=bool)
            for colour in (BACKGROUND, BED_FILL, BED_LINE):  # the bed is drawn even when the model is not
                empty |= (pixels == np.array(colour, dtype=np.uint8)).all(axis=2)
            fill.append((name, float((~empty).mean())))
        if (folder / "print.png").exists():
            pixels = np.asarray(Image.open(folder / "print.png").convert("RGB"))
            ink.append((name, float((pixels == np.array(INK, dtype=np.uint8)).all(axis=2).sum())))
    return {
        "emptiest model sheets": sorted(fill, key=lambda item: item[1])[:count],
        "least ink in print silhouettes": sorted(ink, key=lambda item: item[1])[:count],
    }


def summarize(rows: list[Row], out_dir: Path | None = None) -> str:
    """A readable report of the whole sweep. The first line says how many files; the verdict says if anything broke."""
    files = len({row["id"] for row in rows})
    counts = outcome_counts(rows)
    broken = sum(n for (_, outcome), n in counts.items() if outcome in ("crash", "timeout"))
    crashes = sum(n for (_, outcome), n in counts.items() if outcome == "crash")
    timeouts = sum(n for (_, outcome), n in counts.items() if outcome == "timeout")
    lines = [f"{files} file{'s' if files != 1 else ''} swept, {len(rows)} steps"]
    lines.append(
        "no crashes or timeouts"
        if not broken
        else f"{crashes} crash{'es' if crashes != 1 else ''} and {timeouts} timeout{'s' if timeouts != 1 else ''}: "
        "these are bugs in the server, look at them first"
    )

    lines += ["", "steps (outcome: count):"]
    for step in ("inspect", "preview_model", "orientation", "slice"):
        parts = [
            f"{outcome} {counts[(step, outcome)]}"
            for outcome in ("ok", "refused", "timeout", "crash")
            if counts[(step, outcome)]
        ]
        lines.append(f"  {step:14} " + ", ".join(parts))
    for row in rows:
        if status(row) in ("crash", "timeout"):
            lines.append(f"  ! {status(row)} in {row['step']}: {row['path']}  {row.get('crash', '')}")

    refused = refusals(rows)
    lines += ["", f"refused slices ({len(refused)}):"]
    lines += [f"  {path}\n      {reason}" for path, reason in refused] or ["  none"]

    groups = warning_groups(rows)
    lines += ["", f"warnings on successful slices ({sum(n for n, _ in groups.values())}):"]
    lines += [f"  {n}x {text}\n      e.g. {example}" for text, (n, example) in groups.items()] or ["  none"]

    lines += ["", "time per step (median / 90th percentile / max, seconds):"]
    lines += [
        f"  {step:14} {median:6.1f} {p90:6.1f} {longest:6.1f}"
        for step, (median, p90, longest) in timing_stats(rows).items()
    ]

    lines += ["", "inspect_model findings:"]
    lines += [f"  {n:4}  {what}" for what, n in inspect_counts(rows).items()]

    lines += ["", "suggest_orientation findings (files scored with close_holes off):"]
    lines += [f"  {n:4}  {what}" for what, n in orientation_counts(rows).items()]

    mismatched = height_mismatches(rows)
    lines += ["", f"printed height far from the model's height ({len(mismatched)}):"]
    lines += [f"  ratio {ratio:4.2f}  {path}" for path, ratio in mismatched] or ["  none"]

    if out_dir is not None:
        lines += ["", "pictures with the least in them:"]
        for title, found in image_outliers(out_dir, rows).items():
            lines.append(f"  {title}:")
            lines += [f"    {value:10.3f}  {path}" for path, value in found] or ["    (no pictures)"]
    return "\n".join(lines)
