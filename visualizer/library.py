"""The part library: one place to look up a ready-made drawing of a part.

Two sources, kept in separate folders (see parts/README.md):

    parts/opus/       drawn by hand by Claude Opus in the coding session. Checked first.
    parts/generated/  drawn by Sonnet/Haiku at runtime, for parts the Opus set doesn't have
                      (catalog parts it's missing, and extras invented for unusual requests
                      like "a satellite with a laser"). One JSON file per part, saved the
                      first time it's drawn and reused after that. Meant to be reviewed
                      and redrawn by Opus later, then moved into parts/opus/.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path

from .parts.opus.drawings import LIBRARY as OPUS
from .parts.opus.drawings import _key, placeholder_payload
from .parts.opus.drawings import entries as opus_entries
from .placement import recenter

GENERATED_DIR = Path(os.environ.get("VISUALIZER_GENERATED_DIR", Path(__file__).parent / "parts" / "generated"))
_lock = threading.Lock()
_generated: dict[str, dict] = {}
_loaded_from: Path | None = None


def set_generated_dir(path) -> None:
    """Point the generated-parts folder somewhere else (tests use a temp folder)."""
    global GENERATED_DIR, _loaded_from
    with _lock:
        GENERATED_DIR, _loaded_from = Path(path), None
        _generated.clear()


def _load_generated() -> dict[str, dict]:
    global _loaded_from
    with _lock:
        if _loaded_from != GENERATED_DIR:
            _generated.clear()
            for f in sorted(GENERATED_DIR.glob("*.json")):
                try:
                    e = json.loads(f.read_text())
                    _generated[_key(e["name"])] = {**e, "source": "generated", "file": f.name}
                except (OSError, ValueError, KeyError):
                    continue
            _loaded_from = GENERATED_DIR
        return _generated


def lookup(name: str, mass_kg: float | None = None) -> dict | None:
    """The drawing for a part name, or None. Opus drawings win; placeholders are sized from their mass."""
    key = _key(name)
    if key.endswith("(to be chosen)"):
        return placeholder_payload(name, mass_kg or 0.5)
    return OPUS.get(key) or _load_generated().get(key)


def generated_extras() -> list[dict]:
    """Extras drawn for earlier requests (laser, robotic arm, ...), so the model can reuse them by name."""
    return [e for e in _load_generated().values() if e.get("kind") == "extra"]


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:60] or "part"


def save_generated(name: str, shapes: list[dict], *, kind: str, model: str, vendor: str = "",
                   purpose: str = "", note: str = "", request: str = "",
                   mass_kg: float | None = None, power_w: float | None = None) -> dict | None:
    """Save a part the model drew so it's reused next time. Never replaces an existing drawing.

    kind: "catalog" (a real part missing from the Opus drawings) or "extra" (invented for a request).
    shapes are in the part's own frame; they're re-centered on their bounding box before saving.
    """
    if not shapes or lookup(name):
        return None
    shapes, size = recenter(shapes)
    entry = {
        "name": name.strip()[:80], "vendor": vendor or ("AI-added" if kind == "extra" else ""),
        "kind": kind, "mount": "stack", "size": size,
        "note": note or ("drawn by " + model + "; own +z is up"),
        "purpose": purpose[:300], "mass_kg": mass_kg, "power_w": power_w, "estimate": True,
        "drawn_by": model, "drawn_at": time.strftime("%Y-%m-%d %H:%M"), "request": request[:300],
        "review": "Drawn by a smaller model at runtime. Opus: check the size and detail, redraw it in "
                  "parts/opus/drawings.py if needed, then delete this file.",
        "shapes": shapes,
    }
    with _lock:
        GENERATED_DIR.mkdir(parents=True, exist_ok=True)
        path = GENERATED_DIR / f"{_slug(name)}.json"
        n = 2
        while path.exists():
            path = GENERATED_DIR / f"{_slug(name)}-{n}.json"
            n += 1
        path.write_text(json.dumps(entry, indent=1))
        _generated[_key(entry["name"])] = {**entry, "source": "generated", "file": path.name}
    return _generated[_key(entry["name"])]


def entries() -> list[dict]:
    """Every drawing once: Opus first, then generated."""
    return opus_entries() + [e for k, e in _load_generated().items() if k not in OPUS]
