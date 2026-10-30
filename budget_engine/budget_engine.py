#!/usr/bin/env python3
"""CubeSat budget engine.

Reads components from cubesat.db and computes mass, power/energy, cost, orbit
lifetime and cost-efficiency budgets for a configuration, then writes a JSON
report meant to be read by people and LLMs.

Usage:
    python3 budget_engine.py --config-id 2
    python3 budget_engine.py --config-file my_sat.json --altitude-km 450
    python3 budget_engine.py --all --out reports/all.json

Config file format:
    {"name": "My 3U", "form_factor": "3U",
     "items": [{"component_id": 2, "quantity": 1},
               {"component_id": 81, "quantity": 1, "duty_cycle": 0.3}],
     "mission": {"altitude_km": 400}}       # optional, overrides CLI assumptions
"""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
from dataclasses import asdict, dataclass, field, fields, replace
from datetime import datetime, timezone
from pathlib import Path

MU_EARTH = 3.986004418e14       # m^3/s^2
R_EARTH = 6_378_137.0           # m
G0 = 9.80665                    # m/s^2
SECONDS_PER_YEAR = 365.25 * 86400
REENTRY_ALTITUDE_KM = 150.0
LIFETIME_CAP_YEARS = 50.0
ELECTRIC_ISP_THRESHOLD_S = 1000  # above this, treat as low-thrust spiral transfers

# Fraction of each orbit a component draws its rated power_w.
DEFAULT_DUTY_CYCLE = {
    "structure": 0.0, "solar": 0.0, "battery": 0.0, "platform": 1.0,
    "eps": 1.0, "obc": 1.0, "adcs": 1.0,
    "comms": 0.15,       # transmit time per orbit (ground-station passes)
    "imager": 0.15,      # imaging + readout per orbit
    "propulsion": 0.10,  # firing time per orbit
    "gnss": 1.0,         # continuous fix; lower it if the receiver is cycled
    "antenna_uhf": 0.0, "antenna_l": 0.0, "antenna_s": 0.0, "antenna_x": 0.0,  # passive
    "reaction_wheel": 0.10,  # power_w is PEAK; steady-state draw is a small fraction
    "magnetorquer": 0.30,    # momentum dumping / detumble
    "star_tracker": 1.0, "sun_sensor": 1.0, "horizon_sensor": 1.0,
    "magnetometer": 1.0, "gyro": 1.0,
}

# Vallado exponential atmosphere (base altitude km, base density kg/m^3, scale height km)
ATMOSPHERE = [
    (150, 2.070e-9, 22.523), (180, 5.464e-10, 29.740), (200, 2.789e-10, 37.105),
    (250, 7.248e-11, 45.546), (300, 2.418e-11, 53.628), (350, 9.518e-12, 53.298),
    (400, 3.725e-12, 58.515), (450, 1.585e-12, 60.828), (500, 6.967e-13, 63.822),
    (600, 1.454e-13, 71.835), (700, 3.614e-14, 88.667), (800, 1.170e-14, 124.64),
    (900, 5.245e-15, 181.05), (1000, 3.019e-15, 268.00),
]


@dataclass
class MissionParams:
    altitude_km: float = 500.0
    design_life_years: float = 5.0          # electronics/battery wear-out cap
    launch_cost_per_u_usd: float = 60_000   # rideshare: 1U ~$40-80k, 3U ~$100-250k
    solar_derate: float = 0.75              # pointing (cosine) losses, temperature, degradation
    default_eps_efficiency_pct: float = 85.0
    max_battery_dod: float = 0.30           # LEO cycling depth-of-discharge limit
    drag_coefficient: float = 2.2
    atmosphere_density_scale: float = 1.0   # Vallado table ~ high solar activity; ~0.3 for solar minimum


@dataclass
class Item:
    component: dict
    quantity: int
    duty_cycle: float

    @property
    def subsystem(self) -> str:
        return self.component["subsystem"]

    def total(self, key: str) -> float:
        value = self.component.get(key)
        return 0.0 if value is None else value * self.quantity


@dataclass
class Configuration:
    name: str
    form_factor: str
    items: list[Item]
    id: int | None = None
    source: str = "database"
    warnings: list[str] = field(default_factory=list)
    mission: dict = field(default_factory=dict)  # per-configuration MissionParams overrides


# --------------------------------------------------------------------------- loading

def connect(db_path: Path) -> sqlite3.Connection:
    if not db_path.exists():
        raise SystemExit(f"Database not found: {db_path} (run database/build.sh)")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _components_by_id(conn: sqlite3.Connection, ids: list[int]) -> dict[int, dict]:
    marks = ",".join("?" * len(ids))
    rows = conn.execute(
        f"SELECT c.*, s.segment, s.efficiency_metric, s.efficiency_unit "
        f"FROM component c JOIN subsystem s ON s.code = c.subsystem WHERE c.id IN ({marks})",
        ids,
    ).fetchall()
    return {r["id"]: dict(r) for r in rows}


def _build_items(conn, raw_items: list[dict], warnings: list[str]) -> list[Item]:
    components = _components_by_id(conn, [i["component_id"] for i in raw_items])
    items = []
    for raw in raw_items:
        comp = components.get(raw["component_id"])
        if comp is None:
            warnings.append(f"Unknown component_id {raw['component_id']} skipped.")
            continue
        duty = raw.get("duty_cycle")
        if duty is None:
            duty = DEFAULT_DUTY_CYCLE.get(comp["subsystem"], 1.0)
        items.append(Item(comp, int(raw.get("quantity", 1)), float(duty)))
    return items


def load_db_configuration(conn, config_id: int) -> Configuration:
    row = conn.execute("SELECT * FROM configuration WHERE id = ?", (config_id,)).fetchone()
    if row is None:
        raise SystemExit(f"No configuration with id {config_id}")
    raw = [dict(r) for r in conn.execute(
        "SELECT component_id, quantity FROM configuration_item WHERE configuration_id = ?",
        (config_id,))]
    cfg = Configuration(row["name"], row["form_factor"], [], id=config_id)
    cfg.items = _build_items(conn, raw, cfg.warnings)
    return cfg


def load_file_configuration(conn, path: Path) -> Configuration:
    data = json.loads(path.read_text())
    cfg = Configuration(data.get("name", path.stem), data["form_factor"], [], source=str(path))
    cfg.items = _build_items(conn, data["items"], cfg.warnings)
    known = {f.name for f in fields(MissionParams)}
    for key, value in data.get("mission", {}).items():
        if key in known:
            cfg.mission[key] = float(value)
        else:
            cfg.warnings.append(f"UNKNOWN_MISSION_KEY: {key}")
    return cfg


def load_form_factor(conn, code: str) -> dict:
    row = conn.execute("SELECT * FROM form_factor WHERE code = ?", (code,)).fetchone()
    if row is None:
        raise SystemExit(f"Unknown form factor {code}")
    return dict(row)


# --------------------------------------------------------------------------- physics

def atmospheric_density(alt_km: float, scale_factor: float = 1.0) -> float:
    base = ATMOSPHERE[0]
    for layer in ATMOSPHERE:
        if alt_km >= layer[0]:
            base = layer
    h0, rho0, scale = base
    return scale_factor * rho0 * math.exp(-(alt_km - h0) / scale)


def orbit_geometry(alt_km: float) -> dict:
    r = R_EARTH + alt_km * 1000
    period_s = 2 * math.pi * math.sqrt(r ** 3 / MU_EARTH)
    # Cylindrical shadow, beta angle 0 (worst case)
    eclipse_fraction = math.asin(R_EARTH / r) / math.pi
    return {
        "radius_m": r,
        "velocity_m_s": math.sqrt(MU_EARTH / r),
        "period_min": period_s / 60,
        "eclipse_fraction": eclipse_fraction,
        "sunlit_min": period_s / 60 * (1 - eclipse_fraction),
        "eclipse_min": period_s / 60 * eclipse_fraction,
    }


def mean_cross_section_m2(envelope_mm: str) -> float:
    """Tumbling convex body: mean projected area = surface area / 4."""
    a, b, c = (float(x) / 1000 for x in envelope_mm.split("x"))
    return (2 * (a * b + b * c + a * c)) / 4


def natural_lifetime_years(alt_km: float, ballistic_m2_kg: float, density_scale: float = 1.0) -> float:
    """Integrate circular-orbit drag decay down to reentry altitude."""
    a = R_EARTH + alt_km * 1000
    t = 0.0
    while (a - R_EARTH) / 1000 > REENTRY_ALTITUDE_KM:
        rate = atmospheric_density((a - R_EARTH) / 1000, density_scale) * ballistic_m2_kg * math.sqrt(MU_EARTH * a)
        dt = min(86400.0, 1000.0 / rate)  # <= 1 day or <= 1 km of decay per step
        a -= rate * dt
        t += dt
        if t > LIFETIME_CAP_YEARS * SECONDS_PER_YEAR:
            return LIFETIME_CAP_YEARS
    return t / SECONDS_PER_YEAR


def hohmann_dv(r1: float, r2: float) -> float:
    v1 = math.sqrt(MU_EARTH / r1)
    v2 = math.sqrt(MU_EARTH / r2)
    at = (r1 + r2) / 2
    return abs(math.sqrt(MU_EARTH * (2 / r1 - 1 / at)) - v1) + abs(v2 - math.sqrt(MU_EARTH * (2 / r2 - 1 / at)))


def max_altitude_raise_km(r1: float, dv: float, electric: bool) -> float | None:
    """Altitude gain achievable with dv. None means escape-capable / beyond GEO."""
    if dv <= 0:
        return 0.0
    r_geo = 42_164_000.0
    if electric:  # Edelbaum coplanar spiral: dv = v1 - v2
        v2 = math.sqrt(MU_EARTH / r1) - dv
        if v2 <= math.sqrt(MU_EARTH / r_geo):
            return None
        return (MU_EARTH / v2 ** 2 - r1) / 1000
    if hohmann_dv(r1, r_geo) <= dv:
        return None
    lo, hi = r1, r_geo
    for _ in range(60):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if hohmann_dv(r1, mid) < dv else (lo, mid)
    return (lo - r1) / 1000


# --------------------------------------------------------------------------- budgets

def mass_budget(cfg: Configuration, ff: dict) -> dict:
    total = sum(i.total("mass_kg") for i in cfg.items)
    margin = ff["max_mass_kg"] - total
    by_sub: dict[str, float] = {}
    for i in cfg.items:
        by_sub[i.subsystem] = round(by_sub.get(i.subsystem, 0) + i.total("mass_kg"), 3)
    missing = [i.component["name"] for i in cfg.items if i.component["mass_kg"] is None]
    return {
        "total_mass_kg": round(total, 3),
        "structural_limit_kg": ff["max_mass_kg"],
        "limit_source": f"CubeSat Design Specification max mass for {ff['code']}",
        "margin_kg": round(margin, 3),
        "utilization_pct": round(100 * total / ff["max_mass_kg"], 1),
        "over_limit": margin < 0,
        "overage_kg": round(-margin, 3) if margin < 0 else 0.0,
        "by_subsystem_kg": dict(sorted(by_sub.items(), key=lambda kv: -kv[1])),
        "components_missing_mass": missing,
    }


def power_budget(cfg: Configuration, orbit: dict, p: MissionParams) -> dict:
    eps_effs = [i.component["efficiency"] for i in cfg.items
                if i.subsystem == "eps" and i.component["efficiency"] is not None]
    eps_eff = (min(eps_effs) if eps_effs else p.default_eps_efficiency_pct) / 100

    peak_gen = sum(i.total("power_gen_w") for i in cfg.items)
    sunlit_gen = peak_gen * p.solar_derate * eps_eff          # usable W while in sunlight
    avg_gen = sunlit_gen * (1 - orbit["eclipse_fraction"])    # orbit average

    loads = []
    for i in cfg.items:
        peak = i.total("power_w")
        if peak:
            loads.append({"component": i.component["name"], "subsystem": i.subsystem,
                          "peak_w": round(peak, 2), "duty_cycle": i.duty_cycle,
                          "orbit_avg_w": round(peak * i.duty_cycle, 3)})
    loads.sort(key=lambda l: -l["orbit_avg_w"])
    avg_load = sum(l["orbit_avg_w"] for l in loads)
    peak_load = sum(l["peak_w"] for l in loads)
    net_avg = avg_gen - avg_load
    period_h = orbit["period_min"] / 60

    battery_wh = sum(i.total("energy_wh") for i in cfg.items)
    usable_wh = battery_wh * p.max_battery_dod
    eclipse_wh = avg_load * orbit["eclipse_min"] / 60
    dod = eclipse_wh / battery_wh if battery_wh else None

    return {
        "solar_peak_generation_w": round(peak_gen, 2),
        "sunlit_usable_generation_w": round(sunlit_gen, 2),
        "orbit_avg_generation_w": round(avg_gen, 2),
        "orbit_avg_consumption_w": round(avg_load, 2),
        "net_orbit_avg_power_w": round(net_avg, 2),
        "net_energy_per_orbit_wh": round(net_avg * period_h, 2),
        "net_energy_per_day_wh": round(net_avg * 24, 1),
        "energy_balance": "POSITIVE" if net_avg >= 0 else "NEGATIVE",
        "generation_to_consumption_ratio": round(avg_gen / avg_load, 2) if avg_load else None,
        "peak_consumption_all_on_w": round(peak_load, 2),
        "peak_exceeds_sunlit_generation": peak_load > sunlit_gen,
        "eps_conversion_efficiency_pct": round(eps_eff * 100, 1),
        "battery": {
            "capacity_wh": battery_wh,
            "usable_wh_at_max_dod": round(usable_wh, 2),
            "eclipse_energy_needed_wh": round(eclipse_wh, 2),
            "eclipse_depth_of_discharge_pct": round(dod * 100, 1) if dod is not None else None,
            "max_allowed_dod_pct": p.max_battery_dod * 100,
            "survives_eclipse": battery_wh > 0 and eclipse_wh <= usable_wh,
        },
        "loads": loads,
    }


def cost_budget(cfg: Configuration, ff: dict, p: MissionParams) -> dict:
    known = sum(i.total("cost_usd") for i in cfg.items)
    by_basis: dict[str, float] = {}
    for i in cfg.items:
        if i.component["cost_usd"] is not None:
            b = i.component["cost_basis"]
            by_basis[b] = by_basis.get(b, 0) + i.total("cost_usd")
    missing = [i.component["name"] for i in cfg.items
               if i.component["cost_usd"] is None and i.subsystem not in ("structure",)]
    launch = ff["units"] * p.launch_cost_per_u_usd
    return {
        "hardware_cost_known_usd": round(known),
        "hardware_cost_by_basis_usd": {k: round(v) for k, v in by_basis.items()},
        "estimated_share_of_hardware_cost_pct": round(100 * by_basis.get("estimate", 0) / known, 1) if known else None,
        "components_without_price": missing,
        "hardware_cost_is_lower_bound": bool(missing),
        "launch_cost_usd": round(launch),
        "launch_cost_basis": f"{ff['units']}U x ${p.launch_cost_per_u_usd:,.0f}/U rideshare",
        "total_mission_cost_usd": round(known + launch),
    }


def orbit_budget(cfg: Configuration, ff: dict, mass_kg: float, orbit: dict, p: MissionParams) -> dict:
    area = mean_cross_section_m2(ff["envelope_mm"])
    ballistic = p.drag_coefficient * area / mass_kg if mass_kg else 0.0
    natural = (natural_lifetime_years(p.altitude_km, ballistic, p.atmosphere_density_scale)
               if ballistic else LIFETIME_CAP_YEARS)

    rho = atmospheric_density(p.altitude_km, p.atmosphere_density_scale)
    drag_dv_per_year = 0.5 * rho * orbit["velocity_m_s"] ** 2 * ballistic * SECONDS_PER_YEAR

    thrusters = [i for i in cfg.items if i.subsystem == "propulsion"]
    prop_kg = sum(i.total("propellant_kg") for i in thrusters)
    isp = 0.0
    if thrusters and prop_kg:
        # propellant-weighted Isp
        isp = sum(i.total("propellant_kg") * (i.component["efficiency"] or 0) for i in thrusters) / prop_kg
    dv = isp * G0 * math.log(mass_kg / (mass_kg - prop_kg)) if prop_kg and mass_kg > prop_kg else 0.0
    electric = isp >= ELECTRIC_ISP_THRESHOLD_S

    sk_years = dv / drag_dv_per_year if drag_dv_per_year else LIFETIME_CAP_YEARS
    in_orbit_years = min(natural + sk_years, LIFETIME_CAP_YEARS)
    operational = min(in_orbit_years, p.design_life_years)
    raise_km = max_altitude_raise_km(orbit["radius_m"], dv, electric)

    return {
        "altitude_km": p.altitude_km,
        "orbital_period_min": round(orbit["period_min"], 1),
        "eclipse_min_per_orbit": round(orbit["eclipse_min"], 1),
        "mean_cross_section_m2": round(area, 4),
        "ballistic_coefficient_m2_per_kg": round(ballistic, 5),
        "natural_orbit_lifetime_years": round(natural, 2),
        "drag_makeup_dv_m_s_per_year": round(drag_dv_per_year, 2),
        "has_propulsion": bool(thrusters),
        "propellant_kg": round(prop_kg, 3),
        "effective_isp_s": round(isp, 1),
        "propulsion_type": ("electric (low-thrust spiral)" if electric else "chemical/cold-gas (impulsive)") if thrusters else None,
        "delta_v_m_s": round(dv, 1),
        "station_keeping_years_from_propellant": round(sk_years, 1) if thrusters else 0.0,
        "max_altitude_raise_km": round(raise_km, 1) if raise_km is not None else "beyond GEO / escape-capable",
        "total_years_in_orbit": round(in_orbit_years, 2),
        "operational_years": round(operational, 2),
        "operational_years_limited_by": "design life" if in_orbit_years > p.design_life_years else "orbital decay",
    }


def propulsion_power_check(cfg: Configuration, power: dict, orbit: dict) -> dict | None:
    thrusters = [i for i in cfg.items if i.subsystem == "propulsion" and i.component["power_w"]]
    if not thrusters:
        return None
    thruster_w = sum(i.total("power_w") for i in thrusters)
    base_w = power["orbit_avg_consumption_w"] - sum(i.total("power_w") * i.duty_cycle for i in thrusters)
    surplus_sunlit = power["sunlit_usable_generation_w"] - base_w
    deficit = thruster_w - surplus_sunlit
    usable_wh = power["battery"]["usable_wh_at_max_dod"]
    return {
        "thruster_power_w": round(thruster_w, 1),
        "sunlit_surplus_for_thruster_w": round(surplus_sunlit, 2),
        "can_fire_on_solar_alone": deficit <= 0,
        "battery_assisted_firing_min_per_orbit": (
            "unlimited in sunlight" if deficit <= 0
            else round(min(usable_wh / deficit * 60, orbit["sunlit_min"]), 1)),
        "max_sustainable_thruster_duty_cycle": round(max(0.0, min(1.0,
            (power["orbit_avg_generation_w"] - base_w) / thruster_w)), 3),
    }


def cost_efficiency(cost: dict, power: dict, orbit: dict, mass_kg: float) -> dict:
    total = cost["total_mission_cost_usd"]
    gen = power["orbit_avg_generation_w"]
    load = power["orbit_avg_consumption_w"]
    years = orbit["operational_years"]
    # Energy-negative satellites can only run their loads a fraction of the time.
    sustainable = min(1.0, gen / load) if load else 1.0
    effective_years = years * sustainable
    watt_years = gen * effective_years

    def per(x):
        return round(total / x) if x else None

    return {
        "usd_per_operational_year": per(years),
        "sustainable_operation_fraction": round(sustainable, 3),
        "effective_operational_years": round(effective_years, 2),
        "usd_per_effective_operational_year": per(effective_years),
        "usd_per_orbit_avg_watt": per(gen),
        "usd_per_watt_year": per(watt_years),
        "usd_per_kg_in_orbit": per(mass_kg),
        "launch_share_of_total_pct": round(100 * cost["launch_cost_usd"] / total, 1) if total else None,
        "usd_per_delta_v_m_s": per(orbit["delta_v_m_s"]),
        "costs_are_lower_bound": cost["hardware_cost_is_lower_bound"],
    }


# --------------------------------------------------------------------------- report

def evaluate(conn, cfg: Configuration, p: MissionParams) -> dict:
    ff = load_form_factor(conn, cfg.form_factor)
    orbit = orbit_geometry(p.altitude_km)
    mass = mass_budget(cfg, ff)
    power = power_budget(cfg, orbit, p)
    cost = cost_budget(cfg, ff, p)
    orb = orbit_budget(cfg, ff, mass["total_mass_kg"], orbit, p)
    prop_power = propulsion_power_check(cfg, power, orbit)
    eff = cost_efficiency(cost, power, orb, mass["total_mass_kg"])

    # Terse CODE: detail strings so a reader can scan them cheaply.
    warnings = list(cfg.warnings)
    if mass["over_limit"]:
        warnings.append(f"OVER_MASS: +{mass['overage_kg']} kg")
    if power["energy_balance"] == "NEGATIVE":
        warnings.append(f"ENERGY_NEGATIVE: {power['net_energy_per_orbit_wh']} Wh/orbit")
    if not power["battery"]["survives_eclipse"]:
        warnings.append("ECLIPSE_FAIL: no battery" if not power["battery"]["capacity_wh"]
                        else f"ECLIPSE_FAIL: DoD {power['battery']['eclipse_depth_of_discharge_pct']}%")
    if power["peak_exceeds_sunlit_generation"]:
        warnings.append("PEAK_OVER_SOLAR")
    if prop_power and not prop_power["can_fire_on_solar_alone"]:
        warnings.append(f"THRUSTER_BATTERY_LIMITED: {prop_power['thruster_power_w']}/"
                        f"{prop_power['sunlit_surplus_for_thruster_w']} W")
    if not any(i.subsystem == "eps" for i in cfg.items):
        warnings.append("NO_EPS")
    if cost["hardware_cost_is_lower_bound"]:
        warnings.append(f"UNPRICED: {', '.join(cost['components_without_price'])}")
    if mass["components_missing_mass"]:
        warnings.append(f"NO_MASS: {', '.join(mass['components_missing_mass'])}")

    summary = {
        "mass_kg": mass["total_mass_kg"],
        "limit_kg": mass["structural_limit_kg"],
        "margin_kg": mass["margin_kg"],
        "energy": power["energy_balance"],
        "net_w": power["net_orbit_avg_power_w"],
        "cost_usd": cost["total_mission_cost_usd"],
        "cost_min_only": cost["hardware_cost_is_lower_bound"],
        "years": orb["operational_years"],
        "usd_per_watt_year": eff["usd_per_watt_year"],
    }

    return {
        "configuration": {"id": cfg.id, "name": cfg.name, "form_factor": cfg.form_factor, "source": cfg.source,
                          "mission_overrides": cfg.mission or None},
        "summary": summary,
        "warnings": warnings,
        "mass_budget": mass,
        "power_budget": power,
        "propulsion_power_check": prop_power,
        "cost_budget": cost,
        "orbit_and_propulsion": orb,
        "cost_efficiency": eff,
        "components": [{
            "id": i.component["id"], "name": i.component["name"], "vendor": i.component["vendor"],
            "subsystem": i.subsystem, "quantity": i.quantity,
            "unit_mass_kg": i.component["mass_kg"], "mass_basis": i.component["mass_basis"],
            "unit_cost_usd": i.component["cost_usd"], "cost_basis": i.component["cost_basis"],
            "unit_peak_power_w": i.component["power_w"], "unit_generation_w": i.component["power_gen_w"],
            "duty_cycle": i.duty_cycle,
        } for i in cfg.items],
    }


METHODOLOGY = {
    "mass": "Sum of quantity x unit mass, compared to the CubeSat Design Specification max mass for the form factor.",
    "power_generation": "orbit_avg = peak solar W x solar_derate x EPS efficiency x sunlit fraction (cylindrical shadow, beta=0 worst case).",
    "power_consumption": "orbit_avg = sum(peak W x duty_cycle). Duty cycles default per subsystem; override per item in a config file.",
    "energy_balance": "POSITIVE if orbit-average generation >= orbit-average consumption.",
    "battery": "Eclipse energy = avg consumption x eclipse duration; must be <= capacity x max depth of discharge.",
    "orbit_lifetime": "Circular-orbit drag decay integrated with the Vallado exponential atmosphere down to 150 km. Tumbling mean cross-section, Cd=2.2, deployed panels ignored. "
                      "Scale density with atmosphere_density_scale (1.0 = high solar activity, conservative).",
    "delta_v": "Tsiolkovsky: Isp x g0 x ln(m_wet / m_dry). Station-keeping years = delta-v / annual drag make-up delta-v.",
    "launch_cost": "Form-factor units x per-U rideshare price.",
    "cost_efficiency": "usd_per_watt_year = total mission cost / (orbit-avg generation W x effective operational years). "
                       "effective years = operational years x min(1, generation/consumption). Lower is better.",
}


def build_report(reports: list[dict], p: MissionParams) -> dict:
    out = {
        "report_type": "cubesat_budget",
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "how_to_read": ("Read 'summary' and 'warnings' first; details follow. Units in key names. "
                        "cost_min_only=true: some parts unpriced. *_basis 'estimate' = unsourced."),
        "mission_assumptions": asdict(p),
        "default_duty_cycles": DEFAULT_DUTY_CYCLE,
        "methodology": METHODOLOGY,
        "configurations": reports,
    }
    if len(reports) > 1:
        # Builds over the structural limit can't fly as specified, so they rank last.
        ranked = sorted(reports, key=lambda r: (r["mass_budget"]["over_limit"],
                                                r["cost_efficiency"]["usd_per_watt_year"] or float("inf")))
        out["comparison_ranked_by_usd_per_watt_year"] = [{
            "rank": n, "name": r["configuration"]["name"],
            "usd_per_watt_year": r["cost_efficiency"]["usd_per_watt_year"],
            "total_mission_cost_usd": r["cost_budget"]["total_mission_cost_usd"],
            "over_limit": r["mass_budget"]["over_limit"],
            "mass_margin_kg": r["mass_budget"]["margin_kg"],
            "energy_balance": r["power_budget"]["energy_balance"],
            "operational_years": r["orbit_and_propulsion"]["operational_years"],
            "cost_is_lower_bound": r["cost_budget"]["hardware_cost_is_lower_bound"],
        } for n, r in enumerate(ranked, 1)]
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--config-id", type=int, action="append", help="Configuration id from the database (repeatable)")
    src.add_argument("--config-file", type=Path, action="append", help="JSON configuration file (repeatable)")
    src.add_argument("--all", action="store_true", help="Evaluate every configuration in the database")
    here = Path(__file__).resolve().parent
    ap.add_argument("--db", type=Path, default=here.parent / "database" / "cubesat.db")
    ap.add_argument("--out", type=Path, default=here / "reports" / "budget_report.json")
    defaults = MissionParams()
    for name, value in asdict(defaults).items():
        ap.add_argument(f"--{name.replace('_', '-')}", type=float, default=value)
    args = ap.parse_args()

    params = MissionParams(**{k: getattr(args, k) for k in asdict(defaults)})
    conn = connect(args.db)
    if args.all:
        configs = [load_db_configuration(conn, r["id"]) for r in conn.execute("SELECT id FROM configuration ORDER BY id")]
    elif args.config_id:
        configs = [load_db_configuration(conn, i) for i in args.config_id]
    else:
        configs = [load_file_configuration(conn, f) for f in args.config_file]

    report = build_report([evaluate(conn, c, replace(params, **c.mission)) for c in configs], params)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2))
    for r in report["configurations"]:
        print(f"\n== {r['configuration']['name']} ==")
        print("  " + ", ".join(f"{k}={v}" for k, v in r["summary"].items()))
        for w in r["warnings"]:
            print("  ! " + w)
    print(f"\nWrote {args.out}")


if __name__ == "__main__":
    main()
