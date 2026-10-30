# 3D visualizer

Turns a design from `designer/` into a 3D scene of the CubeSat that `front-end/index.html` draws with three.js. You can rotate it, explode it to see every part, and hover a part (or its row in the parts table) to see what it is.

```
design (parts list) ──> Claude lays it out in 3D ──> check & repair ──> scene JSON ──> three.js in front-end/index.html
```

## Which model draws it

| | |
|---|---|
| **Sonnet 5.5, effort high** | used until the Sonnet budget of **25,000 tokens** (input + output) is spent |
| **Haiku 5.5** | used after that, and as a backup if a Sonnet call fails |
| **Rule-based layout** | shown instantly while the model works, and used when there's no API key or every call fails |

- The 25k cap is hard. Before each Sonnet call the worst case is reserved, so a call can't go over the limit. If there isn't room for a full scene (~8k tokens), it uses Haiku.
- The count is saved in `visualizer/usage.json` (not in git), so it survives restarts.
  - `python -m visualizer --budget` shows it.
  - `python -m visualizer --reset-budget` starts it over.
- The same parts list is drawn only once per server run. Asking again reuses the saved scene and costs nothing. The **Redraw** button asks the model for a fresh one.
- A Sonnet scene has about 100 shapes, costs about 8k tokens (3.4k in, 4.6k out) and takes 20-30 s, so 25k covers 2-3 drawings. Shapes use short keys (`k`, `c`, `s`, `a`, `m`) and whole millimetres to keep the output small.
- **Thinking is off** by default. With it on, Sonnet spent over 9k tokens thinking before writing anything, which would use most of the budget on one picture. To try it anyway, set `VISUALIZER_SONNET_THINKING=adaptive`.
- Other settings (environment variables):
  - `VISUALIZER_SONNET_MODEL`, `VISUALIZER_HAIKU_MODEL`
  - `VISUALIZER_SONNET_TOKEN_LIMIT`
  - `VISUALIZER_USAGE_FILE`

## What the model gets and returns

- **Gets:** the form factor, the envelope in mm, and one line per physical item: ref, slot, part name, vendor, mass and power. Four solar panels are four refs.
- **Returns:** a JSON scene, enforced by structured output (`SCENE_SCHEMA` in `generator.py`). Each part is a handful of boxes and cylinders (the prompt lists typical details per part type: rails and ribs, chips and connectors on boards, reaction wheels, lens rings, hinges), with a material and an `explode` offset. The model also returns:
  - a fit verdict (fits / tight / doesn't fit) with a reason, which is the closest thing to a volume check the project has;
  - a one-line summary.
- **Repair pass** (`scene.repair`):
  - drops unknown refs and fills in any missing part from the rule-based layout;
  - clamps sizes and positions and caps the shape count;
  - notes any internal part placed outside the frame.

The model output is only ever drawn as boxes and cylinders, never run as code. Surface detail (solar cells, board traces, brushed aluminium, foil) comes from textures the page draws itself, so it costs no tokens.

Coordinates are in mm, with the origin at the center of the structure. z runs along the rails: +z is the top (zenith) end and -z is the Earth-facing end.

## Run it

From the repo root, with the parser's venv:

```bash
sat-parser/.venv/bin/python server.py                    # web prototype at http://localhost:8000
sat-parser/.venv/bin/python -m visualizer "3U camera"    # terminal: generate a scene, print a summary
sat-parser/.venv/bin/python -m visualizer --no-llm --json "6U camera"
sat-parser/.venv/bin/python -m pytest visualizer/tests   # offline: fake client and the web API, no tokens
```

## Files

| File | What it does |
|---|---|
| `generator.py` | Prompt, schema, model choice, fallbacks, cache |
| `budget.py` | The Sonnet token budget (hard cap, saved to `usage.json`) |
| `scene.py` | Scene format, repair pass and the rule-based layout |
| `__main__.py` | Command line |
| `tests/` | Offline tests for the visualizer and the web API: `python -m pytest visualizer/tests` |
| `../server.py` | Local web server: serves the page and its API (`/api/budget`, `/api/cubesat-chat`, `/api/visual`, `/api/tokens`) |
| `../front-end/index.html` | The web page: chat, budget, flags, 3D model, build plan |
