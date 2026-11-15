"""Run every tool over a folder of models and report what happened (the dogfood sweep, docs/dogfooding.md).

    uv run poe dogfood run <folder> [--out DIR] [--workers N] [--match TEXT] [--limit N]
    uv run poe dogfood report [--out DIR]

Each step of each file runs in its own process with a timeout, so one model that hangs the server cannot stop the
sweep. Results go to <out>/results.jsonl, with the pictures beside them; the G-code is deleted after use.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from dogfood import report, steps

MODEL_SUFFIXES = {".stl", ".3mf", ".obj", ".step", ".stp", ".amf"}
TIMEOUTS = {"inspect": 240, "preview_model": 240, "slice": 900}  # seconds, per step
DEFAULT_OUT = Path("output/dogfood")
_SCRIPTS = Path(__file__).resolve().parents[1]


def discover(root: Path, match: str | None = None, limit: int | None = None) -> list[Path]:
    """The model files under `root`, sorted, skipping hidden folders inside it (those above it do not count)."""
    files = sorted(
        path
        for path in root.rglob("*")
        if path.is_file()
        and path.suffix.lower() in MODEL_SUFFIXES
        and not any(part.startswith(".") for part in path.relative_to(root).parts)
    )
    if match:
        files = [path for path in files if match.lower() in path.relative_to(root).as_posix().lower()]
    return files[:limit] if limit else files


def _step_in_subprocess(step: str, path: Path, out_dir: Path, setup: steps.Setup) -> dict[str, Any]:
    command = [
        sys.executable,
        "-m",
        "dogfood.sweep",
        "step",
        step,
        str(path),
        str(out_dir),
        json.dumps(setup.to_dict()),
    ]
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(filter(None, [str(_SCRIPTS), os.environ.get("PYTHONPATH")]))}
    try:
        done = subprocess.run(command, capture_output=True, text=True, timeout=TIMEOUTS[step], env=env, check=False)
    except subprocess.TimeoutExpired:
        return {"step": step, "ok": False, "timeout": TIMEOUTS[step]}
    lines = [line for line in done.stdout.splitlines() if line.startswith("{")]
    if lines:
        return json.loads(lines[-1])
    last = (done.stderr.strip().splitlines() or ["no output"])[-1]
    return {"step": step, "ok": False, "crash": f"the step process died: {last[:200]}"}


def run_sweep(root: Path, files: list[Path], out: Path, setup: steps.Setup, workers: int) -> list[dict[str, Any]]:
    out.mkdir(parents=True, exist_ok=True)
    results = out / "results.jsonl"
    results.unlink(missing_ok=True)
    (out / "config.json").write_text(json.dumps({"root": str(root), "files": len(files), **setup.to_dict()}, indent=2))
    lock = threading.Lock()
    rows: list[dict[str, Any]] = []

    def work(item: tuple[int, Path]) -> None:
        index, path = item
        for step in steps.STEPS:
            row = _step_in_subprocess(step, path, out / f"{index:03d}", setup)
            row.update(
                id=index, path=path.relative_to(root).as_posix(), size_mb=round(path.stat().st_size / 1048576, 1)
            )
            with lock:
                rows.append(row)
                with results.open("a") as handle:
                    handle.write(json.dumps(row) + "\n")
        with lock:
            print(f"  {len({r['id'] for r in rows if r['step'] == 'slice'})}/{len(files)}  {path.name}", flush=True)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(work, enumerate(files)))
    return rows


def _run(args: argparse.Namespace) -> int:
    root = Path(args.folder).expanduser().resolve()
    if not root.is_dir():
        print(f"{root} is not a folder", file=sys.stderr)
        return 2
    files = discover(root, args.match, args.limit)
    if not files:
        print(f"no model files found under {root}", file=sys.stderr)
        return 2
    setup = asyncio.run(steps.choose_setup(args.printer_profile, args.print_profile, args.material_profile))
    print(
        f"sweeping {len(files)} files with {setup.printer_profile} / {setup.print_profile} / {setup.material_profile}"
    )
    rows = run_sweep(root, files, args.out, setup, args.workers)
    print("\n" + report.summarize(rows, args.out))
    return 1 if any(report.status(row) in ("crash", "timeout") for row in rows) else 0


def _report(args: argparse.Namespace) -> int:
    results = args.out / "results.jsonl"
    if not results.is_file():
        print(f"no results at {results}; run the sweep first", file=sys.stderr)
        return 2
    print(report.summarize(report.load_rows(results), args.out))
    return 0


def _step(args: argparse.Namespace) -> int:
    setup = steps.Setup(**json.loads(args.setup))
    print(json.dumps(steps.run_step(args.step, Path(args.path), setup, Path(args.out_dir))))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="dogfood", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    commands = parser.add_subparsers(dest="command", required=True)

    run = commands.add_parser("run", help="sweep a folder of models, then print the report")
    run.add_argument("folder", help="folder to search for STL, 3MF, OBJ, STEP and AMF files")
    run.add_argument(
        "--out", type=Path, default=DEFAULT_OUT, help=f"where results and pictures go (default {DEFAULT_OUT})"
    )
    run.add_argument("--workers", type=int, default=3, help="files processed at once (default 3)")
    run.add_argument("--match", help="only files whose path contains this text, ignoring case")
    run.add_argument("--limit", type=int, help="only the first N files")
    run.add_argument("--printer-profile", help="printer for non-project models (default: the first installed)")
    run.add_argument("--print-profile", help="print profile (default: the printer's first)")
    run.add_argument("--material-profile", help="filament profile (default: the print profile's first)")
    run.set_defaults(handler=_run)

    summary = commands.add_parser("report", help="print the report for an earlier sweep")
    summary.add_argument("--out", type=Path, default=DEFAULT_OUT)
    summary.set_defaults(handler=_report)

    step = commands.add_parser("step", help=argparse.SUPPRESS)  # internal: one step in its own process
    for name in ("step", "path", "out_dir", "setup"):
        step.add_argument(name)
    step.set_defaults(handler=_step)

    args = parser.parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    sys.exit(main())
