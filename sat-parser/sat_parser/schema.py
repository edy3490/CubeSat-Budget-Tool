"""The satellite spec: the one JSON format the parser produces and the budget engine reads.

Agree on this file with the Python (budget engine) person first. If you change a field
here, update the tool schema in llm.py and the keyword rules in fallback.py to match.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Allowed values. Keep these in sync with the rows in the parts table, so the
# parser can never produce something the budget engine has no data for.
# ---------------------------------------------------------------------------
ALLOWED_SIZES = (1, 3, 6, 12)                       # CubeSat form factors, in U
PAYLOADS = ("camera", "radio_relay", "sensor", "other")
ORBITS = ("LEO", "SSO")                             # low Earth orbit, sun-synchronous

Payload = Literal["camera", "radio_relay", "sensor", "other"]
Orbit = Literal["LEO", "SSO"]

# Values used when the user does not say. Every default that gets used is listed
# in SatSpec.assumed, so the UI can show "Assumed: 3U, 500 km" instead of hiding it.
DEFAULTS = {
    "size_u": 3,
    "payload": "other",
    "orbit": "LEO",
    "altitude_km": 500,
    "lifetime_years": 1.0,
}

# Sanity ranges. Out-of-range numbers are clamped and a warning is added.
ALTITUDE_RANGE_KM = (200, 2000)
LIFETIME_RANGE_YEARS = (0.1, 10.0)


class SatSpec(BaseModel):
    """A cleaned, validated satellite request. Every field is always filled in."""

    size_u: int = Field(description="CubeSat size in U (1, 3, 6 or 12)")
    payload: Payload
    orbit: Orbit
    altitude_km: int
    lifetime_years: float
    mission_goal: str = Field(default="", description="What it is for, e.g. 'Image wildfires'. Empty if the user didn't say")
    notes: str = Field(default="", description="Anything the user asked for that doesn't fit a field")
    off_topic: bool = Field(default=False, description="True if the text isn't a satellite idea")
    assumed: list[str] = Field(default_factory=list, description="Fields filled from DEFAULTS")
    warnings: list[str] = Field(default_factory=list, description="Values that were changed to fit")


def _snap_size(value) -> tuple[int, Optional[str]]:
    """Round a size to the nearest allowed form factor. Returns (size, warning or None)."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return DEFAULTS["size_u"], f"Couldn't read size {value!r}; used {DEFAULTS['size_u']}U"
    best = min(ALLOWED_SIZES, key=lambda s: abs(s - v))
    if best != v:
        return best, f"Size {value}U isn't a supported form factor; used {best}U"
    return best, None


def _clamp(value, low, high, name, default):
    """Clamp a number into [low, high]. Returns (number, warning or None)."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default, f"Couldn't read {name} {value!r}; used {default}"
    if v < low:
        return low, f"{name} {value} is below {low}; used {low}"
    if v > high:
        return high, f"{name} {value} is above {high}; used {high}"
    return v, None


def normalize(raw: dict) -> SatSpec:
    """Turn whatever the parser produced (LLM or keywords) into a valid SatSpec.

    `raw` may be missing fields or contain bad values; this function never trusts it.
    """
    raw = dict(raw or {})
    assumed: list[str] = []
    warnings: list[str] = list(raw.pop("warnings", []) or [])
    raw.pop("assumed", None)  # recomputed below, never trusted from input

    def missing(key):
        return raw.get(key) in (None, "")

    # size_u
    if missing("size_u"):
        size_u = DEFAULTS["size_u"]
        assumed.append("size_u")
    else:
        size_u, w = _snap_size(raw["size_u"])
        if w:
            warnings.append(w)

    # payload
    payload = raw.get("payload")
    if missing("payload"):
        payload = DEFAULTS["payload"]
        assumed.append("payload")
    elif payload not in PAYLOADS:
        warnings.append(f"Unknown payload {payload!r}; used 'other'")
        payload = "other"

    # orbit
    orbit = str(raw.get("orbit") or "").upper()
    if not orbit:
        orbit = DEFAULTS["orbit"]
        assumed.append("orbit")
    elif orbit not in ORBITS:
        warnings.append(f"Orbit {raw['orbit']!r} isn't supported yet; used LEO")
        orbit = "LEO"

    # altitude_km
    if missing("altitude_km"):
        altitude = DEFAULTS["altitude_km"]
        assumed.append("altitude_km")
    else:
        altitude, w = _clamp(raw["altitude_km"], *ALTITUDE_RANGE_KM, "altitude_km", DEFAULTS["altitude_km"])
        if w:
            warnings.append(w)

    # lifetime_years
    if missing("lifetime_years"):
        lifetime = DEFAULTS["lifetime_years"]
        assumed.append("lifetime_years")
    else:
        lifetime, w = _clamp(raw["lifetime_years"], *LIFETIME_RANGE_YEARS, "lifetime_years", DEFAULTS["lifetime_years"])
        if w:
            warnings.append(w)

    return SatSpec(
        size_u=int(size_u),
        payload=payload,
        orbit=orbit,
        altitude_km=int(round(float(altitude))),
        lifetime_years=round(float(lifetime), 2),
        mission_goal=str(raw.get("mission_goal") or "")[:200],
        notes=str(raw.get("notes") or "")[:500],
        off_topic=bool(raw.get("off_topic", False)),
        assumed=assumed,
        warnings=warnings,
    )
