# CubeSat Budget Tool

Type a satellite idea and get a CubeSat: real parts, cost, SWaP, checks, a build plan and a 3D model you can explore.

## Key features

**Design by describing it**
- Write the mission in plain English ("a 6U CubeSat that images wildfires for 1 year"). Claude Haiku turns it into a spec: size, payload, orbit, altitude and lifetime. A keyword parser takes over when there's no API key.
- Change the design by chatting ("make it 12U", "raise the orbit to 700 km"). Each edit builds on the last.
- Suggested edits under the chat change after every message and skip ones the design already matches.

**Real parts and real numbers**
- Parts come from a database of 330 real CubeSat parts (NASA's 2026 small-spacecraft survey, plus vendor and catalog data), each with its data source.
- The designer picks parts that fit the frame and the budget.
- **Mass:** total against the CubeSat limit for the size, with the margin.
- **Power:** orbit-average generation against use, and whether the battery survives eclipse.
- **Cost:** hardware plus launch, marked as a minimum when a part has no public price.
- **Build time.**
- **Flags** warn about problems: over mass, negative energy, a missing subsystem, an orbit that decays too fast or breaks the 5-year deorbit rule, and thrusters limited by the battery.
- **Build plan:** a week-by-week timeline of phases, and what to start now.

**3D model**
- Claude Sonnet lays the satellite out from pre-drawn part models; a rule-based layout shows instantly while it works.
- Rotate, zoom, explode the satellite into its parts, show labels, and hover a part (or its table row) to see what it is and what it does.
- **How it works** explains the satellite and its layout for non-engineers. Unusual requests ("with a laser") get plausible extra parts, marked as estimates.
- **Export STEP** (named, coloured solid parts for SolidWorks, Fusion 360, FreeCAD or Onshape) or **Export STL** (a mesh for 3D printing).

**Launch simulation**
- 🚀 **Launch** flies your own satellite to its orbit, with orbit facts.
- **Follow satellite** (or press F) rides along with the rocket and then the satellite.

**Projects**
- Every design is saved in your browser as a project you can reopen, rename (✎) or delete (×).
- Saved projects still work after the server restarts.
- Light and dark mode (🌙 / ☀️).

**Ready to host**
- `render.yaml` deploys the site to Render.
- AI calls are rate limited per visitor and per site. Over a limit, the site keeps working without AI instead of failing.

## Run it locally

Needs Python 3.9 or newer. Always open the page through `server.py`: opening `index.html` directly,
or serving it with VS Code Live Server or `python -m http.server`, gives a **405** error because those
servers can't answer the page's API calls.

### macOS / Linux

```bash
cd sat-parser && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt && cd ..   # once
sat-parser/.venv/bin/python server.py       # then open http://localhost:8000
```

### Windows (PowerShell)

Run from the repo folder. Use `py` (the Python launcher) instead of `python3`; on Windows the venv's
programs are in `.venv\Scripts\`, not `.venv/bin/`.

```powershell
# once
py -3 -m venv sat-parser\.venv
sat-parser\.venv\Scripts\python.exe -m pip install -r sat-parser\requirements.txt

# each time, then open http://localhost:8000
sat-parser\.venv\Scripts\python.exe server.py
```

In Command Prompt (`cmd`) the same commands work. If something fails:


| Problem                                                      | Fix                                                                                                                                                                                                |
| ------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `py` not found, or `python` opens the Microsoft Store        | Install Python from python.org with **"Add python.exe to PATH"** ticked, or turn off the `python.exe` alias in *Settings &gt; Apps &gt; Advanced app settings &gt; App execution aliases*.         |
| `&&` is not a valid statement separator                      | Windows PowerShell 5.1 doesn't support `&&`. Run the commands one per line as shown.                                                                                                               |
| `PermissionError: [WinError 10013]` or the address is in use | Windows reserves some ports (often 8000). Pick another: `... server.py --port 8080`, then open [http://localhost:8080](http://localhost:8080).                                                     |
| `running scripts is disabled on this system`                 | Only `Activate.ps1` triggers this, and the commands above don't need it. If you want to activate the venv anyway, run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` first.                 |
| The API key is ignored                                       | PowerShell's `echo ... > .env` saves the file as UTF-16, which isn't read. Create it with `Set-Content sat-parser\.env "ANTHROPIC_API_KEY=sk-..." -Encoding ascii`, or in Notepad (save as UTF-8). |
| 405 error in the page                                        | The page isn't being served by `server.py`; see above.                                                                                                                                             |


### API key

Put `ANTHROPIC_API_KEY=...` in `sat-parser/.env` to use Claude. Without a key it still works, using the keyword parser and the rule-based 3D layout. Add `--no-llm` to force that mode.

## Layout


| Folder           | What it is                                                                            |
| ---------------- | ------------------------------------------------------------------------------------- |
| `sat-parser/`    | Idea text to a structured spec (Claude Haiku, with a keyword fallback)                |
| `database/`      | Parts table (`cubesat.db`)                                                            |
| `budget_engine/` | Mass, power, orbit and cost math                                                      |
| `designer/`      | Picks parts, runs the checks, makes the build plan                                    |
| `visualizer/`    | 3D layout of the design (Sonnet, no token limit) and STEP/STL export for CAD                |
| `front-end/`     | `index.html`: the web page (chat, budget, flags, 3D model, build plan)                |
| `server.py`      | Serves the page and its API, running the designer and visualizer                      |
