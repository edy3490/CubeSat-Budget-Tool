"""Idea text -> parsed spec -> parts list -> budget -> build plan, as one plain dict.

The dict is JSON-ready so a front end can use it as-is later.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from . import _paths  # noqa: F401  (puts sat-parser on sys.path)
from .build_plan import build_plan
from .configurator import GNSS_WORDS, PROPULSION_WORDS, design

from sat_parser import SatSpec, parse_idea  # noqa: E402


@dataclass
class Result:
    spec: Optional[SatSpec]      # pass back as `previous` for follow-ups like "make it 6U"
    data: dict


def design_to_dict(d) -> dict:
    r = d.report
    cost = r["cost_budget"]
    parts = []
    for p in d.picks:
        c = p.component
        unit = c.get("cost_usd")
        parts.append({
            "slot": p.slot, "part": c["name"], "vendor": c["vendor"], "part_id": c["id"],
            "quantity": p.quantity,
            "unit_cost_usd": unit, "line_cost_usd": round(unit * p.quantity) if unit is not None else None,
            "cost_basis": c.get("cost_basis"),
            "unit_mass_kg": c["mass_kg"], "line_mass_kg": round(c["mass_kg"] * p.quantity, 3) if c["mass_kg"] is not None else None,
            "peak_power_w": (c["power_w"] or 0) * p.quantity or None,
            "generation_w": (c["power_gen_w"] or 0) * p.quantity or None,
            "estimated_placeholder": bool(c.get("placeholder")),
            "why": p.why,
        })
    mass, power, orb = r["mass_budget"], r["power_budget"], r["orbit_and_propulsion"]
    return {
        "name": d.name,
        "form_factor": d.form_factor,
        "status": "closes" if d.closes else "does_not_close",
        "margins": d.tier,
        "parts": parts,
        "cost": {
            "hardware_usd": cost["hardware_cost_known_usd"],
            "launch_usd": cost["launch_cost_usd"],
            "launch_basis": cost["launch_cost_basis"],
            "total_usd": cost["total_mission_cost_usd"],
            "is_minimum": cost["hardware_cost_is_lower_bound"],
            "unpriced_parts": cost["components_without_price"],
        },
        "swap": {
            "size": {"form_factor": d.form_factor, "envelope_mm": _envelope(d)},
            "weight": {"total_kg": mass["total_mass_kg"], "limit_kg": mass["structural_limit_kg"],
                       "margin_kg": mass["margin_kg"], "used_pct": mass["utilization_pct"],
                       "by_subsystem_kg": mass["by_subsystem_kg"]},
            "power": {"generation_avg_w": power["orbit_avg_generation_w"],
                      "consumption_avg_w": power["orbit_avg_consumption_w"],
                      "net_avg_w": power["net_orbit_avg_power_w"],
                      "ratio": power["generation_to_consumption_ratio"],
                      "peak_all_on_w": power["peak_consumption_all_on_w"],
                      "battery_wh": power["battery"]["capacity_wh"],
                      "eclipse_dod_pct": power["battery"]["eclipse_depth_of_discharge_pct"]},
            "orbit": {"altitude_km": orb["altitude_km"], "period_min": orb["orbital_period_min"],
                      "eclipse_min": orb["eclipse_min_per_orbit"],
                      "years_in_orbit": orb["total_years_in_orbit"],
                      "natural_decay_years": orb["natural_orbit_lifetime_years"],
                      "delta_v_m_s": orb["delta_v_m_s"]},
        },
        "checks": d.checks,
        "decisions": d.decisions,
        "engine_warnings": r["warnings"],
        "budget_report": r,
    }


def _envelope(d) -> str:
    from ._paths import be, DB_PATH
    conn = be.connect(DB_PATH)
    return be.load_form_factor(conn, d.form_factor)["envelope_mm"]


def _add_requests(spec: SatSpec, text: str) -> SatSpec:
    """Copy hardware requests the parser may have missed (the keyword fallback never fills
    notes) into notes, so the designer sees them and they carry over to follow-up edits."""
    t, notes = text.lower(), spec.notes.lower()
    adds = [label for label, words in (("needs propulsion", PROPULSION_WORDS), ("needs GNSS", GNSS_WORDS))
            if any(w in t for w in words) and not any(w in notes for w in words)]
    if not adds:
        return spec
    return spec.model_copy(update={"notes": "; ".join(filter(None, [spec.notes, *adds]))})


def run(text: str, previous: Optional[SatSpec] = None, use_llm: Optional[bool] = None) -> Result:
    parsed = parse_idea(text, previous=previous, use_llm=use_llm)
    spec = _add_requests(parsed.spec, text)
    data = {
        "idea": text,
        "parse": {"source": parsed.source, "error": parsed.error, "usage": parsed.usage, "spec": spec.model_dump()},
    }
    if spec.off_topic:
        data["off_topic"] = True
        return Result(spec=previous, data=data)

    d = design(spec)
    data["design"] = design_to_dict(d)
    data["build_plan"] = build_plan(d)
    return Result(spec=spec, data=data)


def from_spec(spec: SatSpec, text: str = "") -> Result:
    """Rebuild the design for a spec that was already parsed, with no parser call: a saved
    project after a server restart. Same parts as before unless the parts database changed."""
    d = design(spec)
    return Result(spec=spec, data={
        "idea": text,
        "parse": {"source": "saved", "error": None, "usage": None, "spec": spec.model_dump()},
        "design": design_to_dict(d), "build_plan": build_plan(d),
    })
