# 3D visualizer

Turns a design from `designer/` into a 3D scene of the CubeSat that `front-end/index.html` draws with three.js. You can rotate it, explode it to see every part, and hover a part (or its row in the parts table) to see what it is.

```
design (parts list) ──> Claude places library parts ──> expand from library, check & repair ──> scene JSON ──> three.js
```

## Part library (`library.py` + `parts/`)

Every part the designer picks is drawn ahead of time, so most of the time the model only places parts. The drawings live in two folders, kept apart so it's clear who drew what (details in `parts/README.md`):

| Folder | Drawn by |
|---|---|
| `parts/opus/drawings.py` | **Claude Opus**, in the coding session (not through the API). 37 drawings covering all 34 parts the designer used across 1,536 test ideas, plus 8 alternates. Real dimensions where known; estimates are marked. Checked first. |
| `parts/generated/*.json` | **Sonnet or Haiku**, at runtime. Saved automatically the first time the model draws something the Opus set lacks: a catalog part with no drawing, or an extra invented for an unusual request (laser, robotic arm, ...). Reused from then on. Each file records who drew it, when, why, and a note asking Opus to review and redraw it. |

- Each part is drawn in its own frame, centered on its bounding box, with its own +z as "up". That's the components side of a board, the cells side of a panel, and the outward side of an antenna. A camera's lens is on its own -z.
- `python -m visualizer --library` lists both sets and checks that nothing the designer picks is missing.

Because parts are pre-drawn, the model only **places** them (`placement.py`):

| Field | Meaning |
|---|---|
| `pos` | where the part's bounding-box center goes (body frame, mm) |
| `up` | which body direction its own +z points: +x, -x, +y, -y, +z or -z |
| `spin` | a turn about its own z: 0, 90, 180 or 270 |

That's about 45 output tokens a part (plus its one-line role, below) instead of about 300 to draw it. The model only draws a part from scratch if it isn't in the library, and that drawing is saved to `parts/generated/`.

## Explanation and extras

In the same call, the model explains the satellite for a non-engineer. The page shows this under the 3D model as "How it works":

- **Overview:** how the satellite does its mission (what does the job, how data and commands reach the ground, where power comes from, how it points).
- **Role per part:** what each part does here and why it suits the job. It's grounded in the designer's own reason for the pick, which is passed to the model. The role also shows when you hover the part.
- **Why this layout:** why the main parts sit where they do, and how that leads to the fit verdict.

**Extras.** The model also gets the request text, the mission goal and any notes. If the request asks for something no listed part can do ("a satellite with a laser beam"), it adds 1-3 plausible extra parts:
- each has a name, a purpose, and an estimated mass and power;
- it draws and places them, or reuses an earlier extra by name;
- impossible or unsafe ideas get a small, plausible version, and the purpose says so.

Extras appear in the 3D model, in "How it works" and in the parts table, marked as estimates. They aren't added to the budget totals. On an edit they're kept, and the model can drop one the request no longer wants.

**Edits only place what changed.** When a design is an edit of one that was already laid out with the same form factor, the unchanged parts keep their place. The model gets their bounding boxes as context and is asked only about the new or changed parts. A new form factor places everything again, which is still cheap.

The rule-based layout uses the library too, so the instant model has the same detail. It also checks volume: it stacks the inside parts and reports how much height they need against what the frame has.

## Which model places it

| | |
|---|---|
| **Sonnet 5.5, effort medium** | used until the Sonnet budget of **25,000 tokens** (input + output, cached input at its price) is spent |
| **Haiku 5.5** | used after that, and as a backup if a Sonnet call fails |
| **Rule-based layout** | shown instantly while the model works, and used when there's no API key or every call fails |

Measured costs with Sonnet, as counted against the budget:

| | Tokens | Time |
|---|---|---|
| New design, within 5 minutes of the last call | about 3.6k (1.9k in, 3.3k cached = 0.3k, 1.4k out) | ~10 s |
| New design after a 5-minute gap (cache rewritten) | about 7.5k (1.9k in, 3.3k written = 4.2k, 1.4k out) | ~10 s |
| Edit | less: only new or changed parts are placed | ~7 s |
| Same parts list and request again | 0 (reused, even after a restart) | instant |

So 25k covers about 6 designs made in a row. How the count is kept down:

- **Prompt caching.** The instructions and output format (~3.3k tokens) are the same on every call, so they're cached. A call within 5 minutes of the last reads them at a tenth of the price, and the budget counts them that way (a cache write counts 1.25x).
- **Finished layouts are saved** to `visualizer/scene_cache.json` (not in git, last 40 kept), so a design seen before costs nothing, even after a restart. A change to the instructions starts fresh.
- **Copies are described once.** Later copies of a part (the second solar panel) are sent as `same_as` the first, and share its role sentence.
- **Medium effort.** In a side-by-side test on three designs, medium matched high on layout quality with ~9% less output.

- The 25k cap is hard. Before each Sonnet call the worst case is reserved (a deliberately high input estimate plus the maximum output), so a call can't go over the limit. If the worst case doesn't fit, it uses Haiku.
- The count is saved in `visualizer/usage.json` (not in git), so it survives restarts.
  - `python -m visualizer --budget` shows it.
  - `python -m visualizer --reset-budget` starts it over.
- Scenes are reused by parts list and request, across restarts. **Redraw** asks for a fresh one.
- **Thinking is off** by default; with it on, Sonnet spends thousands of tokens thinking per call. To turn it on, set `VISUALIZER_SONNET_THINKING=adaptive`.
- Other settings (environment variables):
  - `VISUALIZER_SONNET_MODEL`, `VISUALIZER_HAIKU_MODEL`
  - `VISUALIZER_SONNET_EFFORT` (default `medium`)
  - `VISUALIZER_SONNET_TOKEN_LIMIT`
  - `VISUALIZER_USAGE_FILE`

## What the model gets and returns

- **Gets:**
  - the request text, mission goal and notes;
  - the form factor and envelope;
  - one line per physical item to place (four solar panels are four refs), with the designer's reason for the pick and the library size plus which way the part faces, or `"draw": true` if the part isn't in the library;
  - the names of extras drawn for earlier requests;
  - on an edit, the bounding boxes of the parts already placed.
- **Returns:** structured JSON (`SCENE_SCHEMA` in `generator.py`):
  - a placement and a one-line role per part;
  - shapes only for parts it had to draw;
  - the description (overview and layout);
  - any extras, plus refs of earlier extras to drop;
  - a fit verdict (fits / tight / doesn't fit) with a reason;
  - a one-line summary.
- **Server side:**
  - library parts are expanded, and model-drawn parts are placed and saved to `parts/generated/`;
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
| `library.py` | Looks up a part's drawing (Opus first, then generated) and saves new generated drawings |
| `parts/opus/drawings.py` | The parts Opus drew |
| `parts/generated/` | Parts Sonnet/Haiku drew at runtime, one JSON file each, for Opus to review |
| `placement.py` | Turning and moving library parts into place; exploded-view offsets |
| `generator.py` | Prompt, schema, model choice, description and extras, edits, fallbacks, cache |
| `budget.py` | The Sonnet token budget (hard cap, saved to `usage.json`) |
| `scene.py` | Scene format, repair pass, and the rule-based layout and volume check |
| `__main__.py` | Command line |
| `tests/` | Offline tests for the visualizer and the web API: `python -m pytest visualizer/tests` |
| `../server.py` | Local web server: serves the page and its API (`/api/budget`, `/api/cubesat-chat`, `/api/visual`, `/api/tokens`) |
| `../front-end/index.html` | The web page: chat, budget, flags, 3D model, build plan |
