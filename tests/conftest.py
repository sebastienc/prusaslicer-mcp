import pytest

from prusaslicer_mcp.config import PrusaSlicerNotFound, find_executable


@pytest.fixture(scope="session")
def prusaslicer():
    try:
        return find_executable()
    except PrusaSlicerNotFound:
        pytest.skip("PrusaSlicer not installed")


@pytest.fixture
def cube_stl(tmp_path):
    """A 20 mm ASCII STL cube."""
    v = [(0,0,0),(20,0,0),(20,20,0),(0,20,0),(0,0,20),(20,0,20),(20,20,20),(0,20,20)]
    f = [(0,2,1),(0,3,2),(4,5,6),(4,6,7),(0,1,5),(0,5,4),(1,2,6),(1,6,5),(2,3,7),(2,7,6),(3,0,4),(3,4,7)]
    lines = ["solid c"]
    for a, b, c in f:
        lines.append("facet normal 0 0 0\nouter loop")
        lines += [f"vertex {v[i][0]} {v[i][1]} {v[i][2]}" for i in (a, b, c)]
        lines.append("endloop\nendfacet")
    lines.append("endsolid c")
    p = tmp_path / "cube.stl"
    p.write_text("\n".join(lines))
    return p
