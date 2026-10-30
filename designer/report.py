"""Plain-text rendering of a pipeline result for the terminal."""
from __future__ import annotations

MARK = {"pass": "ok  ", "warn": "WARN", "fail": "FAIL"}


def _money(v) -> str:
    return "—" if v is None else f"${v:,.0f}"


def _num(v, fmt="{:g}") -> str:
    return "—" if v is None else fmt.format(v)


def _years(v) -> str:
    return "50+" if v >= 50 else f"{v:g}"  # the budget engine caps orbit life at 50 years


def _cut(s: str, n: int) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"


def render(data: dict) -> str:
    out: list[str] = []
    w = out.append
    p = data["parse"]
    spec = p["spec"]

    if data.get("off_topic"):
        return "That doesn't look like a satellite idea. Try: 'a 3U camera sat in polar orbit for 2 years'."

    d = data["design"]
    status = "CLOSES" if d["status"] == "closes" else "DOES NOT CLOSE"
    margins = f" ({d['margins']} margins)" if d["margins"] else ""
    failed = [ch["check"] for ch in d["checks"] if ch["status"] == "fail"]
    joiner = ", but fails: " if d["status"] == "closes" else " — fails: "
    failed = joiner + ", ".join(failed) if failed else ""
    w(f"\n=== {d['name']} — {d['form_factor']} ===   {status}{margins}{failed}")
    w(f"Parsed by: {p['source']}" + (f"  (fallback reason: {p['error']})" if p["source"] == "fallback" and p["error"] else ""))
    w(f"Spec: {spec['size_u']}U, payload={spec['payload']}, {spec['orbit']} {spec['altitude_km']} km, "
      f"{spec['lifetime_years']:g} yr" + (f", goal: {spec['mission_goal']}" if spec["mission_goal"] else ""))
    if spec["assumed"]:
        w("Assumed (not stated): " + ", ".join(spec["assumed"]))
    for x in spec["warnings"]:
        w("Parser note: " + x)
    if spec["notes"]:
        w("Your notes: " + spec["notes"])

    # Parts and cost
    w("\nPARTS & COST")
    w(f"  {'For':<20} {'Part':<34} {'Vendor':<18} {'Qty':>3} {'Unit $':>9} {'Line $':>9} {'kg':>6} {'W':>6}")
    for x in d["parts"]:
        star = "*" if x["unit_cost_usd"] is not None and x["cost_basis"] == "estimate" else ""
        power = x["generation_w"] and f"+{x['generation_w']:g}" or _num(x["peak_power_w"])
        w(f"  {_cut(x['slot'], 20):<20} {_cut(x['part'], 34):<34} {_cut(x['vendor'], 18):<18} {x['quantity']:>3} "
          f"{_money(x['unit_cost_usd']):>9} {_money(x['line_cost_usd']) + star:>9} {_num(x['line_mass_kg']):>6} {power:>6}")
    c = d["cost"]
    w(f"  {'Hardware (priced parts)':<40} {_money(c['hardware_usd']):>12}")
    w(f"  {'Launch: ' + c['launch_basis']:<40} {_money(c['launch_usd']):>12}")
    w(f"  {'TOTAL' + (' (minimum)' if c['is_minimum'] else ''):<40} {_money(c['total_usd']):>12}")
    if c["unpriced_parts"]:
        w(f"  No public price: {', '.join(c['unpriced_parts'])}")
    w("  * = estimate, not a vendor price.  W column: + is generation, otherwise peak draw.")

    # SWaP
    s = d["swap"]
    wt, pw, orb = s["weight"], s["power"], s["orbit"]
    w("\nSWaP")
    w(f"  Size    {s['size']['form_factor']}  ({s['size']['envelope_mm']} mm)")
    w(f"  Weight  {wt['total_kg']} / {wt['limit_kg']} kg  ({wt['used_pct']}% used, {wt['margin_kg']} kg spare)")
    w(f"  Power   makes {pw['generation_avg_w']} W, uses {pw['consumption_avg_w']} W on average "
      f"(net {pw['net_avg_w']:+} W, {_num(pw['ratio'])}x); everything on at once: {pw['peak_all_on_w']} W")
    w(f"          battery {_num(pw['battery_wh'])} Wh, each eclipse drains {_num(pw['eclipse_dod_pct'])}%")
    w(f"  Orbit   {orb['altitude_km']:g} km, {orb['period_min']} min per orbit, {orb['eclipse_min']} min in shadow; "
      f"stays up {_years(orb['years_in_orbit'])} yrs" + (f", {orb['delta_v_m_s']} m/s delta-v" if orb["delta_v_m_s"] else ""))

    w("\nCHECKS")
    for ch in d["checks"]:
        w(f"  [{MARK[ch['status']]}] {ch['check']:<12} {ch['detail']}")
    for x in d["decisions"]:
        w(f"  note: {x}")
    if d["engine_warnings"]:
        w("  budget engine flags: " + "; ".join(_cut(x, 80) for x in d["engine_warnings"]))

    # Build plan
    b = data["build_plan"]
    w(f"\nBUILD PLAN  (~{b['expected_weeks']} weeks to delivery, up to {b['worst_case_weeks']} if parts run late)")
    w("  Start now:")
    for x in b["start_now"]:
        w(f"    - {x}")
    for n, ph in enumerate(b["phases"], 1):
        w(f"  {n}. {ph['phase']}  (weeks {ph['weeks'][0]}-{ph['weeks'][1]})")
        for x in ph["steps"]:
            w(f"    - {x}")
    w(f"  ({b['lead_time_note']})")

    w("\nWHY THESE PARTS")
    for x in d["parts"]:
        if x["why"]:
            w(f"  {_cut(x['slot'], 20):<20} {x['why']}")
    return "\n".join(out)
