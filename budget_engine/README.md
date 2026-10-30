# CubeSat Budget Engine

Evaluates a CubeSat configuration against the [component database](../database/README.md) and
writes a JSON report covering mass, power and energy, cost, orbit lifetime and cost efficiency.
The report is kept compact so an LLM can read it cheaply. Python 3 standard library only.

## Usage

```sh
python3 budget_engine.py --all                                  # every reference build in the DB + ranking
python3 budget_engine.py --config-id 2 --altitude-km 450        # one DB build, custom altitude
python3 budget_engine.py --config-file examples/hyperspectral_3u.json
python3 budget_engine.py --config-file a.json --config-file b.json --out reports/compare.json
```

The defaults are `--db ../database/cubesat.db` and `--out reports/budget_report.json`, both resolved
relative to this folder, so the engine runs from any working directory.

### Mission assumptions (CLI flags)

| Flag | Default | Meaning |
|---|---|---|
| `--altitude-km` | 500 | Circular orbit altitude |
| `--design-life-years` | 5 | Cap on operational life (electronics/battery wear-out) |
| `--launch-cost-per-u-usd` | 60000 | Rideshare price per U |
| `--solar-derate` | 0.75 | Pointing, temperature and degradation losses on solar output |
| `--default-eps-efficiency-pct` | 85 | Used when the build has no EPS with a known efficiency |
| `--max-battery-dod` | 0.30 | Allowed battery depth of discharge per eclipse |
| `--drag-coefficient` | 2.2 | Drag coefficient |
| `--atmosphere-density-scale` | 1.0 | 1.0 = high solar activity (conservative); ~0.3 for solar minimum |

## Configuration files

```json
{
  "name": "My 3U",
  "form_factor": "3U",
  "mission": {"altitude_km": 400},
  "items": [
    {"component_id": 2, "quantity": 1},
    {"component_id": 81, "quantity": 1, "duty_cycle": 0.3}
  ]
}
```

- `component_id` is the `id` in the database's `component` table.
- `duty_cycle` (optional) is the fraction of each orbit the part draws its rated `power_w`.
  When it's omitted, the subsystem default below applies.
- `mission` (optional) overrides any CLI assumption for this build only, using the flag names
  with underscores (e.g. `altitude_km`). Unknown keys produce an `UNKNOWN_MISSION_KEY` warning.

### Default duty cycles

| Subsystem | Default | Reason |
|---|---|---|
| `eps`, `obc`, `adcs`, `gnss`, star/sun/horizon sensors, magnetometers, gyros | 1.0 | Always on |
| `comms`, `imager` | 0.15 | Ground passes / imaging time per orbit |
| `propulsion` | 0.10 | Firing time per orbit |
| `reaction_wheel` | 0.10 | Database stores peak power; steady-state draw is far lower |
| `magnetorquer` | 0.30 | Momentum dumping |
| structure, solar, battery, antennas | 0 | No continuous draw |

## Examples

| File | What it exercises |
|---|---|
| `examples/iot_relay_1u.json` | Small, cheap, short-lived 1U |
| `examples/hyperspectral_3u.json` | Typical healthy 3U imager |
| `examples/vleo_feep_imager_6u.json` | 350 km orbit kept up by an electric thruster (`mission` override) |
| `examples/high_cadence_imaging_6u.json` | High duty cycles leading to a NEGATIVE energy balance |
| `examples/hydrazine_demo_1u.json` | Over the 1U mass limit |
| `examples/overloaded_3u.json` | Over mass, energy-negative, no battery: every warning at once |

`reports/` holds generated output from these examples and the database's reference builds.

## Report format

Each entry in `configurations` starts with:

```json
"summary": {"mass_kg": 2.658, "limit_kg": 6.0, "margin_kg": 3.342, "energy": "POSITIVE",
            "net_w": 9.61, "cost_usd": 288900, "cost_min_only": true, "years": 1.58,
            "usd_per_watt_year": 12959},
"warnings": ["UNPRICED: iOBC, Mantis"]
```

A negative `margin_kg` means the build is over the structural limit. `cost_min_only: true` means
some parts have no price, so costs are lower bounds.

Warning codes: `OVER_MASS`, `ENERGY_NEGATIVE`, `ECLIPSE_FAIL`, `PEAK_OVER_SOLAR`,
`THRUSTER_BATTERY_LIMITED`, `NO_EPS`, `UNPRICED`, `NO_MASS`, `UNKNOWN_MISSION_KEY`.

Detailed sections follow:

| Section | Contents |
|---|---|
| `mass_budget` | Total vs CDS limit, margin, `over_limit`, `overage_kg`, mass by subsystem |
| `power_budget` | Orbit-average generation vs consumption, `energy_balance`, Wh per orbit/day, battery eclipse depth of discharge, peak-load check, per-load breakdown |
| `propulsion_power_check` | Whether the thruster can fire on solar alone; max sustainable thruster duty cycle |
| `cost_budget` | Hardware cost by data basis, launch cost, total, unpriced parts |
| `orbit_and_propulsion` | Drag-decay lifetime, delta-v, station-keeping years, max altitude raise, operational years |
| `cost_efficiency` | $/watt-year (headline, lower is better), $/effective operational year, $/kg, $/(m/s) |
| `components` | Each part with quantity, unit values, data basis and duty cycle |

With more than one build, `comparison_ranked_by_usd_per_watt_year` ranks them. Builds over the
mass limit always rank last.

## Method

- **Mass:** sum of quantity × unit mass, compared with the CubeSat Design Specification limit for the form factor.
- **Power:** orbit-average generation = peak solar × solar derate × EPS efficiency × sunlit fraction
  (cylindrical shadow, beta = 0, the worst case). Consumption = Σ peak power × duty cycle.
- **Battery:** eclipse energy (average load × eclipse time) must be ≤ capacity × max depth of discharge.
- **Lifetime:** circular-orbit drag decay integrated with the Vallado exponential atmosphere down to 150 km,
  using the tumbling mean cross-section. Deployed panels are ignored.
- **Delta-v:** Tsiolkovsky equation with propellant-weighted Isp. Electric thrusters (Isp ≥ 1000 s) use a
  low-thrust spiral for altitude raise; others use Hohmann.
- **Cost efficiency:** total cost / (orbit-average generation × effective operational years), where
  effective years = operational years × min(1, generation / consumption).

## Tests

```sh
python3 -m unittest tests/test_budget_engine.py     # from this folder or the repo root
```

The tests rebuild the database first via `../database/build.sh`.
