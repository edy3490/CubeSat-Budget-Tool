"""Command line for the 3D visual generator.

    python -m visualizer "3U camera cubesat"      # design it, generate the 3D scene, print a summary
    python -m visualizer --json "3U camera"       # print the full scene JSON
    python -m visualizer --no-llm "3U camera"     # default layout only, no API calls
    python -m visualizer --budget                 # show the Sonnet token budget
    python -m visualizer --reset-budget           # start the 25k Sonnet budget over
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .budget import TokenBudget
from .generator import SceneGenerator

REPO = Path(__file__).resolve().parent.parent


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m visualizer", description="Generate a 3D scene of a CubeSat design.")
    ap.add_argument("idea", nargs="*")
    ap.add_argument("--json", action="store_true", help="print the full scene JSON")
    ap.add_argument("--no-llm", action="store_true", help="default layout only, no API calls")
    ap.add_argument("--budget", action="store_true", help="show the token budget")
    ap.add_argument("--reset-budget", action="store_true", help="reset the Sonnet token count to 0")
    args = ap.parse_args(argv)

    budget = TokenBudget()
    if args.reset_budget:
        budget.reset()
        print("Sonnet token count reset to 0.")
    if args.budget or args.reset_budget:
        print(json.dumps(budget.status(), indent=2))
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
    out = SceneGenerator(budget).generate(r.data["design"], use_llm=not args.no_llm)
    if args.json:
        print(json.dumps(out, indent=1))
        return 0
    s = out["scene"]
    print(f"{r.data['design']['form_factor']} {r.data['design']['name']}")
    print(f"source: {out['source']}  model: {out['model']}  usage: {out['usage']}")
    print(f"parts: {len(s['parts'])}  shapes: {sum(len(p['shapes']) for p in s['parts'])}")
    print(f"fit: {s['fit']['verdict']} - {s['fit']['note']}")
    print(f"summary: {s['summary']}")
    for a in out["attempts"]:
        print("attempt:", a)
    for note in out["repairs"]:
        print("repair:", note)
    b = out["budget"]
    print(f"Sonnet budget: {b['sonnet_tokens_used']:,} / {b['sonnet_token_limit']:,} tokens used; next call uses {b['active_model']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
