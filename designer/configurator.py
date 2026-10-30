"""Turn a SatSpec into a parts list, using the parts table and the budget engine.

How it picks:
  1. Fixed core for every satellite: structure, flight computer, UHF radio for commands.
  2. Options for the payload, pointing (ADCS), power (solar + EPS + batteries) and,
     if needed, propulsion.
  3. Try combinations in order (best payload first, cheapest power first) and keep the
     first one that passes the budget engine's mass, power, eclipse and lifetime checks and
     physically fits inside the frame (the 3D layout's column packing, so both agree).
     It tries comfortable margins first, then tight ones. If nothing passes, it returns
     the closest attempt with the problems listed.
  4. If nothing works at the requested size: an assumed size moves up to the next one that
     works; a size the user chose stays, with a note naming the smallest size that works.

Where the table has nothing to rank by (e.g. no prices for flight computers), a part is
hand-picked below with the reason next to it.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

from ._paths import DB_PATH, be
from visualizer.scene import inside_fit

# --------------------------------------------------------------------------- hand-picked parts
OBC_ID = 41                      # NanoMind A3200: lowest power draw of the flight computers
TTC_RADIO_ID = 60                # EnduroSat UHF Transceiver II: cheapest priced UHF radio
TTC_ANTENNA_ID = 331             # EnduroSat UHF antenna, same vendor as the radio
S_BAND = (63, 357)               # EnduroSat S-band transmitter + matching antenna (small sats)
X_BAND = (64, 389)               # EnduroSat X-band transmitter + 4x4 patch (6U and up)
RELAY_RADIO_ID = 61              # ISIS TRXVU duplex: the relay payload itself
RELAY_ANTENNA_ID = 334           # ISIS antenna system, same vendor as the relay radio
GNSS_ID, GNSS_ANTENNA_ID = 305, 344  # NovAtel OEM719 + light L1 patch: tells images/burns where they happened
BATTERY_ID = 30                  # NanoAvionics 2S2P: the only battery with a price
ADCS_POINTING = (52, 51, 50)     # true 3-axis pointing for cameras, best value first
ADCS_BASIC = (54, 53)            # spin/momentum control is enough for radios and sensors
ADCS_LAST_RESORT = 54            # single wheel; used for a camera only if nothing 3-axis fits

# Solar layouts per size: (component id, quantity). Body panels first, then deployables.
SOLAR_LAYOUTS = {
    1: [(13, 4)],
    3: [(10, 2), (10, 4), (11, 2), (12, 2)],
    6: [(14, 2), (14, 4)],
    12: [(14, 4), (14, 6)],
}
BATTERY_COUNTS = (0, 1, 2, 3)

# Payloads the table has no parts for get a reserved mass/power allowance, by size.
PAYLOAD_ALLOWANCE = {1: (0.2, 1.0), 3: (0.5, 2.0), 6: (1.5, 5.0), 12: (3.0, 10.0)}  # (kg, W)
DUTY = {"relay": 0.3, "sensor": 1.0, "other": 0.5}

PROPULSION_WORDS = ("propulsion", "thruster", "maneuver", "manoeuv", "orbit rais", "station keep",
                    "station-keep", "deorbit", "de-orbit", "formation")
GNSS_WORDS = ("gps", "gnss")

FCC_DEORBIT_YEARS = 5.0          # US rule: leave LEO within 5 years of mission end
TYPICAL_DESIGN_LIFE_YEARS = 5.0  # most CubeSat parts aren't rated much past this


@dataclass(frozen=True)
class Tier:
    name: str
    max_mass_use: float          # fraction of the CubeSat mass limit
    min_power_ratio: float       # orbit-average generation / consumption


TIERS = (Tier("comfortable", 0.90, 1.25), Tier("tight", 1.00, 1.00))


@dataclass
class Pick:
    slot: str                    # what the part is for, e.g. "payload", "downlink radio"
    component: dict              # a parts-table row, or a placeholder (see _placeholder)
    quantity: int = 1
    duty_cycle: Optional[float] = None
    why: str = ""

    def item(self):
        duty = self.duty_cycle
        if duty is None:
            duty = be.DEFAULT_DUTY_CYCLE.get(self.component["subsystem"], 1.0)
        return be.Item(self.component, self.quantity, duty)

    def unit_cost(self) -> float:
        return self.component.get("cost_usd") or 0.0


@dataclass
class Design:
    spec: object                 # SatSpec
    name: str
    form_factor: str
    picks: list[Pick]
    params: object               # be.MissionParams
    tier: Optional[str]          # "comfortable", "tight", or None if it doesn't close
    report: dict                 # be.evaluate() output
    checks: list[dict] = field(default_factory=list)
    decisions: list[str] = field(default_factory=list)

    @property
    def closes(self) -> bool:
        return self.tier is not None


# --------------------------------------------------------------------------- catalog

class Catalog:
    def __init__(self, conn):
        rows = conn.execute(
            "SELECT c.*, s.segment, s.efficiency_metric, s.efficiency_unit "
            "FROM component c JOIN subsystem s ON s.code = c.subsystem").fetchall()
        self.parts = {r["id"]: dict(r) for r in rows}
        self.form_factors = {r["code"]: dict(r) for r in conn.execute("SELECT * FROM form_factor")}

    def get(self, part_id: int) -> dict:
        if part_id not in self.parts:
            raise KeyError(f"Part {part_id} is missing from the parts table; update designer/configurator.py")
        return self.parts[part_id]

    def subsystem(self, code: str) -> list[dict]:
        return [p for p in self.parts.values() if p["subsystem"] == code]


def _placeholder(subsystem: str, name: str, mass_kg: float, power_w: float,
                 cost_usd: Optional[float] = None, note: str = "") -> dict:
    """A stand-in part for something the table doesn't have. Always marked as an estimate."""
    return {
        "id": None, "subsystem": subsystem, "name": name, "vendor": "TBD", "form_factor": None,
        "mass_kg": mass_kg, "mass_basis": "estimate",
        "cost_usd": cost_usd, "cost_basis": "estimate" if cost_usd is not None else None,
        "power_w": power_w, "power_gen_w": None, "efficiency": None, "energy_wh": None,
        "propellant_kg": None, "notes": note, "placeholder": True,
    }


# --------------------------------------------------------------------------- options

def _structure(cat: Catalog, size: int) -> Pick:
    code = f"{size}U"
    priced = [p for p in cat.subsystem("structure")
              if p["form_factor"] == code and p["cost_usd"] is not None and p["mass_kg"] is not None]
    if priced:
        p = min(priced, key=lambda p: p["cost_usd"])
        return Pick("structure", p, why="cheapest priced structure for this size")
    # No structure of this size: scale the largest priced one by volume.
    base = max((p for p in cat.subsystem("structure") if p["cost_usd"] and p["mass_kg"]),
               key=lambda p: cat.form_factors[p["form_factor"]]["units"])
    factor = size / cat.form_factors[base["form_factor"]]["units"]
    comp = _placeholder("structure", f"{code} structure (estimated)", round(base["mass_kg"] * factor, 3), 0.0,
                        round(base["cost_usd"] * factor),
                        f"No {code} structure in the parts table; scaled {factor:g}x from {base['vendor']} {base['name']}")
    return Pick("structure", comp, why=comp["notes"])


def _wants(spec, words) -> bool:
    text = f"{spec.notes} {spec.mission_goal}".lower()
    return any(w in text for w in words)


def _gnss(cat: Catalog) -> list[Pick]:
    return [Pick("GNSS receiver", cat.get(GNSS_ID), why="lowest-power receiver with a known mass"),
            Pick("GNSS antenna", cat.get(GNSS_ANTENNA_ID), why="lightest L1 patch")]


def payload_options(cat: Catalog, spec) -> list[list[Pick]]:
    size = spec.size_u
    if spec.payload == "camera":
        radio, antenna = X_BAND if size >= 6 else S_BAND
        downlink = [Pick("downlink radio", cat.get(radio),
                         why=("X-band" if size >= 6 else "S-band") + " to move image data fast"),
                    Pick("downlink antenna", cat.get(antenna), why="matches the downlink radio")]
        fits = {None, f"{size}U"} | ({"6U"} if size == 12 else set())
        imagers = [p for p in cat.subsystem("imager") if p["form_factor"] in fits and p["mass_kg"] is not None]
        imagers.sort(key=lambda p: (p["efficiency"] if p["efficiency"] is not None else math.inf, p["power_w"] or 0))
        options = []
        for p in imagers:
            if p["efficiency"] is not None:
                gsd = p["efficiency"] * spec.altitude_km / 500
                why = f"{gsd:.1f} m per pixel at {spec.altitude_km} km"
            else:
                why = "resolution not listed"
            options.append([Pick("payload", p, why=why)] + downlink)
        return options

    if spec.payload == "radio_relay":
        return [[Pick("payload", cat.get(RELAY_RADIO_ID), duty_cycle=DUTY["relay"],
                      why=f"duplex UHF radio for store-and-forward, on {DUTY['relay']:.0%} of each orbit"),
                 Pick("payload antenna", cat.get(RELAY_ANTENNA_ID), why="matches the relay radio")]]

    kg, w = PAYLOAD_ALLOWANCE[size]
    label = "Sensor payload" if spec.payload == "sensor" else "Custom payload"
    comp = _placeholder("payload_tbd", f"{label} (to be chosen)", kg, w,
                        note="The parts table has no parts of this kind yet; mass and power are reserved.")
    return [[Pick("payload", comp, duty_cycle=DUTY[spec.payload],
                  why=f"reserves {kg} kg and {w} W for a {size}U satellite")]]


def adcs_options(cat: Catalog, spec) -> list[list[Pick]]:
    code = f"{spec.size_u}U"
    if spec.payload == "camera":
        ids = [i for i in ADCS_POINTING if cat.get(i)["form_factor"] in (None, code)] + [ADCS_LAST_RESORT]
        return [[Pick("pointing (ADCS)", cat.get(i),
                      why="3-axis pointing to aim the camera" if i != ADCS_LAST_RESORT
                      else "single wheel only; nothing 3-axis fit")] for i in ids]
    # Last resort, when nothing else fits (a full 1U): no unit at all. Passive magnetic stabilization
    # (a magnet and hysteresis rods on the frame) is common on small satellites that needn't point.
    return [[Pick("pointing (ADCS)", cat.get(i), why="basic attitude control is enough for this payload")]
            for i in ADCS_BASIC] + [[]]


def power_options(cat: Catalog, size: int) -> list[list[Pick]]:
    """Every solar layout x EPS x battery count, cheapest first."""
    eps_parts = [p for p in cat.subsystem("eps") if p["cost_usd"] is not None and p["mass_kg"] is not None]
    battery = cat.get(BATTERY_ID)
    options = []
    for solar_id, solar_qty in SOLAR_LAYOUTS[size]:
        solar = cat.get(solar_id)
        for eps in eps_parts:
            for n in BATTERY_COUNTS:
                picks = [Pick("solar", solar, solar_qty, why=f"{solar_qty} x {solar['power_gen_w']} W"),
                         Pick("power system (EPS)", eps, why="regulates and switches power")]
                if n:
                    picks.append(Pick("battery", battery, n, why="covers the eclipse part of each orbit"))
                options.append(picks)
    options.sort(key=lambda ps: (sum(p.unit_cost() * p.quantity for p in ps),
                                 sum((p.component["mass_kg"] or 0) * p.quantity for p in ps)))
    return options


def propulsion_options(cat: Catalog, has_gnss: bool) -> list[list[Pick]]:
    """Thrusters with known mass and propellant, lightest first. Adds GNSS for orbit knowledge."""
    thrusters = [p for p in cat.subsystem("propulsion") if p["mass_kg"] and p["propellant_kg"]]
    thrusters.sort(key=lambda p: p["mass_kg"])
    extra = [] if has_gnss else _gnss(cat)
    return [[Pick("propulsion", p, why=f"{p['efficiency']:g} s Isp, {p['propellant_kg']} kg propellant")] + extra
            for p in thrusters]


# --------------------------------------------------------------------------- search

def _config(name: str, code: str, picks: list[Pick]):
    return be.Configuration(name, code, [p.item() for p in picks], source="designer")


def _quick_check(cfg, ff, orbit, params, tier: Tier):
    """Mass and power only (fast). Returns (passes, penalty for ranking near-misses)."""
    mass = be.mass_budget(cfg, ff)
    power = be.power_budget(cfg, orbit, params)
    use = mass["total_mass_kg"] / ff["max_mass_kg"]
    ratio = power["generation_to_consumption_ratio"] or math.inf
    eclipse_ok = power["battery"]["survives_eclipse"]
    passes = use <= tier.max_mass_use and ratio >= tier.min_power_ratio and eclipse_ok
    penalty = max(0.0, use - 1.0) * 10 + max(0.0, 1.0 - ratio) + (0 if eclipse_ok else 0.5)
    return passes, penalty, mass


def _layout_parts(picks: list[Pick]) -> list[dict]:
    """Picks as the design-style part dicts the 3D layout reads."""
    return [{"slot": p.slot, "part": p.component["name"], "unit_mass_kg": p.component["mass_kg"],
             "quantity": p.quantity, "peak_power_w": (p.component["power_w"] or 0) * p.quantity or None,
             "estimated_placeholder": bool(p.component.get("placeholder"))} for p in picks]


def _fit(picks: list[Pick], ff: dict) -> tuple[float, float, str]:
    """(stack height needed, height available, verdict) for the inside parts, in mm."""
    return inside_fit(_layout_parts(picks), [float(v) for v in ff["envelope_mm"].split("x")])


def _orbit(cfg, ff, mass_kg, orbit, params) -> dict:
    return be.orbit_budget(cfg, ff, mass_kg, orbit, params)


SIZES = tuple(sorted(SOLAR_LAYOUTS))


def design(spec, conn=None) -> Design:
    """Pick parts for a SatSpec and run the budget engine on them. If nothing works at the
    requested size, an assumed size moves up; a chosen one stays, with a note."""
    conn = conn or be.connect(DB_PATH)
    d = _search(spec, conn)
    if d.closes:
        return d
    for size in (s for s in SIZES if s > spec.size_u):
        bigger = _search(spec.model_copy(update={"size_u": size}), conn)
        if not bigger.closes:
            continue
        if "size_u" in spec.assumed:
            bigger.decisions.insert(0, f"A {spec.size_u}U was too small for these parts, so this is a {size}U.")
            return bigger
        d.decisions.append(f"Nothing in the parts table makes a {spec.size_u}U work for this mission; "
                           f"the smallest size that does is {size}U.")
        break
    return d


def _search(spec, conn) -> Design:
    cat = Catalog(conn)
    size, code = spec.size_u, f"{spec.size_u}U"
    ff = cat.form_factors[code]
    params = be.MissionParams(altitude_km=float(spec.altitude_km), design_life_years=float(spec.lifetime_years))
    orbit = be.orbit_geometry(params.altitude_km)
    name = spec.mission_goal or f"{code} {spec.payload.replace('_', ' ')} CubeSat"
    decisions: list[str] = []

    want_gnss = spec.payload == "camera" or _wants(spec, GNSS_WORDS)
    want_prop = _wants(spec, PROPULSION_WORDS)
    core = [_structure(cat, size),
            Pick("flight computer", cat.get(OBC_ID), why="lowest power draw"),
            Pick("command radio (UHF)", cat.get(TTC_RADIO_ID), why="cheapest priced UHF radio"),
            Pick("command antenna", cat.get(TTC_ANTENNA_ID), why="matches the command radio")]
    if want_gnss:
        core += _gnss(cat)

    payloads = payload_options(cat, spec)
    adcs = adcs_options(cat, spec)
    power = power_options(cat, size)
    props = propulsion_options(cat, want_gnss)
    prop_choices = props if want_prop else [[]] + props
    if want_prop:
        decisions.append("Propulsion added because the idea asks for it.")

    best = None  # (penalty, picks) of the closest miss
    ballistic_no_prop = None  # for suggesting a higher orbit instead of a thruster
    for tier in TIERS:
        for payload in payloads:
            for prop in prop_choices:
                life_failed = False
                for adc in adcs:
                    for pw in power:
                        picks = core + payload + adc + pw + prop
                        cfg = _config(name, code, picks)
                        passes, penalty, mass = _quick_check(cfg, ff, orbit, params, tier)
                        if passes:
                            need, room, verdict = _fit(picks, ff)
                            if verdict == "does_not_fit":
                                passes, penalty = False, penalty + need / room - 1
                        if not passes:
                            if best is None or penalty < best[0]:
                                best = (penalty, picks)
                            continue
                        orb = _orbit(cfg, ff, mass["total_mass_kg"], orbit, params)
                        years = orb["total_years_in_orbit"]
                        if years >= spec.lifetime_years:
                            if prop and not want_prop:
                                alt = ballistic_no_prop and _altitude_for_lifetime(
                                    spec.lifetime_years, ballistic_no_prop, params.atmosphere_density_scale)
                                decisions.append(
                                    f"Propulsion added: without it the orbit at {spec.altitude_km} km "
                                    f"decays before the {spec.lifetime_years:g}-year mission ends."
                                    + (f" Or fly at {alt} km or higher and skip the thruster."
                                       if alt and alt > spec.altitude_km else ""))
                            if payload is not payloads[0]:
                                decisions.append("Best payload option didn't fit; used the next one that does.")
                            if not adc:
                                decisions.append("No attitude-control unit: none fit alongside the other parts, so it "
                                                 "relies on passive magnetic stabilization (a magnet and hysteresis rods "
                                                 "on the frame). Fine for a payload that needn't point.")
                            return _finish(conn, spec, name, code, picks, params, tier.name, decisions)
                        shortfall = 1.0 + (spec.lifetime_years - years) / spec.lifetime_years
                        if best is None or shortfall < best[0]:
                            best = (shortfall, picks)
                        if not prop:
                            ballistic_no_prop = orb["ballistic_coefficient_m2_per_kg"]
                        life_failed = True  # more power or pointing won't fix decay; try the next thruster
                        break
                    if life_failed:
                        break

    decisions.append("No combination in the parts table passes every check; showing the closest attempt.")
    return _finish(conn, spec, name, code, best[1], params, None, decisions)


# --------------------------------------------------------------------------- checks

def _altitude_for_lifetime(years: float, ballistic: float, scale: float) -> Optional[int]:
    """Lowest altitude (km, up to 1000) where natural decay takes at least `years`."""
    lo, hi = 200.0, 1000.0
    if be.natural_lifetime_years(hi, ballistic, scale) < years:
        return None
    for _ in range(20):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if be.natural_lifetime_years(mid, ballistic, scale) < years else (lo, mid)
    return int(math.ceil(hi / 10) * 10)


def _checks(spec, report: dict, picks: list[Pick], params, ff: dict) -> list[dict]:
    mass, power = report["mass_budget"], report["power_budget"]
    orb, cost = report["orbit_and_propulsion"], report["cost_budget"]
    checks = []

    def add(name, status, detail):
        checks.append({"check": name, "status": status, "detail": detail})

    use = mass["utilization_pct"]
    add("Mass", "fail" if mass["over_limit"] else "warn" if use > 90 else "pass",
        f"{mass['total_mass_kg']} of {mass['structural_limit_kg']} kg ({use}% used)")

    ratio = power["generation_to_consumption_ratio"]
    add("Power", "fail" if power["energy_balance"] == "NEGATIVE" else "warn" if ratio and ratio < 1.25 else "pass",
        f"makes {power['orbit_avg_generation_w']} W, uses {power['orbit_avg_consumption_w']} W on average"
        + (f" ({ratio}x)" if ratio else ""))

    bat = power["battery"]
    add("Eclipse", "pass" if bat["survives_eclipse"] else "fail",
        f"battery {bat['capacity_wh']} Wh, eclipse uses {bat['eclipse_depth_of_discharge_pct']}% "
        f"(limit {bat['max_allowed_dod_pct']:g}%)" if bat["capacity_wh"] else "no battery")

    years = orb["total_years_in_orbit"]
    shown = "50+" if years >= be.LIFETIME_CAP_YEARS else f"{years:g}"
    detail = f"stays up {shown} yrs at {spec.altitude_km} km; mission needs {spec.lifetime_years:g}"
    if years < spec.lifetime_years:
        alt = _altitude_for_lifetime(spec.lifetime_years, orb["ballistic_coefficient_m2_per_kg"],
                                     params.atmosphere_density_scale)
        detail += f"; try {alt} km or higher" if alt else ""
    add("Lifetime", "pass" if years >= spec.lifetime_years else "fail", detail)

    if spec.lifetime_years > TYPICAL_DESIGN_LIFE_YEARS:
        add("Design life", "warn", f"{spec.lifetime_years:g} yrs is past the ~{TYPICAL_DESIGN_LIFE_YEARS:g} yrs most CubeSat parts are rated for")

    natural = orb["natural_orbit_lifetime_years"]
    limit = spec.lifetime_years + FCC_DEORBIT_YEARS
    if natural <= limit:
        add("Deorbit", "pass", f"natural decay in {natural:g} yrs (rule: within {FCC_DEORBIT_YEARS:g} yrs of mission end)")
    elif orb["has_propulsion"]:
        add("Deorbit", "warn", f"natural decay takes {natural:g} yrs; save propellant to lower the orbit at end of mission")
    else:
        add("Deorbit", "fail", f"natural decay takes {'50+' if natural >= be.LIFETIME_CAP_YEARS else f'{natural:g}'} yrs, over the {FCC_DEORBIT_YEARS:g}-yr rule; "
                               "fly lower or add a deorbit device")

    need, room, verdict = _fit(picks, ff)
    add("Fits inside", {"fits": "pass", "tight": "warn", "does_not_fit": "fail"}[verdict],
        f"inside parts need about {need:.0f} mm stacked; the frame has {room:.0f} mm")

    if any(p.slot == "pointing (ADCS)" and p.component["id"] == ADCS_LAST_RESORT for p in picks) \
            and spec.payload == "camera":
        add("Pointing", "warn", "only a single reaction wheel fit; the camera can't be aimed precisely")

    if any(p.component.get("placeholder") and p.slot == "payload" for p in picks):
        add("Payload", "warn", "no matching part in the table; mass and power are a reserved allowance")

    unpriced = cost["components_without_price"]
    add("Pricing", "warn" if unpriced else "pass",
        f"{len(unpriced)} part(s) have no public price; total is a minimum" if unpriced else "every part is priced")
    return checks


def _finish(conn, spec, name, code, picks, params, tier, decisions) -> Design:
    report = be.evaluate(conn, _config(name, code, picks), params)
    ff = dict(conn.execute("SELECT * FROM form_factor WHERE code = ?", (code,)).fetchone())
    return Design(spec=spec, name=name, form_factor=code, picks=picks, params=params, tier=tier,
                  report=report, checks=_checks(spec, report, picks, params, ff), decisions=decisions)
