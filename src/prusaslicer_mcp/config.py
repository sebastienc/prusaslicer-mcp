"""Locate the PrusaSlicer executable and its data directory."""

from __future__ import annotations

import glob
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

_MAC_GLOBS = [
    "/Applications/PrusaSlicer.app/Contents/MacOS/PrusaSlicer",
    "/Applications/*/PrusaSlicer.app/Contents/MacOS/PrusaSlicer",
    "~/Applications/PrusaSlicer.app/Contents/MacOS/PrusaSlicer",
    "~/Applications/*/PrusaSlicer.app/Contents/MacOS/PrusaSlicer",
]
_WIN_GLOBS = [
    r"C:\Program Files\Prusa3D\PrusaSlicer\prusa-slicer-console.exe",
    r"C:\Program Files (x86)\Prusa3D\PrusaSlicer\prusa-slicer-console.exe",
]
_PATH_NAMES = ["prusa-slicer", "PrusaSlicer", "prusa-slicer-console"]


class PrusaSlicerNotFound(RuntimeError):
    pass


@dataclass(frozen=True)
class Config:
    executable: Path
    datadir: Path | None
    output_dir: Path
    timeout: float


def _is_executable(p: Path) -> bool:
    return p.is_file() and os.access(p, os.X_OK)


def find_executable() -> Path:
    """Resolve the PrusaSlicer binary: env override, PATH, then known install locations."""
    env = os.environ.get("PRUSASLICER_PATH")
    if env:
        p = Path(env).expanduser()
        if _is_executable(p):
            return p
        raise PrusaSlicerNotFound(f"PRUSASLICER_PATH is set but not an executable file: {p}")

    for name in _PATH_NAMES:
        found = shutil.which(name)
        if found:
            return Path(found)

    patterns = _MAC_GLOBS if sys.platform == "darwin" else _WIN_GLOBS if sys.platform == "win32" else []
    for pattern in patterns:
        for match in sorted(glob.glob(os.path.expanduser(pattern))):
            if _is_executable(Path(match)):
                return Path(match)

    raise PrusaSlicerNotFound(
        "PrusaSlicer not found. Install it or set PRUSASLICER_PATH to the executable."
    )


def default_datadir() -> Path | None:
    env = os.environ.get("PRUSASLICER_DATADIR")
    if env:
        return Path(env).expanduser()
    if sys.platform == "darwin":
        p = Path.home() / "Library/Application Support/PrusaSlicer"
    elif sys.platform == "win32":
        p = Path(os.environ.get("APPDATA", "")) / "PrusaSlicer"
    else:
        p = Path.home() / ".config/PrusaSlicer"
    return p if p.is_dir() else None


def load_config() -> Config:
    return Config(
        executable=find_executable(),
        datadir=default_datadir(),
        output_dir=Path(os.environ.get("PRUSASLICER_MCP_OUTPUT_DIR", "output")).expanduser().resolve(),
        timeout=float(os.environ.get("PRUSASLICER_MCP_TIMEOUT", "600")),
    )
