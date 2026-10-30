"""Offline tests: keyword parser only, no API calls.

Run from the repo root:  python -m pytest designer/tests
"""
import json
import unittest

from designer import run
from designer.report import render


def go(text, previous=None):
    return run(text, previous=previous, use_llm=False)


def parts(result):
    return {p["slot"]: p for p in result.data["design"]["parts"]}


def check(result, name):
    return next(c for c in result.data["design"]["checks"] if c["check"] == name)


class DesignerTest(unittest.TestCase):
    def test_3u_camera_closes_with_imager_and_s_band(self):
        r = go("3U camera cubesat in a polar orbit at 550 km for 2 years")
        d = r.data["design"]
        self.assertEqual(d["status"], "closes")
        p = parts(r)
        self.assertEqual(p["payload"]["part"].split()[0], "MultiScape100")
        self.assertIn("S-Band", p["downlink radio"]["part"])
        self.assertIn("pointing (ADCS)", p)
        self.assertLessEqual(d["swap"]["weight"]["total_kg"], d["swap"]["weight"]["limit_kg"])
        self.assertGreaterEqual(d["swap"]["power"]["ratio"], 1.0)

    def test_cost_total_is_priced_parts_plus_launch(self):
        d = go("3U camera cubesat").data["design"]
        priced = sum(p["line_cost_usd"] or 0 for p in d["parts"])
        self.assertEqual(d["cost"]["hardware_usd"], priced)
        self.assertEqual(d["cost"]["total_usd"], priced + d["cost"]["launch_usd"])
        self.assertTrue(d["cost"]["is_minimum"])  # imagers have no public price

    def test_1u_camera_does_not_fit_and_says_3u_does(self):
        # The smallest camera in the table is taller than a 1U's inside on its own.
        r = go("1U camera cubesat")
        d = r.data["design"]
        self.assertEqual((d["form_factor"], d["status"]), ("1U", "does_not_close"))   # the size the user chose stays
        self.assertEqual(check(r, "Fits inside")["status"], "fail")
        self.assertTrue(any("smallest size that does is 3U" in x for x in d["decisions"]))

    def test_1u_beacon_fits_without_a_reaction_wheel(self):
        r = go("1U beacon")
        d = r.data["design"]
        self.assertEqual((d["form_factor"], d["status"]), ("1U", "closes"))
        self.assertNotEqual(check(r, "Fits inside")["status"], "fail")
        self.assertNotIn("pointing (ADCS)", parts(r))
        self.assertTrue(any("passive magnetic stabilization" in x for x in d["decisions"]))
        bench = next(ph for ph in r.data["build_plan"]["phases"] if ph["phase"].startswith("Bench build"))
        self.assertTrue(any("passive magnet" in st for st in bench["steps"]))

    def test_an_assumed_size_moves_up_when_nothing_fits(self):
        from sat_parser.schema import normalize
        from designer.configurator import design
        spec = normalize({"payload": "camera"}).model_copy(update={"size_u": 1})   # size still marked assumed
        d = design(spec)
        self.assertEqual(d.form_factor, "3U")
        self.assertTrue(d.closes)
        self.assertIn("A 1U was too small", d.decisions[0])

    def test_every_design_that_closes_fits_inside(self):
        for idea in ("1U beacon", "1U radio relay", "3U camera cubesat", "3U sensor", "6U camera", "12U camera",
                     "3U camera at 300 km for 3 years", "3U radio relay at 600 km, needs a thruster"):
            r = go(idea)
            if r.data["design"]["status"] == "closes":
                self.assertNotEqual(check(r, "Fits inside")["status"], "fail", idea)

    def test_6u_camera_uses_x_band(self):
        self.assertIn("X-Band", parts(go("6U camera cubesat"))["downlink radio"]["part"])

    def test_12u_uses_estimated_structure(self):
        s = parts(go("12U camera cubesat"))["structure"]
        self.assertTrue(s["estimated_placeholder"])
        self.assertEqual(s["cost_basis"], "estimate")

    def test_sensor_gets_reserved_allowance(self):
        r = go("3U radiation sensor cubesat")
        self.assertTrue(parts(r)["payload"]["estimated_placeholder"])
        self.assertEqual(check(r, "Payload")["status"], "warn")

    def test_low_orbit_long_mission_adds_propulsion(self):
        r = go("3U camera at 300 km for 3 years")
        self.assertIn("propulsion", parts(r))
        self.assertEqual(check(r, "Lifetime")["status"], "pass")
        self.assertTrue(any("Propulsion added" in x for x in r.data["design"]["decisions"]))

    def test_asking_for_a_thruster_adds_one(self):
        r = go("3U radio relay at 600 km, needs a thruster")
        self.assertIn("propulsion", parts(r))

    def test_high_orbit_fails_deorbit_rule(self):
        r = go("3U sensor at 800 km for 1 year")
        self.assertEqual(check(r, "Deorbit")["status"], "fail")
        self.assertIn("fails: Deorbit", render(r.data))

    def test_follow_up_edits_previous_spec(self):
        first = go("3U camera cubesat at 550 km")
        second = go("make it 6U", previous=first.spec)
        self.assertEqual(second.data["design"]["form_factor"], "6U")
        self.assertEqual(second.spec.altitude_km, 550)
        self.assertEqual(second.spec.payload, "camera")

    def test_build_plan_covers_every_part(self):
        r = go("6U camera for wildfires sso 500 km 3 years")
        plan = r.data["build_plan"]
        self.assertEqual(len(plan["order_list"]), len(r.data["design"]["parts"]))
        self.assertGreater(plan["worst_case_weeks"], plan["expected_weeks"] - 1)
        self.assertEqual([p["phase"] for p in plan["phases"]][0], "Design")

    def test_result_is_json_and_renders(self):
        for idea in ("1U iot radio relay", "12U camera", "3U sensor"):
            r = go(idea)
            json.dumps(r.data)
            self.assertIn("BUILD PLAN", render(r.data))


if __name__ == "__main__":
    unittest.main()
