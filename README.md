# Hackathon

Type a satellite idea and get a CubeSat: real parts, cost, SWaP, checks, a build plan and a 3D model you can explode.

```bash
cd sat-parser && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt && cd ..   # once
sat-parser/.venv/bin/python server.py       # then open http://localhost:8000
```

Put `ANTHROPIC_API_KEY=...` in `sat-parser/.env` to use Claude. Without a key it still works, using the keyword parser and the rule-based 3D layout.

| Folder | What it is |
|---|---|
| `sat-parser/` | Idea text to a structured spec (Claude Haiku, with a keyword fallback) |
| `database/` | Parts table (`cubesat.db`) |
| `budget_engine/` | Mass, power, orbit and cost math |
| `designer/` | Picks parts, runs the checks, makes the build plan |
| `visualizer/` | 3D layout of the design (Sonnet until 25k tokens, then Haiku) |
| `front-end/` | `index.html`: the web page (chat, budget, flags, 3D model, build plan) |
| `server.py` | Serves the page and its API, running the designer and visualizer |
