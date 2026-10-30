"""Test app: type a satellite idea, get a CubeSat design.

    python -m designer                         # interactive
    python -m designer "6U camera for wildfires, polar orbit"
    python -m designer --json "3U radio relay"  # full JSON (what a front end would get)
    python -m designer --no-llm "..."           # keyword parser only, no API calls

In interactive mode each new message edits the last design ("make it 6U", "fly at 400 km").
Commands: new (start over), json (dump the last result), quit.
"""
from __future__ import annotations

import argparse
import json

from ._paths import REPO
from .pipeline import run
from .report import render

try:  # pick up ANTHROPIC_API_KEY from .env files if python-dotenv is installed
    from dotenv import load_dotenv
    load_dotenv(REPO / ".env")
    load_dotenv(REPO / "sat-parser" / ".env")
except ImportError:
    pass


def _show(result, as_json: bool):
    print(json.dumps(result.data, indent=2) if as_json else render(result.data))


def interactive(use_llm):
    print("CubeSat designer. Describe an idea; follow-ups edit it. Commands: new, json, quit.")
    spec, last = None, None
    while True:
        try:
            text = input("\nidea> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not text:
            continue
        if text.lower() in ("quit", "exit", "q"):
            return
        if text.lower() == "new":
            spec, last = None, None
            print("Starting over.")
            continue
        if text.lower() == "json":
            print(json.dumps(last.data, indent=2) if last else "Nothing yet.")
            continue
        last = run(text, previous=spec, use_llm=use_llm)
        spec = last.spec
        _show(last, as_json=False)


def main():
    ap = argparse.ArgumentParser(description="Design a CubeSat from an idea.")
    ap.add_argument("idea", nargs="?", help="The idea in plain language (omit for interactive mode)")
    ap.add_argument("--json", action="store_true", help="Print the full result as JSON")
    ap.add_argument("--no-llm", action="store_true", help="Use only the keyword parser")
    args = ap.parse_args()
    use_llm = False if args.no_llm else None
    if args.idea:
        _show(run(args.idea, use_llm=use_llm), args.json)
    else:
        interactive(use_llm)


if __name__ == "__main__":
    main()
