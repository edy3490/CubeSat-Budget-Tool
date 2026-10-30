import sqlite3, sys
from dataclasses import replace
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
sys.path.insert(0, str(ROOT)); sys.path.append(str(ROOT / "sat-parser"))

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from budget_engine.budget_engine import MissionParams, evaluate, load_form_factor
from sat_parser import parse_idea
from sat_parser.schema import SatSpec          # confirm this import path
from api.bridge import spec_to_config, build_configuration
from api.adapter import to_frontend, compose_reply

DB = ROOT / "database" / "cubesat.db"
app = FastAPI()

class ChatIn(BaseModel):
    messages: list[dict]
    spec: dict = {}

def run_budget(spec: dict):
    conn = sqlite3.connect(DB); conn.row_factory = sqlite3.Row
    try:
        cfg = build_configuration(conn, spec_to_config(conn, spec))
        report = evaluate(conn, cfg, replace(MissionParams(), **cfg.mission))
        return to_frontend(report, load_form_factor(conn, cfg.form_factor)["units"], spec)
    except (ValueError, KeyError, SystemExit) as e:
        raise HTTPException(422, str(e))
    finally:
        conn.close()

@app.post("/api/budget")
def budget(spec: dict):
    return {"spec": spec, "budget": run_budget(spec)}

@app.post("/api/cubesat-chat")
def chat(body: ChatIn):
    prev = SatSpec.model_validate(body.spec) if body.spec else None
    result = parse_idea(body.messages[-1]["content"], previous=prev)
    if result.spec.off_topic:
        return {"reply": "Describe a satellite idea, like 'a 3U camera sat in polar orbit'.", "spec": body.spec, "budget": None}
    spec = result.spec.model_dump()
    return {"reply": compose_reply(result), "spec": spec, "budget": run_budget(spec)}

app.mount("/", StaticFiles(directory=ROOT / "front-end", html=True), name="ui")
