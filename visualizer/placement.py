"""Put a library part into the satellite: turn it in 90-degree steps, then move it.

A part is drawn in its own frame, centered on its bounding box, with its own +z as
its "up" (components side of a board, cells side of a panel, outward side of an
antenna). Placing it takes:

    pos   where the center of its bounding box goes, in the body frame (mm)
    up    which body direction its own +z points: +x -x +y -y +z -z
    spin  a turn about its own z before placing: 0, 90, 180 or 270 degrees

For side faces (up = +x, -x, +y or -y) the part's own y runs along the rails
(body +z) and its own x runs across the face, so a solar panel drawn with its
length along y lies the right way on any long face.

Also here: the exploded-view offsets, worked out from where each part ends up.
"""
from __future__ import annotations

UPS = ("+x", "-x", "+y", "-y", "+z", "-z")
SPINS = (0, 90, 180, 270)

# Local point (x, y, z) -> body point, for each "up". All are proper rotations.
_MAP = {
    "+z": lambda x, y, z: (x, y, z),
    "-z": lambda x, y, z: (x, -y, -z),
    "+x": lambda x, y, z: (z, x, y),
    "-x": lambda x, y, z: (-z, -x, y),
    "+y": lambda x, y, z: (-x, z, y),
    "-y": lambda x, y, z: (x, -z, y),
}
_AXES = "xyz"


def _spin(x: float, y: float, spin: int) -> tuple[float, float]:
    for _ in range((spin // 90) % 4):
        x, y = -y, x
    return x, y


def _rotate(v, up: str, spin: int):
    x, y = _spin(v[0], v[1], spin)
    return _MAP[up](x, y, v[2])


def body_size(size, up: str, spin: int) -> list[float]:
    """A part's [x, y, z] size once placed (in the body frame)."""
    return [round(abs(c), 1) for c in _rotate(size, up, spin)]


def place(shapes: list[dict], pos, up: str = "+z", spin: int = 0) -> list[dict]:
    """Shapes in a part's own frame -> shapes in the body frame."""
    up = up if up in _MAP else "+z"
    spin = int(spin) if int(spin) in SPINS else 0
    out = []
    for s in shapes:
        c = _rotate(s["center"], up, spin)
        unit = [0, 0, 0]
        unit[_AXES.index(s.get("axis", "z"))] = 1
        axis = _AXES[[abs(a) for a in _rotate(unit, up, spin)].index(1)]
        out.append({
            "kind": s["kind"],
            "center": [round(c[i] + pos[i], 1) for i in range(3)],
            "size": body_size(s["size"], up, spin),
            "axis": axis,
            "material": s["material"],
        })
    return out


def bbox(shapes: list[dict]) -> tuple[list[float], list[float]]:
    lo = [min(s["center"][i] - s["size"][i] / 2 for s in shapes) for i in range(3)]
    hi = [max(s["center"][i] + s["size"][i] / 2 for s in shapes) for i in range(3)]
    return lo, hi


def recenter(shapes: list[dict]) -> tuple[list[dict], list[float]]:
    """Move shapes so their bounding box is centered on the origin. Returns (shapes, size)."""
    lo, hi = bbox(shapes)
    mid = [(lo[i] + hi[i]) / 2 for i in range(3)]
    moved = [{**s, "center": [round(s["center"][i] - mid[i], 2) for i in range(3)]} for s in shapes]
    return moved, [round(hi[i] - lo[i], 1) for i in range(3)]


def auto_explode(parts: list[dict], envelope: list[float], is_structure, spread: float) -> None:
    """Set each part's exploded-view offset from where it sits.

    Inside parts spread out along the rails; parts on a side move straight out;
    parts on an end move past the spread stack, stacked in order; the structure stays.
    """
    half = [e / 2 for e in envelope]
    ends = {1: [], -1: []}
    for p in parts:
        if is_structure(p):
            p["explode"] = [0, 0, 0]
            continue
        lo, hi = bbox(p["shapes"])
        c = [(lo[i] + hi[i]) / 2 for i in range(3)]
        out = [abs(c[i]) - half[i] for i in range(3)]
        i = out.index(max(out))
        if out[i] <= 0:
            p["explode"] = [0, 0, round(c[2] * spread, 1)]
        elif i == 2:
            ends[1 if c[2] > 0 else -1].append((abs(c[2]), p))
        else:
            v = [0.0, 0.0, 0.0]
            v[i] = 120.0 if c[i] > 0 else -120.0
            if hi[2] - lo[2] < envelope[2] * 0.6:       # small side parts also follow the stack spread
                v[2] = round(c[2] * spread, 1)
            p["explode"] = v
    for sign, found in ends.items():
        for rank, (_, p) in enumerate(sorted(found, key=lambda t: t[0])):
            p["explode"] = [0, 0, round(sign * (half[2] * spread + 60 + 70 * rank), 1)]
