"""Turns the parser's SatSpec (dict) into a budget-engine configuration."""
from dataclasses import fields
from budget_engine.budget_engine import Configuration, MissionParams, _build_items

BASE = ["structure", "solar", "battery", "eps", "obc", "adcs", "comms"]
QTY = {"structure": lambda u: u, "solar": lambda u: 2 * u}   # parts per design; tune these
PAYLOAD_SUBSYSTEM = {}      # payload value -> subsystem code; default is "imager"
OVERRIDES = {}              # force a part by subsystem: {"eps": 12}
PAYLOAD_IDS = {
    "camera":       81,    # Mantis: general imager
    "sensor":       80,    # Chameleon (MS/HS): multispectral/hyperspectral, for the methane case
    "spectrometer": 108,   # HyperScape100
    "hyperspectral": 108,
    "imager":       84,    # iSIM-90
    "radio":        62,    # S-Band Transmitter, as a comms payload
    "iot":          61,    # TRXVU UHF/VHF Duplex
    "radio_relay": 61,   # TRXVU UHF/VHF Duplex: store-and-forward relay
    "other":       82,   # Caiman: generic fallback imager, change as you like
}

def pick(conn, sub):
    if sub in OVERRIDES:
        return OVERRIDES[sub]
    r = conn.execute("SELECT id FROM component WHERE subsystem=? AND mass_kg IS NOT NULL "
                     "ORDER BY cost_usd IS NULL, cost_usd LIMIT 1", (sub,)).fetchone()
    return r["id"] if r else None

def spec_to_config(conn, spec):
    units = spec.get("size_u") or 6
    form = f"{units:g}U"
    payload = spec.get("payload") or "camera"
    ids = [(PAYLOAD_IDS.get(payload) or pick(conn, PAYLOAD_SUBSYSTEM.get(payload, "imager")), 1)]
    ids += [(pick(conn, s), QTY[s](units) if s in QTY else 1) for s in BASE]
    return {"name": f"{form} {payload}", "form_factor": form,
            "items": [{"component_id": i, "quantity": q} for i, q in ids if i],
            "mission": {"altitude_km": float(spec.get("altitude_km") or 500),
                        "design_life_years": float(spec.get("lifetime_years") or 1)}}

def build_configuration(conn, data):
    cfg = Configuration(data["name"], data["form_factor"], [], source="api")
    cfg.items = _build_items(conn, data["items"], cfg.warnings)
    known = {f.name for f in fields(MissionParams)}
    cfg.mission = {k: float(v) for k, v in data["mission"].items() if k in known}
    return cfg