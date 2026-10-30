"""Command line for the 3D visual generator.

    python -m visualizer "3U camera cubesat"      # design it, generate the 3D scene, print a summary
    python -m visualizer --json "3U camera"       # print the full scene JSON
    python -m visualizer --no-llm "3U camera"     # default layout only, no API calls
    python -m visualizer --budget                 # show the Sonnet token count and cost so far
    python -m visualizer --reset-budget           # start the count over
    python -m visualizer --library                # list the part library and check it covers the designer
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .budget import TokenUsage
from .generator import SceneGenerator

REPO = Path(__file__).resolve().parent.parent


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m visualizer", description="Generate a 3D scene of a CubeSat design.")
    ap.add_argument("idea", nargs="*")
    ap.add_argument("--json", action="store_true", help="print the full scene JSON")
    ap.add_argument("--no-llm", action="store_true", help="default layout only, no API calls")
    ap.add_argument("--budget", action="store_true", help="show the Sonnet token count and cost so far")
    ap.add_argument("--reset-budget", action="store_true", help="reset the Sonnet token count to 0")
    ap.add_argument("--library", action="store_true", help="list the part library and check coverage")
    args = ap.parse_args(argv)

    if args.library:
        return show_library()

    usage = TokenUsage()
    if args.reset_budget:
        usage.reset()
        print("Sonnet token count reset to 0.")
    if args.budget or args.reset_budget:
        print(json.dumps(usage.status(), indent=2))
        if not args.idea:
            return 0
    if not args.idea:
        ap.print_help()
        return 1

    try:
        from dotenv import load_dotenv
        load_dotenv(REPO / ".env")
        load_dotenv(REPO / "sat-parser" / ".env")
    except ImportError:
        pass
    from designer import run

    r = run(" ".join(args.idea), use_llm=False if args.no_llm else None)
    if r.data.get("off_topic"):
        print("That doesn't look like a satellite idea.")
        return 1
    request = {"text": " ".join(args.idea), "goal": r.spec.mission_goal, "notes": r.spec.notes}
    out = SceneGenerator(budget).generate(r.data["design"], use_llm=not args.no_llm, request=request)
    if args.json:
        print(json.dumps(out, indent=1))
        return 0
    s = out["scene"]
    print(f"{r.data['design']['form_factor']} {r.data['design']['name']}")
    print(f"source: {out['source']}  model: {out['model']}  usage: {out['usage']}")
    print(f"parts: {len(s['parts'])}  shapes: {sum(len(p['shapes']) for p in s['parts'])}")
    print(f"fit: {s['fit']['verdict']} - {s['fit']['note']}")
    print(f"summary: {s['summary']}")
    if s.get("description"):
        print(f"\nHow it works: {s['description']['overview']}")
        for p in s["parts"]:
            if p.get("role"):
                print(f"  - {p['label']}: {p['role']}")
        print(f"Layout: {s['description']['layout']}")
    for p in s["parts"]:
        if p.get("extra"):
            x = p["extra"]
            print(f"extra: {x['name']} ({x['mass_kg']} kg, {x['power_w']} W, {x['drawing']}): {x['purpose']}")
    if out.get("saved"):
        print("saved to parts/generated/:", ", ".join(out["saved"]))
    for a in out["attempts"]:
        print("attempt:", a)
    for note in out["repairs"]:
        print("repair:", note)
    t = out["tokens"]
    print(f"{t['model']}: {t['tokens_used']:,} tokens so far, about ${t['cost_usd']:.2f}")
    return 0


def show_library() -> int:
    """List library parts, then run a spread of ideas and report parts the library doesn't have."""
    import itertools

    from designer import run
    from .library import entries, lookup

    for e in sorted(entries(), key=lambda e: (e["source"] != "opus", e["mount"], e["name"])):
        size = " x ".join(f"{v:g}" for v in e["size"])
        who = "opus     " if e["source"] == "opus" else f"generated ({e.get('drawn_by', '?')}, {e.get('kind', '?')}, {e.get('file')})"
        print(f"{who}  {e['mount']:5}  {size:>22} mm  {len(e['shapes']):3} shapes  {e['name']} ({e['vendor']})"
              + ("  [estimated size]" if e["estimate"] and e["source"] == "opus" else ""))
    ideas = [f"{s} {p} at {o} for {l}{x}" for s, p, o, l, x in itertools.product(
        ("1U", "3U", "6U", "12U"), ("camera", "radio relay", "radiation sensor", "demo payload"),
        ("300 km", "550 km", "800 km"), ("1 year", "5 years"), ("", " needs a thruster", " needs GPS"))]
    missing = {}
    for idea in ideas:
        for p in run(idea, use_llm=False).data["design"]["parts"]:
            if not lookup(p["part"], p["unit_mass_kg"]):
                missing.setdefault(p["part"], idea)
    print(f"\nChecked {len(ideas)} ideas: " + ("every part is in the library." if not missing else
          f"{len(missing)} part(s) missing (the model draws these from scratch):"))
    for name, idea in missing.items():
        print(f"  {name}   e.g. \"{idea}\"")
    return 0


if __name__ == "__main__":
    sys.exit(main())
