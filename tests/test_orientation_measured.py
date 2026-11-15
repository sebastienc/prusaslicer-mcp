"""suggest_orientation with profiles: each option is sliced once with supports and the real numbers are reported.

PrusaSlicer is faked at `--export-gcode`: it writes G-code whose support share depends on the rotation it was given,
so what is under test is the tool's own measuring, ranking and error handling (ADR 0019).
"""

from __future__ import annotations

import math
from pathlib import Path
from types import SimpleNamespace

import pytest
import trimesh
from mcp.server.mcpserver.exceptions import ToolError

from prusaslicer_mcp import cli, server
from prusaslicer_mcp.config import Config
from prusaslicer_mcp.server import Measurement, OrientationOption

PROFILES = {"printer_profile": "Mini", "print_profile": "0.20mm", "material_profile": "PLA"}


def gcode(
    perimeter_mm: float, support_mm: float, grams: float = 10.0, seconds: str = "1h 0m 0s", interface_mm: float = 0.0
) -> str:
    """The G-code of a print with that much perimeter, support and support interface, and PrusaSlicer's footer."""
    return (
        "M83\n;LAYER_CHANGE\n;Z:0.2\n"
        f";TYPE:Perimeter\nG1 X10 Y0 E{perimeter_mm}\n"
        f";TYPE:Support material\nG1 X20 Y0 E{support_mm}\n"
        f";TYPE:Support material interface\nG1 X30 Y0 E{interface_mm}\n"
        f"; filament used [mm] = {perimeter_mm + support_mm + interface_mm}\n; total filament used [g] = {grams}\n"
        f"; estimated printing time (normal mode) = {seconds}\n"
    )


@pytest.fixture
def fake_slicer(tmp_path, monkeypatch):
    """A fake PrusaSlicer. `.support` maps (rotate_x, rotate_y) to the support share of the print; `.refuse` lists
    rotations it refuses. Everything it was asked is in `.calls`."""
    monkeypatch.setattr(
        server,
        "_config",
        Config(executable=tmp_path / "PrusaSlicer", datadir=None, output_dir=tmp_path / "out", timeout=5),
    )
    calls: list[list[str]] = []
    inputs: list[bytes | None] = []
    state = SimpleNamespace(support={}, refuse=set(), default_support=0.0, grams=10.0, interface=0.0, times={})

    def rotation(args: list[str]) -> tuple[float, float]:
        def value(flag: str) -> float:
            return float(args[args.index(flag) + 1]) if flag in args else 0.0

        return value("--rotate-x"), value("--rotate-y")

    async def fake_run(config, args, timeout=None):
        calls.append(args)
        given = Path(args[-1])
        inputs.append(given.read_bytes() if given.is_file() else None)
        turn = rotation(args)
        if turn in state.refuse:
            return cli.CliResult(1, "", "There is an object with no extrusions in the first layer.\nObject name: x")
        share = state.support.get(turn, state.default_support)
        Path(args[args.index("--output") + 1]).write_text(
            gcode(
                100.0 * (1 - share - state.interface),
                100.0 * share,
                state.grams,
                state.times.get(turn, "1h 0m 0s"),
                100.0 * state.interface,
            )
        )
        return cli.CliResult(0, "", "")

    monkeypatch.setattr(cli, "run", fake_run)
    return SimpleNamespace(calls=calls, inputs=inputs, state=state, tmp=tmp_path)


def cube_stl(path: Path) -> Path:
    trimesh.creation.box(extents=(20, 20, 20)).export(path)
    return path


def cone_stl(path: Path, with_base: bool = True, apex_up: bool = True) -> Path:
    mesh = trimesh.creation.cone(radius=20, height=10, sections=48)
    if not with_base:
        mesh = trimesh.Trimesh(mesh.vertices, mesh.faces[mesh.face_normals[:, 2] > -0.99])
    if not apex_up:
        mesh.apply_transform(trimesh.transformations.rotation_matrix(math.pi, [1, 0, 0]))
    mesh.export(path)
    return path


def taken(option: OrientationOption) -> Measurement:
    """What was measured for an option; fails the test if nothing was."""
    assert option.measured is not None
    return option.measured


def support_of(option: OrientationOption) -> float:
    support = taken(option).support_g
    assert support is not None
    return support


def seconds_of(option: OrientationOption) -> int:
    seconds = taken(option).estimated_time_seconds
    assert seconds is not None
    return seconds


async def measured(model: Path, count: int = 5, close_holes: bool = False):
    return await server.suggest_orientation(
        str(model),
        count=count,
        close_holes=close_holes,
        printer_profile=PROFILES["printer_profile"],
        print_profile=PROFILES["print_profile"],
        material_profile=PROFILES["material_profile"],
    )


async def test_each_option_is_sliced_with_supports_and_reports_the_real_numbers(fake_slicer, tmp_path):
    # Given a cube, and a slicer that puts a quarter of one orientation's print into support
    model = cube_stl(tmp_path / "cube.stl")
    fake_slicer.state.support[(0.0, 0.0)] = 0.25
    fake_slicer.state.grams = 8.0

    # When orientations are suggested with profiles
    advice = await measured(model, count=2)

    # Then every option carries what the slice measured, and the as-stored one is a quarter support
    assert all(option.measured is not None for option in advice.options)
    stored = next(option for option in advice.options if option.as_stored)
    assert taken(stored).support_g == pytest.approx(2.0)
    assert taken(stored).filament_g == pytest.approx(8.0)
    assert taken(stored).estimated_time == "1h 0m 0s"
    assert taken(stored).estimated_time_seconds == 3600
    assert taken(stored).refused is None


async def test_the_slices_use_the_profiles_force_supports_on_and_carry_the_rotation(fake_slicer, tmp_path):
    # Given a cone standing apex down, whose best orientation needs a rotation
    model = cone_stl(tmp_path / "cone.stl", apex_up=False)

    # When orientations are suggested with profiles
    advice = await measured(model, count=1)

    # Then every slice names the profiles, turns supports on, and carries its option's rotation
    best = advice.options[0]
    for option, args in zip(advice.options, fake_slicer.calls, strict=True):
        assert args[args.index("--printer-profile") + 1] == "Mini"
        assert "--support-material=1" in args
        assert "--support-material-auto=1" in args
        if option.rotate_x:
            assert float(args[args.index("--rotate-x") + 1]) == pytest.approx(option.rotate_x)
    assert best.rotate_x != 0 or best.rotate_y != 0


async def test_options_are_re_ranked_by_the_support_actually_measured(fake_slicer, tmp_path):
    # Given a cube, where geometry sees every orientation as equal but the slicer finds the as-stored one cheapest
    model = cube_stl(tmp_path / "cube.stl")
    fake_slicer.state.default_support = 0.4
    fake_slicer.state.support[(0.0, 0.0)] = 0.1

    # When orientations are suggested with profiles
    advice = await measured(model, count=3)

    # Then the as-stored option comes first by measurement, ranks are renumbered, and its geometric rank is kept
    assert advice.options[0].as_stored is True
    assert [option.rank for option in advice.options] == list(range(1, len(advice.options) + 1))
    assert advice.options[0].geometry_rank > 1 or advice.options[0].as_stored
    supports = [support_of(option) for option in advice.options]
    assert supports == sorted(supports)


async def test_an_unstable_option_stays_below_stable_ones_however_little_support_it_needs(fake_slicer, tmp_path):
    # Given a cone standing apex down (as stored it rests on a point) and a slicer that says it needs no support
    model = cone_stl(tmp_path / "cone.stl", apex_up=False)
    fake_slicer.state.default_support = 0.5
    fake_slicer.state.support[(0.0, 0.0)] = 0.0

    # When orientations are suggested with profiles
    advice = await measured(model, count=2)

    # Then the unstable as-stored option is after the stable best one, whatever it measured
    stable = [option for option in advice.options if option.stable]
    unstable = [option for option in advice.options if not option.stable]
    assert stable
    assert unstable
    assert max(option.rank for option in stable) < min(option.rank for option in unstable)


async def test_an_option_prusaslicer_refuses_is_shown_as_refused_and_ranked_last(fake_slicer, tmp_path):
    # Given a cube, where the slicer refuses the as-stored orientation
    model = cube_stl(tmp_path / "cube.stl")
    fake_slicer.state.refuse.add((0.0, 0.0))

    # When orientations are suggested with profiles
    advice = await measured(model, count=3)

    # Then that option says why, has no numbers, and is last; the others are measured
    refused = [option for option in advice.options if taken(option).refused]
    assert len(refused) == 1
    assert refused[0].as_stored is True
    assert "no extrusions in the first layer" in (taken(refused[0]).refused or "")
    assert taken(refused[0]).support_g is None
    assert advice.options[-1] is refused[0]
    assert all(taken(option).support_g is not None for option in advice.options if option is not refused[0])


async def test_without_profiles_nothing_is_sliced(fake_slicer, tmp_path):
    # Given a cube
    model = cube_stl(tmp_path / "cube.stl")

    # When orientations are suggested without profiles
    advice = await server.suggest_orientation(str(model))

    # Then nothing is sliced and nothing is measured
    assert fake_slicer.calls == []
    assert all(option.measured is None for option in advice.options)
    assert [option.geometry_rank for option in advice.options] == [option.rank for option in advice.options]


@pytest.mark.parametrize("given", [("printer_profile",), ("printer_profile", "print_profile")], ids=["one", "two"])
async def test_a_partial_set_of_profiles_is_refused_before_anything_is_sliced(fake_slicer, tmp_path, given):
    # Given a cube and only some of the three profiles
    model = cube_stl(tmp_path / "cube.stl")

    # When orientations are suggested
    with pytest.raises(ToolError, match="all three"):
        await server.suggest_orientation(
            str(model),
            printer_profile=PROFILES["printer_profile"] if "printer_profile" in given else None,
            print_profile=PROFILES["print_profile"] if "print_profile" in given else None,
            material_profile=PROFILES["material_profile"] if "material_profile" in given else None,
        )

    # Then nothing was sliced
    assert fake_slicer.calls == []


async def test_measuring_more_than_six_options_is_refused_because_each_is_a_slice(fake_slicer, tmp_path):
    # Given a cube and a request to measure seven options
    model = cube_stl(tmp_path / "cube.stl")

    # When orientations are suggested with profiles
    with pytest.raises(ToolError, match="at most 6"):
        await measured(model, count=7)

    # Then nothing was sliced
    assert fake_slicer.calls == []


async def test_close_holes_slices_the_capped_copy_so_the_measure_matches_the_score(fake_slicer, tmp_path):
    # Given a cone with no base
    model = cone_stl(tmp_path / "scan.stl", with_base=False)

    # When orientations are suggested with profiles and close_holes
    await measured(model, count=1, close_holes=True)

    # Then every slice was given a watertight copy, not the original file
    loaded = trimesh.load(__import__("io").BytesIO(fake_slicer.inputs[0]), file_type="stl")
    assert isinstance(loaded, trimesh.Trimesh)
    assert loaded.is_watertight
    assert Path(fake_slicer.calls[0][-1]) != model.resolve()


async def test_the_measuring_slices_leave_no_files_behind(fake_slicer, tmp_path):
    # Given a cube
    model = cube_stl(tmp_path / "cube.stl")

    # When orientations are measured
    await measured(model, count=2)

    # Then the folders the G-code was written into are gone, and nothing is in the configured output folder
    for args in fake_slicer.calls:
        assert not Path(args[args.index("--output") + 1]).parent.exists()
    assert not (tmp_path / "out").exists() or list((tmp_path / "out").iterdir()) == []


async def test_a_print_with_no_extrusion_at_all_has_zero_support_not_an_error(fake_slicer, tmp_path, monkeypatch):
    # Given a slicer whose G-code has no extruding moves
    model = cube_stl(tmp_path / "cube.stl")

    async def empty(config, args, timeout=None):
        Path(args[args.index("--output") + 1]).write_text(
            "M83\n;LAYER_CHANGE\n; filament used [mm] = 0\n; total filament used [g] = 0\n"
            "; estimated printing time (normal mode) = 1m 0s\n"
        )
        return cli.CliResult(0, "", "")

    monkeypatch.setattr(cli, "run", empty)

    # When orientations are measured
    advice = await measured(model, count=1)

    # Then the support is zero
    assert all(taken(option).support_g == 0.0 for option in advice.options)


async def test_support_interface_layers_count_as_support(fake_slicer, tmp_path):
    # Given a cube whose print is 10% support and 10% support interface, of 10 g
    model = cube_stl(tmp_path / "cube.stl")
    fake_slicer.state.default_support = 0.1
    fake_slicer.state.interface = 0.1

    # When orientations are measured
    advice = await measured(model, count=1)

    # Then both count: 2 g of support
    assert all(taken(option).support_g == pytest.approx(2.0) for option in advice.options)


async def test_when_support_is_equal_the_shorter_print_comes_first(fake_slicer, tmp_path):
    # Given a cube where every orientation needs the same support but the as-stored one takes longer to print
    model = cube_stl(tmp_path / "cube.stl")
    fake_slicer.state.default_support = 0.2
    fake_slicer.state.times[(0.0, 0.0)] = "3h 0m 0s"

    # When orientations are measured
    advice = await measured(model, count=3)

    # Then the as-stored one, the slowest, is last
    assert advice.options[-1].as_stored is True
    seconds = [seconds_of(option) for option in advice.options]
    assert seconds == sorted(seconds)


async def test_when_support_and_time_are_equal_the_geometric_order_decides(fake_slicer, tmp_path):
    # Given a cube where every orientation measures the same
    model = cube_stl(tmp_path / "cube.stl")
    fake_slicer.state.default_support = 0.2

    # When orientations are measured
    advice = await measured(model, count=4)

    # Then the order is the geometric one
    assert [option.geometry_rank for option in advice.options] == sorted(
        option.geometry_rank for option in advice.options
    )


async def test_measurement_can_overturn_the_geometric_order_and_the_ranks_follow_it(fake_slicer, tmp_path):
    # Given a cube where geometry puts the as-stored orientation first but it measures worst
    model = cube_stl(tmp_path / "cube.stl")
    geometric = await server.suggest_orientation(str(model), count=3)
    assert geometric.options[0].as_stored
    fake_slicer.state.default_support = 0.1
    fake_slicer.state.support[(0.0, 0.0)] = 0.5

    # When orientations are measured
    advice = await measured(model, count=3)

    # Then the as-stored one is last, its geometric rank is still 1, and the ranks run 1, 2, 3...
    assert advice.options[-1].as_stored is True
    assert advice.options[-1].geometry_rank == 1
    assert [option.rank for option in advice.options] == list(range(1, len(advice.options) + 1))
