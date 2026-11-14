"""Read the settings PrusaSlicer stores inside a project 3MF."""

from __future__ import annotations

import re
import zipfile
from pathlib import Path

from pydantic import BaseModel

_CONFIG_ENTRY = "Metadata/Slic3r_PE.config"
_LINE = re.compile(r"^; ([a-z0-9_]+) = (.*)$")

# The settings that most change what a print looks like, so a caller can see what a project customises.
KEY_SETTINGS = (
    "layer_height",
    "perimeters",
    "fill_density",
    "fill_pattern",
    "top_solid_layers",
    "bottom_solid_layers",
    "brim_width",
    "support_material",
    "support_material_auto",
)


class ProjectInfo(BaseModel):
    printer_profile: str | None = None
    print_profile: str | None = None
    material_profile: str | None = None
    settings: dict[str, str] = {}


def _unquote_all(value: str) -> str:
    """`"A";"B"` (one name per extruder) becomes `A; B`; an unquoted value is returned as is."""
    return "; ".join(part.strip().strip('"') for part in value.split(";")) if value.startswith('"') else value


def read_project(path: Path) -> ProjectInfo | None:
    """Return the settings stored in a 3MF saved from PrusaSlicer, or None if it is not such a project."""
    if path.suffix.lower() != ".3mf":
        return None
    try:
        with zipfile.ZipFile(path) as archive:
            text = archive.read(_CONFIG_ENTRY).decode(errors="replace")
    except (zipfile.BadZipFile, KeyError):
        return None

    values: dict[str, str] = {}
    for line in text.splitlines():
        match = _LINE.match(line)
        if match:
            values[match.group(1)] = match.group(2).strip()

    return ProjectInfo(
        printer_profile=values.get("printer_settings_id"),
        print_profile=values.get("print_settings_id"),
        material_profile=_unquote_all(values["filament_settings_id"]) if "filament_settings_id" in values else None,
        settings={key: values[key] for key in KEY_SETTINGS if key in values},
    )
