# 3D visualizer

Turns a design from `designer/` into a 3D scene of the CubeSat that `front-end/index.html` draws with three.js. You can rotate it, explode it to see every part, and hover a part (or its row in the parts table) to see what it is.

```
design (parts list) ──> Claude places library parts ──> expand from library, check & repair ──> scene JSON ──> three.js
```

## Part library (`library.py`)

Every part the designer picks is drawn once, ahead of time, in `library.py`. Claude Opus drew them in the coding session, not through the API.

- **Coverage:** 37 drawings (39 part names). The list came from running 1,536 different ideas through the designer, which used 34 distinct parts, plus 8 alternates it can pick.
- **Sources:** sizes come from public dimensions where known. The rest are estimated from mass and form factor and marked `estimate`.
- **Frame:** each part is drawn in its own frame, centered on its bounding box, with its own +z as "up". That's the components side of a board, the cells side of a panel, and the outward side of an antenna. A camera's lens is on its own -z.
- **Checking it:** `python -m visualizer --library` lists the library and runs 288 ideas to check that nothing the designer picks is missing.
- **Adding a part:** add an `_add(...)` call. The helpers (`card`, `panel`, `frame`, `lens_stack`, ...) do most of the work.

Because parts are pre-drawn, the model only **places** them (`placement.py`):

| Field | Meaning |
|---|---|
| `pos` | where the part's bounding-box center goes (body frame, mm) |
| `up` | which body direction its own +z points: +x, -x, +y, -y, +z or -z |
| `spin` | a turn about its own z: 0, 90, 180 or 270 |

That's about 45 output tokens a part instead of about 300 to draw it. The model only draws a part from scratch if it isn't in the library.

**Edits only place what changed.** When a design is an edit of one that was already laid out with the same form factor, the unchanged parts keep their place. The model gets their bounding boxes as context and is asked only about the new or changed parts. A new form factor places everything again, which is still cheap.

The rule-based layout uses the library too, so the instant model has the same detail. It also checks volume: it stacks the inside parts and reports how much height they need against what the frame has.

## Which model places it

| | |
|---|---|
| **Sonnet 5.5, effort high** | used until the Sonnet budget of **25,000 tokens** (input + output) is spent |
| **Haiku 5.5** | used after that, and as a backup if a Sonnet call fails |
| **Rule-based layout** | shown instantly while the model works, and used when there's no API key or every call fails |

Measured costs with Sonnet:

| | Tokens | Time |
|---|---|---|
| New 3U/6U design | about 4k (3.3k in, 0.8k out) | ~6 s |
| Edit | about 3.3k (2.9k in, 0.3k out) | ~4 s |
| Same parts list again | 0 (reused) | instant |

So 25k covers about 6-7 designs. Before the library, a scene drawn from scratch cost about 8k and took 20-30 s. Most of the cost is now the fixed instructions sent with each call (input).

- The 25k cap is hard. Before each Sonnet call the worst case is reserved (a deliberately high input estimate plus the maximum output), so a call can't go over the limit. If the worst case doesn't fit, it uses Haiku.
- The count is saved in `visualizer/usage.json` (not in git), so it survives restarts.
  - `python -m visualizer --budget` shows it.
  - `python -m visualizer --reset-budget` starts it over.
- Scenes are reused by parts list for the life of the server. **Redraw** asks for a fresh one.
- **Thinking is off** by default; with it on, Sonnet spends thousands of tokens thinking per call. To turn it on, set `VISUALIZER_SONNET_THINKING=adaptive`.
- Other settings (environment variables):
  - `VISUALIZER_SONNET_MODEL`, `VISUALIZER_HAIKU_MODEL`
  - `VISUALIZER_SONNET_TOKEN_LIMIT`
  - `VISUALIZER_USAGE_FILE`

## What the model gets and returns

- **Gets:**
  - the form factor and envelope;
  - one line per physical item to place (four solar panels are four refs), with the library size and a note on which way the part faces, or `"draw": true` if the part isn't in the library;
  - on an edit, the bounding boxes of the parts already placed.
- **Returns:** structured JSON (`SCENE_SCHEMA` in `generator.py`):
  - a placement per part;
  - shapes only for parts it had to draw;
  - a fit verdict (fits / tight / doesn't fit) with a reason;
  - a one-line summary.
- **Server side:**
  - library parts are expanded, and model-drawn parts are placed;
  - exploded-view offsets are worked out from where each part sits (`placement.auto_explode`);
  - `scene.repair` drops unknown refs, fills missing parts from the rule-based layout, clamps numbers and notes inside parts that stick out of the frame.

The model output is only ever drawn as boxes and cylinders, never run as code. Surface detail (solar cells, board traces, brushed aluminium, foil) comes from textures the page draws itself.

Coordinates are in mm, with the origin at the center of the structure. z runs along the rails: +z is the top (zenith) end and -z is the Earth-facing end.

## Run it

From the repo root, with the parser's venv:

```bash
sat-parser/.venv/bin/python server.py                    # web prototype at http://localhost:8000
sat-parser/.venv/bin/python -m visualizer "3U camera"    # terminal: lay out a design, print a summary
sat-parser/.venv/bin/python -m visualizer --no-llm --json "6U camera"
sat-parser/.venv/bin/python -m visualizer --library      # list the part library, check coverage
sat-parser/.venv/bin/python -m pytest visualizer/tests   # offline: fake client and the web API, no tokens
```

## Files

| File | What it does |
|---|---|
| `library.py` | The part library: a ready-made drawing of each part |
| `placement.py` | Turning and moving library parts into place; exploded-view offsets |
| `generator.py` | Prompt, schema, model choice, edits, fallbacks, cache |
| `budget.py` | The Sonnet token budget (hard cap, saved to `usage.json`) |
| `scene.py` | Scene format, repair pass, and the rule-based layout and volume check |
| `__main__.py` | Command line |
| `tests/` | Offline tests for the visualizer and the web API: `python -m pytest visualizer/tests` |
| `../server.py` | Local web server: serves the page and its API (`/api/budget`, `/api/cubesat-chat`, `/api/visual`, `/api/tokens`) |
| `../front-end/index.html` | The web page: chat, budget, flags, 3D model, build plan |
