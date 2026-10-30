"""Opus-drawn parts: a ready-made 3D drawing of each part the designer picks.

Drawn by hand (by Claude Opus in the coding session, not through the API) from
public dimensions where known, and estimated from mass and form factor where not
(`estimate=True`). The 34 parts come from running 1,536 different satellite ideas
through the designer; 8 alternates it can pick are included too.
Run `python -m visualizer --library` to list them and check coverage.
Parts drawn by Sonnet/Haiku at runtime live in ../generated/ instead (see ../README.md).

Each drawing is in the part's own frame, in mm, centered on its bounding box,
with its own +z as "up" (see placement.py):
    stack parts (boards, ADCS, cameras, thrusters)  +z = top of the stack
    side parts (solar panels)                         +z = outward (cells side), own y = along the rails
    end parts (UHF antennas, patches)                 +z = outward
    wings (deployable arrays)                         +z = cells side, own y = away from the hinge
Shapes are axis-aligned boxes; a cylinder fills its box along `axis`.
"""
from __future__ import annotations

from ...placement import recenter

LIBRARY: dict[str, dict] = {}     # normalized name -> entry (aliases share an entry)


def _key(name: str) -> str:
    return " ".join(name.lower().split())


def _add(name, vendor, mount, note, shapes, aliases=(), estimate=False, size=None):
    if size is None:                  # structures pass their envelope as size and stay on the origin
        shapes, size = recenter(shapes)
    entry = {"name": name, "vendor": vendor, "mount": mount, "note": note,
             "size": size, "shapes": shapes, "estimate": estimate, "source": "opus"}
    for n in (name, *aliases):
        LIBRARY[_key(n)] = entry


# ---------------------------------------------------------------- drawing helpers

def box(c, s, m, kind="box", axis="z"):
    return {"kind": kind, "center": [float(v) for v in c], "size": [float(v) for v in s], "axis": axis, "material": m}


def cyl(c, d, length, m, axis="z"):
    size = {"x": (length, d, d), "y": (d, length, d), "z": (d, d, length)}[axis]
    return box(c, size, m, "cylinder", axis)


def card(w=90, d=96, z=0.0, t=1.6, standoff=5, header=True, m="pcb"):
    """A PC/104 board: PCB, stack header along -x, corner standoffs underneath. Top surface at z + t."""
    out = [box((0, 0, z + t / 2), (w, d, t), m)]
    out += [cyl((sx * (w / 2 - 4.5), sy * (d / 2 - 4.5), z - standoff / 2), 5, standoff, "aluminum")
            for sx in (-1, 1) for sy in (-1, 1)]
    if header:
        out.append(box((-w / 2 + 7, 0, z + t + 4.5), (5, 64, 9), "black"))
    return out


def chips(z, spots):
    """Small black ICs: spots = [(x, y, sx, sy), ...] on a board top at height z."""
    return [box((x, y, z + 0.8), (sx, sy, 1.6), "black") for x, y, sx, sy in spots]


def coax(x, y, z, axis="x", m="gold"):
    return cyl((x, y, z), 6, 9, m, axis)


def frame(X, Y, Z):
    """CubeSat structure: rails with feet, end frames, ribs at each 1U, side posts on wide faces, stack rods."""
    r = 8.5
    out = [box((sx * (X / 2 - r / 2), sy * (Y / 2 - r / 2), 0), (r, r, Z - 13), "aluminum")
           for sx in (-1, 1) for sy in (-1, 1)]
    out += [box((sx * (X / 2 - r / 2), sy * (Y / 2 - r / 2), ez * (Z / 2 - 3.25)), (r - 1, r - 1, 6.5), "black")
            for sx in (-1, 1) for sy in (-1, 1) for ez in (-1, 1)]                               # rail feet
    out += [cyl((X / 2 - r / 2, Y / 2 - r / 2, Z / 2 + 1), 4, 2, "gold"),                       # separation springs
            cyl((-X / 2 + r / 2, -Y / 2 + r / 2, Z / 2 + 1), 4, 2, "gold")]
    out += [box((sx * (X / 2 - r / 2), -Y / 2 + r / 2 + 0.0, -Z / 2 - 1.5), (5, 5, 3), "black") for sx in (-1, 1)]  # kill switches
    ribs = [ez * (Z / 2 - 9) for ez in (-1, 1)] + [-Z / 2 + 113.5 * n for n in range(1, int(Z // 113.5))]
    for zc in ribs:
        out += [box((0, sy * (Y / 2 - 2.5), zc), (X - 2 * r, 5, 6), "aluminum") for sy in (-1, 1)]
        out += [box((sx * (X / 2 - 2.5), 0, zc), (5, Y - 2 * r, 6), "aluminum") for sx in (-1, 1)]
    if Y > 150:   # 6U / 12U: posts splitting the wide faces
        out += [box((sx * (X / 2 - 2.5), 0, 0), (5, 6, Z - 24), "aluminum") for sx in (-1, 1)]
    if X > 150:
        out += [box((0, sy * (Y / 2 - 2.5), 0), (6, 5, Z - 24), "aluminum") for sy in (-1, 1)]
    nx, ny = (2 if X > 150 else 1), (2 if Y > 150 else 1)
    for i in range(nx):
        for j in range(ny):
            cx, cy = -X / 2 + X / nx * (i + .5), -Y / 2 + Y / ny * (j + .5)
            out += [cyl((cx + sx * 40.5, cy + sy * 43.5, 0), 3, Z - 24, "titanium")
                    for sx in (-1, 1) for sy in (-1, 1)]                                           # stack rods
    return out


def panel(w, length, cells=True, extras=()):
    """Solar panel: substrate (own z = 0..1.6) with cells on +z; own y along its length."""
    out = [box((0, 0, 0.8), (w, length, 1.6), "pcb")]
    if cells:
        out.append(box((0, 0, 1.8), (w - 6, length - 8, 0.4), "solar"))
    out.append(box((0, -length / 2 + 6, -1.5), (20, 6, 3), "black"))              # harness connector (back)
    out.append(box((w / 2 - 9, length / 2 - 9, 2.3), (8, 8, 1.2), "black"))       # sun sensor
    out.append(box((w / 2 - 9, length / 2 - 9, 3.0), (5, 5, 0.3), "glass"))
    return out + list(extras)


def tapes(span, length, z, width=4):
    """Four deployed tape-spring antenna elements from the sides of a square base."""
    return ([box((sx * (span / 2 + length / 2), sy * 20, z), (length, width, 0.6), "aluminum") for sx, sy in ((1, 1), (-1, -1))]
            + [box((sx * 20, sy * (span / 2 + length / 2), z), (width, length, 0.6), "aluminum") for sx, sy in ((-1, 1), (1, -1))])


def lens_stack(d, length, z_bottom, rings=2, baffle=True):
    """Lens barrel from z_bottom upward, focus rings, glass at the bottom, optional baffle below."""
    out = [cyl((0, 0, z_bottom + length / 2), d, length, "black")]
    for k in range(rings):
        out.append(cyl((0, 0, z_bottom + length * (0.25 + 0.4 * k)), d + 5, 4, "aluminum"))
    out.append(cyl((0, 0, z_bottom + 1), d * 0.8, 2, "glass"))
    if baffle:
        out.append(cyl((0, 0, z_bottom - 6), d + 2, 12, "black"))
    return out


# ---------------------------------------------------------------- structures

for _name, _env, _vendor, _est in (
        ("1U CubeSat Structure", (100, 100, 113.5), "EnduroSat", False),
        ("3U CubeSat Structure", (100, 100, 340.5), "EnduroSat", False),
        ("6U CubeSat Structure", (100, 226.3, 366), "EnduroSat", False),
        ("12U structure (estimated)", (226.3, 226.3, 366), "TBD", True)):
    _add(_name, _vendor, "frame", "the structure itself: place at pos [0, 0, 0], up +z", frame(*_env),
         estimate=_est, size=[float(v) for v in _env])

# ---------------------------------------------------------------- boards

_add("NanoMind A3200", "GomSpace", "stack", "flight computer module on a PC/104 carrier; components on own +z",
     card() + [box((8, 6, 7.4), (65, 40, 1.6), "pcb")]
     + [cyl((8 + sx * 29, 6 + sy * 16, 4.4), 3, 4.4, "aluminum") for sx in (-1, 1) for sy in (-1, 1)]
     + chips(8.2, [(14, 10, 14, 14), (-8, 12, 9, 6), (-8, 0, 6, 6), (22, -6, 5, 5)])
     + [box((8, -12, 9.8), (34, 4, 3), "black"), box((32, -40, 3.6), (16, 6, 4), "white")])

_add("UHF Transceiver II", "EnduroSat", "stack", "radio board; shielded can on own +z, coax connectors on own +x edge",
     card() + [box((6, 0, 5.6), (66, 78, 8), "aluminum"), box((6, 0, 9.7), (34, 18, 0.2), "white")]
     + [coax(46, sy * 22, 4.5) for sy in (-1, 1)]
     + chips(1.6, [(30, 40, 8, 5), (-20, -42, 10, 5)]))

_add("TRXVU UHF/VHF Duplex", "ISISPACE", "stack", "UHF/VHF radio board; two shielded sections on own +z",
     card() + [box((14, 18, 5.1), (54, 40, 7), "aluminum"), box((14, -24, 4.6), (54, 34, 6), "aluminum")]
     + [coax(46, sy * 30, 4.5) for sy in (-1, 1)]
     + chips(1.6, [(-24, 30, 10, 10), (-24, -30, 8, 8)]))

_add("S-Band Transmitter", "EnduroSat", "stack", "S-band radio board; amplifier block and coax on own +x side",
     card() + [box((-2, 4, 5.1), (58, 70, 7), "aluminum"), box((30, -18, 6.1), (22, 30, 9), "aluminum")]
     + [coax(46, -18, 6)] + chips(1.6, [(30, 32, 10, 10), (-20, -40, 12, 6)]))

_add("X-Band Transmitter", "EnduroSat", "stack", "X-band radio board with a finned heat sink on own +z",
     card() + [box((0, 0, 5.6), (70, 80, 8), "aluminum")]
     + [box((0, -30 + 10 * k, 13.6), (60, 2, 8), "aluminum") for k in range(7)]
     + [coax(46, sy * 24, 5) for sy in (-1, 1)] + chips(1.6, [(-30, 42, 10, 5)]))

_add("NanoPower P31U", "GomSpace", "stack", "power board (EPS); converters and connectors on own +z",
     card() + chips(1.6, [(-18, 20, 12, 12), (2, 20, 12, 12), (22, 20, 12, 12), (10, -6, 16, 10)])
     + [cyl((sx * 14 + 2, -26, 5.6), 10, 8, "black") for sx in (-1, 0, 1)]                         # inductors
     + [box((34, -36, 4.6), (14, 10, 6), "white"), box((34, 36, 4.6), (14, 10, 6), "white"),
        box((-24, -40, 4.1), (22, 6, 5), "pcb")])

_add("CubeSat EPS 1.0", "NanoAvionics", "stack", "power board (EPS); components on own +z",
     card() + chips(1.6, [(-14, 18, 14, 14), (10, 18, 14, 14), (0, -10, 20, 12)])
     + [cyl((sx * 16, -32, 5.1), 9, 7, "black") for sx in (-1, 1)]
     + [box((36, sy * 30, 4.6), (10, 14, 6), "white") for sy in (-1, 1)])

_add("iEPS Type A (2-cell battery)", "ISISPACE", "stack", "power board with two 18650 cells on own +z",
     card() + [cyl((6, sy * 20, 12.6), 18.5, 65, "white", "x") for sy in (-1, 1)]
     + [box((6 + sx * 34, 0, 12.6), (3, 62, 20), "black") for sx in (-1, 1)]
     + chips(1.6, [(-30, 40, 10, 6), (34, -42, 8, 5)]))

_add("iEPS Type B (4-cell battery)", "ISISPACE", "stack", "power board with four 18650 cells on own +z",
     card() + [cyl((6, y, 12.6), 18.5, 65, "white", "x") for y in (-30, -10, 10, 30)]
     + [box((6 + sx * 34, 0, 12.6), (3, 82, 20), "black") for sx in (-1, 1)]
     + chips(1.6, [(-30, 44, 10, 5), (34, -44, 8, 4)]))

_add("Battery Pack 2S2P", "NanoAvionics", "stack", "four 18650 cells lying on a board, own +z = top",
     card() + [cyl((6, y, 12.6), 18.5, 65, "white", "x") for y in (-30, -10, 10, 30)]
     + [box((6 + sx * 34.5, 0, 12.6), (4, 84, 20), "black") for sx in (-1, 1)]              # cell holders
     + [box((6, sy * 20, 22.4), (70, 4, 1.5), "black") for sy in (-1, 1)]                   # straps
     + [box((-30, -44, 3.6), (14, 5, 4), "white")])

_add("OEM719", "NovAtel", "stack", "GNSS receiver card on a PC/104 carrier; coax on own +x edge",
     card() + [box((10, 4, 7.4), (46, 71, 1.6), "pcb"), box((10, 6, 10.2), (38, 52, 4), "aluminum")]
     + [cyl((10 + sx * 19, 4 + sy * 31, 4.4), 3, 4.4, "aluminum") for sx in (-1, 1) for sy in (-1, 1)]
     + [coax(40, -24, 9), box((10, -30, 9.4), (24, 4, 2.5), "black")])

# ---------------------------------------------------------------- attitude control

_add("CubeWheel Small (Gen1)", "CubeSpace", "stack", "one small reaction wheel on a mounting plate, own +z = top",
     [box((0, 0, 1), (90, 96, 2), "aluminum"), box((0, 0, 3), (34, 34, 2), "pcb"),
      box((0, 0, 15), (28, 28, 22), "black"), cyl((0, 0, 27.5), 26, 3, "aluminum"),
      box((20, 0, 5), (8, 10, 4), "white")])

_add("CubeADCS 3-Axis", "CubeSpace", "stack",
     "ADCS stack: computer board, three reaction wheels, magnetorquers; own +z = top",
     card() + chips(1.6, [(10, 14, 14, 14), (-14, -16, 10, 10), (24, -24, 8, 8)])
     + [box((0, 0, 14), (88, 94, 2), "aluminum")]                                               # wheel bracket
     + [cyl((sx * 40.5, sy * 43.5, 8), 5, 10, "aluminum") for sx in (-1, 1) for sy in (-1, 1)]
     + [box((-22, -22, 30), (34, 34, 30), "black"), cyl((-22, -22, 46), 30, 3, "aluminum"),    # z wheel
        box((24, -22, 32), (30, 34, 34), "black"), cyl((40, -22, 32), 30, 3, "aluminum", "x"),  # x wheel
        box((-22, 24, 32), (34, 30, 34), "black"), cyl((-22, 40, 32), 30, 3, "aluminum", "y")]  # y wheel
     + [cyl((30, 6, 8), 10, 52, "copper", "y"), cyl((0, 0, 52), 10, 60, "copper", "x")]        # torque rods
     + [box((28, 28, 51), (24, 24, 3), "pcb"), cyl((28, 28, 54), 12, 4, "glass")])             # sensor head

_add("CubeADCS Y-Momentum", "CubeSpace", "stack", "ADCS with one momentum wheel and magnetorquers; own +z = top",
     card() + chips(1.6, [(10, 14, 14, 14), (-14, -16, 10, 10)])
     + [cyl((0, 6, 20), 50, 22, "aluminum", "y"), box((0, 6, 20), (54, 6, 40), "black")]
     + [cyl((0, -36, 8), 9, 70, "copper", "x"), cyl((34, 6, 8), 9, 60, "copper", "y")], estimate=True)

_add("XACT-15", "Blue Canyon", "stack", "ADCS unit with star tracker; star-tracker lens on own +z",
     [box((0, 0, 22), (95, 95, 44), "black"), box((0, 0, 44.5), (95, 95, 1), "gold"),
      cyl((22, 22, 52), 36, 16, "black"), cyl((22, 22, 60.5), 26, 1, "glass"),
      box((-46, -20, 14), (4, 26, 10), "gold"), box((-46, 20, 14), (4, 14, 8), "black")], estimate=True)

_add("XACT-100", "Blue Canyon", "stack", "ADCS unit with star tracker; star-tracker lens on own +z",
     [box((0, 0, 48), (98, 98, 96), "black"), box((0, 0, 96.5), (98, 98, 1), "gold"),
      cyl((24, 24, 104), 40, 16, "black"), cyl((24, 24, 112.5), 30, 1, "glass"),
      box((-48, -20, 20), (4, 30, 12), "gold"), box((-48, 24, 20), (4, 16, 8), "black")], estimate=True)

# ---------------------------------------------------------------- cameras (lens on own -z)

def _imager(body_w, body_h, lens_d, lens_len, flange=True):
    out = [box((0, 0, lens_len + body_h / 2), (body_w, body_w, body_h), "black"),           # electronics / focal plane
           box((0, 0, lens_len + body_h + 0.8), (body_w - 6, body_w - 6, 1.6), "pcb"),
           box((body_w / 2 - 14, 0, lens_len + body_h + 4), (14, 26, 6), "gold"),           # connector
           box((-body_w / 2 + 12, body_w / 2 - 12, lens_len + body_h + 2.5), (12, 12, 3), "black")]
    if flange:
        out.append(box((0, 0, lens_len - 2), (body_w + 2, body_w + 2, 4), "aluminum"))     # mounting flange
    return out + lens_stack(lens_d, lens_len, 0, rings=2)


_add("MultiScape100 CIS", "Simera Sense", "stack", "multispectral camera; lens and baffle point along own -z",
     _imager(96, 60, 84, 104), aliases=("TriScape100", "HyperScape100"))
_add("Caiman", "Dragonfly Aerospace", "stack", "imager for 6U; lens and baffle point along own -z",
     _imager(96, 70, 90, 130), estimate=True)
_add("Mantis", "Dragonfly Aerospace", "stack", "compact imager; lens and baffle point along own -z",
     _imager(90, 40, 64, 50), estimate=True)

# ---------------------------------------------------------------- propulsion (nozzle on own +z)

_add("NANO (FEEP)", "Enpulsion", "stack", "FEEP thruster; emitter crown on own +z (fires along +z)",
     [box((0, 0, 30), (98, 98, 60), "aluminum"), box((0, 0, 1), (94, 94, 2), "pcb"),
      cyl((0, 0, 66), 56, 12, "titanium"), cyl((0, 0, 73), 34, 2, "gold"),
      cyl((32, 32, 66), 8, 12, "black"), cyl((-32, -32, 66), 8, 12, "black"),
      box((-47, 0, 20), (4, 30, 12), "gold")])

_add("MEMS Cold Gas Module", "NanoSpace", "stack", "cold-gas thruster module; nozzles on own +z",
     [box((0, 0, 1), (90, 96, 2), "pcb"), box((0, 0, 13), (80, 80, 20), "titanium")]
     + [cyl((sx * 34, sy * 34, 26), 6, 6, "aluminum") for sx in (-1, 1) for sy in (-1, 1)]
     + [box((0, 0, 24), (30, 30, 3), "black")], estimate=True)

_add("PUC electrothermal", "CU Aerospace / VACCO", "stack", "warm-gas thruster; nozzle on own +z",
     [box((0, 0, 1), (94, 94, 2), "pcb"), box((0, 0, 24), (90, 90, 40), "titanium"),
      box((26, 26, 48), (22, 22, 8), "aluminum"), cyl((0, 0, 51), 16, 14, "aluminum"),
      cyl((0, 0, 59), 10, 3, "black")], estimate=True)

_add("BIT-3 RF ion (iodine)", "Busek", "stack", "RF ion thruster with iodine tank; thruster head on own +z",
     [box((0, 0, 1), (94, 94, 2), "pcb"), box((0, 0, 24), (94, 94, 44), "aluminum"),          # power unit
      cyl((0, 0, 74), 70, 56, "titanium"),                                                     # propellant tank
      cyl((0, 0, 112), 52, 20, "black"), cyl((0, 0, 122.5), 44, 1, "gold"),                    # thruster head + grid
      cyl((34, 34, 112), 10, 16, "aluminum")], estimate=True)                                  # cathode

_add("MiPS (cold gas)", "VACCO", "stack", "cold-gas propulsion unit; four nozzles on own +z",
     [box((0, 0, 44), (96, 96, 88), "titanium"), box((0, 0, 1), (92, 92, 2), "pcb")]
     + [cyl((sx * 38, sy * 38, 92), 8, 8, "aluminum") for sx in (-1, 1) for sy in (-1, 1)]
     + [box((0, 0, 89), (40, 40, 2), "gold")], estimate=True)

# ---------------------------------------------------------------- solar (cells on own +z, length along own y)

_add("1U Solar Panel X/Y", "EnduroSat", "side", "body panel for a 1U face; cells on own +z, own y along the rails",
     panel(83, 98))
_add("3U Solar Panel (body-mounted)", "EnduroSat", "side", "body panel for a 3U long face; cells on own +z, own y along the rails",
     panel(83, 326))
_add("6U Solar Panel", "EnduroSat", "side",
     "panel for a 226 x 366 face (a 6U/12U wide face); cells on own +z, own y along the rails; on a 6U only the two wide faces fit it, so extra ones are wings",
     panel(220, 360))
_add("3U Deployable Solar Array", "EnduroSat", "wing",
     "deployed wing; cells on own +z, hinge at its own -y end, place it with up +z at the top end reaching outward",
     panel(83, 326, extras=[cyl((sx * 30, -166, 0.8), 6, 14, "aluminum", "x") for sx in (-1, 1)]), estimate=True)
_add("3U Double Deployable Solar Array", "EnduroSat", "wing",
     "deployed two-panel wing; cells on own +z, hinge at its own -y end, place it with up +z at the top end reaching outward",
     [{**s, "center": [s["center"][0], s["center"][1] + dy, s["center"][2]]}
      for dy in (-167, 167) for s in panel(83, 326)]                                          # two panels
     + [cyl((sx * 30, y, 0.8), 6, 14, "aluminum", "x") for sx in (-1, 1) for y in (-334, 0)],  # hinges
     estimate=True)

# ---------------------------------------------------------------- antennas (outward on own +z)

_add("UHF Antenna 1U", "EnduroSat", "end",
     "UHF antenna module for an end face (98 x 98 base); size includes the four deployed tape antennas",
     [box((0, 0, 0.8), (98, 98, 1.6), "pcb")]
     + [box((0, sy * 40, 4.6), (98, 18, 6), "black") for sy in (-1, 1)]
     + [box((sx * 40, 0, 4.6), (18, 62, 6), "black") for sx in (-1, 1)]
     + [box((sx * 40, sy * 40, 8.2), (8, 8, 1.4), "white") for sx in (-1, 1) for sy in (-1, 1)]   # burn resistors
     + tapes(98, 172, 5))

_add("CubeSat Antenna System 1U/3U", "ISISPACE", "end",
     "deployable UHF/VHF antenna system for an end face (98 x 98 base); size includes the deployed elements",
     [box((0, 0, 3.5), (98, 98, 7), "black"), box((0, 0, 7.2), (60, 60, 0.4), "pcb")]
     + [box((sx * 44, sy * 44, 7.6), (8, 8, 1.2), "aluminum") for sx in (-1, 1) for sy in (-1, 1)]
     + tapes(98, 520, 4, width=3)[:2] + tapes(98, 170, 4, width=3)[2:])

_add("GNSS Patch Antenna L1/E1", "EnduroSat", "end", "small GNSS patch; radiating side on own +z, face it to zenith",
     [box((0, 0, 0.8), (40, 40, 1.6), "pcb"), box((0, 0, 3.6), (25, 25, 4), "white"),
      box((0, 0, 5.75), (18, 18, 0.3), "aluminum"), cyl((3, 3, 6), 2, 0.6, "gold"),
      cyl((0, 0, -3), 6, 6, "gold")])

_add("S-band Antenna Commercial", "EnduroSat", "end", "2 x 2 S-band patch array; radiating side on own +z",
     [box((0, 0, 0.8), (82, 82, 1.6), "white")]
     + [box((sx * 20, sy * 20, 1.8), (30, 30, 0.4), "copper") for sx in (-1, 1) for sy in (-1, 1)]
     + [cyl((0, 0, -3), 6, 6, "gold"), box((0, 0, -0.5), (60, 60, 1), "aluminum")])

_add("X-band 4x4 Patch Antenna", "EnduroSat", "end", "4 x 4 X-band patch array; radiating side on own +z",
     [box((0, 0, 0.8), (80, 80, 1.6), "white"), box((0, 0, -0.5), (70, 70, 1), "aluminum")]
     + [box((-25.5 + 17 * i, -25.5 + 17 * j, 1.8), (9, 9, 0.4), "copper") for i in range(4) for j in range(4)]
     + [cyl((0, 0, -3.5), 6, 5, "gold")])


# ---------------------------------------------------------------- payload placeholders

def placeholder_payload(name: str, mass_kg: float) -> dict:
    """'Sensor payload (to be chosen)' etc.: a generic box sized from the mass allowance."""
    h = max(30.0, min(200.0, mass_kg * 90))
    sensor = "sensor" in name.lower()
    shapes = [box((0, 0, 1), (88, 88, 2), "pcb"), box((0, 0, 2 + h / 2), (84, 84, h), "gold"),
              box((30, 30, h + 3.5), (16, 24, 3), "black")]
    if sensor:
        shapes.append(cyl((0, 0, -4), 30, 8, "black"))                     # sensor head on own -z
    shapes, size = recenter(shapes)
    return {"name": name, "vendor": "TBD", "mount": "stack",
            "note": "payload not chosen yet: a box sized from its mass allowance" + ("; sensor head on own -z" if sensor else ""),
            "size": size, "shapes": shapes, "estimate": True, "source": "opus"}


def entries() -> list[dict]:
    """Each library entry once (aliases share an entry)."""
    seen, out = set(), []
    for e in LIBRARY.values():
        if id(e) not in seen:
            seen.add(id(e))
            out.append(e)
    return out
