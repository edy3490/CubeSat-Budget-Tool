import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ENGINE_DIR = Path(__file__).resolve().parent.parent
DATABASE_DIR = ENGINE_DIR.parent / "database"

# Load by path: a plain `import budget_engine` resolves to the budget_engine/ folder
# when tests run from the repo root.
_spec = importlib.util.spec_from_file_location("budget_engine_module", ENGINE_DIR / "budget_engine.py")
be = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = be
_spec.loader.exec_module(be)


def run(config_items, form_factor="3U", **params):
    conn = be.connect(DATABASE_DIR / "cubesat.db")
    cfg = be.Configuration("test", form_factor, [])
    cfg.items = be._build_items(conn, config_items, cfg.warnings)
    return be.evaluate(conn, cfg, be.MissionParams(**params))


class BudgetEngineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        subprocess.run([str(DATABASE_DIR / "build.sh")], check=True, capture_output=True)

    def test_over_limit_reports_overage(self):
        # 1U with a 2.9 kg ion thruster cannot fit 2.0 kg
        r = run([{"component_id": 1}, {"component_id": 74}], form_factor="1U")
        m = r["mass_budget"]
        self.assertTrue(m["over_limit"])
        self.assertAlmostEqual(m["overage_kg"], 0.12 + 2.9 - 2.0, places=3)
        self.assertLess(m["margin_kg"], 0)

    def test_negative_energy_without_solar(self):
        r = run([{"component_id": 2}, {"component_id": 20}, {"component_id": 40}])
        p = r["power_budget"]
        self.assertEqual(p["energy_balance"], "NEGATIVE")
        self.assertLess(p["net_energy_per_orbit_wh"], 0)
        self.assertFalse(p["battery"]["survives_eclipse"])

    def test_positive_energy_and_duty_override(self):
        base = [{"component_id": 2}, {"component_id": 11, "quantity": 2}, {"component_id": 22}]
        low = run(base + [{"component_id": 81, "duty_cycle": 0.1}])
        high = run(base + [{"component_id": 81, "duty_cycle": 0.9}])
        self.assertEqual(low["power_budget"]["energy_balance"], "POSITIVE")
        self.assertGreater(high["power_budget"]["orbit_avg_consumption_w"],
                           low["power_budget"]["orbit_avg_consumption_w"])

    def test_propulsion_extends_life_and_gives_delta_v(self):
        base = [{"component_id": 4}, {"component_id": 12, "quantity": 2}, {"component_id": 22}]
        dry = run(base)
        wet = run(base + [{"component_id": 73}])
        self.assertEqual(dry["orbit_and_propulsion"]["delta_v_m_s"], 0)
        self.assertGreater(wet["orbit_and_propulsion"]["delta_v_m_s"], 100)
        self.assertGreaterEqual(wet["orbit_and_propulsion"]["operational_years"],
                                dry["orbit_and_propulsion"]["operational_years"])

    def test_lifetime_increases_with_altitude(self):
        self.assertGreater(be.natural_lifetime_years(600, 0.02), be.natural_lifetime_years(400, 0.02))

    def test_eclipse_fraction_500km(self):
        self.assertAlmostEqual(be.orbit_geometry(500)["eclipse_fraction"], 0.378, places=2)

    def test_mission_override_from_config_file(self):
        conn = be.connect(DATABASE_DIR / "cubesat.db")
        cfg = be.load_file_configuration(conn, ENGINE_DIR / "examples" / "vleo_feep_imager_6u.json")
        self.assertEqual(cfg.mission, {"altitude_km": 350.0})
        r = be.evaluate(conn, cfg, be.replace(be.MissionParams(), **cfg.mission))
        self.assertEqual(r["orbit_and_propulsion"]["altitude_km"], 350.0)
        self.assertEqual(r["configuration"]["mission_overrides"], {"altitude_km": 350.0})

    def test_over_limit_configs_rank_last(self):
        heavy = run([{"component_id": 1}, {"component_id": 75}, {"component_id": 13, "quantity": 4},
                     {"component_id": 23}], form_factor="1U")
        light = run([{"component_id": 2}, {"component_id": 10}, {"component_id": 22}])
        ranking = be.build_report([heavy, light], be.MissionParams())["comparison_ranked_by_usd_per_watt_year"]
        self.assertTrue(heavy["mass_budget"]["over_limit"])
        self.assertTrue(ranking[-1]["over_limit"])

    def test_example_configs_all_evaluate(self):
        conn = be.connect(DATABASE_DIR / "cubesat.db")
        for path in sorted((ENGINE_DIR / "examples").glob("*.json")):
            with self.subTest(example=path.name):
                cfg = be.load_file_configuration(conn, path)
                self.assertFalse([w for w in cfg.warnings if w.startswith("Unknown component_id")])
                be.evaluate(conn, cfg, be.replace(be.MissionParams(), **cfg.mission))

    def test_gnss_draws_power_and_antennas_add_mass_only(self):
        base = [{"component_id": 2}, {"component_id": 11, "quantity": 2}, {"component_id": 22}]
        plain = run(base)
        fitted = run(base + [{"component_id": 308}, {"component_id": 344}])  # piNAV-NG + L1 patch
        self.assertAlmostEqual(fitted["power_budget"]["orbit_avg_consumption_w"]
                               - plain["power_budget"]["orbit_avg_consumption_w"], 0.124, places=2)
        self.assertAlmostEqual(fitted["mass_budget"]["total_mass_kg"]
                               - plain["mass_budget"]["total_mass_kg"], 0.024 + 0.017, places=3)

    def test_wheels_use_peak_power_duty_and_sensors_run_continuously(self):
        base = [{"component_id": 2}, {"component_id": 11, "quantity": 2}, {"component_id": 22}]
        plain = run(base)
        adcs = run(base + [{"component_id": 54, "quantity": 3},   # CubeWheel CW0017, 0.85 W peak
                           {"component_id": 512}])                # NanoAvionics ST-1, 1.2 W
        added = (adcs["power_budget"]["orbit_avg_consumption_w"]
                 - plain["power_budget"]["orbit_avg_consumption_w"])
        self.assertAlmostEqual(added, 3 * 0.85 * 0.10 + 1.2, places=2)

    def test_missing_core_subsystems_are_flagged(self):
        # Structure, solar and a battery only: no EPS, flight computer or radio
        r = run([{"component_id": 2}, {"component_id": 11, "quantity": 2}, {"component_id": 30}])
        self.assertEqual(r["required_subsystems"]["missing"], ["eps", "obc", "comms"])
        self.assertFalse(r["summary"]["complete"])
        self.assertIn("MISSING_SUBSYSTEM: eps, obc, comms", r["warnings"])

    def test_eps_battery_counts_as_storage_and_imager_needs_attitude_control(self):
        # iEPS Type B has a 45 Wh battery built in; the imager has no ADCS to point it
        r = run([{"component_id": 2}, {"component_id": 11, "quantity": 2}, {"component_id": 22},
                 {"component_id": 40}, {"component_id": 60}, {"component_id": 80}])
        self.assertEqual(r["required_subsystems"]["missing"], ["adcs"])
        with_adcs = run([{"component_id": 2}, {"component_id": 11, "quantity": 2}, {"component_id": 22},
                         {"component_id": 40}, {"component_id": 60}, {"component_id": 80}, {"component_id": 52}])
        self.assertTrue(with_adcs["required_subsystems"]["complete"])

    def test_incomplete_configs_rank_after_complete(self):
        bare = run([{"component_id": 2}, {"component_id": 11, "quantity": 2}])
        full = run([{"component_id": 2}, {"component_id": 11, "quantity": 2}, {"component_id": 22},
                    {"component_id": 40}, {"component_id": 60}])
        ranking = be.build_report([bare, full], be.MissionParams())["comparison_ranked_by_usd_per_watt_year"]
        self.assertEqual([x["complete"] for x in ranking], [True, False])

    def test_cli_writes_json(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "r.json"
            subprocess.run([sys.executable, str(ENGINE_DIR / "budget_engine.py"), "--all", "--out", str(out)],
                           check=True, capture_output=True)
            data = json.loads(out.read_text())
            self.assertEqual(len(data["configurations"]), 5)
            self.assertIn("comparison_ranked_by_usd_per_watt_year", data)


if __name__ == "__main__":
    unittest.main()
