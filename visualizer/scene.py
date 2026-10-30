"""3D scene format, a check-and-repair pass for model output, and a default layout.

A scene is plain JSON the web page draws with three.js:

    {"envelope_mm": [x, y, z], "summary": str, "fit": {"verdict", "note"},
     "parts": [{"ref", "part_index", "label", "explode": [dx, dy, dz],
                "shapes": [{"kind", "center": [x, y, z], "size": [x, y, z], "axis", "material"}]}]}

Units are mm in the satellite's body frame: origin at the center of the structure,
z along the long rails (+z = top/zenith end, -z = bottom/Earth-facing end).
Every shape is an axis-aligned box; a cylinder fills its box along `axis`.
`explode` is how far the part moves (mm) when the view is fully exploded.
"""
from __future__ import annotations

import math

from .library import lookup
from .placement import auto_explode, place

KINDS = ("box", "cylinder")
AXES = ("x", "y", "z")
MATERIALS = ("aluminum", "black", "pcb", "solar", "gold", "glass", "copper", "white", "titanium", "kapton")

MAX_SHAPES_PER_PART = 60    # library parts are detailed; the 12U frame alone is 52 shapes
MAX_SHAPES_TOTAL = 900
GAP_MM = 1            # default layout: space between stacked parts
BAFFLE_MM = 12        # a camera's baffle may stick out of the Earth-facing face by this much
SPREAD = 1.6         # default layout: the exploded stack is (1 + SPREAD) times as long
REACH_MM = 900       # nothing may sit further than this outside the structure
MIN_SIZE_MM = 0.5


def envelope(design: dict) -> list[float]:
    return [float(v) for v in design["swap"]["size"]["envelope_mm"].split("x")]


def instances(design: dict) -> list[dict]:
    """One entry per physical item: a part with quantity 4 becomes 4 refs (p9.1 .. p9.4)."""
    out = []
    for i, p in enumerate(design["parts"]):
        for n in range(1, p["quantity"] + 1):
            ref = f"p{i}" if p["quantity"] == 1 else f"p{i}.{n}"
            out.append({"ref": ref, "part_index": i, "instance": n, "of": p["quantity"], "part": p})
    return out


def kind_of(part: dict) -> str:
    """Rough category used by the default layout and the prompt."""
    slot, name = part["slot"].lower(), part["part"].lower()
    if slot == "structure":
        return "structure"
    if slot == "solar":
        return "solar_deployed" if "deploy" in name else "solar_body"
    if "antenna" in slot:
        if "gnss" in slot:
            return "patch_zenith"
        if "uhf" in slot or "command" in slot or "payload antenna" in slot:
            return "whip_antenna"
        return "patch_nadir"
    if slot == "payload":
        if part.get("estimated_placeholder"):
            return "payload_box"
        return "imager" if part["peak_power_w"] and part["unit_mass_kg"] and part["unit_mass_kg"] > 0.3 else "board"
    if slot == "propulsion":
        return "thruster"
    if slot == "battery":
        return "battery"
    if slot == "pointing (adcs)":
        return "adcs"
    return "board"


# ---------------------------------------------------------------- repair

def _vec(v, default, lo, hi) -> list[float]:
    out = []
    for i in range(3):
        try:
            x = float(v[i])
        except (TypeError, ValueError, IndexError):
            x = default[i]
        if not math.isfinite(x):
            x = default[i]
        out.append(round(min(max(x, lo[i]), hi[i]), 1))
    return out


def repair(raw: dict, design: dict) -> tuple[dict, list[str]]:
    """Check a model-made scene against the design and fix what can be fixed.

    Unknown refs are dropped, missing parts get their default-layout shapes, numbers are
    clamped to a sane range, and shape counts are capped. Returns (scene, notes about fixes).
    """
    env = envelope(design)
    want = {i["ref"]: i for i in instances(design)}
    fallback = {p["ref"]: p for p in default_scene(design)["parts"]}
    notes: list[str] = []

    parts, seen, total = [], set(), 0
    for p in raw.get("parts") or []:
        if not isinstance(p, dict):
            continue
        ref = str(p.get("ref", ""))
        if ref not in want or ref in seen:
            continue
        seen.add(ref)
        shapes = []
        for s in (p.get("shapes") or [])[:MAX_SHAPES_PER_PART]:
            if not isinstance(s, dict) or total >= MAX_SHAPES_TOTAL:
                continue
            shapes.append(clean_shape(s, env))
            total += 1
        if not shapes:
            notes.append(f"{ref}: no usable shapes, used the default layout")
            shapes = fallback[ref]["shapes"]
        explode = _vec(p.get("explode"), fallback[ref]["explode"], [-REACH_MM] * 3, [REACH_MM] * 3)
        info = want[ref]
        parts.append({"ref": ref, "part_index": info["part_index"],
                      "label": _label(info), "explode": explode, "shapes": shapes,
                      **({"place": p["place"]} if isinstance(p.get("place"), dict) else {})})

    for ref, info in want.items():
        if ref not in seen:
            notes.append(f"{ref} ({info['part']['part']}): missing, used the default layout")
            parts.append(fallback[ref])

    parts.sort(key=lambda p: list(want).index(p["ref"]))
    outside = [p["label"] for p in parts if _inside_part(p, design) and _sticks_out(p, env)]
    if outside:
        notes.append("Placed partly outside the frame: " + ", ".join(outside))

    fit = raw.get("fit") if isinstance(raw.get("fit"), dict) else {}
    verdict = fit.get("verdict") if fit.get("verdict") in ("fits", "tight", "does_not_fit") else "unknown"
    return {
        "envelope_mm": env,
        "summary": str(raw.get("summary") or "")[:400],
        "fit": {"verdict": verdict, "note": str(fit.get("note") or "")[:400]},
        "parts": parts,
    }, notes


def clean_shape(s: dict, env: list[float]) -> dict:
    """One shape with valid kind, axis and material and numbers clamped to a sane range.
    The model writes short keys (k, c, s, a, m); long names are accepted too."""
    kind, axis, mat = s.get("k", s.get("kind")), s.get("a", s.get("axis")), s.get("m", s.get("material"))
    return {
        "kind": kind if kind in KINDS else "box",
        "center": _vec(s.get("c", s.get("center")), [0, 0, 0],
                       [-(e / 2 + REACH_MM) for e in env], [e / 2 + REACH_MM for e in env]),
        "size": _vec(s.get("s", s.get("size")), [10, 10, 10], [MIN_SIZE_MM] * 3, [e + 2 * REACH_MM for e in env]),
        "axis": axis if axis in AXES else "z",
        "material": mat if mat in MATERIALS else "aluminum",
    }


def explode(scene: dict, design: dict) -> dict:
    """Set every part's exploded-view offset from where it sits (see placement.auto_explode)."""
    auto_explode(scene["parts"], scene["envelope_mm"],
                 lambda p: kind_of(design["parts"][p["part_index"]]) == "structure", SPREAD)
    return scene


def _label(info: dict) -> str:
    p = info["part"]
    suffix = f" ({info['instance']}/{info['of']})" if info["of"] > 1 else ""
    return f"{p['part']}{suffix}"


def _inside_part(scene_part: dict, design: dict) -> bool:
    return kind_of(design["parts"][scene_part["part_index"]]) in ("board", "battery", "adcs", "imager", "payload_box")


def _sticks_out(scene_part: dict, env: list[float], slack: float = 15) -> bool:
    for s in scene_part["shapes"]:
        for i in range(3):
            if abs(s["center"][i]) + s["size"][i] / 2 > env[i] / 2 + slack:
                return True
    return False


# ---------------------------------------------------------------- default layout

def _box(center, size, material, kind="box", axis="z") -> dict:
    return {"kind": kind, "center": [round(c, 1) for c in center], "size": [round(s, 1) for s in size],
            "axis": axis, "material": material}


def _module(k: str, part: dict, cx, cy, cz, w, d, h, Z) -> list[dict]:
    """Shapes for one stacked module (payload, ADCS, battery, thruster or board)."""
    bot = cz - h / 2
    if k == "imager":
        barrel = min(w, d) * 0.62
        return [_box((cx, cy, cz + h * .2), (w * .95, d * .95, h * .6), "black"),                 # camera body
                _box((cx, cy, cz + h * .5 - 1), (w * .9, d * .9, 2), "pcb"),                          # electronics
                _box((cx + w * .3, cy, cz + h * .5 + 3), (14, 24, 6), "gold"),                        # connector
                _box((cx, cy, bot + h * .2), (barrel, barrel, h * .2), "black", "cylinder"),          # lens barrel
                _box((cx, cy, bot + h * .31), (barrel * 1.08, barrel * 1.08, 4), "aluminum", "cylinder"),   # focus rings
                _box((cx, cy, bot + h * .12), (barrel * 1.05, barrel * 1.05, 3), "aluminum", "cylinder"),
                _box((cx, cy, -Z / 2 - 3), (barrel * .95, barrel * .95, 8), "black", "cylinder"),     # baffle
                _box((cx, cy, -Z / 2 + 1.5), (barrel * .75, barrel * .75, 2), "glass", "cylinder")]
    if k == "adcs":
        wheel = min(w, d) * .3
        return [_box((cx, cy, bot + 1), (w * .95, d * .95, 1.6), "pcb"),
                _box((cx - w * .22, cy - d * .22, bot + 3 + wheel * .2), (wheel, wheel, wheel * .4), "aluminum", "cylinder", "z"),
                _box((cx + w * .22, cy - d * .22, bot + 3 + wheel * .5), (wheel * .4, wheel, wheel), "aluminum", "cylinder", "x"),
                _box((cx - w * .22, cy + d * .22, bot + 3 + wheel * .5), (wheel, wheel * .4, wheel), "aluminum", "cylinder", "y"),
                _box((cx + w * .2, cy + d * .25, bot + 6), (w * .45, 7, 7), "copper", "cylinder", "x"),       # torque rods
                _box((cx + w * .3, cy + d * .05, bot + 6), (7, d * .35, 7), "copper", "cylinder", "y"),
                _box((cx, cy, cz + h * .45), (w * .95, d * .95, 1.6), "pcb"),
                _box((cx - w * .25, cy + d * .25, cz + h * .45 + 2.5), (14, 14, 3), "black")]
    if k == "battery":
        out = [_box((cx, cy, bot + 1), (w * .95, d * .95, 1.6), "pcb"),
               _box((cx + w * .35, cy, bot + 3.5), (8, 24, 3.5), "gold")]
        for sx in (-1, 1):
            for sy in (-1, 1):
                out.append(_box((cx + sx * w * .2, cy + sy * d * .2, cz + 1), (18, 18, h - 6), "white", "cylinder"))
        out += [_box((cx, cy + sy * d * .2, cz + h / 2 - 2), (w * .7, 4, 3), "black") for sy in (-1, 1)]   # holder straps
        return out
    if k == "thruster":
        return [_box((cx, cy, bot + 2), (w * .95, d * .95, 2), "pcb"),
                _box((cx, cy, cz - 3), (min(w, d) * .8, min(w, d) * .8, h - 16), "titanium", "cylinder"),     # tank
                _box((cx + w * .3, cy + d * .3, cz + h / 2 - 8), (16, 16, 12), "aluminum"),              # valve block
                _box((cx, cy, Z / 2 + 4), (14, 14, 10), "aluminum", "cylinder"),                       # nozzle
                _box((cx, cy, Z / 2 + 10), (20, 20, 4), "black", "cylinder")]
    if k == "payload_box":
        return [_box((cx, cy, cz), (w * .9, d * .9, h), "gold"),
                _box((cx, cy, bot + 1), (w * .95, d * .95, 1.6), "pcb")]
    # Board: PCB, components, an edge connector, corner spacers; radios get a shielded can.
    radio = "radio" in part["slot"]
    out = [_box((cx, cy, bot + 1.5), (w * .95, d * .95, 1.6), "pcb"),
           _box((cx - w * .1, cy + d * .05, bot + 4), (w * .5 if radio else 16, d * .4 if radio else 16, 5 if radio else 2.5),
                "aluminum" if radio else "black"),
           _box((cx + w * .25, cy - d * .25, bot + 3.2), (10, 10, 2), "black"),
           _box((cx, cy + d * .44, bot + 4.5), (w * .55, 5, 6), "black"),                               # stack connector
           _box((cx - w * .42, cy - d * .3, bot + 4), (6, 6, 5), "gold", "cylinder")]                   # SMA / test point
    out += [_box((cx + sx * (w * .47 - 4), cy + sy * (d * .47 - 4), bot - 2), (5, 5, 4), "aluminum", "cylinder")
            for sx in (-1, 1) for sy in (-1, 1)]                                                          # spacers
    return out


def _height_mm(part: dict, k: str) -> float:
    """Stack height guess from part type and mass (no dimensions in the parts table)."""
    m = part["unit_mass_kg"] or 0.2
    if k == "imager":
        return min(max(m * 110, 60), 220)
    if k == "payload_box":
        return min(max(m * 90, 40), 200)
    if k == "adcs":
        return min(max(m * 80, 15), 100)
    if k == "battery":
        return 20
    if k == "thruster":
        return min(max(m * 95, 40), 120)
    return 10 if m < 0.1 else 16   # PC/104-style boards


def _columns(env: list[float]) -> list[tuple[float, float, float, float]]:
    """Board columns inside the frame: (center x, center y, width x, width y)."""
    x, y = env[0], env[1]
    nx, ny = (2 if x > 150 else 1), (2 if y > 150 else 1)
    w, d = x / nx - 10, y / ny - 10
    return [(-x / 2 + x / nx * (i + .5), -y / 2 + y / ny * (j + .5), w, d) for i in range(nx) for j in range(ny)]


def default_scene(design: dict) -> dict:
    """Rule-based layout from the part library. Shown instantly, and used when no model is available.

    Parts missing from the library fall back to simple generic shapes (_module).
    """
    env = envelope(design)
    X, Y, Z = env
    items = instances(design)
    parts = []

    def add(info, shapes, meta=None):
        parts.append({"ref": info["ref"], "part_index": info["part_index"], "label": _label(info),
                      "explode": [0, 0, 0], "shapes": shapes, **({"place": meta} if meta else {})})

    def put(info, entry, pos, up="+z", spin=0):
        pos = [round(v, 1) for v in pos]
        add(info, place(entry["shapes"], pos, up, spin), {"pos": pos, "up": up, "spin": spin})

    def entry_of(info):
        return lookup(info["part"]["part"], info["part"]["unit_mass_kg"])

    # Inside: packed into columns from the bottom up; thrusters from the top down. Boards carry
    # their own standoffs, so parts sit 1 mm apart; a camera's baffle goes through the bottom face.
    cols = _columns(env)
    floor, ceiling = -Z / 2 + 6, Z / 2 - 6
    bottom = [floor] * len(cols)
    start = [floor] * len(cols)              # lower for a column whose camera pokes through the bottom
    top = [ceiling] * len(cols)
    order = {"imager": 0, "payload_box": 0, "adcs": 1, "board": 2, "battery": 3}
    inside = sorted((i for i in items if kind_of(i["part"]) in order), key=lambda i: order[kind_of(i["part"])])
    for info in inside + [i for i in items if kind_of(i["part"]) == "thruster"]:
        k, e = kind_of(info["part"]), entry_of(info)
        h = e["size"][2] if e else _height_mm(info["part"], k)
        if k == "thruster":
            c = max(range(len(cols)), key=lambda j: top[j])
            cz = top[c] - h / 2
            top[c] -= h + GAP_MM
        else:
            c = min(range(len(cols)), key=lambda j: bottom[j])
            if k == "imager" and bottom[c] == floor:
                bottom[c] = start[c] = -Z / 2 - BAFFLE_MM
            cz = bottom[c] + h / 2
            bottom[c] += h + GAP_MM
        cx, cy, w, d = cols[c]
        if e:
            put(info, e, (cx, cy, cz))
        else:
            add(info, _module(k, info["part"], cx, cy, cz, w, d, h, Z))

    for info in (i for i in items if kind_of(i["part"]) == "structure"):
        e = entry_of(info)
        if e:
            put(info, e, (0, 0, 0))
        else:
            r = 8.5
            add(info, [_box((sx * (X / 2 - r / 2), sy * (Y / 2 - r / 2), 0), (r, r, Z), "aluminum")
                       for sx in (-1, 1) for sy in (-1, 1)])

    # Solar: body panels on the long faces; panels too wide for a face, and deployables, become
    # wings at the top end reaching outward.
    faces = [(1, 0), (-1, 0), (0, 1), (0, -1)]
    face_up = {(1, 0): "+x", (-1, 0): "-x", (0, 1): "+y", (0, -1): "-y"}
    wing_spin = {(1, 0): 270, (-1, 0): 90, (0, 1): 0, (0, -1): 180}     # turns own +y to point outward
    layer = {f: 0.0 for f in faces}
    wings = []
    for n, info in enumerate(i for i in items if kind_of(i["part"]) == "solar_body"):
        face, e = faces[n % 4], entry_of(info)
        face_width = Y if face[0] else X
        if e and e["size"][0] > face_width + 10:
            wings.append((face, info))
            continue
        t = e["size"][2] if e else 2
        off = (X if face[0] else Y) / 2 + layer[face] + t / 2 + 0.5
        layer[face] += t + 0.5
        pos = (face[0] * off, face[1] * off, 0)
        if e:
            put(info, e, pos, face_up[face])
        else:
            add(info, [_box(pos, (t, Y - 4, Z - 8) if face[0] else (X - 4, t, Z - 8), "solar")])
    wings += [(faces[n % 4], info) for n, info in enumerate(i for i in items if kind_of(i["part"]) == "solar_deployed")]
    for face, info in wings:
        e = entry_of(info)
        length, t = (e["size"][1], e["size"][2]) if e else (Z - 10, 2)
        reach = (X if face[0] else Y) / 2 + 4 + length / 2
        pos = (face[0] * reach, face[1] * reach, Z / 2 - t / 2)
        if e:
            put(info, e, pos, "+z", wing_spin[face])
        else:
            add(info, [_box(pos, (length, Y - 6, t) if face[0] else (X - 6, length, t), "solar")])

    # Antennas: UHF modules on the ends (top first), GNSS patch facing zenith, downlink patch on
    # the -y side near the Earth-facing end (the end face holds the camera lens).
    top_level = Z / 2
    whips = [i for i in items if kind_of(i["part"]) == "whip_antenna"]
    for n, info in enumerate(whips):
        e = entry_of(info)
        h = e["size"][2] if e else 7
        up = "+z" if n == 0 else "-z"
        zc = (Z / 2 + h / 2) if n == 0 else -(Z / 2 + h / 2)
        if e:
            put(info, e, (0, 0, zc), up)
        else:
            add(info, [_box((0, 0, zc), (min(X, 98), min(Y, 98), h), "black")])
        if n == 0:
            top_level = Z / 2 + h
    for info in (i for i in items if kind_of(i["part"]) == "patch_zenith"):
        e = entry_of(info)
        h = e["size"][2] if e else 4
        x, y = X / 4, Y / 4
        on_antenna = whips and abs(x) + 20 <= 49 and abs(y) + 20 <= 49
        zc = (top_level if on_antenna else Z / 2) + h / 2
        if e:
            put(info, e, (x, y, zc))
        else:
            add(info, [_box((x, y, zc), (30, 30, h), "copper")])
    for info in (i for i in items if kind_of(i["part"]) == "patch_nadir"):
        e = entry_of(info)
        h, side = (e["size"][2], e["size"][1]) if e else (2, 45)
        yc = -(Y / 2 + layer[(0, -1)] + h / 2 + 1)
        zc = -Z / 2 + side / 2 + 8
        if e:
            put(info, e, (0, yc, zc), "-y")
        else:
            add(info, [_box((0, yc, zc), (side, h, side), "copper")])

    # Volume check: does the fullest column's stack fit between the end frames?
    use = [(bottom[j] - start[j] + ceiling - top[j] - GAP_MM, ceiling - start[j]) for j in range(len(cols))]
    need, room = max(use, key=lambda u: u[0] / u[1])
    # Within 5% over still counts as tight: real stacks can sit closer than these drawings.
    verdict = "does_not_fit" if need > room * 1.05 else "tight" if need > room * 0.92 else "fits"
    fit_note = f"Stacked, the inside parts need about {need:.0f} mm and the frame has {room:.0f} mm"
    if need > room:
        fit_note += (f"; {need - room:.0f} mm over, so it only fits with closer board spacing than these drawings use"
                     if verdict == "tight" else f"; {need - room:.0f} mm over")
    fit_note += ". Sizes come from the part library (some are estimates)."

    parts.sort(key=lambda p: [i["ref"] for i in items].index(p["ref"]))
    scene = {
        "envelope_mm": env,
        "summary": "Rule-based layout: library parts stacked along the rails, payload at the Earth-facing end.",
        "fit": {"verdict": verdict, "note": fit_note},
        "parts": parts,
    }
    return explode(scene, design)
