"""Find the sibling projects (budget engine, parser, database) from anywhere in the repo."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DB_PATH = REPO / "database" / "cubesat.db"


def _load_budget_engine():
    # Load by path: `import budget_engine` would find the budget_engine/ folder instead of the file.
    # Same module name as budget_engine/tests, so both share one copy.
    name = "budget_engine_module"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, REPO / "budget_engine" / "budget_engine.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


be = _load_budget_engine()

if str(REPO / "sat-parser") not in sys.path:
    sys.path.insert(0, str(REPO / "sat-parser"))
