"""Token meter for the 3D visuals (Sonnet). No limit: it counts, so spend stays visible.

The count is saved to a file so it survives restarts. tokens_used is every token of
every call (input, cache writes, cache reads, output); cost_usd prices them at
Sonnet 5.5 rates, so cached input shows as the cheap part it is.
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

SONNET_MODEL = os.environ.get("VISUALIZER_SONNET_MODEL", "claude-sonnet-5-5")
# Sonnet 5.5, $ per million tokens: input, 5-minute cache write (1.25x), cache read (0.1x), output.
PRICE_PER_MTOK = {"input": 2.00, "cache_write": 2.50, "cache_read": 0.20, "output": 10.00}
USAGE_FILE = Path(os.environ.get("VISUALIZER_USAGE_FILE", Path(__file__).with_name("usage.json")))


def cost_usd(input_tokens: int, output_tokens: int, cache_write: int = 0, cache_read: int = 0) -> float:
    counts = {"input": input_tokens, "output": output_tokens, "cache_write": cache_write, "cache_read": cache_read}
    return sum(PRICE_PER_MTOK[k] * int(v) for k, v in counts.items()) / 1e6


class TokenUsage:
    def __init__(self, path: Path = USAGE_FILE):
        self.path = Path(path)
        self._lock = threading.Lock()
        self._data = self._load()

    def _load(self) -> dict:
        try:
            data = json.loads(self.path.read_text())
            if isinstance(data, dict) and "cost_usd" in data:
                return {"tokens_used": int(data.get("tokens_used", 0)), "cost_usd": float(data["cost_usd"]),
                        "calls": list(data.get("calls", []))}
            if isinstance(data, dict):
                # A file from the old 25k budget: its count weighted cached tokens and had no cost.
                # Rebuild both from its call log (the last 50 calls), or keep the old count without one.
                calls = [c for c in data.get("calls", []) if isinstance(c, dict) and "claude-sonnet" in str(c.get("model"))]
                counts = [(int(c.get("input_tokens") or 0), int(c.get("output_tokens") or 0),
                           int(c.get("cache_write") or 0), int(c.get("cache_read") or 0)) for c in calls]
                if counts:
                    return {"tokens_used": sum(map(sum, counts)), "cost_usd": round(sum(cost_usd(*n) for n in counts), 6),
                            "calls": calls}
                return {"tokens_used": int(data.get("sonnet_tokens_used", 0)), "cost_usd": 0.0, "calls": []}
        except (OSError, ValueError, TypeError, AttributeError):
            pass
        return {"tokens_used": 0, "cost_usd": 0.0, "calls": []}

    def _save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._data, indent=1))
        tmp.replace(self.path)

    @property
    def used(self) -> int:
        return self._data["tokens_used"]

    def record(self, model: str, input_tokens: int, output_tokens: int, note: str = "",
               cache_write: int = 0, cache_read: int = 0) -> None:
        usd = cost_usd(input_tokens, output_tokens, cache_write, cache_read)
        with self._lock:
            self._data["tokens_used"] += int(input_tokens) + int(output_tokens) + int(cache_write) + int(cache_read)
            self._data["cost_usd"] = round(self._data["cost_usd"] + usd, 6)
            self._data["calls"] = (self._data["calls"] + [{
                "at": time.strftime("%Y-%m-%d %H:%M:%S"), "model": model,
                "input_tokens": input_tokens, "cache_write": cache_write, "cache_read": cache_read,
                "output_tokens": output_tokens, "cost_usd": round(usd, 6), "note": note,
            }])[-50:]
            self._save()

    def reset(self) -> None:
        with self._lock:
            self._data = {"tokens_used": 0, "cost_usd": 0.0, "calls": []}
            self._save()

    def status(self) -> dict:
        with self._lock:
            return {"model": SONNET_MODEL, "tokens_used": self.used, "cost_usd": round(self._data["cost_usd"], 4)}
