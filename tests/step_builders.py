"""Build a small valid STEP file (a cube as a B-rep solid) so real-binary tests need no model file in the repo."""

from __future__ import annotations

_HEADER = """ISO-10303-21;
HEADER;
FILE_DESCRIPTION(('cube'),'2;1');
FILE_NAME('cube.step','2026-01-01T00:00:00',(''),(''),'','','');
FILE_SCHEMA(('CONFIG_CONTROL_DESIGN'));
ENDSEC;
DATA;
"""


def step_cube(size: float = 20.0) -> str:
    """A STEP file holding one cube, `size` mm on a side, with a corner at the origin."""
    entities: list[str] = []

    def add(text: str) -> int:
        entities.append(f"#{len(entities) + 1}={text};")
        return len(entities)

    def vertex_bits(index: int) -> tuple[int, int, int]:
        return index & 1, (index >> 1) & 1, (index >> 2) & 1

    points = [
        add(f"CARTESIAN_POINT('',({x * size:g},{y * size:g},{z * size:g}))") for x, y, z in map(vertex_bits, range(8))
    ]
    vertices = [add(f"VERTEX_POINT('',#{point})") for point in points]

    edges: dict[tuple[int, int], int] = {}
    for a in range(8):
        for axis in range(3):
            b = a | (1 << axis)
            if a == b:
                continue
            direction = [0.0, 0.0, 0.0]
            direction[axis] = 1.0
            d = add(f"DIRECTION('',({direction[0]:g},{direction[1]:g},{direction[2]:g}))")
            v = add(f"VECTOR('',#{d},{size:g})")
            line = add(f"LINE('',#{points[a]},#{v})")
            edges[(a, b)] = add(f"EDGE_CURVE('',#{vertices[a]},#{vertices[b]},#{line},.T.)")

    faces = []
    for axis in range(3):
        u, v = (axis + 1) % 3, (axis + 2) % 3  # u x v = axis, so counter-clockwise in (u, v) looks from outside
        for side in (1, 0):
            corners = []
            for cu, cv in ((0, 0), (1, 0), (1, 1), (0, 1)):
                bits = [0, 0, 0]
                bits[axis], bits[u], bits[v] = side, cu, cv
                corners.append(bits[0] | bits[1] << 1 | bits[2] << 2)
            if side == 0:
                corners = corners[::-1]  # the outward normal is -axis, so run the other way round
            oriented = []
            for p, q in zip(corners, corners[1:] + corners[:1], strict=True):
                key, forward = ((p, q), True) if (p, q) in edges else ((q, p), False)
                oriented.append(add(f"ORIENTED_EDGE('',*,*,#{edges[key]},{'.T.' if forward else '.F.'})"))
            loop = add(f"EDGE_LOOP('',({','.join(f'#{o}' for o in oriented)}))")
            bound = add(f"FACE_OUTER_BOUND('',#{loop},.T.)")
            normal = [0.0, 0.0, 0.0]
            normal[axis] = 1.0 if side else -1.0
            reference = [0.0, 0.0, 0.0]
            reference[u] = 1.0
            n = add(f"DIRECTION('',({normal[0]:g},{normal[1]:g},{normal[2]:g}))")
            r = add(f"DIRECTION('',({reference[0]:g},{reference[1]:g},{reference[2]:g}))")
            placement = add(f"AXIS2_PLACEMENT_3D('',#{points[corners[0]]},#{n},#{r})")
            plane = add(f"PLANE('',#{placement})")
            faces.append(add(f"ADVANCED_FACE('',(#{bound}),#{plane},.T.)"))

    shell = add(f"CLOSED_SHELL('',({','.join(f'#{f}' for f in faces)}))")
    solid = add(f"MANIFOLD_SOLID_BREP('cube',#{shell})")

    origin = add("CARTESIAN_POINT('',(0.,0.,0.))")
    z_axis = add("DIRECTION('',(0.,0.,1.))")
    x_axis = add("DIRECTION('',(1.,0.,0.))")
    frame = add(f"AXIS2_PLACEMENT_3D('',#{origin},#{z_axis},#{x_axis})")
    length = add("(LENGTH_UNIT()NAMED_UNIT(*)SI_UNIT(.MILLI.,.METRE.))")
    angle = add("(NAMED_UNIT(*)PLANE_ANGLE_UNIT()SI_UNIT($,.RADIAN.))")
    solid_angle = add("(NAMED_UNIT(*)SI_UNIT($,.STERADIAN.)SOLID_ANGLE_UNIT())")
    uncertainty = add(f"UNCERTAINTY_MEASURE_WITH_UNIT(LENGTH_MEASURE(1.E-07),#{length},'distance_accuracy_value','')")
    context = add(
        "(GEOMETRIC_REPRESENTATION_CONTEXT(3)"
        f"GLOBAL_UNCERTAINTY_ASSIGNED_CONTEXT((#{uncertainty}))"
        f"GLOBAL_UNIT_ASSIGNED_CONTEXT((#{length},#{angle},#{solid_angle}))REPRESENTATION_CONTEXT('',''))"
    )
    shape = add(f"ADVANCED_BREP_SHAPE_REPRESENTATION('cube',(#{frame},#{solid}),#{context})")

    application = add("APPLICATION_CONTEXT('configuration controlled 3d designs')")
    add(f"APPLICATION_PROTOCOL_DEFINITION('international standard','config_control_design',1994,#{application})")
    product_context = add(f"PRODUCT_CONTEXT('',#{application},'mechanical')")
    product = add(f"PRODUCT('cube','cube','',(#{product_context}))")
    formation = add(f"PRODUCT_DEFINITION_FORMATION('','',#{product})")
    definition_context = add(f"PRODUCT_DEFINITION_CONTEXT('part definition',#{application},'design')")
    definition = add(f"PRODUCT_DEFINITION('design','',#{formation},#{definition_context})")
    definition_shape = add(f"PRODUCT_DEFINITION_SHAPE('','',#{definition})")
    add(f"SHAPE_DEFINITION_REPRESENTATION(#{definition_shape},#{shape})")

    return _HEADER + "\n".join(entities) + "\nENDSEC;\nEND-ISO-10303-21;\n"
