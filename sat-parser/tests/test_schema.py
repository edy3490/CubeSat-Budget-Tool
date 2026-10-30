"""normalize() is the safety net: whatever comes in, a valid SatSpec comes out."""
from sat_parser.schema import DEFAULTS, normalize


def test_empty_input_uses_all_defaults_and_marks_them_assumed():
    spec = normalize({})
    assert spec.size_u == DEFAULTS["size_u"]
    assert spec.orbit == "LEO"
    assert set(spec.assumed) == {"size_u", "payload", "orbit", "altitude_km", "lifetime_years"}
    assert spec.warnings == []


def test_stated_values_are_kept_and_not_marked_assumed():
    spec = normalize({"size_u": 6, "payload": "camera", "orbit": "SSO",
                      "altitude_km": 550, "lifetime_years": 2})
    assert (spec.size_u, spec.payload, spec.orbit, spec.altitude_km, spec.lifetime_years) == \
           (6, "camera", "SSO", 550, 2.0)
    assert spec.assumed == []


def test_odd_size_rounds_up_to_a_form_factor_with_warning():
    spec = normalize({"size_u": 5})
    assert spec.size_u == 6
    assert any("5U" in w for w in spec.warnings)


def test_2u_rounds_up_to_3u_not_down_to_1u():
    spec = normalize({"size_u": 2})
    assert spec.size_u == 3
    assert any("2" in w and "3U" in w for w in spec.warnings)


def test_huge_size_snaps_to_12u():
    assert normalize({"size_u": 100}).size_u == 12


def test_altitude_out_of_range_is_clamped():
    assert normalize({"altitude_km": 36000}).altitude_km == 2000
    assert normalize({"altitude_km": 50}).altitude_km == 200


def test_lifetime_out_of_range_is_clamped():
    assert normalize({"lifetime_years": 50}).lifetime_years == 10.0


def test_unknown_payload_becomes_other_with_warning():
    spec = normalize({"payload": "laser cannon"})
    assert spec.payload == "other"
    assert spec.warnings


def test_unsupported_orbit_becomes_leo_with_warning():
    spec = normalize({"orbit": "GEO"})
    assert spec.orbit == "LEO"
    assert any("GEO" in w for w in spec.warnings)


def test_lowercase_orbit_is_accepted():
    assert normalize({"orbit": "sso"}).orbit == "SSO"


def test_garbage_numbers_fall_back_to_defaults():
    spec = normalize({"size_u": "big", "altitude_km": "high"})
    assert spec.size_u == DEFAULTS["size_u"]
    assert spec.altitude_km == DEFAULTS["altitude_km"]
    assert len(spec.warnings) == 2


def test_input_cannot_fake_the_assumed_list():
    spec = normalize({"assumed": ["nothing"], "size_u": 3})
    assert "nothing" not in spec.assumed
