"""Export a scene for CAD: STEP (solid assembly) or STL (triangle mesh).

STEP (ISO 10303-21, AP214) is what CAD tools import as solids. The file is an assembly: one component per part (named after it, e.g. "Solar panel (2/4)"),
each holding one solid per box or cylinder, coloured by material. Geometry stays in the
satellite's body frame in mm (origin at the center of the structure, +z the top end), so
every component sits at the identity and parts can be moved apart in CAD. Opens in
SolidWorks, Fusion 360, FreeCAD, Onshape, Inventor and anything else that reads STEP.

STL is one binary triangle mesh in mm, with no names or colours. Slicers for 3D printing
and mesh tools read it, and CAD tools can import it as a mesh body.

Only the standard library is used: boxes and cylinders are written straight out as
B-rep (planes, lines, circles and a cylindrical surface) or as triangles.
"""
from __future__ import annotations

import math
import re
import struct
from datetime import datetime, timezone

# Plain colours for CAD, close to how the page draws each material (RGB 0-1).
COLOURS = {
    "aluminum": (0.76, 0.79, 0.82), "black": (0.17, 0.18, 0.21), "pcb": (0.12, 0.48, 0.29),
    "solar": (0.11, 0.18, 0.44), "gold": (0.83, 0.65, 0.23), "glass": (0.56, 0.76, 1.0),
    "copper": (0.77, 0.48, 0.27), "white": (0.91, 0.91, 0.93), "titanium": (0.54, 0.56, 0.6),
    "kapton": (0.79, 0.54, 0.11),
}
STL_SEGMENTS = 48    # sides on a cylinder in the mesh
UNIT = {"x": (1.0, 0.0, 0.0), "y": (0.0, 1.0, 0.0), "z": (0.0, 0.0, 1.0)}
ACROSS = {"x": (0.0, 1.0, 0.0), "y": (0.0, 0.0, 1.0), "z": (1.0, 0.0, 0.0)}   # any direction normal to the axis


def _str(s: str) -> str:
    """A STEP string literal: quotes doubled, non-ASCII as \\X2\\ hex."""
    out = []
    for ch in str(s):
        if ch == "'":
            out.append("''")
        elif ch == "\\":
            out.append("\\\\")
        elif 32 <= ord(ch) < 127:
            out.append(ch)
        elif ord(ch) <= 0xFFFF:
            out.append(f"\\X2\\{ord(ch):04X}\\X0\\")
    return "'" + "".join(out) + "'"


def _num(v: float) -> str:
    return f"{v:.6f}".rstrip("0")       # STEP reals need the ".": 12.5 -> "12.5", 3 -> "3."


def _sub(a, b):
    return tuple(x - y for x, y in zip(a, b))


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _dot(a, b):
    return sum(x * y for x, y in zip(a, b))


class _Writer:
    def __init__(self):
        self.lines: list[str] = []

    def add(self, entity: str) -> str:
        self.lines.append(entity)
        return f"#{len(self.lines)}"

    def point(self, p):
        return self.add(f"CARTESIAN_POINT('',({','.join(map(_num, p))}))")

    def direction(self, d):
        return self.add(f"DIRECTION('',({','.join(map(_num, d))}))")

    def axis(self, origin, z, x):
        return self.add(f"AXIS2_PLACEMENT_3D('',{self.point(origin)},{self.direction(z)},{self.direction(x)})")

    def vertex(self, p):
        return self.add(f"VERTEX_POINT('',{self.point(p)})")

    def line_edge(self, va, vb, a, b):
        d = _sub(b, a)
        length = _dot(d, d) ** 0.5
        vec = self.add(f"VECTOR('',{self.direction(tuple(x / length for x in d))},{_num(length)})")
        line = self.add(f"LINE('',{self.point(a)},{vec})")
        return self.add(f"EDGE_CURVE('',{va},{vb},{line},.T.)")

    def face(self, oriented_edges, surface):
        loop = self.add(f"EDGE_LOOP('',({','.join(oriented_edges)}))")
        bound = self.add(f"FACE_OUTER_BOUND('',{loop},.T.)")
        return self.add(f"ADVANCED_FACE('',({bound}),{surface},.T.)")

    def oriented(self, edge, forward):
        return self.add(f"ORIENTED_EDGE('',*,*,{edge},{'.T.' if forward else '.F.'})")

    def solid(self, name, faces):
        shell = self.add(f"CLOSED_SHELL('',({','.join(faces)}))")
        return self.add(f"MANIFOLD_SOLID_BREP({_str(name)},{shell})")

    # ---- shapes
    def box(self, name, center, size):
        half = [s / 2 for s in size]
        corners = [tuple(center[i] + (half[i] if (n >> i) & 1 else -half[i]) for i in range(3)) for n in range(8)]
        verts = [self.vertex(c) for c in corners]
        edges = {}
        for n in range(8):
            for i in range(3):
                m = n | (1 << i)
                if m != n:
                    edges[(n, m)] = self.line_edge(verts[n], verts[m], corners[n], corners[m])
        faces = []
        for i in range(3):
            for high in (0, 1):
                normal = tuple((1.0 if high else -1.0) if j == i else 0.0 for j in range(3))
                j = (i + 1) % 3
                quad = [n for n in range(8) if (n >> i) & 1 == high]
                quad = [quad[0], quad[1], quad[3], quad[2]]                 # walk around the face
                turn = _cross(_sub(corners[quad[1]], corners[quad[0]]), _sub(corners[quad[2]], corners[quad[1]]))
                if _dot(turn, normal) < 0:
                    quad.reverse()                                          # counter-clockwise seen from outside
                loop = []
                for a, b in zip(quad, quad[1:] + quad[:1]):
                    loop.append(self.oriented(edges[(min(a, b), max(a, b))], a < b))
                face_center = tuple(center[d] + (normal[d] * half[d]) for d in range(3))
                plane = self.add(f"PLANE('',{self.axis(face_center, normal, UNIT['xyz'[j]])})")
                faces.append(self.face(loop, plane))
        return self.solid(name, faces)

    def cylinder(self, name, center, size, axis_name):
        a, u = UNIT[axis_name], ACROSS[axis_name]
        i = "xyz".index(axis_name)
        length = size[i]
        radius = min(size[j] for j in range(3) if j != i) / 2
        base = tuple(center[d] - a[d] * length / 2 for d in range(3))
        top = tuple(center[d] + a[d] * length / 2 for d in range(3))
        p0 = tuple(base[d] + u[d] * radius for d in range(3))
        p1 = tuple(top[d] + u[d] * radius for d in range(3))
        v0, v1 = self.vertex(p0), self.vertex(p1)
        rings = []
        for c, v in ((base, v0), (top, v1)):
            circle = self.add(f"CIRCLE('',{self.axis(c, a, u)},{_num(radius)})")
            rings.append(self.add(f"EDGE_CURVE('',{v},{v},{circle},.T.)"))
        seam = self.line_edge(v0, v1, p0, p1)
        side = self.add(f"CYLINDRICAL_SURFACE('',{self.axis(base, a, u)},{_num(radius)})")
        down = tuple(-x for x in a)
        faces = [
            self.face([self.oriented(rings[0], True), self.oriented(seam, True),
                       self.oriented(rings[1], False), self.oriented(seam, False)], side),
            self.face([self.oriented(rings[0], False)], self.add(f"PLANE('',{self.axis(base, down, u)})")),
            self.face([self.oriented(rings[1], True)], self.add(f"PLANE('',{self.axis(top, a, u)})")),
        ]
        return self.solid(name, faces)


def _product(w: _Writer, name: str, ctx: str, pdc: str) -> tuple[str, str]:
    """A product and its definition; returns (product_definition, product_definition_shape)."""
    prod = w.add(f"PRODUCT({_str(name)},{_str(name)},'',({ctx}))")
    w.add(f"PRODUCT_RELATED_PRODUCT_CATEGORY('part',$,({prod}))")
    pdf = w.add(f"PRODUCT_DEFINITION_FORMATION('','',{prod})")
    pd = w.add(f"PRODUCT_DEFINITION('design','',{pdf},{pdc})")
    return pd, w.add(f"PRODUCT_DEFINITION_SHAPE('','',{pd})")


def file_name(scene_name: str, ext: str = "step") -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", scene_name).strip("-")[:60] or "cubesat"
    return f"{slug}.{ext}"


def to_step(scene: dict, name: str = "CubeSat", exploded: bool = False) -> str:
    """The scene as STEP text. exploded=True moves each part by its exploded-view offset."""
    w = _Writer()
    app = w.add("APPLICATION_CONTEXT('core data for automotive mechanical design processes')")
    w.add(f"APPLICATION_PROTOCOL_DEFINITION('international standard','automotive_design',2000,{app})")
    ctx = w.add(f"PRODUCT_CONTEXT('',{app},'mechanical')")
    pdc = w.add(f"PRODUCT_DEFINITION_CONTEXT('part definition',{app},'design')")
    mm = w.add("(LENGTH_UNIT()NAMED_UNIT(*)SI_UNIT(.MILLI.,.METRE.))")
    rad = w.add("(NAMED_UNIT(*)PLANE_ANGLE_UNIT()SI_UNIT($,.RADIAN.))")
    sr = w.add("(NAMED_UNIT(*)SI_UNIT($,.STERADIAN.)SOLID_ANGLE_UNIT())")
    tol = w.add(f"UNCERTAINTY_MEASURE_WITH_UNIT(LENGTH_MEASURE(1.E-04),{mm},'distance_accuracy_value','')")
    geo = w.add(f"(GEOMETRIC_REPRESENTATION_CONTEXT(3)GLOBAL_UNCERTAINTY_ASSIGNED_CONTEXT(({tol}))"
                f"GLOBAL_UNIT_ASSIGNED_CONTEXT(({mm},{rad},{sr}))REPRESENTATION_CONTEXT('3D',''))")
    origin = (0.0, 0.0, 0.0)

    styles = {}
    for mat, (r, g, b) in COLOURS.items():
        colour = w.add(f"COLOUR_RGB('',{_num(r)},{_num(g)},{_num(b)})")
        area = w.add(f"FILL_AREA_STYLE_COLOUR('',{colour})")
        fill = w.add(f"FILL_AREA_STYLE('',({area}))")
        side = w.add(f"SURFACE_SIDE_STYLE('',({w.add(f'SURFACE_STYLE_FILL_AREA({fill})')}))")
        usage = w.add(f"SURFACE_STYLE_USAGE(.BOTH.,{side})")
        styles[mat] = w.add(f"PRESENTATION_STYLE_ASSIGNMENT(({usage}))")

    top_pd, top_pds = _product(w, name, ctx, pdc)
    top_items, styled, used = [w.axis(origin, UNIT["z"], UNIT["x"])], [], {}
    links = []
    for part in scene["parts"]:
        label = str(part.get("label") or part.get("ref") or "part")
        used[label] = used.get(label, 0) + 1
        if used[label] > 1:
            label = f"{label} #{used[label]}"          # CAD trees want unique component names
        shift = part.get("explode") if exploded else None
        solids = []
        for n, s in enumerate(part["shapes"], 1):
            c = [s["center"][d] + (shift[d] if shift else 0) for d in range(3)]
            solid = (w.cylinder(f"{label} {n}", c, s["size"], s.get("axis", "z")) if s.get("kind") == "cylinder"
                     else w.box(f"{label} {n}", c, s["size"]))
            solids.append(solid)
            styled.append(w.add(f"STYLED_ITEM('',({styles.get(s.get('material'), styles['aluminum'])}),{solid})"))
        if not solids:
            continue
        pd, pds = _product(w, label, ctx, pdc)
        own_axis = w.axis(origin, UNIT["z"], UNIT["x"])
        rep = w.add(f"ADVANCED_BREP_SHAPE_REPRESENTATION({_str(label)},({own_axis},{','.join(solids)}),{geo})")
        w.add(f"SHAPE_DEFINITION_REPRESENTATION({pds},{rep})")
        place = w.axis(origin, UNIT["z"], UNIT["x"])
        top_items.append(place)
        links.append((label, pd, rep, own_axis, place))

    top_rep = w.add(f"SHAPE_REPRESENTATION({_str(name)},({','.join(top_items)}),{geo})")
    w.add(f"SHAPE_DEFINITION_REPRESENTATION({top_pds},{top_rep})")
    for n, (label, pd, rep, own_axis, place) in enumerate(links, 1):
        nauo = w.add(f"NEXT_ASSEMBLY_USAGE_OCCURRENCE('{n}',{_str(label)},'',{top_pd},{pd},$)")
        pds = w.add(f"PRODUCT_DEFINITION_SHAPE('','',{nauo})")
        move = w.add(f"ITEM_DEFINED_TRANSFORMATION('','',{own_axis},{place})")
        rel = w.add(f"(REPRESENTATION_RELATIONSHIP('','',{rep},{top_rep})"
                    f"REPRESENTATION_RELATIONSHIP_WITH_TRANSFORMATION({move})SHAPE_REPRESENTATION_RELATIONSHIP())")
        w.add(f"CONTEXT_DEPENDENT_SHAPE_REPRESENTATION({rel},{pds})")
    if styled:
        w.add(f"MECHANICAL_DESIGN_GEOMETRIC_PRESENTATION_REPRESENTATION('',({','.join(styled)}),{geo})")

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    header = [
        "ISO-10303-21;", "HEADER;",
        f"FILE_DESCRIPTION(({_str(name)}),'2;1');",
        f"FILE_NAME({_str(file_name(name))},'{stamp}',(''),(''),'CubeSat designer','CubeSat designer','');",
        "FILE_SCHEMA(('AUTOMOTIVE_DESIGN { 1 0 10303 214 1 1 1 1 }'));", "ENDSEC;", "DATA;",
    ]
    body = [f"#{n}={line};" for n, line in enumerate(w.lines, 1)]
    return "\n".join(header + body + ["ENDSEC;", "END-ISO-10303-21;", ""])


# ---------------------------------------------------------------- STL

def _box_triangles(center, size):
    half = [v / 2 for v in size]
    corner = lambda n: tuple(center[i] + (half[i] if (n >> i) & 1 else -half[i]) for i in range(3))
    tris = []
    for i in range(3):
        for high in (0, 1):
            normal = tuple((1.0 if high else -1.0) if j == i else 0.0 for j in range(3))
            quad = [corner(n) for n in range(8) if (n >> i) & 1 == high]
            quad = [quad[0], quad[1], quad[3], quad[2]]                     # walk around the face
            if _dot(_cross(_sub(quad[1], quad[0]), _sub(quad[2], quad[1])), normal) < 0:
                quad.reverse()                                              # counter-clockwise seen from outside
            tris += [(normal, quad[0], quad[1], quad[2]), (normal, quad[0], quad[2], quad[3])]
    return tris


def _cylinder_triangles(center, size, axis_name, segments=STL_SEGMENTS):
    i = "xyz".index(axis_name)
    a, u = UNIT[axis_name], ACROSS[axis_name]
    v = _cross(a, u)                                   # u, v, a is right-handed
    length = size[i]
    radius = min(size[j] for j in range(3) if j != i) / 2
    base = tuple(center[d] - a[d] * length / 2 for d in range(3))
    top = tuple(center[d] + a[d] * length / 2 for d in range(3))
    down = tuple(-x for x in a)
    ring = [(math.cos(2 * math.pi * k / segments), math.sin(2 * math.pi * k / segments)) for k in range(segments)]
    at = lambda c, cs: tuple(c[d] + radius * (cs[0] * u[d] + cs[1] * v[d]) for d in range(3))
    tris = []
    for k in range(segments):
        c0, c1 = ring[k], ring[(k + 1) % segments]
        mid = (math.cos(2 * math.pi * (k + .5) / segments), math.sin(2 * math.pi * (k + .5) / segments))
        normal = tuple(mid[0] * u[d] + mid[1] * v[d] for d in range(3))
        b0, b1, t0, t1 = at(base, c0), at(base, c1), at(top, c0), at(top, c1)
        tris += [(normal, b0, b1, t1), (normal, b0, t1, t0),
                 (down, base, b1, b0), (a, top, t0, t1)]
    return tris


def to_stl(scene: dict, name: str = "CubeSat", exploded: bool = False) -> bytes:
    """The scene as one binary STL mesh in mm. exploded=True moves each part by its exploded-view offset."""
    tris = []
    for part in scene["parts"]:
        shift = part.get("explode") if exploded else None
        for s in part["shapes"]:
            c = [s["center"][d] + (shift[d] if shift else 0) for d in range(3)]
            tris += (_cylinder_triangles(c, s["size"], s.get("axis", "z")) if s.get("kind") == "cylinder"
                     else _box_triangles(c, s["size"]))
    # A header starting with "solid" makes some readers take the file for ASCII STL.
    header = f"CubeSat designer, mm: {name}".encode("ascii", "replace")[:80].ljust(80, b" ")
    out = [header, struct.pack("<I", len(tris))]
    for normal, p0, p1, p2 in tris:
        out.append(struct.pack("<12fH", *normal, *p0, *p1, *p2, 0))
    return b"".join(out)
