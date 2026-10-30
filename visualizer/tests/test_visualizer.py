"""Offline tests: a fake API client stands in for Claude, so no tokens are spent.

Run from the repo root:  python -m pytest visualizer/tests
"""
import json
import math
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from designer import run
from visualizer import SceneGenerator, TokenBudget, default_scene, repair
from visualizer.budget import HAIKU_MODEL, SONNET_MODEL
from visualizer.scene import REACH_MM, envelope, instances


def design(idea="3U camera cubesat"):
    return run(idea, use_llm=False).data["design"]


class FakeClient:
    """Answers with a given scene; `script` maps model -> list of behaviours used in order."""

    def __init__(self, scene, out_tokens=3000, script=None):
        self.scene, self.out_tokens, self.script, self.calls = scene, out_tokens, script or {}, []
        self.messages = self

    def create(self, **kw):
        self.calls.append(kw)
        how = (self.script.get(kw["model"]) or ["ok"]).pop(0) if self.script.get(kw["model"]) else "ok"
        if how == "error":
            raise RuntimeError("API down")
        out = min(self.out_tokens, kw["max_tokens"])
        stop = "max_tokens" if how == "truncate" else "end_turn"
        text = "" if how == "truncate" else json.dumps(self.scene)
        return SimpleNamespace(stop_reason=stop, usage=SimpleNamespace(input_tokens=3000, output_tokens=out),
                               content=[SimpleNamespace(type="text", text=text)])


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.budget = TokenBudget(Path(self.tmp.name) / "usage.json", limit=25000)
        self.d = design()
        self.scene = default_scene(self.d)

    def tearDown(self):
        self.tmp.cleanup()

    def gen(self, **kw):
        client = FakeClient(self.scene, **kw)
        return SceneGenerator(self.budget, client=client), client


class DefaultSceneTest(Base):
    def test_every_physical_item_is_drawn_once(self):
        for idea in ("1U iot radio relay", "3U camera at 300 km for 3 years", "6U camera", "12U camera", "3U sensor"):
            d = design(idea)
            s = default_scene(d)
            self.assertEqual([p["ref"] for p in s["parts"]], [i["ref"] for i in instances(d)], idea)
            self.assertTrue(all(p["shapes"] for p in s["parts"]))

    def test_structure_stays_put_and_parts_stay_in_reach(self):
        env = envelope(self.d)
        for p in self.scene["parts"]:
            if p["part_index"] == 0:
                self.assertEqual(p["explode"], [0, 0, 0])
            for s in p["shapes"]:
                for i in range(3):
                    self.assertLessEqual(abs(s["center"][i]), env[i] / 2 + REACH_MM)

    def test_default_3u_layout_needs_no_repairs(self):
        self.assertEqual(repair(self.scene, self.d)[1], [])


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


class BudgetTest(Base):
    def test_sonnet_with_high_effort_then_haiku_after_25k(self):
        g, client = self.gen()
        sources = [g.generate(self.d, regenerate=True)["source"] for _ in range(6)]
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
        self.assertEqual(self.budget.status()["active_model"], HAIKU_MODEL)

    def test_count_survives_restart_and_reset(self):
        g, _ = self.gen()
        g.generate(self.d)
        again = TokenBudget(self.budget.path, limit=25000)
        self.assertEqual(again.used, 6000)
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
