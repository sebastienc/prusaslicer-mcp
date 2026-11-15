"""Unit tests for summarising a dogfood sweep (synthetic result rows; no PrusaSlicer needed)."""

import json

import numpy as np
import pytest
from dogfood import report
from PIL import Image

from prusaslicer_mcp.preview_gcode import INK
from prusaslicer_mcp.preview_model import BACKGROUND


def inspect_row(i, path="a.stl", size=(20, 20, 30), watertight=True, parts=1, fits=True, warnings=(), project=None):
    return {
        "id": i, "path": path, "size_mb": 1.0, "step": "inspect", "ok": True, "seconds": 1.0,
        "triangles": 12, "size": list(size), "watertight": watertight, "parts": parts, "fits": fits,
        "warnings": list(warnings), "project": project,
    }  # fmt: skip


def orientation_row(i, path="a.stl", best_is_stored=True, stored_stable=True, any_stable=True, skipped=None):
    if skipped:
        return {
            "id": i,
            "path": path,
            "size_mb": 1.0,
            "step": "orientation",
            "ok": True,
            "seconds": 0.1,
            "skipped": skipped,
        }
    return {
        "id": i, "path": path, "size_mb": 1.0, "step": "orientation", "ok": True, "seconds": 0.5,
        "best_is_stored": best_is_stored, "stored_rank": 1 if best_is_stored else 3, "stored_stable": stored_stable,
        "any_stable": any_stable, "best": {"rotate_x": 0.0, "rotate_y": 0.0, "height_mm": 10.0, "base_share": 0.5,
                                           "overhang_share": 0.0}, "warnings": [],
    }  # fmt: skip


def slice_row(i, path="a.stl", height=30.0, warnings=(), seconds=3.0, **extra):
    return {
        "id": i, "path": path, "size_mb": 1.0, "step": "slice", "ok": True, "seconds": seconds,
        "settings_from": "profiles", "centered": False, "estimated_time": "1h", "grams": 5.0, "layers": 150,
        "warnings": list(warnings), "printed_height": height, **extra,
    }  # fmt: skip


def failed(i, step, path="a.stl", **fields):
    return {"id": i, "path": path, "size_mb": 1.0, "step": step, "ok": False, "seconds": 1.0, **fields}


def test_a_row_is_classified_by_how_its_step_ended():
    # Given rows for a success, a refusal, a timeout and a crash
    rows = [
        slice_row(0),
        failed(1, "slice", error="Slicing failed (exit 0): All objects are outside of the print volume."),
        failed(2, "slice", timeout=900),
        failed(3, "slice", crash="RuntimeError: boom"),
    ]

    # When each is classified
    statuses = [report.status(row) for row in rows]

    # Then only a missing result is a refusal; a timeout and a crash are bugs worth telling apart
    assert statuses == ["ok", "refused", "timeout", "crash"]


def test_outcomes_are_counted_per_step():
    # Given two inspections and three slices, one of which was refused
    rows = [inspect_row(0), inspect_row(1), slice_row(0), slice_row(1), failed(2, "slice", error="x")]

    # When the outcomes are counted
    counts = report.outcome_counts(rows)

    # Then each (step, outcome) pair has its count
    assert counts[("inspect", "ok")] == 2
    assert counts[("slice", "ok")] == 2
    assert counts[("slice", "refused")] == 1


def test_refusals_list_the_file_and_the_first_line_of_the_reason():
    # Given a refused slice whose message runs over several lines, and a failed preview that is not a slice
    rows = [
        failed(0, "slice", path="big.stl", error="Slicing failed (exit 0): Too big.\nObject name: big.stl"),
        failed(1, "preview_model", path="odd.stl", error="Could not read it"),
    ]

    # When the refusals are listed
    listed = report.refusals(rows)

    # Then only the slice refusal is there, with just the first line of its reason
    assert listed == [("big.stl", "Slicing failed (exit 0): Too big.")]


def test_warnings_are_grouped_ignoring_the_numbers_in_them():
    # Given the same kind of warning on two files with different numbers, and a different one
    rows = [
        slice_row(0, path="a.stl", warnings=["Empty layer between 0.4 and 9."]),
        slice_row(1, path="b.stl", warnings=["Empty layer between 1.2 and 20."]),
        slice_row(2, path="c.stl", warnings=["Floating bridge anchors"]),
        slice_row(3, path="d.stl"),
    ]

    # When they are grouped
    groups = report.warning_groups(rows)

    # Then the two similar ones count together, with the first file as the example
    assert groups["Empty layer between N and N."] == (2, "a.stl")
    assert groups["Floating bridge anchors"] == (1, "c.stl")


def test_timings_give_the_median_the_90th_percentile_and_the_maximum_per_step():
    # Given ten slices taking 1 to 10 seconds
    rows = [slice_row(i, seconds=float(i + 1)) for i in range(10)]

    # When the timings are computed
    median, p90, longest = report.timing_stats(rows)["slice"]

    # Then they describe the spread
    assert (median, p90, longest) == (5.5, 10.0, 10.0)


def test_inspection_findings_are_counted():
    # Given six inspected files covering each finding
    rows = [
        inspect_row(0, watertight=False),
        inspect_row(1, parts=3),
        inspect_row(2, fits=False),
        inspect_row(3, path="x.3mf", warnings=["Stored position is off the bed (x 1..2)."]),
        inspect_row(4, project={"printer_profile": "P"}),
        inspect_row(5),
    ]

    # When the findings are counted
    counts = report.inspect_counts(rows)

    # Then each is reported
    assert counts == {"not watertight": 1, "more than one part": 1, "larger than the bed": 1, "3MF stored off the bed": 1,
                      "PrusaSlicer project": 1}  # fmt: skip


@pytest.mark.parametrize(
    ("printed", "flagged"), [(30.0, False), (29.0, False), (33.0, False), (20.0, True), (60.0, True)]
)
def test_a_printed_height_far_from_the_models_height_is_flagged(printed, flagged):
    # Given a model 30 mm tall that printed to some height
    rows = [inspect_row(0, size=(20, 20, 30)), slice_row(0, height=printed)]

    # When heights are compared
    mismatches = report.height_mismatches(rows)

    # Then only a big difference is flagged
    assert bool(mismatches) is flagged


def test_height_comparison_skips_files_it_cannot_judge():
    # Given a slice with no printed height, a flat model of zero height, and a refused slice
    rows = [
        inspect_row(0), {**slice_row(0), "printed_height": None},
        inspect_row(1, size=(20, 20, 0)), slice_row(1, height=0.2),
        inspect_row(2), failed(2, "slice", error="x"),
    ]  # fmt: skip

    # When heights are compared
    mismatches = report.height_mismatches(rows)

    # Then nothing is claimed about them
    assert mismatches == []


def test_the_emptiest_pictures_are_found(tmp_path):
    # Given three model sheets, one nearly empty, and three silhouettes, one with almost no ink
    def sheet(folder, filled):
        pixels = np.empty((100, 100, 3), np.uint8)
        pixels[:] = BACKGROUND
        pixels[:filled, :] = (10, 10, 10)
        folder.mkdir()
        Image.fromarray(pixels).save(folder / "model.png")

    def silhouette(folder, ink_pixels):
        pixels = np.empty((100, 100, 3), np.uint8)
        pixels[:] = (250, 250, 250)
        pixels.reshape(-1, 3)[:ink_pixels] = INK
        Image.fromarray(pixels).save(folder / "print.png")

    for i, (filled, ink) in enumerate([(50, 4000), (2, 5), (30, 900)]):
        folder = tmp_path / f"{i:03d}"
        sheet(folder, filled)
        silhouette(folder, ink)
    rows = [inspect_row(i, path=f"f{i}.stl") for i in range(3)]

    # When the outliers are found
    outliers = report.image_outliers(tmp_path, rows, count=1)

    # Then the emptiest sheet and the faintest silhouette are named
    assert outliers["emptiest model sheets"][0][0] == "f1.stl"
    assert outliers["least ink in print silhouettes"][0][0] == "f1.stl"


def test_the_summary_leads_with_whether_anything_crashed_or_timed_out(tmp_path):
    # Given a clean sweep and one with a crash
    clean = [inspect_row(0), slice_row(0)]
    crashing = [*clean, failed(1, "slice", crash="RuntimeError: boom")]

    # When both are summarised
    good = report.summarize(clean, tmp_path)
    bad = report.summarize(crashing, tmp_path)

    # Then the first line says which it is
    assert good.splitlines()[0].startswith("1 file")
    assert "no crashes or timeouts" in good
    assert "1 crash" in bad


def test_the_summary_names_each_section(tmp_path):
    # Given a small sweep with a refusal and a warning
    rows = [
        inspect_row(0), slice_row(0, warnings=["print warning: Empty layer between 0.4 and 9."]),
        inspect_row(1), failed(1, "slice", error="Slicing failed (exit 0): Off the bed."),
    ]  # fmt: skip

    # When it is summarised
    text = report.summarize(rows, tmp_path)

    # Then every section a reader looks for is present
    for heading in ("steps", "refused", "warnings", "time per step", "inspect_model findings"):
        assert heading in text
    assert "Off the bed." in text
    assert "Empty layer between N and N." in text


def test_results_round_trip_through_the_file(tmp_path):
    # Given rows written one JSON object per line
    rows = [inspect_row(0), slice_row(0)]
    path = tmp_path / "results.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")

    # When they are loaded
    loaded = report.load_rows(path)

    # Then they come back unchanged
    assert loaded == rows


def test_orientation_findings_are_counted_and_projects_are_left_out():
    # Given four files: one best as stored, one whose as-stored orientation is not the best, one that rests on
    # no real base in any orientation, and a project (which the tool does not score)
    rows = [
        orientation_row(0),
        orientation_row(1, best_is_stored=False, stored_stable=False),
        orientation_row(2, best_is_stored=False, stored_stable=False, any_stable=False),
        orientation_row(3, skipped="PrusaSlicer project"),
    ]

    # When the findings are counted
    counts = report.orientation_counts(rows)

    # Then each file is counted once under what it shows, and the project is only counted as skipped
    assert counts == {
        "scored": 3,
        "as stored is not the best orientation": 2,
        "as stored rests on no real base": 2,
        "no orientation has a real base": 1,
        "skipped (PrusaSlicer projects)": 1,
    }


def test_the_summary_lists_the_orientation_step_and_its_findings():
    # Given rows for one scored file
    rows = [inspect_row(0), orientation_row(0, best_is_stored=False, stored_stable=False), slice_row(0)]

    # When the sweep is summarised
    text = report.summarize(rows)

    # Then the step has its own line and the findings have a section
    assert "orientation" in text.split("steps (outcome: count):")[1].split("refused slices")[0]
    assert "suggest_orientation findings" in text
    assert "as stored is not the best orientation" in text


def test_an_orientation_step_that_failed_is_not_counted_as_scored_and_does_not_break_the_report():
    # Given one scored file and one whose orientation step crashed
    rows = [orientation_row(0), failed(1, "orientation", crash="RuntimeError: boom")]

    # When the findings are counted
    counts = report.orientation_counts(rows)

    # Then only the scored file counts (the crash is reported by the step outcomes, not here)
    assert counts["scored"] == 1
