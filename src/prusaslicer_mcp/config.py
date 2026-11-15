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
_WIN_GUI = "prusa-slicer.exe"  # the GUI build: on Windows it writes nothing to stdout, so a tool cannot use it
_WIN_CONSOLE = "prusa-slicer-console.exe"
_PATH_NAMES = ["prusa-slicer", "PrusaSlicer", "prusa-slicer-console"]


class ConfigError(RuntimeError):
    """The environment configures the server in a way it cannot use."""


class PrusaSlicerNotFound(ConfigError):
    pass


@dataclass(frozen=True)
class Config:
    executable: Path
    datadir: Path | None
    output_dir: Path
    timeout: float


def _is_executable(p: Path) -> bool:
    return p.is_file() and os.access(p, os.X_OK)


def _windows_globs() -> list[str]:
    """Where the Windows installer puts PrusaSlicer, from the environment rather than a hardcoded C: drive."""
    patterns: list[str] = []
    roots = (os.environ.get(name) for name in ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)"))
    for root in dict.fromkeys(r for r in roots if r):  # the first two are usually the same folder
        base = glob.escape(root)
        patterns += [
            os.path.join(base, "Prusa3D", "PrusaSlicer*", _WIN_CONSOLE),
            os.path.join(base, "PrusaSlicer*", _WIN_CONSOLE),
        ]
    local = os.environ.get("LOCALAPPDATA")
    if local:
        patterns.append(os.path.join(glob.escape(local), "Programs", "PrusaSlicer*", _WIN_CONSOLE))
    return patterns


def _prefer_console(p: Path) -> Path:
    """The console build next to a Windows GUI build, whose output (warnings, errors) would otherwise be lost."""
    if p.name.lower() == _WIN_GUI:
        console = p.with_name(_WIN_CONSOLE)
        if _is_executable(console):
            return console
    return p


def find_executable() -> Path:
    """Resolve the PrusaSlicer binary: env override, PATH, then known install locations."""
    env = os.environ.get("PRUSASLICER_PATH")
    if env:
        p = Path(env).expanduser()
        if _is_executable(p):
            return _prefer_console(p)
        raise PrusaSlicerNotFound(f"PRUSASLICER_PATH is set but not an executable file: {p}")

    for name in _PATH_NAMES:
        found = shutil.which(name)
        if found:
            return _prefer_console(Path(found))

    patterns = _MAC_GLOBS if sys.platform == "darwin" else _windows_globs() if sys.platform == "win32" else []
    for pattern in patterns:
        for match in sorted(glob.glob(os.path.expanduser(pattern))):
            if _is_executable(Path(match)):
                return Path(match)

    raise PrusaSlicerNotFound("PrusaSlicer not found. Install it or set PRUSASLICER_PATH to the executable.")


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


def _timeout_from_env() -> float:
    raw = os.environ.get("PRUSASLICER_MCP_TIMEOUT", "600")
    try:
        timeout = float(raw)
    except ValueError:
        timeout = 0.0
    if timeout <= 0:
        raise ConfigError(f"PRUSASLICER_MCP_TIMEOUT must be a positive number of seconds, got {raw!r}")
    return timeout


def load_config() -> Config:
    return Config(
        executable=find_executable(),
        datadir=default_datadir(),
        output_dir=Path(os.environ.get("PRUSASLICER_MCP_OUTPUT_DIR", "output")).expanduser().resolve(),
        timeout=_timeout_from_env(),
    )
