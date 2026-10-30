"""The keyword fallback must handle common phrasings well enough to keep a demo alive."""
import pytest

from sat_parser.fallback import keyword_parse

CASES = [
    # (text, expected subset of fields)
    ("6U CubeSat with a camera to image wildfires", {"size_u": 6, "payload": "camera"}),
    ("a 3 U radio relay sat for ham operators", {"size_u": 3, "payload": "radio_relay"}),
    ("12u cubesat measuring radiation in a polar orbit", {"size_u": 12, "payload": "sensor", "orbit": "SSO"}),
    ("sun-synchronous imaging satellite at 550 km", {"orbit": "SSO", "altitude_km": 550, "payload": "camera"}),
    ("satellite that lasts 18 months", {"lifetime_years": 1.5}),
    ("cubesat for 2 years in low earth orbit", {"lifetime_years": 2.0, "orbit": "LEO"}),
    ("geostationary comms satellite", {"orbit": "GEO", "payload": "radio_relay"}),
]


@pytest.mark.parametrize("text,expected", CASES)
def test_keyword_parse_finds_fields(text, expected):
    out = keyword_parse(text)
    for key, value in expected.items():
        got = out.get(key)
        if isinstance(value, float):
            assert got == pytest.approx(value), f"{key}: expected {value!r}, got {got!r} for {text!r}"
        else:
            assert got == value, f"{key}: expected {value!r}, got {got!r} for {text!r}"


def test_only_found_fields_are_returned():
    out = keyword_parse("a satellite")
    assert "size_u" not in out and "payload" not in out and "altitude_km" not in out


def test_off_topic_text_is_flagged():
    assert keyword_parse("make me a sandwich").get("off_topic") is True


def test_known_limit_weather_question_looks_like_a_sensor():
    # Documents a false positive: "weather" is a sensor keyword, so the fallback
    # thinks this is a satellite idea. The LLM path handles it correctly.
    assert keyword_parse("what's the weather like in LA").get("payload") == "sensor"


def test_space_words_prevent_off_topic():
    assert keyword_parse("I want to launch something into orbit").get("off_topic") is not True
