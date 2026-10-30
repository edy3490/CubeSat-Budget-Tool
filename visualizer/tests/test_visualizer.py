"""Offline tests: a fake API client stands in for Claude, so no tokens are spent.

Run from the repo root:  python -m pytest visualizer/tests
"""
import json
import math
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from designer import run
from visualizer import SceneGenerator, TokenBudget, default_scene, repair
from visualizer import generator as gen_module
from visualizer import library
from visualizer.budget import HAIKU_MODEL, SONNET_MODEL
from visualizer.placement import body_size, place
from visualizer.scene import REACH_MM, envelope, instances


def design(idea="3U camera cubesat"):
    return run(idea, use_llm=False).data["design"]


def placements_for(d, refs=None):
    """What a well-behaved model returns: the rule-based layout's placements, shapes left to the library."""
    out = []
    for p in default_scene(d)["parts"]:
        if refs is None or p["ref"] in refs:
            m = p["place"]
            out.append({"ref": p["ref"], "pos": m["pos"], "up": m["up"], "spin": str(m["spin"]), "shapes": []})
    return {"summary": "test layout", "fit": {"verdict": "fits", "note": "ok"}, "parts": out}


class FakeClient:
    """Answers like the model: placements for the refs the prompt asks for.
    `script` maps model -> list of behaviours ("ok", "error", "truncate") used in order."""

    def __init__(self, out_tokens=1200, script=None):
        self.out_tokens, self.script, self.calls = out_tokens, script or {}, []
        self.messages = self

    def create(self, **kw):
        self.calls.append(kw)
        how = self.script[kw["model"]].pop(0) if self.script.get(kw["model"]) else "ok"
        if how == "error":
            raise RuntimeError("API down")
        prompt = kw["messages"][0]["content"]
        rows = json.loads(prompt.rsplit("\n", 1)[-1])             # the "place these" list is the last line
        d = self.design_for(prompt)
        text = "" if how == "truncate" else json.dumps(placements_for(d, {r["ref"] for r in rows}))
        return SimpleNamespace(stop_reason="max_tokens" if how == "truncate" else "end_turn",
                               usage=SimpleNamespace(input_tokens=3000, output_tokens=min(self.out_tokens, kw["max_tokens"])),
                               content=[SimpleNamespace(type="text", text=text)])

    design_for = None   # set per test: prompt -> design


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.budget = TokenBudget(Path(self.tmp.name) / "usage.json", limit=25000)
        self.d = design()

    def tearDown(self):
        self.tmp.cleanup()

    def gen(self, designs=None, **kw):
        client = FakeClient(**kw)
        designs = designs or [self.d]
        client.design_for = lambda prompt: next(
            (d for d in reversed(designs) if f"Mission: {d['name']}" in prompt and d["form_factor"] in prompt), designs[-1])
        return SceneGenerator(self.budget, client=client), client


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


class ModelPlacesLibraryPartsTest(Base):
    def test_model_only_places_and_library_draws(self):
        g, client = self.gen()
        out = g.generate(self.d)
        self.assertEqual((out["source"], out["mode"], out["drawn"]), ("sonnet", "full", 0))
        call = client.calls[0]
        self.assertNotIn("draw", call["system"].split("Most parts")[0])        # no drawing guide needed
        rows = json.loads(call["messages"][0]["content"].rsplit("\n", 1)[-1])
        self.assertTrue(all("library" in r for r in rows))
        # The scene has the library's full detail even though the model sent no shapes.
        want = sum(len(p["shapes"]) for p in default_scene(self.d)["parts"])
        self.assertEqual(sum(len(p["shapes"]) for p in out["scene"]["parts"]), want)
        self.assertLess(call["max_tokens"], 3000)                              # placing is cheap

    def test_part_missing_from_the_library_gets_drawn(self):
        real = library.lookup
        with mock.patch.object(gen_module, "lookup", lambda name, mass=None: None if name == "OEM719" else real(name, mass)):
            g, client = self.gen()
            out = g.generate(self.d)
        self.assertEqual(out["drawn"], 1)
        call = client.calls[0]
        self.assertIn('"draw":true', call["messages"][0]["content"])
        self.assertIn("not in the library", call["system"])


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


class BudgetTest(Base):
    def test_sonnet_with_high_effort_then_haiku_after_25k(self):
        g, client = self.gen()
        sources = [g.generate(self.d, regenerate=True)["source"] for _ in range(10)]
        self.assertEqual(sources[0], "sonnet")
        self.assertEqual(sources[-1], "haiku")
        self.assertLessEqual(self.budget.used, 25000)          # hard cap, never crossed
        first = client.calls[0]
        self.assertEqual(first["model"], SONNET_MODEL)
        self.assertEqual(first["output_config"]["effort"], "high")
        self.assertEqual(first["thinking"], {"type": "between_tools"})
        last = client.calls[-1]
        self.assertEqual(last["model"], HAIKU_MODEL)
        self.assertEqual(last["thinking"], {"type": "disabled"})

    def test_count_survives_restart_and_reset(self):
        g, client = self.gen()
        g.generate(self.d)
        spent = 3000 + min(1200, client.calls[0]["max_tokens"])
        again = TokenBudget(self.budget.path, limit=25000)
        self.assertEqual(again.used, spent)
        again.reset()
        self.assertEqual(TokenBudget(self.budget.path).used, 0)

    def test_failed_call_releases_its_reservation(self):
        g, _ = self.gen(script={SONNET_MODEL: ["error"]})
        out = g.generate(self.d)
        self.assertEqual(out["source"], "haiku")
        self.assertEqual(self.budget._reserved, 0)
        self.assertEqual(self.budget.used, 0)


class FallbackAndCacheTest(Base):
    def test_truncated_sonnet_falls_back_to_haiku(self):
        g, _ = self.gen(script={SONNET_MODEL: ["truncate"]})
        out = g.generate(self.d)
        self.assertEqual(out["source"], "haiku")
        self.assertFalse(out["attempts"][0]["ok"])

    def test_everything_failing_gives_default_layout_uncached(self):
        g, _ = self.gen(script={SONNET_MODEL: ["error"], HAIKU_MODEL: ["error"]})
        self.assertEqual(g.generate(self.d)["source"], "default")
        self.assertEqual(g.generate(self.d)["source"], "sonnet")    # the failure wasn't cached; it tried again

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
