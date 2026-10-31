"""Offline tests: a fake API client stands in for Claude, so no tokens are spent.

Run from the repo root:  python -m pytest visualizer/tests
"""
import copy
import json
import math
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from designer import run
from visualizer import SceneGenerator, TokenUsage, default_scene, repair
from visualizer import library
from visualizer.budget import SONNET_MODEL, cost_usd
from visualizer.placement import body_size, place
from visualizer import scene as sc
from visualizer.generator import build_prompt
from visualizer.placement import bbox
from visualizer.scene import REACH_MM, envelope, instances


def design(idea="3U camera cubesat"):
    return run(idea, use_llm=False).data["design"]


def placements_for(d, refs=None, extras=(), drop=()):
    """What a well-behaved model returns: the rule-based layout's placements (shapes left to the
    library), a role per part, a description, and any extras."""
    out = []
    for p in default_scene(d)["parts"]:
        if refs is None or p["ref"] in refs:
            m = p["place"]
            out.append({"ref": p["ref"], "role": f"role of {p['label']}", "pos": m["pos"], "up": m["up"],
                        "spin": str(m["spin"]), "shapes": []})
    return {"summary": "test layout", "fit": {"verdict": "fits", "note": "ok"},
            "description": {"overview": "how it works", "layout": "why it fits"},
            "parts": out, "extras": list(extras), "drop_extras": list(drop)}


LASER = {"name": "Pulsed laser emitter", "purpose": "Fires a low-power laser for the demo.", "mass_kg": 0.4, "power_w": 12,
         "pos": [0, 0, 60], "up": "+z", "spin": "0",
         "shapes": [{"k": "box", "c": [0, 0, 0], "s": [60, 60, 30], "a": "z", "m": "black"},
                    {"k": "cylinder", "c": [0, 0, 20], "s": [20, 20, 10], "a": "z", "m": "glass"}]}


class FakeClient:
    """Answers like the model: placements for the refs the prompt asks for.
    `script` maps model -> list of behaviours ("ok", "error", "truncate") used in order."""

    def __init__(self, out_tokens=1200, script=None):
        self.out_tokens, self.script, self.calls = out_tokens, script or {}, []
        self.extras, self.drop = [], []     # what the next replies add / remove
        self.messages = self

    def create(self, **kw):
        self.calls.append(kw)
        how = self.script[kw["model"]].pop(0) if self.script.get(kw["model"]) else "ok"
        if how == "error":
            raise RuntimeError("API down")
        prompt = kw["messages"][0]["content"]
        rows = json.loads(prompt.rsplit("\n", 1)[-1])             # the "place these" list is the last line
        d = self.design_for(prompt)
        text = "" if how == "truncate" else json.dumps(placements_for(d, {r["ref"] for r in rows}, self.extras, self.drop))
        return SimpleNamespace(stop_reason="max_tokens" if how == "truncate" else "end_turn",
                               usage=SimpleNamespace(input_tokens=3000, output_tokens=min(self.out_tokens, kw["max_tokens"])),
                               content=[SimpleNamespace(type="text", text=text)])

    design_for = None   # set per test: prompt -> design


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.usage = TokenUsage(Path(self.tmp.name) / "usage.json")
        self.generated = Path(self.tmp.name) / "generated"      # never write into the real library
        self.real_generated = library.GENERATED_DIR
        library.set_generated_dir(self.generated)
        self.d = design()

    def tearDown(self):
        library.set_generated_dir(self.real_generated)
        self.tmp.cleanup()

    def gen(self, designs=None, **kw):
        client = FakeClient(**kw)
        designs = designs or [self.d]
        client.design_for = lambda prompt: next(
            (d for d in reversed(designs) if f"Satellite: {d['name']}" in prompt and d["form_factor"] in prompt), designs[-1])
        return SceneGenerator(self.usage, client=client), client


class LibraryTest(unittest.TestCase):
    def test_library_covers_every_part_the_designer_picks(self):
        ideas = ["1U iot radio relay", "1U camera", "3U camera at 550 km for 2 years", "3U camera at 300 km for 3 years",
                 "3U radio relay at 600 km needs a thruster", "3U radiation sensor at 800 km", "6U camera for wildfires",
                 "6U technology demo payload at 350 km for 5 years", "12U camera", "12U radio relay needs GPS"]
        for idea in ideas:
            for p in design(idea)["parts"]:
                self.assertIsNotNone(library.lookup(p["part"], p["unit_mass_kg"]), f"{p['part']} ({idea})")

    def test_entries_are_centered_and_sized(self):
        for e in library.entries():
            self.assertTrue(all(v > 0 for v in e["size"]), e["name"])
            self.assertLessEqual(len(e["shapes"]), 60, e["name"])

    def test_placeholder_payload_grows_with_mass(self):
        small, big = library.lookup("Sensor payload (to be chosen)", 0.4), library.lookup("Sensor payload (to be chosen)", 2.0)
        self.assertGreater(big["size"][2], small["size"][2])


class PlacementTest(unittest.TestCase):
    def test_side_faces_put_own_y_along_the_rails(self):
        size = [83, 326, 6]                                   # a 3U panel: own y = its length
        for up, thin in (("+x", 0), ("-x", 0), ("+y", 1), ("-y", 1)):
            s = body_size(size, up, 0)
            self.assertEqual(s[2], 326, up)
            self.assertEqual(s[thin], 6, up)

    def test_spin_swaps_footprint_and_down_flips(self):
        self.assertEqual(body_size([90, 50, 10], "+z", 90), [50, 90, 10])
        lens = {"kind": "cylinder", "center": [0, 0, -40], "size": [60, 60, 20], "axis": "z", "material": "glass"}
        self.assertEqual(place([lens], [0, 0, 0], "-z")[0]["center"], [0, 0, 40])   # turned over: lens now on top
        rod = {"kind": "cylinder", "center": [10, 0, 0], "size": [50, 8, 8], "axis": "x", "material": "copper"}
        moved = place([rod], [1, 2, 3], "+z", 90)[0]
        self.assertEqual((moved["axis"], moved["center"]), ("y", [1, 12, 3]))


class DefaultSceneTest(unittest.TestCase):
    def test_every_physical_item_is_drawn_once_from_the_library(self):
        for idea in ("1U iot radio relay", "3U camera at 300 km for 3 years", "6U camera", "12U camera", "3U sensor"):
            d = design(idea)
            s = default_scene(d)
            self.assertEqual([p["ref"] for p in s["parts"]], [i["ref"] for i in instances(d)], idea)
            self.assertTrue(all("place" in p for p in s["parts"]), idea)

    def test_structure_stays_put_and_parts_stay_in_reach(self):
        d = design()
        env = envelope(d)
        for p in default_scene(d)["parts"]:
            if p["part_index"] == 0:
                self.assertEqual(p["explode"], [0, 0, 0])
            for s in p["shapes"]:
                for i in range(3):
                    self.assertLessEqual(abs(s["center"][i]), env[i] / 2 + REACH_MM)

    def test_volume_verdict(self):
        self.assertEqual(default_scene(design("3U radio relay at 600 km"))["fit"]["verdict"], "fits")
        self.assertEqual(default_scene(design("1U camera"))["fit"]["verdict"], "does_not_fit")


class RepairTest(Base):
    def test_fixes_bad_model_output(self):
        raw = {"summary": "x", "fit": {"verdict": "maybe", "note": "n"}, "parts": [
            {"ref": "p999", "explode": [0, 0, 0], "shapes": [{"kind": "box", "center": [0, 0, 0], "size": [1, 1, 1]}]},
            {"ref": "p1", "explode": ["a", None], "shapes": [
                {"kind": "sphere", "center": [float("nan"), 1e9, 0], "size": [-5, 0, 1e9], "axis": "w", "material": "unobtainium"}]},
            {"ref": "p1", "explode": [0, 0, 0], "shapes": []},
        ]}
        s, notes = repair(raw, self.d)
        self.assertEqual([p["ref"] for p in s["parts"]], [i["ref"] for i in instances(self.d)])
        shape = next(p for p in s["parts"] if p["ref"] == "p1")["shapes"][0]
        self.assertEqual((shape["kind"], shape["axis"], shape["material"]), ("box", "z", "aluminum"))
        self.assertTrue(all(math.isfinite(v) for v in shape["center"] + shape["size"]))
        self.assertTrue(all(v > 0 for v in shape["size"]))
        self.assertEqual(s["fit"]["verdict"], "unknown")
        self.assertTrue(any("missing" in n for n in notes))


class InsideTheFrameTest(Base):
    """Inside parts the model leaves sticking out of the frame are moved back in."""

    def setUp(self):
        super().setUp()
        self.six = design("A 6U CubeSat that images wildfires for 1 year")

    def inside(self, scene, d):
        return [p for p in scene["parts"] if p["part_index"] >= 0 and sc._inside_part(p, d)]

    def assert_all_inside_and_apart(self, scene, d):
        parts = self.inside(scene, d)
        self.assertEqual([p["label"] for p in parts if sc._sticks_out(p, scene["envelope_mm"])], [])
        boxes = [bbox(p["shapes"]) for p in parts]
        for i, a in enumerate(boxes):
            for b in boxes[i + 1:]:
                self.assertFalse(sc._overlap(a, b, 1))

    def test_a_good_layout_is_left_alone(self):
        s = default_scene(self.six)
        before = json.dumps(s)
        self.assertEqual(sc.fix_inside(s, self.six), [])
        self.assertEqual(json.dumps(s), before)

    def test_one_board_too_high_comes_back_in_alone(self):
        s = default_scene(self.six)
        board = next(p for p in self.inside(s, self.six) if p["label"] == "OEM719")
        lo, hi = bbox(board["shapes"])
        sc._move_to(board, (lo, hi), ([lo[0], lo[1], lo[2] + 400], [hi[0], hi[1], hi[2] + 400]))
        others = {p["ref"]: json.dumps(p["shapes"]) for p in s["parts"] if p is not board}
        notes = sc.fix_inside(s, self.six)
        self.assertEqual(len(notes), 1)
        self.assertIn("stuck out of the frame: OEM719", notes[0])
        self.assert_all_inside_and_apart(s, self.six)
        self.assertEqual({p["ref"]: json.dumps(p["shapes"]) for p in s["parts"] if p is not board}, others)

    MODEL_TEXT = {"overview": "how it works", "layout": "Everything is in one stack in the middle and it fits."}

    def one_tall_stack(self):
        # What Sonnet did: every board in one column down the middle, running out of the top.
        s = default_scene(self.six)
        s["description"] = dict(self.MODEL_TEXT)
        s["fit"], s["summary"] = {"verdict": "fits", "note": "uses 340 of 366 mm"}, "one stack"
        z = -envelope(self.six)[2] / 2 - 1
        for p in sorted(self.inside(s, self.six), key=lambda p: bbox(p["shapes"])[0][2]):
            lo, hi = bbox(p["shapes"])
            w = [(hi[k] - lo[k]) / 2 for k in range(2)]
            sc._move_to(p, (lo, hi), ([-w[0], -w[1], z], [w[0], w[1], z + hi[2] - lo[2]]))
            z += hi[2] - lo[2] + 1
        return s

    def test_one_tall_stack_in_a_6u_is_split_into_columns(self):
        s = self.one_tall_stack()
        shared = self.inside(s, self.six)[0]["shapes"]                  # as if carried over from an earlier scene
        notes = sc.fix_inside(s, self.six)
        self.assertTrue(notes[0].startswith("Re-stacked the inside parts in columns"))
        self.assert_all_inside_and_apart(s, self.six)
        self.assertIsNot(self.inside(s, self.six)[0]["shapes"], shared)  # new shapes, the old ones untouched
        cam = next(p for p in self.inside(s, self.six) if sc.kind_of(self.six["parts"][p["part_index"]]) == "imager")
        self.assertLess(bbox(cam["shapes"])[0][2], -envelope(self.six)[2] / 2)   # lens still out the bottom

    def test_after_a_re_stack_the_layout_text_matches_the_drawing(self):
        s = self.one_tall_stack()
        sc.fix_inside(s, self.six)
        text = s["description"]["layout"]
        self.assertNotIn("one stack in the middle", text)                   # the model's words are gone
        self.assertIn("split into 2 side-by-side stacks", text)
        for p in self.inside(s, self.six):
            self.assertIn(p["label"], text)                                 # every inside part is placed in words
        self.assertIn("set by the app, not the model", text)
        self.assertEqual(s["description"]["overview"], "how it works")      # what it does is still true
        self.assertEqual(s["fit"]["verdict"], "fits")
        self.assertNotIn("340", s["fit"]["note"])
        self.assertIn("2 side-by-side stacks", s["summary"])

    def test_a_nudge_keeps_the_models_text(self):
        s = default_scene(self.six)
        s["description"] = dict(self.MODEL_TEXT)
        lower, upper = self.column_pair(s)
        lo, hi = bbox(upper["shapes"])
        sink = (lo[2] - bbox(lower["shapes"])[1][2]) + 3
        sc._move_to(upper, (lo, hi), ([lo[0], lo[1], lo[2] - sink], [hi[0], hi[1], hi[2] - sink]))
        self.assertTrue(sc.fix_inside(s, self.six)[0].startswith("Nudged"))
        self.assertEqual(s["description"], self.MODEL_TEXT)

    def test_when_nothing_fits_the_text_says_so(self):
        s = self.one_tall_stack()
        with mock.patch.object(sc, "inside_z", lambda env: (-60, 60)):     # a frame far too short
            notes = sc.fix_inside(s, self.six)
        self.assertTrue(notes[0].startswith("Not enough room inside"))
        self.assertEqual(s["fit"]["verdict"], "does_not_fit")
        self.assertIn("it doesn't fit", s["description"]["layout"])

    def column_pair(self, s):
        """Two inside parts stacked in the same column, lower one first."""
        parts = sorted(self.inside(s, self.six), key=lambda p: bbox(p["shapes"])[0][2])
        for i, a in enumerate(parts):
            for b in parts[i + 1:]:
                A, B = bbox(a["shapes"]), bbox(b["shapes"])
                if all(min(A[1][k], B[1][k]) - max(A[0][k], B[0][k]) > 1 for k in range(2)) and sc.kind_of(self.six["parts"][a["part_index"]]) != "imager":
                    return a, b

    def test_a_small_overlap_is_nudged_apart_keeping_the_order(self):
        s = default_scene(self.six)
        lower, upper = self.column_pair(s)
        lo, hi = bbox(upper["shapes"])
        sink = (lo[2] - bbox(lower["shapes"])[1][2]) + 3          # 3 mm into the part below
        sc._move_to(upper, (lo, hi), ([lo[0], lo[1], lo[2] - sink], [hi[0], hi[1], hi[2] - sink]))
        before = {p["ref"]: bbox(p["shapes"]) for p in s["parts"]}
        notes = sc.fix_inside(s, self.six)
        self.assertTrue(notes[0].startswith("Nudged along the rails"))
        self.assertIn("overlapped another part", notes[0])
        self.assert_all_inside_and_apart(s, self.six)
        for p in s["parts"]:                                       # small moves, along z only
            b, a = before[p["ref"]], bbox(p["shapes"])
            self.assertEqual((b[0][0], b[0][1]), (a[0][0], a[0][1]))
            self.assertLess(abs(a[0][2] - b[0][2]), 10)
        self.assertLess(bbox(lower["shapes"])[0][2], bbox(upper["shapes"])[0][2])   # order kept

    def test_thrusters_are_kept_clear_of_the_stack(self):
        d = design("3U CubeSat with a propulsion system at 500 km")
        s = default_scene(d)
        thr = [p for p in s["parts"] if p["part_index"] >= 0 and sc.kind_of(d["parts"][p["part_index"]]) == "thruster"]
        self.assertTrue(thr)
        board = next(p for p in s["parts"] if p["part_index"] >= 0 and sc.kind_of(d["parts"][p["part_index"]]) == "board")
        t = bbox(thr[0]["shapes"])
        lo, hi = bbox(board["shapes"])
        mid = (t[0][2] + t[1][2]) / 2                              # drop a board into the middle of the thruster
        sc._move_to(board, (lo, hi), ([lo[0], lo[1], mid], [hi[0], hi[1], mid + hi[2] - lo[2]]))
        self.assertTrue(sc.fix_inside(s, d))
        parts = [p for p in s["parts"] if p["part_index"] >= 0 and sc.kind_of(d["parts"][p["part_index"]]) in sc.INSIDE_KINDS + ("thruster",)]
        boxes = [bbox(p["shapes"]) for p in parts]
        self.assertFalse(any(sc._overlap(a, b, 1) for i, a in enumerate(boxes) for b in boxes[i + 1:]))

    def test_prompt_gives_the_columns_and_the_stack_height(self):
        line = next(l for l in build_prompt(self.six, instances(self.six), []).split("\n") if l.startswith("Inside:"))
        self.assertIn("[[0, -57], [0, 57]]", line)
        self.assertIn("split them across the columns", line)

    def test_model_layout_sticking_out_is_fixed_before_it_is_returned(self):
        g, client = self.gen(designs=[self.six])
        orig = client.create

        def create(**kw):        # the model pushes a board out of the top
            resp = orig(**kw)
            data = json.loads(resp.content[0].text)
            for p in data["parts"]:
                if p["ref"] == "p4":
                    p["pos"][2] += 400
            resp.content[0].text = json.dumps(data)
            return resp
        client.create = create
        out = g.generate(self.six)
        self.assertTrue(any("stuck out of the frame" in n for n in out["repairs"]))
        self.assert_all_inside_and_apart(out["scene"], self.six)


class SolarPanelTest(Base):
    def setUp(self):
        super().setUp()
        self.six = design("A 6U CubeSat that images wildfires for 1 year")

    def panels(self, s, d):
        return [p for p in s["parts"] if p["part_index"] >= 0 and sc.kind_of(d["parts"][p["part_index"]]).startswith("solar")]

    def test_default_panels_and_wings_are_left_alone(self):
        d = copy.deepcopy(self.six)
        solar = next(p for p in d["parts"] if p["slot"] == "solar")
        solar["quantity"] = 4                      # two on the wide faces, two too wide for the narrow ones: wings
        for dd in (self.six, d):
            s = default_scene(dd)
            before = json.dumps(s)
            self.assertEqual(sc.fix_outside(s, dd), [])
            self.assertEqual(json.dumps(s), before)

    def test_a_patch_pushed_through_the_wall_goes_onto_a_face(self):
        # What Sonnet did next: the X-band patch half inside the frame, poking through the side.
        s = default_scene(self.six)
        patch = next(p for p in s["parts"] if p["part_index"] >= 0 and sc.kind_of(self.six["parts"][p["part_index"]]) == "patch_nadir")
        patch["shapes"] = place(library.lookup("X-band 4x4 Patch Antenna")["shapes"], [-54, 0, -140], "-y")
        notes = sc.fix_outside(s, self.six)
        self.assertTrue(any(n.startswith("Put X-band 4x4 Patch Antenna flat on a face") for n in notes))
        lo, hi = bbox(patch["shapes"])
        env = envelope(self.six)
        n = [hi[k] - lo[k] for k in range(3)].index(min(hi[k] - lo[k] for k in range(3)))
        self.assertTrue(lo[n] >= env[n] / 2 - 2 or hi[n] <= -env[n] / 2 + 2)

    def test_an_antenna_module_inside_the_frame_goes_to_the_end_face(self):
        # Sonnet once put the UHF module inside the top of a 3U, on top of a board.
        d = design("3U radio relay at 500 km for 2 years")
        s = default_scene(d)
        uhf = next(p for p in s["parts"] if p["part_index"] >= 0 and sc.kind_of(d["parts"][p["part_index"]]) == "whip_antenna")
        want = json.dumps(uhf["shapes"])
        lo, hi = bbox(uhf["shapes"])
        sc._move_to(uhf, (lo, hi), ([lo[0], lo[1], lo[2] - 30], [hi[0], hi[1], hi[2] - 30]))
        notes = sc.fix_outside(s, d)
        self.assertTrue(any(uhf["label"] in n for n in notes))
        self.assertEqual(json.dumps(uhf["shapes"]), want)

    def test_wide_panels_on_the_narrow_faces_move_to_the_wide_ones(self):
        # What Sonnet did on a 6U: the 220 mm panels on the 100 mm faces, hanging 60 mm past each edge.
        s = default_scene(self.six)
        s["description"] = {"overview": "o", "layout": "Panels on the narrow faces."}
        entry = library.lookup("6U Solar Panel")
        for p, (y, up) in zip(self.panels(s, self.six), [(-117, "-y"), (117, "+y")]):
            p["shapes"] = place(entry["shapes"], [0, y, 0], up)
        patch = next(p for p in s["parts"] if p["part_index"] >= 0 and sc.kind_of(self.six["parts"][p["part_index"]]) == "patch_nadir")
        # The patch flat on the +x face, right where a panel will land.
        patch["shapes"] = place(library.lookup("X-band 4x4 Patch Antenna")["shapes"], [54, 0, -140], "+x")
        notes = sc.fix_outside(s, self.six)
        self.assertTrue(notes[0].startswith("Moved the solar panels to faces they fit"))
        want = {p["ref"]: p["shapes"] for p in self.panels(default_scene(self.six), self.six)}
        for p in self.panels(s, self.six):
            self.assertEqual(p["shapes"], want[p["ref"]])
            self.assertFalse(sc._overlap(bbox(p["shapes"]), bbox(patch["shapes"]), 0.5))
        self.assertTrue(any("X-band" in n and n.startswith("Lifted") for n in notes))   # the patch now sits on its panel
        self.assertIn("moved the solar panels", s["description"]["layout"])


class ModelPlacesLibraryPartsTest(Base):
    def test_model_only_places_and_library_draws(self):
        g, client = self.gen()
        out = g.generate(self.d)
        self.assertEqual((out["source"], out["mode"], out["drawn"]), ("sonnet", "full", 0))
        call = client.calls[0]
        rows = json.loads(call["messages"][0]["content"].rsplit("\n", 1)[-1])
        self.assertTrue(all("library" in r for r in rows if "same_as" not in r))
        # The scene has the library's full detail even though the model sent no shapes.
        want = sum(len(p["shapes"]) for p in default_scene(self.d)["parts"])
        self.assertEqual(sum(len(p["shapes"]) for p in out["scene"]["parts"]), want)
        self.assertLess(call["max_tokens"], 8000)          # a ceiling; drawing everything used to allow 14000

    def test_part_missing_from_the_library_gets_drawn_and_saved(self):
        real = library.lookup
        drawn = [{"k": "box", "c": [0, 0, 0], "s": [46, 71, 11], "a": "z", "m": "pcb"}]
        with mock.patch.object(library, "lookup", lambda name, mass=None: None if name == "OEM719" else real(name, mass)):
            g, client = self.gen()
            orig = client.create

            def create(**kw):        # the model draws the missing part
                resp = orig(**kw)
                data = json.loads(resp.content[0].text)
                for p in data["parts"]:
                    if p["ref"] == "p4":
                        p["shapes"] = drawn
                resp.content[0].text = json.dumps(data)
                return resp
            client.create = create
            out = g.generate(self.d)
        self.assertEqual(out["drawn"], 1)
        self.assertIn('"draw":true', client.calls[0]["messages"][0]["content"])
        self.assertEqual(out["saved"], ["OEM719"])
        saved = json.loads((self.generated / "oem719.json").read_text())
        self.assertEqual((saved["kind"], saved["drawn_by"], saved["vendor"]), ("catalog", SONNET_MODEL, "NovAtel"))


class TokenSavingTest(Base):
    def test_copies_are_described_once_and_share_a_role(self):
        g, client = self.gen()
        orig = client.create

        def create(**kw):        # the model leaves later copies' role empty, as asked
            resp = orig(**kw)
            data = json.loads(resp.content[0].text)
            for p in data["parts"]:
                if "." in p["ref"] and not p["ref"].endswith(".1"):
                    p["role"] = ""
            resp.content[0].text = json.dumps(data)
            return resp
        client.create = create
        out = g.generate(self.d)
        rows = json.loads(client.calls[0]["messages"][0]["content"].rsplit("\n", 1)[-1])
        copies = [r for r in rows if "same_as" in r]
        self.assertTrue(copies)                                   # the test design has repeated parts
        for r in copies:
            self.assertEqual(set(r), {"ref", "copy", "same_as"})  # no repeated part details
            self.assertTrue(r["same_as"].endswith(".1"))
        self.assertTrue(all(p.get("role") for p in out["scene"]["parts"]))

    def test_static_prefix_is_cached_and_cache_reads_cost_a_tenth(self):
        g, client = self.gen()
        orig = client.create

        def create(**kw):
            resp = orig(**kw)
            resp.usage = SimpleNamespace(input_tokens=500, output_tokens=1000,
                                         cache_creation_input_tokens=0, cache_read_input_tokens=3000)
            return resp
        client.create = create
        g.generate(self.d)
        system = client.calls[0]["system"]
        self.assertEqual(system[0]["cache_control"], {"type": "ephemeral"})
        self.assertEqual(self.usage.used, 500 + 1000 + 3000)
        self.assertEqual(self.usage._data["calls"][-1]["cache_read"], 3000)
        # $2/M input, $0.20/M cache read, $10/M output
        self.assertAlmostEqual(self.usage.status()["cost_usd"], (500 * 2 + 3000 * 0.2 + 1000 * 10) / 1e6, places=6)

    def test_finished_layouts_survive_a_restart(self):
        g, client = self.gen()
        g.generate(self.d)
        again, client2 = self.gen()                               # a new generator, as after a restart
        hit = again.generate(self.d)
        self.assertEqual((hit["source"], len(client2.calls)), ("cache", 0))
        self.assertTrue((Path(self.tmp.name) / "scene_cache.json").exists())


class DescriptionAndExtrasTest(Base):
    def test_description_and_roles(self):
        g, client = self.gen()
        out = g.generate(self.d, request={"text": "3U camera cubesat", "goal": "Image crops", "notes": ""})
        s = out["scene"]
        self.assertEqual(s["description"], {"overview": "how it works", "layout": "why it fits"})
        self.assertTrue(all(p.get("role") for p in s["parts"]))
        prompt = client.calls[0]["messages"][0]["content"]
        self.assertIn('Request: "3U camera cubesat"', prompt)
        self.assertIn('"why":', prompt)                           # the designer's reasons are passed on

    def test_designer_notes_reach_the_model_and_the_cache_key(self):
        g, client = self.gen()
        note = "No attitude-control unit: it relies on passive magnetic stabilization."
        g.generate(self.d, request={"text": "1U beacon", "design_notes": [note]})
        self.assertIn("Designer's notes on the parts list", client.calls[0]["messages"][0]["content"])
        self.assertIn("passive magnetic stabilization", client.calls[0]["messages"][0]["content"])
        self.assertNotEqual(SceneGenerator.cache_key(self.d, {"design_notes": [note]}), SceneGenerator.cache_key(self.d, {}))

    def test_prompt_gives_the_fit_verdict_and_end_face_heights(self):
        prompt = build_prompt(self.d, instances(self.d), [])
        need, room, verdict = sc.inside_fit(self.d["parts"], envelope(self.d))
        self.assertIn(f'fit.verdict is \"{verdict}\"', prompt)
        rows = json.loads(prompt.rsplit("\n", 1)[-1])
        uhf = next(r for r in rows if r["part"] == "UHF Antenna 1U")
        z = envelope(self.d)[2] / 2 + library.lookup("UHF Antenna 1U")["size"][2] / 2
        self.assertEqual(uhf["pos_z_on_end_face"], {"+z": round(z, 1), "-z": -round(z, 1)})
        self.assertTrue(all("pos_z_on_end_face" not in r for r in rows if r.get("slot") == "flight computer"))
        patch = next(r for r in rows if r.get("slot") == "downlink antenna")
        t = library.lookup(patch["part"])["size"][2] / 2
        self.assertEqual(patch["pos_on_side_face"]["-y"], -round(envelope(self.d)[1] / 2 + t, 1))

    def test_fit_verdict_always_matches_the_designers_check(self):
        _, _, verdict = sc.inside_fit(self.d["parts"], envelope(self.d))
        for model_says, kept in ((verdict, True), ("does_not_fit" if verdict != "does_not_fit" else "fits", False)):
            g, client = self.gen()
            orig = client.create

            def create(**kw):
                resp = orig(**kw)
                data = json.loads(resp.content[0].text)
                data["fit"] = {"verdict": model_says, "note": "the model's note"}
                resp.content[0].text = json.dumps(data)
                return resp
            client.create = create
            fit = g.generate(self.d, regenerate=True)["scene"]["fit"]
            self.assertEqual(fit["verdict"], verdict)
            self.assertEqual(fit["note"] == "the model's note", kept)

    def test_command_line_runs(self):
        from visualizer.__main__ import main
        with mock.patch("visualizer.__main__.TokenUsage", lambda: self.usage), \
             mock.patch("sys.stdout", new_callable=__import__("io").StringIO) as out:
            self.assertEqual(main(["--no-llm", "1U beacon"]), 0)
        self.assertIn("tokens so far", out.getvalue())

    def test_unusual_request_gets_extras_saved_apart_and_reused(self):
        g, client = self.gen()
        client.extras = [LASER]
        req = {"text": "3U cubesat with a laser beam", "goal": "", "notes": "laser beam"}
        out = g.generate(self.d, request=req)
        extra = [p for p in out["scene"]["parts"] if p.get("extra")]
        self.assertEqual(len(extra), 1)
        self.assertEqual((extra[0]["ref"], extra[0]["part_index"]), ("x1", -1))
        self.assertEqual(extra[0]["extra"]["mass_kg"], 0.4)
        self.assertEqual(out["saved"], ["Pulsed laser emitter"])
        f = self.generated / "pulsed-laser-emitter.json"
        self.assertEqual(json.loads(f.read_text())["kind"], "extra")
        self.assertEqual(library.lookup("Pulsed laser emitter")["source"], "generated")
        # Next laser request: the model is told about it and can reuse it by name without drawing.
        client.extras = [{**LASER, "shapes": []}]
        again = g.generate(design("6U camera cubesat"), request=req)
        self.assertIn("Pulsed laser emitter", client.calls[1]["messages"][0]["content"])
        x = [p for p in again["scene"]["parts"] if p.get("extra")][0]
        self.assertEqual((x["extra"]["drawing"], again["saved"]), ("library", []))
        self.assertEqual(len(x["shapes"]), 2)

    def test_opus_drawings_win_over_generated(self):
        library.save_generated("OEM719", [{"kind": "box", "center": [0, 0, 0], "size": [1, 1, 1], "axis": "z", "material": "pcb"}],
                               kind="catalog", model="test")
        self.assertEqual(library.lookup("OEM719")["source"], "opus")
        self.assertFalse((self.generated / "oem719.json").exists())

    def test_edit_keeps_extras_and_can_drop_them(self):
        first = design("3U camera at 550 km for 2 years")
        second = design("3U camera at 300 km for 3 years")
        g, client = self.gen(designs=[first, second])
        client.extras = [LASER]
        req = {"text": "laser cubesat", "goal": "", "notes": "laser"}
        a = g.generate(first, request=req)
        client.extras = []
        b = g.generate(second, previous={"design": first, "scene": a["scene"], "source": a["source"]},
                       request={**req, "text": "fly at 300 km for 3 years"})
        self.assertEqual(b["mode"], "edit")
        self.assertEqual([p["ref"] for p in b["scene"]["parts"] if p.get("extra")], ["x1"])
        self.assertIn('"ref":"x1"', client.calls[1]["messages"][0]["content"])
        client.drop = ["x1"]
        c = g.generate(second, previous={"design": second, "scene": b["scene"], "source": b["source"]},
                       request={**req, "text": "remove the laser", "notes": ""})
        self.assertFalse(any(p.get("extra") for p in c["scene"]["parts"]))

    def test_goal_and_notes_are_part_of_the_cache_key(self):
        a = SceneGenerator.cache_key(self.d, {"goal": "Image crops", "notes": ""})
        self.assertNotEqual(a, SceneGenerator.cache_key(self.d, {"goal": "Image crops", "notes": "laser"}))


class EditTest(Base):
    def test_edit_only_places_what_changed(self):
        first, second = design("3U camera at 550 km for 2 years"), design("3U camera at 300 km for 3 years")
        g, client = self.gen(designs=[first, second])
        a = g.generate(first)
        b = g.generate(second, previous={"design": first, "scene": a["scene"], "source": a["source"]})
        self.assertEqual(b["mode"], "edit")
        items = lambda d: {(i["part"]["slot"], i["part"]["part"], i["instance"]) for i in instances(d)}
        new_parts = items(second) - items(first)          # e.g. a thruster and two more solar panels
        self.assertEqual(b["placed"], len(new_parts))
        self.assertGreater(b["reused"], 10)
        prompt = client.calls[1]["messages"][0]["content"]
        self.assertIn("This is an edit", prompt)
        self.assertEqual(len(json.loads(prompt.rsplit("\n", 1)[-1])), len(new_parts))
        self.assertEqual(len(b["scene"]["parts"]), len(instances(second)))

    def test_new_size_places_everything_again(self):
        first, second = design("3U camera cubesat"), design("6U camera cubesat")
        g, _ = self.gen(designs=[first, second])
        a = g.generate(first)
        b = g.generate(second, previous={"design": first, "scene": a["scene"], "source": a["source"]})
        self.assertEqual((b["mode"], b["reused"]), ("full", 0))


class UsageTest(Base):
    def test_always_sonnet_with_no_limit(self):
        g, client = self.gen()
        sources = [g.generate(self.d, regenerate=True)["source"] for _ in range(12)]
        self.assertEqual(set(sources), {"sonnet"})
        self.assertGreater(self.usage.used, 25000)             # the old cap is gone
        self.assertEqual({c["model"] for c in client.calls}, {SONNET_MODEL})
        first = client.calls[0]
        self.assertEqual(first["output_config"]["effort"], "medium")
        self.assertEqual(first["thinking"], {"type": "between_tools"})

    def test_count_and_cost_survive_restart_and_reset(self):
        g, client = self.gen()
        out = g.generate(self.d)
        out_tokens = min(1200, client.calls[0]["max_tokens"])
        again = TokenUsage(self.usage.path)
        self.assertEqual(again.used, 3000 + out_tokens)
        self.assertAlmostEqual(again.status()["cost_usd"], cost_usd(3000, out_tokens), places=6)
        self.assertEqual(out["tokens"]["tokens_used"], 3000 + out_tokens)
        again.reset()
        self.assertEqual(TokenUsage(self.usage.path).used, 0)

    def test_an_old_budget_file_still_loads(self):
        self.usage.path.write_text(json.dumps({"sonnet_tokens_used": 6850, "haiku_tokens_used": 0, "calls": []}))
        self.assertEqual(TokenUsage(self.usage.path).used, 6850)


class FallbackAndCacheTest(Base):
    def test_a_cut_off_answer_is_retried_with_more_room(self):
        g, client = self.gen(script={SONNET_MODEL: ["truncate"]})
        out = g.generate(self.d)
        self.assertEqual(out["source"], "sonnet")
        self.assertEqual([a["ok"] for a in out["attempts"]], [False, True])
        self.assertLess(client.calls[0]["max_tokens"], client.calls[1]["max_tokens"])

    def test_a_failed_call_gives_the_default_layout_uncached(self):
        g, client = self.gen(script={SONNET_MODEL: ["error"]})
        self.assertEqual(g.generate(self.d)["source"], "default")
        self.assertEqual(len(client.calls), 1)                      # no retry for an error the SDK already retried
        self.assertEqual(g.generate(self.d)["source"], "sonnet")    # the failure wasn't cached; it tried again

    def test_layouts_haiku_made_are_not_reused(self):
        g, _ = self.gen()
        g.generate(self.d)
        path = Path(self.tmp.name) / "scene_cache.json"
        saved = json.loads(path.read_text())
        path.write_text(json.dumps({k: {**v, "source": "haiku"} for k, v in saved.items()}))
        again, client = self.gen()
        self.assertEqual(again.generate(self.d)["source"], "sonnet")
        self.assertEqual(len(client.calls), 1)

    def test_same_design_is_cached_and_redraw_skips_cache(self):
        g, client = self.gen()
        g.generate(self.d)
        hit = g.generate(design("3U camera cubesat"))
        self.assertEqual((hit["source"], hit["cached_from"]), ("cache", "sonnet"))
        self.assertEqual(len(client.calls), 1)
        g.generate(self.d, regenerate=True)
        self.assertEqual(len(client.calls), 2)

    def test_no_llm_uses_default_layout(self):
        g, client = self.gen()
        self.assertEqual(g.generate(self.d, use_llm=False)["source"], "default")
        self.assertEqual(client.calls, [])


if __name__ == "__main__":
    unittest.main()
