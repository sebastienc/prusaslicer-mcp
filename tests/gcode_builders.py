"""Build small G-code files in the form PrusaSlicer writes them, for the preview tests."""


def square(cx: float, cy: float, half: float) -> list[tuple[float, float, float, float]]:
    """The four edges of a square, as (x0, y0, x1, y1)."""
    a, b, c, d = (cx - half, cy - half), (cx + half, cy - half), (cx + half, cy + half), (cx - half, cy + half)
    return [(*a, *b), (*b, *c), (*c, *d), (*d, *a)]


def layer(z: float, *features: tuple[str, list[tuple[float, float, float, float]]]) -> str:
    """One layer in the form PrusaSlicer writes it: a layer change, its z, then features with their moves."""
    lines = [";LAYER_CHANGE", f";Z:{z}", f";HEIGHT:{z}"]
    for name, edges in features:
        lines.append(f";TYPE:{name}")
        for x0, y0, x1, y1 in edges:
            lines.append(f"G1 X{x0} Y{y0} F9000")  # travel to the start
            lines.append(f"G1 X{x1} Y{y1} E0.5 F1800")  # extrude
    return "\n".join(lines) + "\n"
