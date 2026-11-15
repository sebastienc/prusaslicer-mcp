"""The dogfood sweep: finding model files (unit) and running it end to end (needs a real PrusaSlicer)."""

import json

import pytest
import trimesh
from conftest import PROJECT_CONFIG
from dogfood import sweep


def touch(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x")
    return path


def test_every_supported_model_type_is_found_whatever_its_case(tmp_path):
    # Given one file of each supported type and some that are not models
    for name in ("a.stl", "b.3MF", "c.obj", "d.step", "e.stp", "f.amf", "notes.txt", "print.gcode", "readme.md"):
        touch(tmp_path / name)

    # When the folder is searched
    found = [p.name for p in sweep.discover(tmp_path)]

    # Then exactly the model files are returned, in order
    assert found == ["a.stl", "b.3MF", "c.obj", "d.step", "e.stp", "f.amf"]


def test_files_are_found_in_subfolders_but_not_in_hidden_ones(tmp_path):
    # Given models in a sub-folder and in hidden folders, including a hidden folder that holds the whole library
    touch(tmp_path / "pots" / "pot.stl")
    touch(tmp_path / ".git" / "hidden.stl")
    touch(tmp_path / "pots" / ".cache" / "also-hidden.stl")

    # When the folder is searched
    found = [p.relative_to(tmp_path).as_posix() for p in sweep.discover(tmp_path)]

    # Then hidden folders are skipped
    assert found == ["pots/pot.stl"]


def test_a_library_inside_a_hidden_folder_is_still_searched(tmp_path):
    # Given a library that lives under a hidden folder, as cloud-synced folders sometimes do
    library = tmp_path / ".hidden-parent" / "models"
    touch(library / "a.stl")

    # When that library is searched
    found = [p.name for p in sweep.discover(library)]

    # Then only folders inside it count as hidden, not the ones above it
    assert found == ["a.stl"]


def test_a_match_text_narrows_the_search_and_a_limit_caps_it(tmp_path):
    # Given five models, three with "pot" in their path
    for name in ("pot-1.stl", "pot-2.stl", "pot-3.stl", "vase.stl", "key.stl"):
        touch(tmp_path / name)

    # When the search is narrowed and capped
    matched = [p.name for p in sweep.discover(tmp_path, match="POT")]
    capped = [p.name for p in sweep.discover(tmp_path, match="pot", limit=2)]

    # Then matching ignores case, and the limit keeps the first ones
    assert matched == ["pot-1.stl", "pot-2.stl", "pot-3.stl"]
    assert capped == ["pot-1.stl", "pot-2.stl"]


def test_an_empty_folder_is_reported_not_swept(tmp_path, capsys):
    # Given a folder with no models in it

    # When the sweep is asked to run over it
    code = sweep.main(["run", str(tmp_path), "--out", str(tmp_path / "out")])

    # Then it says so and fails, instead of reporting an empty success
    assert code == 2
    assert "no model files" in capsys.readouterr().err


def test_a_folder_that_does_not_exist_is_reported(tmp_path, capsys):
    # Given a path that does not exist

    # When the sweep is asked to run over it
    code = sweep.main(["run", str(tmp_path / "missing"), "--out", str(tmp_path / "out")])

    # Then it says so and fails
    assert code == 2
    assert "not a folder" in capsys.readouterr().err


def test_running_the_sweep_over_real_models_records_every_step(tmp_path, capsys, prusaslicer, make_3mf):
    # Given a folder with an STL, a plain 3MF modelled around the origin, and a PrusaSlicer project
    library = tmp_path / "library"
    library.mkdir()
    trimesh.creation.box(extents=(20, 20, 20)).export(library / "cube.stl")
    make_3mf(name="plain.3mf", at=(0.0, 0.0, 10.0)).rename(library / "plain.3mf")
    make_3mf(name="project.3mf", config=PROJECT_CONFIG).rename(library / "project.3mf")
    out = tmp_path / "out"

    # When the sweep is run over it
    code = sweep.main(["run", str(library), "--out", str(out), "--workers", "1"])

    # Then all three steps of all three files succeeded, with their pictures, and nothing crashed
    assert code == 0
    rows = [json.loads(line) for line in (out / "results.jsonl").read_text().splitlines()]
    assert len(rows) == 9
    assert all(row["ok"] for row in rows), [r for r in rows if not r["ok"]]
    assert sorted(p.name for p in out.glob("*/model.png")) == ["model.png"] * 3
    assert sorted(p.name for p in out.glob("*/print.png")) == ["print.png"] * 3
    assert not list(out.glob("*/*.gcode")), "the G-code is deleted after use to save disk"
    summary = capsys.readouterr().out
    assert "3 files" in summary
    assert "no crashes or timeouts" in summary


def test_the_sweep_uses_a_projects_own_settings_and_centres_a_plain_3mf(tmp_path, prusaslicer, make_3mf):
    # Given a plain 3MF around the origin and a project
    library = tmp_path / "library"
    library.mkdir()
    make_3mf(name="plain.3mf", at=(0.0, 0.0, 10.0)).rename(library / "plain.3mf")
    make_3mf(name="project.3mf", config=PROJECT_CONFIG).rename(library / "project.3mf")
    out = tmp_path / "out"

    # When the sweep is run over it
    sweep.main(["run", str(library), "--out", str(out), "--workers", "1"])

    # Then the project was sliced with its own settings and the plain 3MF was centred for it
    slices = {json.loads(line)["path"]: json.loads(line) for line in (out / "results.jsonl").read_text().splitlines()
              if json.loads(line)["step"] == "slice"}  # fmt: skip
    assert slices["project.3mf"]["settings_from"] == "project"
    assert slices["plain.3mf"]["settings_from"] == "profiles"
    assert slices["plain.3mf"]["centered"] is True


@pytest.fixture
def fake_sweep(tmp_path, monkeypatch):
    """A sweep that does no real work: the caller chooses the rows it 'produced'."""
    from dogfood import steps

    async def choose(*_):
        return steps.Setup("Printer", "Print", "Filament", 180, 180, 180)

    produced: list[dict] = []
    monkeypatch.setattr(sweep.steps, "choose_setup", choose)
    monkeypatch.setattr(sweep, "run_sweep", lambda root, files, out, setup, workers: produced)
    library = tmp_path / "library"
    touch(library / "a.stl")
    return produced, library, tmp_path / "out"


def row(step, **fields):
    return {"id": 0, "path": "a.stl", "size_mb": 1.0, "step": step, "seconds": 1.0, **fields}


@pytest.mark.parametrize(
    ("fields", "expected"),
    [
        ({"crash": "RuntimeError: boom"}, 1),
        ({"timeout": 900}, 1),
        ({"error": "Slicing failed (exit 0): Off the bed."}, 0),
    ],
    ids=["crash", "timeout", "refusal"],
)
def test_the_sweep_fails_for_crashes_and_timeouts_but_not_for_refusals(fake_sweep, fields, expected):
    # Given a sweep whose slice step ended in a crash, a timeout, or an ordinary refusal
    produced, library, out = fake_sweep
    produced.append(row("slice", ok=False, **fields))

    # When the sweep is run
    code = sweep.main(["run", str(library), "--out", str(out)])

    # Then only a crash or a timeout (a bug in the server) makes it fail; a refusal is a legitimate answer
    assert code == expected
