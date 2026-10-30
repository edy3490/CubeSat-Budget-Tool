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

MAX_SHAPES_PER_PART = 12
MAX_SHAPES_TOTAL = 160
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
            shapes.append({
                "kind": s.get("kind") if s.get("kind") in KINDS else "box",
                "center": _vec(s.get("center"), [0, 0, 0], lo_c, hi_c),
                "size": _vec(s.get("size"), [10, 10, 10], [MIN_SIZE_MM] * 3, max_s),
                "axis": s.get("axis") if s.get("axis") in AXES else "z",
                "material": s.get("material") if s.get("material") in MATERIALS else "aluminum",
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
        if k == "imager":
            barrel = min(w, d) * 0.8
            shapes = [_box((cx, cy, cz + h * 0.15), (w * .95, d * .95, h * .7), "black"),
                      _box((cx, cy, cz - h * 0.35), (barrel, barrel, h * .3), "black", "cylinder"),
                      _box((cx, cy, -Z / 2 - 1), (barrel * .7, barrel * .7, 3), "glass", "cylinder")]
        elif k == "adcs":
            shapes = [_box((cx, cy, cz - h * .3), (w * .95, d * .95, 2), "pcb"),
                      _box((cx, cy, cz + h * .1), (w * .9, d * .9, h * .7), "aluminum")]
        elif k == "battery":
            shapes = [_box((cx, cy, cz - h * .4), (w * .95, d * .95, 2), "pcb")]
            for sx in (-1, 1):
                for sy in (-1, 1):
                    shapes.append(_box((cx + sx * w * .22, cy + sy * d * .22, cz + 2), (18, 18, h - 6), "white", "cylinder"))
        elif k == "thruster":
            shapes = [_box((cx, cy, cz), (w * .9, d * .9, h - 8), "titanium"),
                      _box((cx, cy, Z / 2 + 4), (14, 14, 10), "aluminum", "cylinder")]
        elif k == "payload_box":
            shapes = [_box((cx, cy, cz), (w * .9, d * .9, h), "gold")]
        else:
            shapes = [_box((cx, cy, cz - h / 2 + 1.5), (w * .95, d * .95, 1.6), "pcb"),
                      _box((cx, cy, cz + 2), (w * .6, d * .5, h - 6), "black" if "radio" in info["part"]["slot"] else "aluminum")]
        # Exploded: the stack spreads out along the rails.
        add(info, shapes, (0, 0, cz * SPREAD))

    # Structure: corner rails and a frame at each end.
    for info in (i for i in items if kind_of(i["part"]) == "structure"):
        r = 8.5
        shapes = [_box((sx * (X / 2 - r / 2), sy * (Y / 2 - r / 2), 0), (r, r, Z), "aluminum")
                  for sx in (-1, 1) for sy in (-1, 1)]
        for ez in (-1, 1):
            zc = ez * (Z / 2 - 3)
            shapes += [_box((0, sy * (Y / 2 - 3), zc), (X, 6, 6), "aluminum") for sy in (-1, 1)]
            shapes += [_box((sx * (X / 2 - 3), 0, zc), (6, Y, 6), "aluminum") for sx in (-1, 1)]
        add(info, shapes, (0, 0, 0))

    # Solar panels: body panels on the long faces; deployables as wings off the top end.
    faces = [(1, 0), (-1, 0), (0, 1), (0, -1)]
    body = [i for i in items if kind_of(i["part"]) == "solar_body"]
    wings = [i for i in items if kind_of(i["part"]) == "solar_deployed"]
    for n, info in enumerate(body):
        fx, fy = faces[n % 4]
        layer = n // 4
        off = 1.5 + layer * 3
        if fx:
            shapes = [_box((fx * (X / 2 + off), 0, 0), (2, Y - 4, Z - 8), "solar")]
        else:
            shapes = [_box((0, fy * (Y / 2 + off), 0), (X - 4, 2, Z - 8), "solar")]
        add(info, shapes, (fx * 110, fy * 110, 0))
    for n, info in enumerate(wings):
        fx, fy = faces[n % 4]
        panels = 2 if "double" in info["part"]["part"].lower() else 1
        span = (Z - 10) * panels
        if fx:
            shapes = [_box((fx * (X / 2 + 4 + span / 2), 0, Z / 2 - 4), (span, Y - 6, 2), "solar")]
        else:
            shapes = [_box((0, fy * (Y / 2 + 4 + span / 2), Z / 2 - 4), (X - 6, span, 2), "solar")]
        add(info, shapes, (fx * 80, fy * 80, 60))

    # Antennas.
    for info in (i for i in items if kind_of(i["part"]).startswith(("whip", "patch"))):
        k = kind_of(info["part"])
        if k == "whip_antenna":
            zc = Z / 2 + 4
            whip = 170
            shapes = [_box((0, 0, zc), (min(X, 98), min(Y, 98), 7), "black")]
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
        for s in p["shapes"]:
            s["center"][2] = -Z / 2 - 4
        p["explode"][2] = -(Z / 2 * SPREAD + 70)

    parts.sort(key=lambda p: [i["ref"] for i in items].index(p["ref"]))
    return {
        "envelope_mm": env,
        "summary": "Default layout: boards stacked along the rails, payload at the Earth-facing end.",
        "fit": {"verdict": "unknown", "note": "The default layout uses rough size guesses; it doesn't check fit."},
        "parts": parts,
    }
