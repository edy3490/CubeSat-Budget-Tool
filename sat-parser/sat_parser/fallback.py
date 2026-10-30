"""Keyword fallback: a no-AI parser used when the API is down, slow, or returns junk.

It's deliberately simple. It only fills fields it finds, and leaves the rest for
schema.normalize() to default (and mark as assumed).
"""
from __future__ import annotations

import re

# Order matters: the first payload whose keywords appear wins.
PAYLOAD_KEYWORDS = {
    "camera": ["camera", "imag", "photo", "picture", "pictures", "observe earth", "earth observation", "video"],
    "radio_relay": ["radio", "relay", "communicat", "comms", "messag", "iot", "ham ", "amateur", "internet", "transponder", "beacon"],
    "sensor": ["sensor", "measur", "radiation", "magnetometer", "magnetic", "temperature", "spectrometer",
               "detector", "weather", "atmospher"],
}

SPACE_WORDS = ["satellite", "cubesat", "sat ", "orbit", "spacecraft", "space", "launch", "leo", "smallsat"]


def keyword_parse(text: str) -> dict:
    """Return only the fields found in the text."""
    t = " " + text.lower() + " "
    out: dict = {}

    # Size: "6U", "6 U", "6-U", "12u cubesat"
    m = re.search(r"\b(\d{1,2})\s*-?\s*u\b", t)
    if m:
        out["size_u"] = int(m.group(1))

    # Payload
    for payload, words in PAYLOAD_KEYWORDS.items():
        if any(w in t for w in words):
            out["payload"] = payload
            break

    # Orbit
    if re.search(r"sun[\s-]?synchronous|\bsso\b|\bpolar\b", t):
        out["orbit"] = "SSO"
    elif re.search(r"\bgeo\b|geostationary|geosynchronous", t):
        out["orbit"] = "GEO"  # normalize() will turn this into LEO with a warning
    elif re.search(r"\bleo\b|low earth orbit", t):
        out["orbit"] = "LEO"

    # Altitude: "550 km", "550km"
    m = re.search(r"(\d{3,5})\s*km\b", t)
    if m:
        out["altitude_km"] = int(m.group(1))

    # Lifetime: "2 years", "18 months", "1.5 yr"
    m = re.search(r"(\d+(?:\.\d+)?)\s*(years?|yrs?|months?)\b", t)
    if m:
        n = float(m.group(1))
        out["lifetime_years"] = n / 12 if m.group(2).startswith("month") else n

    # Off-topic if nothing space-related and no payload found
    if "payload" not in out and "size_u" not in out and not any(w in t for w in SPACE_WORDS):
        out["off_topic"] = True

    # mission_goal stays unset: keywords can't tell what the satellite is for.
    return out
