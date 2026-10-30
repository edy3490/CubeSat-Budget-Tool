"""parse_idea() with a fake client: checks the request we send and every fallback path."""
import pytest

from sat_parser import parse_idea
from sat_parser.llm import MODEL


# ---------- happy path ----------

def test_llm_result_is_validated_and_returned(fake_client):
    client = fake_client(tool_input={"size_u": 6, "payload": "camera", "orbit": "SSO",
                                     "off_topic": False, "mission_goal": "Image wildfires"})
    result = parse_idea("6U camera sat in SSO to image wildfires", client=client)
    assert result.source == "llm"
    assert result.error is None
    assert result.spec.size_u == 6 and result.spec.orbit == "SSO"
    assert set(result.spec.assumed) == {"altitude_km", "lifetime_years"}
    assert result.usage == {"input_tokens": 900, "output_tokens": 80}


def test_request_forces_the_tool_and_caps_cost(fake_client):
    client = fake_client(tool_input={"off_topic": False})
    parse_idea("3U cubesat", client=client)
    req = client.messages.calls[0]
    assert req["model"] == MODEL
    assert req["tool_choice"] == {"type": "tool", "name": "set_spec"}
    assert req["max_tokens"] <= 500
    assert req["tools"][0]["name"] == "set_spec"


def test_bad_llm_values_are_cleaned_not_trusted(fake_client):
    client = fake_client(tool_input={"size_u": 50, "altitude_km": 99999, "payload": "death ray"})
    spec = parse_idea("huge sat", client=client).spec
    assert spec.size_u == 12
    assert spec.altitude_km == 2000
    assert spec.payload == "other"
    assert len(spec.warnings) == 3


def test_off_topic_is_passed_through(fake_client):
    client = fake_client(tool_input={"off_topic": True})
    assert parse_idea("make me a sandwich", client=client).spec.off_topic is True


# ---------- fallback paths ----------

def test_api_error_falls_back_to_keywords(fake_client):
    client = fake_client(raise_exc=TimeoutError("venue wifi died"))
    result = parse_idea("6U camera cubesat", client=client)
    assert result.source == "fallback"
    assert "TimeoutError" in result.error
    assert result.spec.size_u == 6 and result.spec.payload == "camera"


def test_model_answering_in_text_falls_back(fake_client):
    client = fake_client(no_tool=True)
    result = parse_idea("3U radio relay", client=client)
    assert result.source == "fallback"
    assert result.spec.payload == "radio_relay"


def test_no_api_key_uses_fallback_without_calling_anything(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    result = parse_idea("6U camera cubesat")
    assert result.source == "fallback"


def test_use_llm_false_never_calls_client(fake_client):
    client = fake_client(tool_input={"size_u": 12})
    result = parse_idea("6U camera cubesat", client=client, use_llm=False)
    assert client.messages.calls == []
    assert result.spec.size_u == 6


# ---------- input handling ----------

@pytest.mark.parametrize("text", ["", "   ", None])
def test_empty_input_raises_a_friendly_error(text):
    with pytest.raises(ValueError, match="Describe"):
        parse_idea(text, use_llm=False)


def test_very_long_input_is_truncated(fake_client):
    client = fake_client(tool_input={"off_topic": False})
    parse_idea("camera " * 2000, client=client)
    sent = client.messages.calls[0]["messages"][0]["content"]
    assert len(sent) < 2200


# ---------- follow-up edits ("make it 12U") ----------

def test_followup_sends_previous_spec_to_llm(fake_client):
    first = parse_idea("6U camera cubesat in SSO", use_llm=False).spec
    client = fake_client(tool_input={"size_u": 12, "payload": "camera", "orbit": "SSO"})
    parse_idea("make it 12U", previous=first, client=client)
    sent = client.messages.calls[0]["messages"][0]["content"]
    assert "Earlier spec" in sent and '"payload": "camera"' in sent


def test_followup_in_fallback_keeps_earlier_values():
    first = parse_idea("6U camera cubesat in a sun-synchronous orbit", use_llm=False).spec
    second = parse_idea("make it 12U", previous=first, use_llm=False).spec
    assert second.size_u == 12
    assert second.payload == "camera"   # kept from turn 1
    assert second.orbit == "SSO"        # kept from turn 1
    assert second.off_topic is False


def test_followup_does_not_freeze_earlier_defaults():
    first = parse_idea("6U camera cubesat", use_llm=False).spec      # altitude was assumed
    second = parse_idea("make it 12U", previous=first, use_llm=False).spec
    assert "altitude_km" in second.assumed                             # still shown as an assumption
