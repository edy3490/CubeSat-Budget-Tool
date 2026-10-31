"""Local web server for the CubeSat prototype: serves front-end/index.html and its JSON API.

    sat-parser/.venv/bin/python server.py            # then open http://localhost:8000
    sat-parser/.venv/bin/python server.py --port 8080 --no-llm

API (POST bodies are JSON; errors come back as {"detail": "..."}):
    POST /api/budget        {}                              -> starter design
    POST /api/cubesat-chat  {"messages": [...], "spec": {}} -> {"reply", "spec", "budget", ...}
    POST /api/visual        {"design_id", "regenerate"}     -> 3D scene placed by Sonnet
    POST /api/restore       {"design_id", "spec", "text"}   -> re-register a saved project's design after a restart
    POST /api/export        {"design_id", "format", "exploded", "name"} -> the 3D model as a STEP or STL file for CAD
    GET  /api/tokens                                        -> Sonnet tokens and cost so far

`spec` is opaque to the page: it sends back whatever the last response gave it.
`budget` is the page's summary shape (mass, power, cost, rows, notes); the full
design, build plan and quick 3D layout come alongside it.

The API key stays on the server; the page never sees it. Listens on localhost only unless
--host / HOST says otherwise (the Render config sets 0.0.0.0). AI calls are rate limited per
visitor and per site (see LIMITS); over a limit, requests fall back to the non-AI path.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import sys
import threading
import time
from collections import OrderedDict, deque
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

from designer import from_spec, run                   # noqa: E402  (also puts sat-parser on sys.path)
from sat_parser import SatSpec                        # noqa: E402
from visualizer import SceneGenerator, default_scene  # noqa: E402
from visualizer.export import file_name, to_step, to_stl  # noqa: E402

PAGE = REPO / "front-end" / "index.html"
STARTER_IDEA = "6U CubeSat that images wildfires from low Earth orbit for 1 year"
MAX_BODY_BYTES = 256_000
MAX_IDEA_CHARS = 2_000
KEEP_DESIGNS = 100


# ---------------------------------------------------------------- AI limits (for a public site)
# Over a limit, a request still works, just without AI (keyword parser, rule-based 3D layout),
# so one busy visitor can't run up the API bill. Set any of these to 0 to turn it off.

def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


LIMITS = {   # (per visitor per hour, whole site per hour)
    "chat": (_env_int("CHAT_PER_VISITOR_HOUR", 30), _env_int("CHAT_PER_HOUR", 400)),
    "visual": (_env_int("VISUAL_PER_VISITOR_HOUR", 10), _env_int("VISUAL_PER_HOUR", 100)),
}
# Behind a host's proxy (Render, Railway, ...) every request comes from the proxy, so the visitor's
# address is read from X-Forwarded-For instead.
TRUST_PROXY = os.environ.get("TRUST_PROXY", "").lower() in ("1", "true", "yes")


class RateLimiter:
    """Sliding one-hour window per (kind, visitor), plus one per kind for the whole site."""

    def __init__(self, limits: dict):
        self.limits = limits
        self._hits: dict[tuple, deque] = {}
        self._lock = threading.Lock()

    def allow(self, kind: str, visitor: str) -> bool:
        per_visitor, overall = self.limits[kind]
        now = time.monotonic()
        with self._lock:
            if len(self._hits) > 5000:   # forget visitors who have gone quiet
                self._hits = {k: d for k, d in self._hits.items() if d and now - d[-1] < 3600}
            mine = self._hits.setdefault((kind, visitor), deque())
            everyone = self._hits.setdefault((kind, None), deque())
            for d in (mine, everyone):
                while d and now - d[0] > 3600:
                    d.popleft()
            if (per_visitor and len(mine) >= per_visitor) or (overall and len(everyone) >= overall):
                return False
            mine.append(now)
            everyone.append(now)
            return True


LIMITER = RateLimiter(LIMITS)
LIMIT_NOTE = "(AI limit reached for now, so this used the keyword parser. It'll be back within the hour.)"


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

    def put(self, entry: dict, key: str | None = None) -> str:
        key = key or secrets.token_hex(8)
        with self._lock:
            self._designs[key] = entry
            while len(self._designs) > KEEP_DESIGNS:
                self._designs.popitem(last=False)
        return key

    def get(self, key) -> dict | None:
        with self._lock:
            return self._designs.get(key) if isinstance(key, str) else None

    def tokens(self) -> dict:
        return {**self.generator.usage.status(), "llm": self.use_llm}

    @staticmethod
    def _entry(r, previous_id: str | None) -> dict:
        # What the user asked for: the 3D call uses it to explain the satellite and add extras.
        # The designer's notes (e.g. no attitude-control unit) keep the 3D description consistent with the parts list.
        request = {"text": r.data["idea"], "goal": r.spec.mission_goal, "notes": r.spec.notes,
                   "design_notes": r.data["design"]["decisions"]}
        return {"spec": r.spec.model_dump(), "design": r.data["design"], "previous_id": previous_id, "request": request}

    def respond(self, r, llm_used: bool, previous_id: str | None = None) -> dict:
        """Package a designer Result in the page's response shape."""
        design_id = self.put(self._entry(r, previous_id))
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

    def restore(self, key, spec_fields, text: str = "") -> bool:
        """Re-register a design the browser saved but this server has forgotten (it restarted, or
        the design aged out), under the same id so the page's references stay valid. The design is
        rebuilt from its spec, so its 3D layout comes back from the scene cache without a model call."""
        if not isinstance(key, str) or not re.fullmatch(r"[0-9a-f]{16}", key):
            return False
        if self.get(key):
            return True
        if not isinstance(spec_fields, dict):
            return False
        try:
            spec = SatSpec.model_validate({k: v for k, v in spec_fields.items() if k in SatSpec.model_fields})
        except ValueError:
            return False
        entry = self._entry(from_spec(spec, str(text or "")[:MAX_IDEA_CHARS]), None)
        scene = self.generator.cached(entry["design"], entry["request"])
        if scene:
            entry["scene"], entry["scene_source"] = scene, "cache"
        self.put(entry, key)
        return True

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
    def _send(self, code: int, body: bytes, ctype: str, download: str | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        if download:
            self.send_header("Content-Disposition", f'attachment; filename="{download}"')
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, obj) -> None:
        self._send(code, json.dumps(obj).encode(), "application/json")

    def _error(self, code: int, detail: str) -> None:
        self._json(code, {"detail": detail})

    def _visitor(self) -> str:
        fwd = self.headers.get("X-Forwarded-For") if TRUST_PROXY else None
        return fwd.split(",")[0].strip() if fwd else self.client_address[0]

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
            if path == "/api/restore":
                ok = self.state.restore(body.get("design_id"), body.get("spec"), body.get("text"))
                return self._json(200, {"restored": True}) if ok else self._error(400, "can't restore that design")
            if path == "/api/export":
                return self._export(body)
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
        limited = self.state.use_llm and not LIMITER.allow("chat", self._visitor())
        use_llm = self.state.use_llm and not limited
        r = run(text, previous=previous, use_llm=None if use_llm else False)
        if r.data.get("off_topic"):
            return self._json(200, {
                "reply": "That doesn't look like a satellite idea. Try something like: a 3U CubeSat that images crops from a polar orbit.",
                "spec": body.get("spec") or {}, "off_topic": True})
        out = self.state.respond(r, use_llm, previous_id)
        if limited:
            out["reply"] = out["reply"].replace("(Keyword parser, offline mode.)", LIMIT_NOTE)
        self._json(200, out)

    def _visual(self, body: dict):
        entry = self.state.get(body.get("design_id"))
        if not entry:
            return self._error(404, "unknown design; make a new one")
        # An edit of a design that was already drawn only needs its new or changed parts placed.
        prev = self.state.get(entry.get("previous_id"))
        previous = ({"design": prev["design"], "scene": prev["scene"], "source": prev["scene_source"]}
                    if prev and prev.get("scene") else None)
        out = self.state.generator.generate(entry["design"], regenerate=bool(body.get("regenerate")),
                                            use_llm=self.state.use_llm and LIMITER.allow("visual", self._visitor()),
                                            previous=previous,
                                            request=entry.get("request"))
        entry["scene"], entry["scene_source"] = out["scene"], out["source"]
        self._json(200, out)

    def _export(self, body: dict):
        fmt = body.get("format", "step")
        if fmt not in ("step", "stl"):
            return self._error(400, "format must be step or stl")
        entry = self.state.get(body.get("design_id"))
        if not entry:
            return self._error(404, "unknown design; make a new one")
        # The model's drawing once it has arrived, otherwise the quick layout the page is showing.
        scene = entry.get("scene") or default_scene(entry["design"])
        # The user's name for the project, if they gave one; it names the file and the CAD assembly.
        name = str(body.get("name") or "").strip()[:80] or entry["design"].get("name") or "CubeSat"
        exploded = bool(body.get("exploded"))
        if fmt == "stl":
            return self._send(200, to_stl(scene, name, exploded), "model/stl", download=file_name(name, "stl"))
        self._send(200, to_step(scene, name, exploded).encode("ascii"), "application/step", download=file_name(name))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Serve the CubeSat prototype at http://localhost:PORT")
    ap.add_argument("--port", type=int, default=_env_int("PORT", 8000))
    ap.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"),
                    help="0.0.0.0 to accept outside visitors (set by the hosting config)")
    ap.add_argument("--no-llm", action="store_true", help="keyword parser and default 3D layout only (no API calls)")
    args = ap.parse_args(argv)

    has_key = bool(os.environ.get("ANTHROPIC_API_KEY"))
    use_llm = has_key and not args.no_llm
    Handler.state = State(use_llm)
    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    t = Handler.state.generator.usage.status()
    print(f"CubeSat prototype: http://localhost:{args.port}", flush=True)
    if use_llm:
        print(f"3D visuals: {t['model']} ({t['tokens_used']:,} tokens so far, about ${t['cost_usd']:.2f}).", flush=True)
        print("AI limits per hour (visitor / whole site): " + ", ".join(
            f"{k} {a or '∞'} / {b or '∞'}" for k, (a, b) in LIMITS.items()), flush=True)
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
