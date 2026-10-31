"""The web API front-end/index.html depends on, run offline (keyword parser, rule-based 3D)."""
import json
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import server


class ServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        server.Handler.state = server.State(use_llm=False)
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()

    def post(self, path, body, headers=None):
        req = urllib.request.Request(self.base + path, data=json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json", **(headers or {})})
        with urllib.request.urlopen(req) as r:
            return json.load(r)

    def chat(self, text, spec=None):
        return self.post("/api/cubesat-chat", {"messages": [{"role": "user", "content": text}], "spec": spec or {}})

    def test_page_and_starter(self):
        with urllib.request.urlopen(self.base + "/") as r:
            self.assertIn(b"CubeSat Budget Tool", r.read())
        out = self.post("/api/budget", {})
        self.assertIsNone(out["reply"])
        b = out["budget"]
        for key in ("mass", "maxMass", "massRatio", "massState", "watts", "powRatio", "powState", "cost", "rows", "notes"):
            self.assertIn(key, b)
        self.assertEqual(b["form"], "6U")
        self.assertEqual(len(b["rows"]), len(out["design"]["parts"]))

    def test_follow_up_uses_the_spec_it_was_given(self):
        first = self.chat("3U camera cubesat at 550 km")
        second = self.chat("make it 6U", spec=first["spec"])
        self.assertEqual(second["budget"]["form"], "6U")
        self.assertEqual(second["budget"]["altitude"], 550)
        self.assertNotEqual(first["spec"]["design_id"], second["spec"]["design_id"])

    def test_visual_for_a_design(self):
        out = self.chat("1U iot radio relay")
        v = self.post("/api/visual", {"design_id": out["design_id"]})
        self.assertEqual(v["source"], "default")       # offline: rule-based layout
        self.assertEqual(len(v["scene"]["parts"]), len(out["quick_scene"]["parts"]))

    def export(self, body):
        req = urllib.request.Request(self.base + "/api/export", method="POST", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req) as r:
            return r.headers["Content-Disposition"], r.read()

    def test_export_downloads_step_and_stl(self):
        out = self.chat("3U camera cubesat")
        disposition, step = self.export({"design_id": out["design_id"]})        # STEP is the default
        self.assertIn("attachment", disposition)
        self.assertTrue(disposition.endswith('.step"'))
        self.assertTrue(step.startswith(b"ISO-10303-21;"))
        self.assertEqual(step.count(b"NEXT_ASSEMBLY_USAGE_OCCURRENCE("), len(out["quick_scene"]["parts"]))
        disposition, stl = self.export({"design_id": out["design_id"], "format": "stl"})
        self.assertTrue(disposition.endswith('.stl"'))
        self.assertEqual(len(stl), 84 + 50 * int.from_bytes(stl[80:84], "little"))
        disposition, step = self.export({"design_id": out["design_id"], "name": "Wildfire Watcher"})
        self.assertTrue(disposition.endswith('filename="Wildfire-Watcher.step"'))
        self.assertIn(b"PRODUCT('Wildfire Watcher'", step)
        for body, code in (({"design_id": "nope"}, 404), ({"design_id": out["design_id"], "format": "obj"}, 400)):
            with self.subTest(body=body), self.assertRaises(urllib.error.HTTPError) as e:
                self.post("/api/export", body)
            self.assertEqual(e.exception.code, code)

    def test_saved_design_is_restored_after_a_restart(self):
        out = self.chat("3U camera cubesat at 550 km")
        key, state = out["design_id"], server.Handler.state
        # Pretend the drawing the page shows came from Sonnet and was saved to the scene cache.
        entry = state.get(key)
        drawn = {**out["quick_scene"], "summary": "drawn by the model"}
        cache_key = state.generator.cache_key(entry["design"], entry["request"])
        state.generator._cache[cache_key] = {"scene": drawn, "source": "sonnet"}
        try:
            with state._lock:
                state._designs.clear()                       # the server restarted
            with self.assertRaises(urllib.error.HTTPError) as e:
                self.post("/api/visual", {"design_id": key})
            self.assertEqual(e.exception.code, 404)

            self.assertTrue(self.post("/api/restore", {"design_id": key, "spec": out["spec"],
                                                       "text": "3U camera cubesat at 550 km"})["restored"])
            restored = state.get(key)
            self.assertEqual(restored["design"]["parts"], entry["design"]["parts"])    # same parts, same id
            self.assertEqual(restored["scene"]["summary"], "drawn by the model")       # no model call needed
            self.assertEqual(self.post("/api/visual", {"design_id": key})["source"], "cache")
            disposition, step = self.export({"design_id": key, "format": "step"})
            self.assertTrue(step.startswith(b"ISO-10303-21;"))
            follow = self.chat("make it 6U", spec=out["spec"])                         # edits still chain
            self.assertEqual(state.get(follow["design_id"])["previous_id"], key)
        finally:
            state.generator._cache.pop(cache_key, None)

    def test_restore_refuses_bad_input(self):
        for body in ({"design_id": "../etc", "spec": {"size_u": 3}}, {"design_id": "ab" * 8, "spec": "nope"},
                     {"design_id": "ab" * 8, "spec": {"size_u": "huge", "payload": "laser"}}):
            with self.subTest(body=body), self.assertRaises(urllib.error.HTTPError) as e:
                self.post("/api/restore", body)
            self.assertEqual(e.exception.code, 400)

    def test_engine_codes_become_sentences(self):
        notes = [n[1] for n in self.chat("3U camera at 300 km for 3 years")["budget"]["notes"]]
        self.assertFalse(any(n.startswith(("UNPRICED", "PEAK_OVER_SOLAR", "THRUSTER_BATTERY_LIMITED")) for n in notes))
        self.assertTrue(any(n.startswith("The thruster needs") for n in notes))

    def test_other_websites_are_refused(self):
        with self.assertRaises(urllib.error.HTTPError) as e:
            self.post("/api/budget", {}, headers={"Origin": "http://evil.example"})
        self.assertEqual(e.exception.code, 403)
        self.assertIn("detail", json.load(e.exception))


if __name__ == "__main__":
    unittest.main()
