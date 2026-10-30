"""Reshapes engine output into what index.html render() reads."""
SEV = {"OVER_MASS": "bad", "ENERGY_NEGATIVE": "bad", "ECLIPSE_FAIL": "bad", "NO_EPS": "bad"}

def _state(r, tight):
    return "over" if r > 1 else "tight" if r > tight else "ok"

def to_frontend(r, units, spec):
    mb, pb, cb = r["mass_budget"], r["power_budget"], r["cost_budget"]
    rows = [{"name": c["name"], "note": c["vendor"] or "", "kg": (c["unit_mass_kg"] or 0) * c["quantity"],
             "w": (c["unit_peak_power_w"] or 0) * c["quantity"], "k": (c["unit_cost_usd"] or 0) * c["quantity"] / 1000}
            for c in r["components"]]
    rows.append({"name": "Launch", "note": cb["launch_cost_basis"], "kg": 0, "w": 0, "k": cb["launch_cost_usd"] / 1000})
    gen, load = pb["orbit_avg_generation_w"], pb["orbit_avg_consumption_w"]
    pr = min(load / gen, 9.99) if gen else 9.99
    mr = mb["utilization_pct"] / 100
    notes = [[SEV.get(w.split(":")[0], "warn"), w] for w in r["warnings"]] or [["good", "No warnings."]]
    ob = r["orbit_and_propulsion"]
    notes.insert(0, ["good", f"Orbit {ob['altitude_km']:g} km: period {ob['orbital_period_min']} min, "
                         f"eclipse {ob['eclipse_min_per_orbit']} min, natural lifetime {ob['natural_orbit_lifetime_years']} yr."])
    return {"form": r["configuration"]["form_factor"], "units": units, "label": str(spec.get("payload", "Payload")),
            "maxMass": mb["structural_limit_kg"], "gen": gen, "rows": rows, "mass": mb["total_mass_kg"],
            "watts": pb["peak_consumption_all_on_w"], "cost": cb["total_mission_cost_usd"] / 1000,
            "massRatio": mr, "powRatio": pr, "massState": _state(mr, .85), "powState": _state(pr, .7),
            "notes": notes, "altitude": r["orbit_and_propulsion"]["altitude_km"],
            "years": r["orbit_and_propulsion"]["operational_years"]}

def compose_reply(result):
    s = result.spec
    parts = [f"Understood: {s.size_u:g}U {s.payload}, {s.orbit} orbit at {s.altitude_km:g} km for {s.lifetime_years:g} years."]
    if s.assumed:  parts.append("Assumed: " + ", ".join(map(str, s.assumed)) + ".")
    if s.warnings: parts.append("Note: " + "; ".join(map(str, s.warnings)) + ".")
    if s.notes:    parts.append(str(s.notes))
    return " ".join(parts)