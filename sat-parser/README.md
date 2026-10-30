# Satellite idea parser

Turns a sentence like *"6U CubeSat that images wildfires from a polar orbit for a year"* into the JSON spec the budget engine reads. It uses Claude Haiku when an API key is set and falls back to keyword rules when it isn't, or when the API fails, so the demo never breaks.

```
text ──> Claude Haiku (forced tool call) ──┐
  │                                        ├──> normalize() ──> SatSpec (always valid)
  └── on any failure ──> keyword rules ────┘
```

## Files

| File | What it does |
|---|---|
| `sat_parser/schema.py` | The spec format, allowed values, defaults and `normalize()`. **Agree on this with the budget-engine person first.** |
| `sat_parser/llm.py` | The prompt, the `set_spec` tool schema, and the API call. |
| `sat_parser/fallback.py` | Keyword rules used when the LLM isn't available. |
| `sat_parser/parser.py` | `parse_idea()`, the only function the app needs to call. |
| `sat_parser/__main__.py` | Command-line demo. |
| `tests/` | Offline tests (free) and live tests (need a key). |

## Setup (about 10 minutes)

### 1. Make a virtual environment and install

macOS or Linux:
```bash
cd sat-parser
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Windows (PowerShell):
```powershell
cd sat-parser
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 2. Check it works with no key

```bash
pytest -m "not live"
```
You should see `37 passed`. The live tests show as skipped, which is expected.

```bash
python -m sat_parser "6U camera cubesat in a polar orbit at 550 km for 18 months"
```
Output says `"source": "fallback"`, meaning the keyword rules handled it.

### 3. Get an API key

1. Sign in at the Claude Console (console.anthropic.com).
2. Add a few dollars of credit (or use credits from the hackathon organizers).
3. Create an API key and copy it.

### 4. Save the key in `.env`

```bash
cp .env.example .env
```
Open `.env` and replace `sk-ant-your-key-here` with your key. `.env` is in `.gitignore`, so it won't be committed. Don't paste the key into code or Slack.

### 5. Run the live tests

```bash
pytest tests/test_live.py -v
```
These 10 tests call the real model. Together they cost well under one cent. If one fails, read the assertion message; it prints the full spec the model produced.

Now the demo uses the model:
```bash
python -m sat_parser "cubesat w/ cam, polar orbit, ~350 miles up"
```
Output says `"source": "llm"` and shows token usage.

## Using it in the app

```python
from sat_parser import parse_idea

result = parse_idea("6U camera cubesat for wildfires")
spec = result.spec                 # a SatSpec, always valid
spec.model_dump()                  # plain dict for the budget engine

# Follow-up edit in the chat ("make it 12U"):
result2 = parse_idea("make it 12U", previous=spec)
```

What each field of `ParseResult` is for:
- `spec.off_topic`: if true, reply "Describe a satellite idea" instead of running the budget.
- `spec.assumed`: fields that were filled with defaults. Show them in the UI ("Assumed: 3U, 500 km").
- `spec.warnings`: values that were changed to fit (e.g. 5U snapped to 6U). Show these too.
- `source`: `"llm"` or `"fallback"`. Handy to display small in a corner during the demo.
- `error`: why the fallback was used, for debugging.

Minimal Streamlit wiring:
```python
import streamlit as st
from sat_parser import parse_idea

if "spec" not in st.session_state:
    st.session_state.spec = None

if text := st.chat_input("Describe your satellite idea"):
    result = parse_idea(text, previous=st.session_state.spec)
    if result.spec.off_topic:
        st.warning("Describe a satellite idea, like 'a 3U camera sat in polar orbit'.")
    else:
        st.session_state.spec = result.spec
        st.json(result.spec.model_dump())
```

## Changing the spec

To add a field (say `propulsion: bool`):
1. Add it to `SatSpec` and handle it in `normalize()` in `schema.py`.
2. Add it to `SPEC_TOOL["input_schema"]["properties"]` in `llm.py`.
3. Optionally add a keyword rule in `fallback.py`.
4. Add a test in `tests/test_schema.py` and a live case in `tests/test_live.py`.

To add a payload or orbit type, add it to `PAYLOADS` / `ORBITS` in `schema.py`; the tool schema reads from those lists automatically. Only add values the parts table has rows for.

## Cost

Each parse is roughly 1,000 input tokens and 100 output tokens. At Haiku 5.5's listed rate ($0.10 / $0.50 per million tokens) that's around $0.0002 per parse. `usage` in the result shows the real counts. Costs are capped by `MAX_TOKENS` in `llm.py` and `MAX_INPUT_CHARS` in `parser.py`.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| Always `"source": "fallback"` with `LLM disabled` | `.env` not loaded. Check the file name is exactly `.env` and you're running from the `sat-parser` folder. |
| `AuthenticationError` in `error` | Wrong or revoked key. |
| `NotFoundError` mentioning the model | The model ID changed. Set `SAT_PARSER_MODEL` in `.env` to a current ID from the Anthropic docs. |
| `BadRequestError` | An API parameter changed for the newer model. Check the Messages API docs for `tools` and `tool_choice`. |
| Live test fails on one case | The model read the text differently. Tighten the rule in `SYSTEM_PROMPT` in `llm.py`, or loosen the test if the model's answer is reasonable. |
