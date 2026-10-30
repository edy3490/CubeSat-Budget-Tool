"""Shared test helpers: a fake Anthropic client so tests run free, offline, and fast."""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


class FakeMessages:
    def __init__(self, tool_input=None, raise_exc=None, no_tool=False):
        self.tool_input = tool_input or {}
        self.raise_exc = raise_exc
        self.no_tool = no_tool
        self.calls = []  # every request the parser sent, for inspection

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.raise_exc:
            raise self.raise_exc
        if self.no_tool:
            content = [SimpleNamespace(type="text", text="Sure! Here is your satellite...")]
        else:
            content = [SimpleNamespace(type="tool_use", name="set_spec", input=self.tool_input)]
        return SimpleNamespace(content=content,
                               usage=SimpleNamespace(input_tokens=900, output_tokens=80))


class FakeClient:
    def __init__(self, **kwargs):
        self.messages = FakeMessages(**kwargs)


@pytest.fixture
def fake_client():
    """Usage: fake_client(tool_input={...}) or fake_client(raise_exc=TimeoutError())."""
    return FakeClient
