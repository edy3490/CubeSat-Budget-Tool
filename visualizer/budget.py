"""Token budget for the 3D visuals: Sonnet until 25k tokens are spent, then Haiku.

The count (input + output tokens of every Sonnet call) is saved to a file so it
survives restarts. It's a hard cap: before each Sonnet call the worst case
(input estimate + max output) is reserved, and Sonnet is only used if that fits.
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

SONNET_MODEL = os.environ.get("VISUALIZER_SONNET_MODEL", "claude-sonnet-5-5")
HAIKU_MODEL = os.environ.get("VISUALIZER_HAIKU_MODEL", "claude-haiku-5-5")
SONNET_TOKEN_LIMIT = int(os.environ.get("VISUALIZER_SONNET_TOKEN_LIMIT", "25000"))
USAGE_FILE = Path(os.environ.get("VISUALIZER_USAGE_FILE", Path(__file__).with_name("usage.json")))


class TokenBudget:
    def __init__(self, path: Path = USAGE_FILE, limit: int = SONNET_TOKEN_LIMIT, min_call: int = 6000):
        self.path = Path(path)
        self.limit = limit
        self.min_call = min_call      # smallest Sonnet call worth making (input + output); only for status()
        self._lock = threading.Lock()
        self._reserved = 0
        self._data = self._load()

    def _load(self) -> dict:
        try:
            data = json.loads(self.path.read_text())
            if isinstance(data.get("sonnet_tokens_used"), int):
                data.setdefault("haiku_tokens_used", 0)
                data.setdefault("calls", [])
                return data
        except (OSError, ValueError, AttributeError):
            pass
        return {"sonnet_tokens_used": 0, "haiku_tokens_used": 0, "calls": []}

    def _save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._data, indent=1))
        tmp.replace(self.path)

    @property
    def used(self) -> int:
        return self._data["sonnet_tokens_used"]

    def reserve(self, input_estimate: int, max_output: int, min_output: int) -> tuple[str, int, int]:
        """Pick the model for the next call. Returns (model, max_tokens, reservation).

        Sonnet if at least `min_output` tokens of output still fit under the limit,
        with max_tokens trimmed so the call can't cross it. Otherwise Haiku.
        Pass the reservation back to record() (or release() if the call fails).
        """
        with self._lock:
            room = self.limit - self.used - self._reserved - input_estimate
            if room >= min_output:
                out = min(max_output, room)
                self._reserved += input_estimate + out
                return SONNET_MODEL, out, input_estimate + out
            return HAIKU_MODEL, max_output, 0

    def release(self, reservation: int) -> None:
        with self._lock:
            self._reserved = max(0, self._reserved - reservation)

    def record(self, model: str, input_tokens: int, output_tokens: int, reservation: int = 0, note: str = "") -> None:
        with self._lock:
            self._reserved = max(0, self._reserved - reservation)
            key = "sonnet_tokens_used" if model == SONNET_MODEL else "haiku_tokens_used"
            self._data[key] += int(input_tokens) + int(output_tokens)
            self._data["calls"] = (self._data["calls"] + [{
                "at": time.strftime("%Y-%m-%d %H:%M:%S"), "model": model,
                "input_tokens": input_tokens, "output_tokens": output_tokens, "note": note,
            }])[-50:]
            self._save()

    def reset(self) -> None:
        with self._lock:
            self._data = {"sonnet_tokens_used": 0, "haiku_tokens_used": 0, "calls": []}
            self._save()

    def status(self) -> dict:
        with self._lock:
            used = self.used
            return {
                "sonnet_model": SONNET_MODEL, "haiku_model": HAIKU_MODEL,
                "sonnet_tokens_used": used, "sonnet_token_limit": self.limit,
                "sonnet_tokens_left": max(0, self.limit - used),
                "haiku_tokens_used": self._data["haiku_tokens_used"],
                "active_model": SONNET_MODEL if self.limit - used >= self.min_call else HAIKU_MODEL,
            }
