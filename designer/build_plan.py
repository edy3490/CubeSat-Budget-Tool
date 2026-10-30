"""Turn a Design into an ordered build plan: what to order, when, and how to put it together.

Lead times are rough industry rules of thumb, not vendor quotes. Confirm with each vendor.
"""
from __future__ import annotations

# Typical weeks from order to delivery (low, high), by subsystem.
LEAD_WEEKS = {
    "structure": (4, 8), "solar": (8, 12), "eps": (6, 10), "battery": (6, 10), "obc": (6, 10),
    "adcs": (12, 20), "comms": (8, 14), "gnss": (6, 10), "imager": (16, 26), "propulsion": (20, 36),
    "antenna_uhf": (6, 10), "antenna_l": (6, 10), "antenna_s": (6, 10), "antenna_x": (6, 10),
    "payload_tbd": (12, 24),
    # ADCS parts bought separately
    "reaction_wheel": (8, 16), "magnetorquer": (6, 10), "star_tracker": (16, 26),
    "sun_sensor": (6, 12), "horizon_sensor": (8, 14), "magnetometer": (6, 10), "gyro": (8, 14),
}
ADCS_PARTS = {"adcs", "reaction_wheel", "magnetorquer", "star_tracker", "sun_sensor", "horizon_sensor", "magnetometer", "gyro"}
AVIONICS = {"eps", "battery", "obc", "comms", "gnss"} | ADCS_PARTS  # needed on the bench first

DESIGN_WEEKS = 3        # requirements, interfaces, design review
FLATSAT_WEEKS = 6       # bench integration and flight software
INTEGRATION_WEEKS = 3
TEST_WEEKS = 5          # vibration, thermal vacuum, RF
DELIVERY_WEEKS = 2

BAND_OF = {"antenna_uhf": "UHF", "antenna_s": "S-band", "antenna_x": "X-band"}


def _lead(sub: str) -> tuple[int, int]:
    return LEAD_WEEKS.get(sub, (8, 12))


def _mid(lead: tuple[int, int]) -> float:
    return sum(lead) / 2


def build_plan(d) -> dict:
    picks = d.picks
    r = d.report
    mass, power, orb = r["mass_budget"], r["power_budget"], r["orbit_and_propulsion"]

    def named(slot):
        return [p for p in picks if p.slot == slot]

    def label(p):
        return f"{p.component['name']} ({p.component['vendor']})" + (f" x{p.quantity}" if p.quantity > 1 else "")

    # Order list, longest lead first.
    orders = []
    for p in picks:
        lead = _lead(p.component["subsystem"])
        cost = p.component.get("cost_usd")
        orders.append({
            "part": p.component["name"], "vendor": p.component["vendor"], "quantity": p.quantity,
            "for": p.slot, "lead_weeks": list(lead),
            "line_cost_usd": round(cost * p.quantity) if cost is not None else None,
        })
    orders.sort(key=lambda o: -o["lead_weeks"][1])

    # Schedule (expected = midpoint lead times; worst = upper bounds).
    def schedule(pick_lead):
        start_order = DESIGN_WEEKS
        avionics_in = start_order + max((pick_lead(_lead(p.component["subsystem"])) for p in picks
                                         if p.component["subsystem"] in AVIONICS), default=0)
        all_in = start_order + max(pick_lead(_lead(p.component["subsystem"])) for p in picks)
        flatsat_end = avionics_in + FLATSAT_WEEKS
        integ_start = max(flatsat_end, all_in)
        test_start = integ_start + INTEGRATION_WEEKS
        deliver_start = test_start + TEST_WEEKS
        return {
            "design": (0, DESIGN_WEEKS), "order": (start_order, all_in), "flatsat": (avionics_in, flatsat_end),
            "integration": (integ_start, test_start), "test": (test_start, deliver_start),
            "delivery": (deliver_start, deliver_start + DELIVERY_WEEKS),
        }

    expected = schedule(_mid)
    worst = schedule(lambda lead: lead[1])

    def weeks(key):
        a, b = expected[key]
        return [round(a), round(b)]

    payload = named("payload")[0]
    downlink = named("downlink radio")
    solar = named("solar")
    deployables = [p for p in picks if "deploy" in p.component["name"].lower()]
    thruster = named("propulsion")
    bands = sorted({BAND_OF[p.component["subsystem"]] for p in picks if p.component["subsystem"] in BAND_OF})

    phases = []

    steps = [f"Freeze the spec: {d.form_factor}, {d.spec.payload.replace('_', ' ')}, "
             f"{d.spec.altitude_km} km {d.spec.orbit}, {d.spec.lifetime_years:g}-year mission."]
    if d.spec.assumed:
        steps.append("Confirm the values the parser assumed: " + ", ".join(d.spec.assumed) + ".")
    if payload.component.get("placeholder"):
        steps.append(f"Choose the actual payload; keep it under {payload.component['mass_kg']} kg "
                     f"and {payload.component['power_w']} W or redo the budget.")
    steps += ["Draw the mechanical layout (which board goes in which slot) and the wiring diagram.",
              "Hold a design review against the budget below before ordering anything expensive."]
    phases.append({"phase": "Design", "weeks": weeks("design"), "steps": steps})

    long_lead = [o for o in orders if o["lead_weeks"][1] >= 20]
    steps = []
    if long_lead:
        steps.append("Order long-lead parts first: " + ", ".join(o["part"] for o in long_lead) + ".")
    steps += ["Order the avionics (EPS, battery, flight computer, radios, ADCS) next so the bench build can start.",
              "Order structure, solar panels and antennas last; they're needed only at integration.",
              "Ask every vendor for a quote and a lead time; parts without a public price are marked in the cost list."]
    phases.append({"phase": "Order parts", "weeks": weeks("order"), "steps": steps})

    steps = [f"Connect {label(named('power system (EPS)')[0])}"
             + (f" and {label(named('battery')[0])}" if named("battery") else "")
             + f" to {label(named('flight computer')[0])} on the bench.",
             f"Bring up {label(named('command radio (UHF)')[0])} and talk to it from a ground station."]
    if named("pointing (ADCS)"):
        steps.append(f"Test {label(named('pointing (ADCS)')[0])} with simulated sensors (hardware-in-the-loop).")
    else:
        steps.append("Check the passive magnet's strength and the hysteresis rods' placement against the attitude simulation.")
    if d.spec.payload == "camera":
        link = f" over the {label(downlink[0])}" if downlink else ""
        steps.append(f"Connect {label(payload)}, take test images and send a full image{link}.")
    elif d.spec.payload == "radio_relay":
        steps.append(f"Store-and-forward test with {label(payload)}: send messages from one ground terminal, receive at another.")
    else:
        steps.append(f"Connect the payload and check data reaches the flight computer and the radio.")
    steps += [f"Flight software: safe mode, beacon, and the 30-minute post-deploy wait before antennas or radios turn on.",
              f"Day-in-the-life test: run a full orbit ({orb['orbital_period_min']} min, {orb['eclipse_min_per_orbit']} min in shadow) "
              f"on a solar simulator; expect about {power['net_orbit_avg_power_w']:+} W net."]
    phases.append({"phase": "Bench build (flatsat)", "weeks": weeks("flatsat"), "steps": steps})

    steps = [f"Mount boards in the {label(named('structure')[0])}."]
    if solar:
        steps.append(f"Fit {label(solar[0])}.")
    if deployables:
        steps.append("Deployment tests (several times each): " + ", ".join(p.component["name"] for p in deployables) + ".")
    steps.append("Fit antennas: " + ", ".join(p.component["name"] for p in picks if p.component["subsystem"].startswith("antenna")) + ".")
    if thruster:
        steps.append(f"Install {label(thruster[0])}; plan propellant loading with the vendor (it's a hazardous operation).")
    steps.append(f"Weigh it (expect {mass['total_mass_kg']} kg, limit {mass['structural_limit_kg']} kg) "
                 "and check the center of mass against the CubeSat Design Specification.")
    phases.append({"phase": "Integration", "weeks": weeks("integration"), "steps": steps})

    phases.append({"phase": "Environmental testing", "weeks": weeks("test"), "steps": [
        "Vibration test to the launch provider's levels.",
        "Thermal vacuum cycling with the satellite powered on.",
        "Radio checks and full functional test after each test; repeat the deployment tests.",
    ]})

    phases.append({"phase": "Delivery", "weeks": weeks("delivery"), "steps": [
        f"Fit check in a {d.form_factor} dispenser.",
        "Charge the battery, set the remove-before-flight pin and deployment switches.",
        "Ship to the launch integrator.",
    ]})

    paperwork = []
    if bands:
        paperwork.append(f"Radio license for {', '.join(bands)}: start in week 0; it often takes 6-12 months.")
    if d.spec.payload == "camera":
        paperwork.append("Remote-sensing license if you're US-based (NOAA); start early.")
    paperwork.append(f"Book a rideshare launch about 12 months ahead "
                     f"({r['cost_budget']['launch_cost_basis']}).")
    paperwork.append(f"Debris plan: natural decay in {orb['natural_orbit_lifetime_years']:g} years.")

    return {
        "expected_weeks": round(expected["delivery"][1]),
        "worst_case_weeks": round(worst["delivery"][1]),
        "lead_time_note": "Lead times are rough rules of thumb, not quotes.",
        "phases": phases,
        "start_now": paperwork,
        "order_list": orders,
    }
