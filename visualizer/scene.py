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

KINDS = ("box", "cylinder")
AXES = ("x", "y", "z")
MATERIALS = ("aluminum", "black", "pcb", "solar", "gold", "glass", "copper", "white", "titanium", "kapton")

MAX_SHAPES_PER_PART = 22
MAX_SHAPES_TOTAL = 260
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

    lo_c = [-(e / 2 + REACH_MM) for e in env]
    hi_c = [e / 2 + REACH_MM for e in env]
    max_s = [e + 2 * REACH_MM for e in env]

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
            # The model writes short keys (k, c, s, a, m); long names are accepted too.
            kind, axis, mat = s.get("k", s.get("kind")), s.get("a", s.get("axis")), s.get("m", s.get("material"))
            shapes.append({
                "kind": kind if kind in KINDS else "box",
                "center": _vec(s.get("c", s.get("center")), [0, 0, 0], lo_c, hi_c),
                "size": _vec(s.get("s", s.get("size")), [10, 10, 10], [MIN_SIZE_MM] * 3, max_s),
                "axis": axis if axis in AXES else "z",
                "material": mat if mat in MATERIALS else "aluminum",
            })
            total += 1
        if not shapes:
            notes.append(f"{ref}: no usable shapes, used the default layout")
            shapes = fallback[ref]["shapes"]
        explode = _vec(p.get("explode"), fallback[ref]["explode"], [-REACH_MM] * 3, [REACH_MM] * 3)
        info = want[ref]
        parts.append({"ref": ref, "part_index": info["part_index"],
                      "label": _label(info), "explode": explode, "shapes": shapes})

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
    """A plain, rule-based layout. Shown instantly, and used when no model is available."""
    env = envelope(design)
    X, Y, Z = env
    items = instances(design)
    parts = []

    def add(info, shapes, explode):
        parts.append({"ref": info["ref"], "part_index": info["part_index"], "label": _label(info),
                      "explode": [round(e, 1) for e in explode], "shapes": shapes})

    # Internals, packed into columns from the bottom up; thrusters from the top down.
    cols = _columns(env)
    bottom = [-Z / 2 + 6] * len(cols)
    top = [Z / 2 - 6] * len(cols)
    order = {"imager": 0, "payload_box": 0, "adcs": 1, "board": 2, "battery": 3}
    inside = sorted((i for i in items if kind_of(i["part"]) in order),
                    key=lambda i: order[kind_of(i["part"])])
    for info in inside + [i for i in items if kind_of(i["part"]) == "thruster"]:
        k = kind_of(info["part"])
        h = _height_mm(info["part"], k)
        if k == "thruster":
            c = max(range(len(cols)), key=lambda j: top[j])
            cz = top[c] - h / 2
            top[c] -= h + 3
        else:
            c = min(range(len(cols)), key=lambda j: bottom[j])
            cz = bottom[c] + h / 2
            bottom[c] += h + 3
        cx, cy, w, d = cols[c]
        shapes = _module(k, info["part"], cx, cy, cz, w, d, h, Z)
        # Exploded: the stack spreads out along the rails.
        add(info, shapes, (0, 0, cz * SPREAD))

    # Structure: corner rails with feet, end frames, ribs at each 1U, and stack rods.
    for info in (i for i in items if kind_of(i["part"]) == "structure"):
        r = 8.5
        shapes = [_box((sx * (X / 2 - r / 2), sy * (Y / 2 - r / 2), 0), (r, r, Z - 13), "aluminum")
                  for sx in (-1, 1) for sy in (-1, 1)]
        shapes += [_box((sx * (X / 2 - r / 2), sy * (Y / 2 - r / 2), ez * (Z / 2 - 3.3)), (r - 1, r - 1, 6.5), "black")
                   for sx in (-1, 1) for sy in (-1, 1) for ez in (-1, 1)]            # rail feet
        ribs = [ez * (Z / 2 - 10) for ez in (-1, 1)] + [-Z / 2 + 113.5 * n for n in range(1, int(Z // 113.5))]
        for zc in ribs:
            shapes += [_box((0, sy * (Y / 2 - 3), zc), (X - 2 * r, 5, 5), "aluminum") for sy in (-1, 1)]
            shapes += [_box((sx * (X / 2 - 3), 0, zc), (5, Y - 2 * r, 5), "aluminum") for sx in (-1, 1)]
        for cx, cy, w, d in _columns(env):                                          # stack rods
            shapes += [_box((cx + sx * (w / 2 - 4), cy + sy * (d / 2 - 4), 0), (3, 3, Z - 24), "titanium", "cylinder")
                       for sx in (-1, 1) for sy in (-1, 1)]
        add(info, shapes, (0, 0, 0))

    # Solar panels: body panels on the long faces; deployables as wings off the top end.
    faces = [(1, 0), (-1, 0), (0, 1), (0, -1)]
    body = [i for i in items if kind_of(i["part"]) == "solar_body"]
    wings = [i for i in items if kind_of(i["part"]) == "solar_deployed"]
    for n, info in enumerate(body):
        fx, fy = faces[n % 4]
        layer = n // 4
        off = 1.5 + layer * 3
        if fx:   # substrate, cells on the outside
            shapes = [_box((fx * (X / 2 + off), 0, 0), (1.6, Y - 4, Z - 8), "pcb"),
                      _box((fx * (X / 2 + off + 1.2), 0, 0), (0.8, Y - 10, Z - 16), "solar")]
        else:
            shapes = [_box((0, fy * (Y / 2 + off), 0), (X - 4, 1.6, Z - 8), "pcb"),
                      _box((0, fy * (Y / 2 + off + 1.2), 0), (X - 10, 0.8, Z - 16), "solar")]
        add(info, shapes, (fx * 110, fy * 110, 0))
    for n, info in enumerate(wings):
        fx, fy = faces[n % 4]
        panels = 2 if "double" in info["part"]["part"].lower() else 1
        span = (Z - 10) * panels
        if fx:
            shapes = [_box((fx * (X / 2 + 4 + span / 2), 0, Z / 2 - 4), (span, Y - 6, 1.6), "pcb"),
                      _box((fx * (X / 2 + 4 + span / 2), 0, Z / 2 - 2.8), (span - 6, Y - 12, 0.8), "solar")]
            shapes += [_box((fx * (X / 2 + 3), hy * (Y / 2 - 15), Z / 2 - 4), (6, 14, 6), "aluminum", "cylinder", "y") for hy in (-1, 1)]
        else:
            shapes = [_box((0, fy * (Y / 2 + 4 + span / 2), Z / 2 - 4), (X - 6, span, 1.6), "pcb"),
                      _box((0, fy * (Y / 2 + 4 + span / 2), Z / 2 - 2.8), (X - 12, span - 6, 0.8), "solar")]
            shapes += [_box((hx * (X / 2 - 15), fy * (Y / 2 + 3), Z / 2 - 4), (14, 6, 6), "aluminum", "cylinder", "x") for hx in (-1, 1)]
        add(info, shapes, (fx * 80, fy * 80, 60))

    # Antennas.
    for info in (i for i in items if kind_of(i["part"]).startswith(("whip", "patch"))):
        k = kind_of(info["part"])
        if k == "whip_antenna":
            zc = Z / 2 + 4
            whip = 170
            shapes = [_box((0, 0, zc), (min(X, 98), min(Y, 98), 7), "black"),
                      _box((0, 0, zc + 3.8), (min(X, 98) - 30, min(Y, 98) - 30, 0.6), "pcb")]
            shapes += [_box((sx * 40, 0, zc + 4.5), (8, 16, 3), "white") for sx in (-1, 1)]       # burn-wire housings
            shapes += [_box((0, sy * 40, zc + 4.5), (16, 8, 3), "white") for sy in (-1, 1)]
            shapes += [_box((sx * (49 + whip / 2), 0, zc), (whip, 3, 0.6), "aluminum") for sx in (-1, 1)]
            shapes += [_box((0, sy * (49 + whip / 2), zc), (3, whip, 0.6), "aluminum") for sy in (-1, 1)]
            add(info, shapes, (0, 0, Z / 2 * SPREAD + 70))
            parts[-1]["_whip"] = True
        elif k == "patch_zenith":
            # Sits on top of the UHF antenna module at the zenith end.
            shapes = [_box((X / 4, Y / 4, Z / 2 + 11.5), (30, 30, 4), "copper"),
                      _box((X / 4, Y / 4, Z / 2 + 8.8), (36, 36, 1.6), "white")]
            add(info, shapes, (0, 0, Z / 2 * SPREAD + 130))
        else:
            # Downlink patch on the -y side near the Earth-facing end (the end face holds the lens).
            sz = 60 if "4x4" in info["part"]["part"] else 45
            zc = -Z / 2 + sz / 2 + 8
            shapes = [_box((0, -(Y / 2 + 4.6), zc), (sz + 4, 1.6, sz + 4), "white"),
                      _box((0, -(Y / 2 + 6.4), zc), (sz, 2, sz), "copper")]
            add(info, shapes, (0, -150, zc * SPREAD))

    # Two whip antennas (command + relay): put the second one on the bottom end.
    whips = [p for p in parts if p.pop("_whip", False)]
    for p in whips[1:]:
        for s in p["shapes"]:     # mirror it onto the bottom end
            s["center"][2] = -s["center"][2]
        p["explode"][2] = -(Z / 2 * SPREAD + 70)

    parts.sort(key=lambda p: [i["ref"] for i in items].index(p["ref"]))
    return {
        "envelope_mm": env,
        "summary": "Default layout: boards stacked along the rails, payload at the Earth-facing end.",
        "fit": {"verdict": "unknown", "note": "The default layout uses rough size guesses; it doesn't check fit."},
        "parts": parts,
    }
