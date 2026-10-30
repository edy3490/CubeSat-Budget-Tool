"""Try the parser from a terminal:

    python -m sat_parser "6U camera cubesat in sun-synchronous orbit for 2 years"
    python -m sat_parser --no-llm "3U radio relay at 550 km"
"""
import argparse
import json

from . import parse_idea

try:  # load ANTHROPIC_API_KEY from a .env file if python-dotenv is installed
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def main():
    ap = argparse.ArgumentParser(description="Parse a satellite idea into a spec.")
    ap.add_argument("idea", help="The idea, in plain language (put it in quotes)")
    ap.add_argument("--no-llm", action="store_true", help="Use only the keyword fallback")
    args = ap.parse_args()

    result = parse_idea(args.idea, use_llm=False if args.no_llm else None)
    print(json.dumps({
        "source": result.source,
        "error": result.error,
        "usage": result.usage,
        "spec": result.spec.model_dump(),
    }, indent=2))


if __name__ == "__main__":
    main()
