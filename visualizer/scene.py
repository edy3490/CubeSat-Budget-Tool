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
from .placement import auto_explode, bbox, place

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
                      **({"place": p["place"]} if isinstance(p.get("place"), dict) else {}),
                      **({"role": str(p["role"])[:400]} if p.get("role") else {})})

    for ref, info in want.items():
        if ref not in seen:
            notes.append(f"{ref} ({info['part']['part']}): missing, used the default layout")
            parts.append(fallback[ref])

    parts.sort(key=lambda p: list(want).index(p["ref"]))

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
    auto_explode(scene["parts"], scene["envelope_mm"],      # extras (part_index -1) are never the structure
                 lambda p: p["part_index"] >= 0 and kind_of(design["parts"][p["part_index"]]) == "structure", SPREAD)
    return scene


def _label(info: dict) -> str:
    p = info["part"]
    suffix = f" ({info['instance']}/{info['of']})" if info["of"] > 1 else ""
    return f"{p['part']}{suffix}"


def _inside_part(scene_part: dict, design: dict) -> bool:
    return kind_of(design["parts"][scene_part["part_index"]]) in INSIDE_KINDS


INSIDE_KINDS = ("board", "battery", "adcs", "imager", "payload_box")
UHF_BASE_MM = 98      # a UHF antenna module's base; its library size includes the deployed tapes
OVERLAP_MM = 1        # inside parts closer than this (in all three directions) count as overlapping


def inside_stack_mm(design: dict) -> float:
    """Height the inside parts need stacked in one column, 1 mm apart."""
    hs = []
    for i in instances(design):
        k = kind_of(i["part"])
        if k in INSIDE_KINDS:
            e = lookup(i["part"]["part"], i["part"]["unit_mass_kg"])
            hs.append(e["size"][2] if e else _height_mm(i["part"], k))
    return sum(hs) + GAP_MM * max(len(hs) - 1, 0)


def inside_z(env: list[float]) -> tuple[float, float]:
    """The z range inside parts may use (the default layout's floor and ceiling)."""
    return -env[2] / 2 + 6, env[2] / 2 - 6


def fix_inside(scene: dict, design: dict) -> list[str]:
    """Fix inside parts the model left sticking out of the frame or overlapping each other.
    Changes scene in place.

    Tried in order, keeping the first that works:
    1. Nudge: slide parts along the rails just enough to open the gaps, keeping their order
       (fixes small overlaps in a stack, and a stack that runs a little past an end).
    2. Move: the offenders (parts sticking out, plus the smaller part of each overlapping pair)
       each go to the nearest free spot, in their own column or another one.
    3. Re-stack every inside part in columns like the default layout, keeping the model's
       bottom-to-top order.
    Returns notes about what was changed.
    """
    env = scene["envelope_mm"]
    X, Y, Z = env
    floor, ceiling = inside_z(env)

    def kind(p):
        return "extra" if p.get("extra") else kind_of(design["parts"][p["part_index"]])

    def inside(p):
        if p.get("extra"):     # an added part counts when the model put it inside the frame
            lo, hi = bbox(p["shapes"])
            return all(abs(lo[k] + hi[k]) / 2 < env[k] / 2 - 5 for k in range(3))
        # Thrusters share the stack (they must not overlap it) but their nozzle may stick out.
        return p.get("part_index", -1) >= 0 and kind(p) in INSIDE_KINDS + ("thruster",)

    stack = [p for p in scene["parts"] if p["shapes"] and inside(p)]
    box = {id(p): bbox(p["shapes"]) for p in stack}

    def size(p):
        lo, hi = box[id(p)]
        return [hi[k] - lo[k] for k in range(3)]

    out = [p for p in stack if kind(p) != "thruster" and _sticks_out(p, env)]
    clashing = []          # the smaller part of every overlapping pair (that isn't already moving)
    pairs = [(a, b) for i, a in enumerate(stack) for b in stack[i + 1:] if _overlap(box[id(a)], box[id(b)], OVERLAP_MM)]
    for a, b in pairs:
        if not any(p in out or p in clashing for p in (a, b)):
            clashing.append(min((a, b), key=lambda p: math.prod(size(p))))
    offenders = out + clashing
    if not offenders:
        return []
    def name(p):
        return p["extra"]["name"] if p.get("extra") else p["label"]

    why = "; ".join(t for t in (out and "stuck out of the frame: " + ", ".join(name(p) for p in out),
                                clashing and "overlapped another part: " + ", ".join(name(p) for p in clashing)) if t)

    def target(p, cx, cy, z0):
        sz = size(p)
        return ([cx - sz[0] / 2, cy - sz[1] / 2, z0], [cx + sz[0] / 2, cy + sz[1] / 2, z0 + sz[2]])

    def in_xy(p, cx, cy):
        sz = size(p)
        return abs(cx) + sz[0] / 2 <= X / 2 + 1 and abs(cy) + sz[1] / 2 <= Y / 2 + 1

    def imager(p):
        return kind(p) == "imager"

    # How low and high each part may go. A part that stuck out must come inside the floor and
    # ceiling; others may stay where the model put them; a camera's lens may poke out the bottom.
    def low(p):
        return -Z / 2 - BAFFLE_MM if imager(p) else floor if p in out else min(floor, box[id(p)][0][2])

    def top(p):
        return ceiling if p in out else max(ceiling, box[id(p)][1][2])

    def valid(new):
        for p in stack:
            lo, hi = new[id(p)]
            if lo[2] < low(p) - 0.01 or hi[2] > top(p) + 0.01:
                return False
            if p in out and any(max(-lo[k], hi[k]) > env[k] / 2 + 1 for k in (0, 1)):
                return False   # sticks out sideways: a nudge along z can't fix that
        bs = list(new.values())
        return not any(_overlap(a, b, OVERLAP_MM) for i, a in enumerate(bs) for b in bs[i + 1:])

    # 1. Nudge along the rails, keeping the order.
    nudged = _nudge(stack, box, top)
    if valid(nudged):
        for p in stack:
            if abs(nudged[id(p)][0][2] - box[id(p)][0][2]) > 0.01:
                _move_to(p, box[id(p)], nudged[id(p)])
        return [f"Nudged along the rails ({why})"]

    # 2. Move just the offenders, each to the free spot nearest where the model put it.
    cols = [(c[0], c[1]) for c in _columns(env)]
    taken = [box[id(p)] for p in stack if p not in offenders]
    moves = {}
    for p in sorted(offenders, key=lambda p: box[id(p)][0][2]):
        lo, hi = box[id(p)]
        h = hi[2] - lo[2]
        here = [(lo[k] + hi[k]) / 2 for k in range(3)]
        bottom_z, top_z = low(p), top(p)
        best = None
        for cx, cy in [(here[0], here[1])] + cols:
            if not in_xy(p, cx, cy):
                continue
            for z0 in {bottom_z, lo[2]} | {b[1][2] + GAP_MM for b in taken} | {b[0][2] - GAP_MM - h for b in taken}:
                cand = target(p, cx, cy, z0)
                if z0 < bottom_z - 0.01 or cand[1][2] > top_z + 0.01 or any(_overlap(cand, b, OVERLAP_MM) for b in taken):
                    continue
                dist = math.dist(here, [(cand[0][k] + cand[1][k]) / 2 for k in range(3)])
                if best is None or dist < best[0]:
                    best = (dist, cand)
        if best is None:
            moves = None
            break
        moves[id(p)] = best[1]
        taken.append(best[1])
    if moves is not None:
        for p in offenders:
            _move_to(p, box[id(p)], moves[id(p)])
        describe_layout(scene, design, stack, why)
        return [f"Moved to free space inside the frame ({why})"]

    # 3. Re-stack everything inside in columns (the camera first, lens out the bottom).
    cells = [(X / len({c[0] for c in cols}), Y / len({c[1] for c in cols}))]
    order = sorted(stack, key=lambda p: (0 if kind(p) in ("imager", "payload_box") else 1, box[id(p)][0][2]))
    bottom, new = [floor] * len(cols), {}
    for p in order:
        sz = size(p)
        if sz[0] <= cells[0][0] + 2 and sz[1] <= cells[0][1] + 2:     # fits one column
            c = min(range(len(cols)), key=lambda j: bottom[j])
            if imager(p) and bottom[c] == floor:
                bottom[c] = -Z / 2 - BAFFLE_MM
            new[id(p)] = target(p, *cols[c], bottom[c])
            bottom[c] += sz[2] + GAP_MM
        else:                                                           # too wide: spans every column
            z0 = max(bottom)
            new[id(p)] = target(p, 0, 0, z0)
            bottom = [z0 + sz[2] + GAP_MM] * len(cols)
    if max(b[1][2] for b in new.values()) > ceiling + 1:
        need = inside_stack_mm(design)
        scene["fit"] = {"verdict": "does_not_fit",
                        "note": f"The inside parts need about {need:.0f} mm of stacking, more than the frame holds."}
        desc = scene.get("description")
        if isinstance(desc, dict):     # the model's text may say it fits: say plainly that it doesn't
            desc["layout"] = (desc.get("layout", "") + f" As drawn, though, it doesn't fit: {why}. Stacked, the inside "
                              f"parts need about {need:.0f} mm and the frame has {ceiling - floor:.0f} mm.").strip()
        return [f"Not enough room inside to fix this ({why})"]
    for p in stack:
        _move_to(p, box[id(p)], new[id(p)])
    describe_layout(scene, design, stack, why)
    return [f"Re-stacked the inside parts in columns ({why})"]


def fix_outside(scene: dict, design: dict) -> list[str]:
    """Fix solar panels and patch antennas the model placed badly. Changes scene in place.

    - A body panel is fine when it lies flat on a side face, just outside the frame, without hanging
      past that face's edges or ends, and doesn't overlap another panel; a wing is fine at the top
      end. If any panel isn't, all panels take the default layout's places (wide faces first,
      wings for panels too wide for any face).
    - An antenna (patch, or UHF module for an end face) is fine when it lies flat on a face,
      outside the frame. If not, it takes the default layout's place.
    - A patch or outside extra a panel covers is lifted to sit on top of the panel.
    Returns notes about what was changed.
    """
    env = scene["envelope_mm"]
    Z = env[2]
    default = None

    def kind(p):
        return "extra" if p.get("extra") else kind_of(design["parts"][p["part_index"]])

    def thin(lo, hi):                                 # the thin direction = the face normal
        size = [hi[k] - lo[k] for k in range(3)]
        return size.index(min(size))

    def on_face(lo, hi, n):
        return lo[n] >= env[n] / 2 - 2 or hi[n] <= -env[n] / 2 + 2

    def to_default(p):
        nonlocal default
        default = default or {q["ref"]: q for q in default_scene(design)["parts"]}
        d = default.get(p["ref"])
        if d:
            p["shapes"] = [dict(s) for s in d["shapes"]]
            if d.get("place"):
                p["place"] = dict(d["place"])

    def panel_ok(p):
        lo, hi = bbox(p["shapes"])
        n = thin(lo, hi)
        if n == 2:                                    # lying across the end: only a wing at the top
            return lo[2] >= Z / 2 - 10
        other = 1 - n
        return (on_face(lo, hi, n) and max(-lo[other], hi[other]) <= env[other] / 2 + 3
                and max(-lo[2], hi[2]) <= Z / 2 + 3)

    notes, said = [], []
    panels = [p for p in scene["parts"] if p["shapes"] and kind(p).startswith("solar")]
    bad = [p for p in panels if not panel_ok(p)]
    bad += [a for i, a in enumerate(panels) for b in panels[i + 1:]
            if a not in bad and _overlap(bbox(a["shapes"]), bbox(b["shapes"]), 1)]
    if bad:
        for p in panels:
            to_default(p)
        notes.append(f"Moved the solar panels to faces they fit ({', '.join(p['label'] for p in bad)} didn't)")
        said.append("moved the solar panels to faces they fit")

    # UHF modules first: the default GNSS patch sits on top of the default UHF module.
    antennas = sorted((p for p in scene["parts"] if p["shapes"] and kind(p) in ("whip_antenna", "patch_nadir", "patch_zenith")),
                      key=lambda p: kind(p) != "whip_antenna")
    off = [p for p in antennas if not on_face(*bbox(p["shapes"]), thin(*bbox(p["shapes"])))]
    for p in off:
        to_default(p)
    # A patch buried in a UHF module (say, after the module moved out to the end face) sits on top of it.
    # Only the module's base counts: its size includes the deployed tape antennas, which a patch may sit under.
    def base(b, half=UHF_BASE_MM / 2):
        n = thin(*b)
        c = [(b[0][k] + b[1][k]) / 2 for k in range(3)]
        return ([b[0][k] if k == n else max(b[0][k], c[k] - half) for k in range(3)],
                [b[1][k] if k == n else min(b[1][k], c[k] + half) for k in range(3)])

    whips = [base(bbox(p["shapes"])) for p in antennas if kind(p) == "whip_antenna"]
    for p in antennas:
        if kind(p) != "whip_antenna" and p not in off and any(_overlap(bbox(p["shapes"]), w, 0.5) for w in whips):
            to_default(p)
            off.append(p)
    if off:
        notes.append(f"Put {', '.join(p['label'] for p in off)} flat on a face outside the frame")
        said.append(f"put {_join([p['label'] for p in off])} flat on a face outside the frame")

    lifted = []
    for p in scene["parts"]:
        if not p["shapes"] or kind(p) not in ("patch_nadir", "patch_zenith", "extra"):
            continue
        lo, hi = bbox(p["shapes"])
        if kind(p) == "extra" and all(abs(lo[k] + hi[k]) / 2 < env[k] / 2 - 5 for k in range(3)):
            continue                                  # an extra inside the frame isn't on a face
        for q in panels:
            qlo, qhi = bbox(q["shapes"])
            if not _overlap((lo, hi), (qlo, qhi), 0.5):
                continue
            n = thin(qlo, qhi)
            d = [0.0, 0.0, 0.0]
            d[n] = (qhi[n] + 0.5 - lo[n]) if qlo[n] + qhi[n] > 0 else (qlo[n] - 0.5 - hi[n])
            _move_to(p, (lo, hi), ([lo[k] + d[k] for k in range(3)], [hi[k] + d[k] for k in range(3)]))
            lo, hi = bbox(p["shapes"])
            lifted.append(p["extra"]["name"] if p.get("extra") else p["label"])
    if lifted:
        notes.append(f"Lifted {', '.join(lifted)} onto the solar panel under it")
        said.append(f"set {_join(lifted)} on top of the solar panels")

    desc = scene.get("description")
    if said and isinstance(desc, dict) and desc.get("layout"):
        desc["layout"] += " The app " + _join(said) + "."
    return notes


_ORDINAL = ["One", "the second", "the third", "the fourth", "the fifth", "the sixth"]
_FACES = {(2, 1): "the top (zenith) end", (2, -1): "the Earth-facing end", (0, 1): "a side face", (0, -1): "a side face",
          (1, 1): "a side face", (1, -1): "a side face"}


def _join(names: list[str]) -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def describe_layout(scene: dict, design: dict, stack: list[dict], why: str) -> None:
    """Rewrite the layout text, fit and summary from where the parts actually are. Used after
    fix_inside moved parts to new places, so the model's own words no longer match the drawing."""
    env = scene["envelope_mm"]
    X, Y, Z = env
    floor, ceiling = inside_z(env)
    cols = _columns(env)
    cell = (X / len({c[0] for c in cols}), Y / len({c[1] for c in cols}))

    def name(p):
        return p["extra"]["name"] if p.get("extra") else p["label"]

    def imager(p):
        return not p.get("extra") and kind_of(design["parts"][p["part_index"]]) == "imager"

    groups, wide = [[] for _ in cols], []
    for p in stack:
        lo, hi = bbox(p["shapes"])
        if hi[0] - lo[0] > cell[0] + 2 or hi[1] - lo[1] > cell[1] + 2:
            wide.append(p)
            continue
        c = [(lo[k] + hi[k]) / 2 for k in range(2)]
        groups[min(range(len(cols)), key=lambda j: math.dist(cols[j][:2], c))].append(p)
    groups = [sorted(g, key=lambda p: bbox(p["shapes"])[0][2]) for g in groups if g]

    def names(g):
        return _join([name(p) + (" (lens out through the Earth-facing face)" if imager(p) and bbox(p["shapes"])[0][2] < -Z / 2 else "")
                      for p in g])

    def listed(g):             # "holds X" or "holds, from the Earth-facing end up, X and Y"
        return " " + names(g) if len(g) == 1 else ", from the Earth-facing end up, " + names(g)

    need, room = inside_stack_mm(design), ceiling - floor
    if len(groups) <= 1:
        text = [f"The inside parts sit in one stack along the rails, from the Earth-facing end up: {names(groups[0]) if groups else 'none'}."]
    else:
        reason = f", because in one stack they would need about {need:.0f} mm and the frame has {room:.0f} mm" if need > room else ""
        text = [f"The inside parts are split into {len(groups)} side-by-side stacks along the rails{reason}."]
        text.append("; ".join(f"{_ORDINAL[min(i, len(_ORDINAL) - 1)]} holds{listed(g)}"
                              for i, g in enumerate(groups)) + ".")
    if wide:
        text.append(f"{_join([name(p) for p in wide])} {'takes' if len(wide) == 1 else 'take'} the full width of the frame.")

    # What's on the outside, by face.
    faces: dict[str, list[str]] = {}
    panels = wings = 0
    for p in scene["parts"]:
        if p in stack or not p["shapes"] or (p.get("part_index", -1) >= 0 and kind_of(design["parts"][p["part_index"]]) == "structure"):
            continue
        k = "extra" if p.get("extra") else kind_of(design["parts"][p["part_index"]])
        lo, hi = bbox(p["shapes"])
        if k.startswith("solar"):    # body panels run along the rails; wings are short in z
            wings, panels = (wings, panels + 1) if hi[2] - lo[2] > Z / 2 else (wings + 1, panels)
            continue
        face = next((_FACES[(a, sgn)] for a in (2, 0, 1) for sgn in (1, -1)
                     if (lo[a] >= env[a] / 2 - 3 if sgn > 0 else hi[a] <= -env[a] / 2 + 3)), None)
        if face == "a side face":
            zc = (lo[2] + hi[2]) / 2
            face += " near the Earth-facing end" if zc < -Z / 4 else " near the top end" if zc > Z / 4 else ""
        if face:
            faces.setdefault(face, []).append(name(p))
    outside = [f"{_join(n)} on {f}" for f, n in faces.items()]
    if panels:
        outside.append("the body solar panels on the long faces")
    if wings:
        outside.append("the larger solar panels as wings reaching out from the top end")
    if outside:
        text.append("Outside: " + "; ".join(outside) + ".")

    tallest = max(bbox(p["shapes"])[1][2] for p in stack)
    spare = ceiling - tallest
    verdict = "fits" if spare >= 0.05 * room else "tight"
    fit_note = f"The tallest stack uses {tallest - floor:.0f} of the {room:.0f} mm inside the frame, leaving {max(spare, 0):.0f} mm."
    text.append(f"{fit_note} These positions were set by the app, not the model, because parts {why}.")

    scene["fit"] = {"verdict": verdict, "note": fit_note}
    scene["summary"] = (f"Inside parts in {len(groups)} side-by-side stacks along the rails" if len(groups) > 1
                        else "Inside parts in one stack along the rails") + ", re-arranged so nothing overlaps or sticks out."
    desc = scene.get("description")
    if isinstance(desc, dict):
        desc["layout"] = " ".join(text)


def _nudge(stack, box, top):
    """Separate parts that share footprint area along z with as little movement as possible,
    keeping their order: push each up off the ones below it, then push down from the top
    whatever ended above its allowed top (top(p)). Returns {id(part): (lo, hi)}; the caller checks it."""
    new = {id(p): ([*box[id(p)][0]], [*box[id(p)][1]]) for p in stack}
    order = sorted(stack, key=lambda p: (new[id(p)][0][2], new[id(p)][1][2]))

    def stacked(a, b):        # footprints overlap, so they must not share z
        return all(min(new[id(a)][1][k], new[id(b)][1][k]) - max(new[id(a)][0][k], new[id(b)][0][k]) > OVERLAP_MM for k in range(2))

    def shift(p, dz):
        new[id(p)][0][2] += dz
        new[id(p)][1][2] += dz

    for i, p in enumerate(order):                                   # up
        below = [new[id(q)][1][2] for q in order[:i] if stacked(p, q) and new[id(q)][1][2] - new[id(p)][0][2] > OVERLAP_MM]
        if below:
            shift(p, max(below) + GAP_MM - new[id(p)][0][2])
    for i in range(len(order) - 1, -1, -1):                         # down
        p = order[i]
        caps = [top(p)] + [new[id(q)][0][2] - GAP_MM for q in order[i + 1:]
                           if stacked(p, q) and new[id(p)][1][2] - new[id(q)][0][2] > OVERLAP_MM]
        if new[id(p)][1][2] > min(caps):
            shift(p, min(caps) - new[id(p)][1][2])
    return new


def _overlap(a, b, tol: float = 0.5) -> bool:
    return all(min(a[1][k], b[1][k]) - max(a[0][k], b[0][k]) > tol for k in range(3))


def _move_to(p: dict, old, new) -> None:
    """Shift a part so its bounding box goes from old to new. Builds new shape dicts: the old
    ones may be shared with an earlier scene (edits carry parts over)."""
    d = [new[0][k] - old[0][k] for k in range(3)]
    p["shapes"] = [{**s, "center": [round(s["center"][k] + d[k], 1) for k in range(3)]} for s in p["shapes"]]
    if isinstance(p.get("place"), dict) and isinstance(p["place"].get("pos"), list):
        p["place"] = {**p["place"], "pos": [round(p["place"]["pos"][k] + d[k], 1) for k in range(3)]}


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


def _pack(items: list[dict], env: list[float]):
    """Pack the inside parts into board columns: from the bottom up, thrusters from the top down.
    Boards carry their own standoffs, so parts sit 1 mm apart; a camera's baffle goes through the
    bottom face. Used by the default layout and by the designer's will-it-fit check, so both agree.

    Returns (slots, need, room): slots = [(info, kind, library entry or None, (cx, cy, cz), (w, d, h))],
    and the fullest column's stack height against the height it has."""
    Z = env[2]
    cols = _columns(env)
    floor, ceiling = inside_z(env)
    bottom = [floor] * len(cols)
    start = [floor] * len(cols)              # lower for a column whose camera pokes through the bottom
    top = [ceiling] * len(cols)
    order = {"imager": 0, "payload_box": 0, "adcs": 1, "board": 2, "battery": 3}
    inside = sorted((i for i in items if kind_of(i["part"]) in order), key=lambda i: order[kind_of(i["part"])])
    slots = []
    for info in inside + [i for i in items if kind_of(i["part"]) == "thruster"]:
        k = kind_of(info["part"])
        e = lookup(info["part"]["part"], info["part"]["unit_mass_kg"])
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
        slots.append((info, k, e, (cx, cy, cz), (w, d, h)))
    use = [(bottom[j] - start[j] + ceiling - top[j] - GAP_MM, ceiling - start[j]) for j in range(len(cols))]
    need, room = max(use, key=lambda u: u[0] / u[1])
    return slots, need, room


def fit_verdict(need: float, room: float) -> str:
    # Within 5% over still counts as tight: real stacks can sit closer than these drawings.
    return "does_not_fit" if need > room * 1.05 else "tight" if need > room * 0.92 else "fits"


def inside_fit(parts: list[dict], envelope_mm: list[float]) -> tuple[float, float, str]:
    """Will these parts (design-style dicts: slot, part, unit_mass_kg, quantity, peak_power_w,
    estimated_placeholder) fit inside the frame? Returns (need_mm, room_mm, verdict)."""
    _, need, room = _pack(instances({"parts": parts}), envelope_mm)
    return need, room, fit_verdict(need, room)


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

    # Inside: packed into columns (see _pack).
    slots, need, room = _pack(items, env)
    for info, k, e, (cx, cy, cz), (w, d, h) in slots:
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
        half = (e["size"][1] if e else 30) / 2
        x, y = X / 4, Y / 4
        on_antenna = whips and abs(x) + half <= UHF_BASE_MM / 2 and abs(y) + half <= UHF_BASE_MM / 2
        if whips and not on_antenna:     # beside the UHF module on the top face: clear its base
            y = max(y, UHF_BASE_MM / 2 + half + 1)
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

    verdict = fit_verdict(need, room)
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
