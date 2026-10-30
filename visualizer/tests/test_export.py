"""STEP and STL export: structure checks with the standard library only.

The geometry was also checked in OpenCASCADE (the kernel FreeCAD uses): every solid valid,
volumes matching the scene, names and colours read back.
"""
import math
import re
import struct
import unittest

from designer import run
from visualizer import default_scene
from visualizer.export import STL_SEGMENTS, file_name, to_step, to_stl


def scene(idea="6U camera cubesat"):
    return default_scene(run(idea, use_llm=False).data["design"])


class ExportTest(unittest.TestCase):
    def test_one_solid_per_shape_and_one_component_per_part(self):
        sc = scene()
        step = to_step(sc, "6U camera")
        self.assertTrue(step.startswith("ISO-10303-21;"))
        self.assertTrue(step.rstrip().endswith("END-ISO-10303-21;"))
        self.assertIn("AUTOMOTIVE_DESIGN", step)
        self.assertIn("SI_UNIT(.MILLI.,.METRE.)", step)
        shapes = [s for p in sc["parts"] for s in p["shapes"]]
        self.assertEqual(step.count("MANIFOLD_SOLID_BREP("), len(shapes))
        self.assertEqual(step.count("CYLINDRICAL_SURFACE("), sum(s["kind"] == "cylinder" for s in shapes))
        self.assertEqual(step.count("NEXT_ASSEMBLY_USAGE_OCCURRENCE("), len(sc["parts"]))
        self.assertEqual(step.count("STYLED_ITEM("), len(shapes))

    def test_entity_references_all_resolve(self):
        step = to_step(scene("1U iot radio relay"), "relay")
        defined = set(re.findall(r"^#(\d+)=", step, re.M))
        used = set(re.findall(r"#(\d+)", step))
        self.assertEqual(used - defined, set())

    def test_exploded_moves_parts(self):
        sc = {"parts": [{"label": "Board", "explode": [0, 0, 50],
                         "shapes": [{"kind": "box", "center": [0, 0, 0], "size": [10, 10, 2], "axis": "z", "material": "pcb"}]}]}
        self.assertIn("(5.,5.,1.)", to_step(sc))
        self.assertIn("(5.,5.,51.)", to_step(sc, exploded=True))

    def test_names_are_escaped_and_made_unique(self):
        shape = {"kind": "cylinder", "center": [0, 0, 0], "size": [8, 8, 20], "axis": "x", "material": "gold"}
        sc = {"parts": [{"label": "Bob's µ-laser", "shapes": [shape]}, {"label": "Bob's µ-laser", "shapes": [shape]}]}
        step = to_step(sc)
        self.assertIn("'Bob''s \\X2\\00B5\\X0\\-laser'", step)
        self.assertIn("'Bob''s \\X2\\00B5\\X0\\-laser #2'", step)
        step.encode("ascii")    # STEP files are plain ASCII

    def test_file_name(self):
        self.assertEqual(file_name("6U camera CubeSat"), "6U-camera-CubeSat.step")
        self.assertEqual(file_name("6U camera CubeSat", "stl"), "6U-camera-CubeSat.stl")
        self.assertEqual(file_name("???"), "cubesat.step")


def stl_triangles(data):
    count = struct.unpack_from("<I", data, 80)[0]
    assert len(data) == 84 + 50 * count
    return [struct.unpack_from("<12f", data, 84 + 50 * n) for n in range(count)]


def signed_volume(tris):
    """Positive only if every triangle winds counter-clockwise seen from outside."""
    return sum((a[0] * (b[1] * c[2] - b[2] * c[1]) - a[1] * (b[0] * c[2] - b[2] * c[0])
                + a[2] * (b[0] * c[1] - b[1] * c[0])) / 6 for _, a, b, c in
               ((t[0:3], t[3:6], t[6:9], t[9:12]) for t in tris))


class StlTest(unittest.TestCase):
    def one(self, shape):
        return stl_triangles(to_stl({"parts": [{"label": "p", "explode": [0, 0, 50], "shapes": [shape]}]}))

    def test_box_is_closed_outward_and_exact(self):
        tris = self.one({"kind": "box", "center": [3, -2, 7], "size": [10, 20, 4]})
        self.assertEqual(len(tris), 12)
        self.assertAlmostEqual(signed_volume(tris), 10 * 20 * 4, places=2)

    def test_cylinders_along_each_axis(self):
        for axis in "xyz":
            with self.subTest(axis=axis):
                size = {"x": [30, 8, 9], "y": [8, 30, 9], "z": [8, 9, 30]}[axis]
                tris = self.one({"kind": "cylinder", "center": [5, 5, -5], "size": size, "axis": axis})
                self.assertEqual(len(tris), 4 * STL_SEGMENTS)
                polygon = STL_SEGMENTS / 2 * 4 ** 2 * math.sin(2 * math.pi / STL_SEGMENTS)   # radius 4
                self.assertAlmostEqual(signed_volume(tris), polygon * 30, places=1)
                for t in tris:     # stored normals point the way the winding does
                    n, a, b, c = t[0:3], t[3:6], t[6:9], t[9:12]
                    cross = [(b[1] - a[1]) * (c[2] - a[2]) - (b[2] - a[2]) * (c[1] - a[1]),
                             (b[2] - a[2]) * (c[0] - a[0]) - (b[0] - a[0]) * (c[2] - a[2]),
                             (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])]
                    self.assertGreater(sum(x * y for x, y in zip(n, cross)), 0)

    def test_whole_design_and_exploded(self):
        sc = scene()
        data = to_stl(sc, "6U camera")
        self.assertFalse(data.startswith(b"solid"))     # would be mistaken for ASCII STL
        shapes = [s for p in sc["parts"] for s in p["shapes"]]
        self.assertEqual(len(stl_triangles(data)),
                         sum(4 * STL_SEGMENTS if s["kind"] == "cylinder" else 12 for s in shapes))
        moved = stl_triangles(to_stl({"parts": [{"explode": [0, 0, 50], "shapes": [
            {"kind": "box", "center": [0, 0, 0], "size": [2, 2, 2]}]}]}, exploded=True))
        self.assertEqual(min(t[5] for t in moved), 49)


if __name__ == "__main__":
    unittest.main()
