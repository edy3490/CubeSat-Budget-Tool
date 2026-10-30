# CubeSat designer (test app)

Type a satellite idea, get a CubeSat: parts list with costs, SWaP (size, weight, power), pass/fail checks and a build plan.

```
idea text ──> sat-parser ──> SatSpec ──> configurator ──> budget engine ──> build plan ──> report / JSON
                (LLM or keywords)        (picks parts from database/cubesat.db)
```

## Run it

Uses the parser's virtual environment (see `sat-parser/README.md` for setup). From the repo root:

```bash
source sat-parser/.venv/bin/activate

python -m designer                                   # interactive
python -m designer "6U camera for wildfires, polar orbit, 2 years"
python -m designer --json "3U radio relay"           # full JSON, what a front end would get
python -m designer --no-llm "1U camera"              # keyword parser only, no API calls
```

In interactive mode each message edits the last design (`make it 6U`, `fly at 400 km`). Commands: `new`, `json`, `quit`.

The API key is read from `.env` or `sat-parser/.env`. Without one, the keyword parser is used.

## How parts are picked (`configurator.py`)

1. **Every satellite gets:** the cheapest priced structure for its size, the lowest-power flight computer, and a UHF radio and antenna for commands.
2. **Payload:**
   - camera: imagers that fit the size, sharpest first, plus an S-band (1U/3U) or X-band (6U/12U) downlink and GNSS.
   - radio relay: a duplex UHF radio.
   - sensor or other: there are no such parts in the table yet, so it reserves a mass and power allowance (`PAYLOAD_ALLOWANCE`).
3. **Pointing:** 3-axis ADCS for cameras, a single wheel for everything else. If even that doesn't fit (a full 1U), no unit at all: the satellite relies on passive magnetic stabilization, and a decision note says so.
4. **Power:** every solar layout × EPS × battery count, cheapest first.
5. **Propulsion:** added when the idea asks for it, or when the orbit would decay before the mission ends. Lightest thruster that works.

It tries combinations in that order and keeps the first that passes the budget engine with comfortable margins (≤90% of the mass limit, ≥1.25× power) and fits inside the frame. If none does, it tries tight margins (≤100%, ≥1.0×). If nothing passes, it shows the closest attempt marked **DOES NOT CLOSE**.

**Fitting inside** uses the 3D layout's column packing (`visualizer.scene.inside_fit`, part heights from the part library), so the parts list and the 3D model agree. Within 5% over still counts as tight.

**Size:** if nothing works at the requested size, an assumed size (the 3U default) moves up to the next one that works, with a note. A size the user chose stays, marked DOES NOT CLOSE, with a note naming the smallest size that works (a camera never fits a 1U: the smallest imager is taller than a 1U's inside). Sizes between form factors round up (2U → 3U).

Hand-picked parts (where the table has no number to rank by) are constants at the top of `configurator.py`, each with the reason.

## Checks

Mass, fits inside (stack height vs the frame), power, eclipse (battery), lifetime (orbit decay vs mission length), deorbit (US 5-year rule), design life (>5 years), pointing, payload placeholder, pricing.

## Known limits

- **Costs are minimums.** Imagers, antennas, flight computers and thrusters have no public price in the table. The report lists them.
- **Fitting inside is checked by stack height** in board columns, with heights from the 3D part library (a guess by type and mass for the few parts it doesn't have). It doesn't check board connectors or harness room.
- **12U** has no structure in the table; it uses an estimate scaled from the 6U structure (marked `*`).
- **Lead times** in the build plan are rough rules of thumb, not vendor quotes.
- Orbit decay uses the budget engine's high-solar-activity atmosphere, so lifetimes are on the short (safe) side.

## Files

| File | What it does |
|---|---|
| `pipeline.py` | `run(text, previous)`: the one function a front end needs. Returns a JSON-ready dict. |
| `configurator.py` | Picks parts and runs the checks. |
| `build_plan.py` | Order list, schedule and step-by-step build plan. |
| `report.py` | Terminal text output. |
| `__main__.py` | The command-line app. |
| `tests/` | Offline tests: `python -m pytest designer/tests` |
