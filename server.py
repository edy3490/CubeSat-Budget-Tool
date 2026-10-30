"""Local web server for the CubeSat prototype: serves front-end/index.html and its JSON API.

    sat-parser/.venv/bin/python server.py            # then open http://localhost:8000
    sat-parser/.venv/bin/python server.py --port 8080 --no-llm

API (POST bodies are JSON; errors come back as {"detail": "..."}):
    POST /api/budget        {}                              -> starter design
    POST /api/cubesat-chat  {"messages": [...], "spec": {}} -> {"reply", "spec", "budget", ...}
    POST /api/visual        {"design_id", "regenerate"}     -> 3D scene (Sonnet until 25k tokens, then Haiku)
    GET  /api/tokens                                        -> Sonnet token budget

`spec` is opaque to the page: it sends back whatever the last response gave it.
`budget` is the page's summary shape (mass, power, cost, rows, notes); the full
design, build plan and quick 3D layout come alongside it.

The API key stays on this machine; the page never sees it. Listens on localhost only.
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
import threading
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

REPO = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))

try:
    from dotenv import load_dotenv
    load_dotenv(REPO / ".env")
    load_dotenv(REPO / "sat-parser" / ".env")
except ImportError:
    pass

from designer import run                              # noqa: E402  (also puts sat-parser on sys.path)
from sat_parser import SatSpec                        # noqa: E402
from visualizer import SceneGenerator, default_scene  # noqa: E402

PAGE = REPO / "front-end" / "index.html"
STARTER_IDEA = "6U CubeSat that images wildfires from low Earth orbit for 1 year"
MAX_BODY_BYTES = 256_000
MAX_IDEA_CHARS = 2_000
KEEP_DESIGNS = 100


# ---------------------------------------------------------------- response shapes

def _k(usd):
    return None if usd is None else round(usd / 1000, 1)


# Budget engine warning codes, in words. None = already covered by one of the checks.
ENGINE_WARNINGS = {
    "UNPRICED": None, "OVER_MASS": None, "ENERGY_NEGATIVE": None, "ECLIPSE_FAIL": None,
    "PEAK_OVER_SOLAR": "With everything on at once, the satellite draws more than the panels make; the battery covers the peaks.",
    "THRUSTER_BATTERY_LIMITED": "The thruster needs {} W but only {} W is available, so burns are limited by the battery.",
    "MISSING_SUBSYSTEM": "The build has no part for: {}.",
    "NO_MASS": "Some parts have no mass in the table: {}.",
}


def engine_warning(text: str) -> str | None:
    code, _, detail = text.partition(":")
    if code not in ENGINE_WARNINGS:
        return text
    msg = ENGINE_WARNINGS[code]
    if not msg:
        return None
    if code == "THRUSTER_BATTERY_LIMITED":   # detail looks like "40.0/17.59 W"
        return msg.format(*detail.strip().removesuffix(" W").split("/", 1))
    return msg.format(detail.strip())


def budget_view(data: dict) -> dict:
    """The summary the page draws: stat cards, subsystem rows and flags."""
    d, spec = data["design"], data["parse"]["spec"]
    w, p, c = d["swap"]["weight"], d["swap"]["power"], d["cost"]
    mass_ratio = w["total_kg"] / w["limit_kg"]
    pow_ratio = p["consumption_avg_w"] / p["generation_avg_w"] if p["generation_avg_w"] else 2.0
    flag = {"pass": "good", "warn": "warn", "fail": "bad"}
    return {
        "form": d["form_factor"], "units": spec["size_u"], "altitude": spec["altitude_km"],
        "years": spec["lifetime_years"], "label": spec["payload"].replace("_", " "),
        "mass": w["total_kg"], "maxMass": w["limit_kg"], "massRatio": mass_ratio,
        "massState": "over" if mass_ratio > 1 else "tight" if mass_ratio > 0.9 else "ok",
        "watts": p["consumption_avg_w"], "gen": p["generation_avg_w"], "powRatio": pow_ratio,
        "powState": "over" if p["ratio"] < 1 else "tight" if p["ratio"] < 1.25 else "ok",
        "cost": _k(c["total_usd"]), "hardware": _k(c["hardware_usd"]), "launch": _k(c["launch_usd"]),
        "costIsMinimum": c["is_minimum"], "unpriced": len(c["unpriced_parts"]),
        "rows": [{
            "part_index": i,
            "name": x["part"] + (f" ×{x['quantity']}" if x["quantity"] > 1 else ""),
            "note": f"{x['vendor']} · {x['slot']}" + (" · size estimate" if x["estimated_placeholder"] else ""),
            "kg": x["line_mass_kg"] or 0, "w": x["peak_power_w"] or 0, "gen_w": x["generation_w"] or 0,
            "k": _k(x["line_cost_usd"]), "estimate": x["cost_basis"] == "estimate",
        } for i, x in enumerate(d["parts"])],
        "notes": [[flag.get(ch["status"], ""), f"{ch['check']}: {ch['detail']}"] for ch in d["checks"]]
                 + [["", x] for x in d["decisions"]]
                 + [["warn", m] for m in map(engine_warning, d["engine_warnings"]) if m],
    }


def reply_text(data: dict, llm: bool) -> str:
    d, spec, plan = data["design"], data["parse"]["spec"], data["build_plan"]
    w, p, c = d["swap"]["weight"], d["swap"]["power"], d["cost"]
    failed = [ch["check"] for ch in d["checks"] if ch["status"] == "fail"]
    verdict = ("closes" + (" (tight margins)" if d["margins"] == "tight" else "")) if d["status"] == "closes" else "does NOT close"
    lines = [
        f"{d['name'].rstrip('.')}: {verdict}" + (f", fails {', '.join(failed)}" if failed else "") + ".",
        f"{w['total_kg']:.2f} of {w['limit_kg']:g} kg · power {p['ratio']:.2f}× · ~${c['total_usd'] / 1000:,.0f}k"
        f"{'+' if c['is_minimum'] else ''} with launch · ~{plan['expected_weeks']} weeks to build.",
    ]
    if spec["assumed"]:
        lines.append("Assumed: " + ", ".join(spec["assumed"]) + ".")
    if spec["warnings"]:
        lines.append(" ".join(spec["warnings"]))
    if data["parse"]["source"] == "fallback":
        lines.append("(Keyword parser: the model was unavailable.)" if llm else "(Keyword parser, offline mode.)")
    return "\n".join(lines)


class State:
    """Designs made in this session, so follow-ups and the 3D call can refer to them by id."""

    def __init__(self, use_llm: bool):
        self.use_llm = use_llm
        self.generator = SceneGenerator()
        self._designs: OrderedDict[str, dict] = OrderedDict()
        self._lock = threading.Lock()
        self._starter = None

    def put(self, entry: dict) -> str:
        key = secrets.token_hex(8)
        with self._lock:
            self._designs[key] = entry
            while len(self._designs) > KEEP_DESIGNS:
                self._designs.popitem(last=False)
        return key

    def get(self, key) -> dict | None:
        with self._lock:
            return self._designs.get(key) if isinstance(key, str) else None

    def tokens(self) -> dict:
        return {**self.generator.budget.status(), "llm": self.use_llm}

    def respond(self, r, llm_used: bool, previous_id: str | None = None) -> dict:
        """Package a designer Result in the page's response shape."""
        design_id = self.put({"spec": r.spec.model_dump(), "design": r.data["design"], "previous_id": previous_id})
        return {
            "reply": reply_text(r.data, llm_used),
            "spec": {"design_id": design_id, **r.spec.model_dump()},
            "budget": budget_view(r.data),
            "design_id": design_id,
            "design": r.data["design"],
            "build_plan": r.data["build_plan"],
            "parse": r.data["parse"],
            "quick_scene": default_scene(r.data["design"]),
            "tokens": self.tokens(),
        }

    def starter(self) -> dict:
        # Same design every time, keyword parser only: loading the page costs no tokens.
        if self._starter is None:
            self._starter = run(STARTER_IDEA, use_llm=False)
        out = self.respond(self._starter, llm_used=False)
        out["reply"] = None
        return out


def _previous_spec(state: State, spec) -> SatSpec | None:
    if not isinstance(spec, dict) or not spec:
        return None
    entry = state.get(spec.get("design_id"))
    fields = entry["spec"] if entry else {k: v for k, v in spec.items() if k in SatSpec.model_fields}
    try:
        return SatSpec.model_validate(fields)
    except ValueError:
        return None


class Handler(BaseHTTPRequestHandler):
    state: State  # set in main()
    server_version = "CubeSatProto/1.0"

    def log_message(self, fmt, *args):
        sys.stderr.write("  %s\n" % (fmt % args))

    # ---- helpers
    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, obj) -> None:
        self._send(code, json.dumps(obj).encode(), "application/json")

    def _error(self, code: int, detail: str) -> None:
        self._json(code, {"detail": detail})

    def _same_origin(self) -> bool:
        # Block other websites from driving this server (and spending tokens) through your browser.
        origin = self.headers.get("Origin")
        if origin and urlparse(origin).netloc != self.headers.get("Host"):
            return False
        return (self.headers.get("Content-Type") or "").startswith("application/json")

    def _body(self) -> dict | None:
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return None
        if n < 0 or n > MAX_BODY_BYTES:
            return None
        try:
            data = json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            return None
        return data if isinstance(data, dict) else None

    # ---- routes
    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            return self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
        if path == "/api/tokens":
            return self._json(200, self.state.tokens())
        if path == "/favicon.ico":
            return self._send(204, b"", "image/x-icon")
        self._error(404, "not found")

    def do_POST(self):
        path = urlparse(self.path).path
        if not self._same_origin():
            return self._error(403, "requests must come from this page as JSON")
        body = self._body()
        if body is None:
            return self._error(400, "expected a JSON object")
        try:
            if path == "/api/budget":
                return self._json(200, self.state.starter())
            if path == "/api/cubesat-chat":
                return self._chat(body)
            if path == "/api/visual":
                return self._visual(body)
        except Exception as e:  # noqa: BLE001 - report instead of dropping the connection
            return self._error(500, f"{type(e).__name__}: {e}")
        self._error(404, "not found")

    def _chat(self, body: dict):
        messages = body.get("messages") if isinstance(body.get("messages"), list) else []
        users = [m for m in messages if isinstance(m, dict) and m.get("role") == "user"]
        text = str(users[-1].get("content") or "").strip()[:MAX_IDEA_CHARS] if users else ""
        if not text:
            return self._error(400, "no user message")
        spec = body.get("spec")
        previous = _previous_spec(self.state, spec)
        previous_id = spec.get("design_id") if isinstance(spec, dict) and self.state.get(spec.get("design_id")) else None
        r = run(text, previous=previous, use_llm=None if self.state.use_llm else False)
        if r.data.get("off_topic"):
            return self._json(200, {
                "reply": "That doesn't look like a satellite idea. Try something like: a 3U CubeSat that images crops from a polar orbit.",
                "spec": body.get("spec") or {}, "off_topic": True})
        self._json(200, self.state.respond(r, self.state.use_llm, previous_id))

    def _visual(self, body: dict):
        entry = self.state.get(body.get("design_id"))
        if not entry:
            return self._error(404, "unknown design; make a new one")
        # An edit of a design that was already drawn only needs its new or changed parts placed.
        prev = self.state.get(entry.get("previous_id"))
        previous = ({"design": prev["design"], "scene": prev["scene"], "source": prev["scene_source"]}
                    if prev and prev.get("scene") else None)
        out = self.state.generator.generate(entry["design"], regenerate=bool(body.get("regenerate")),
                                            use_llm=self.state.use_llm, previous=previous)
        entry["scene"], entry["scene_source"] = out["scene"], out["source"]
        self._json(200, out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Serve the CubeSat prototype at http://localhost:PORT")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--no-llm", action="store_true", help="keyword parser and default 3D layout only (no API calls)")
    args = ap.parse_args(argv)

    has_key = bool(os.environ.get("ANTHROPIC_API_KEY"))
    use_llm = has_key and not args.no_llm
    Handler.state = State(use_llm)
    httpd = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    b = Handler.state.generator.budget.status()
    print(f"CubeSat prototype: http://localhost:{args.port}", flush=True)
    if use_llm:
        print(f"3D visuals: {b['sonnet_model']} until {b['sonnet_token_limit']:,} tokens "
              f"({b['sonnet_tokens_used']:,} used so far), then {b['haiku_model']}.", flush=True)
    else:
        print("No API key (or --no-llm): keyword parser and the default 3D layout only.", flush=True)
    print("Ctrl+C to stop.", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
