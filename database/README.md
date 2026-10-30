# CubeSat Component Database

SQLite catalog of 330 CubeSat parts (payloads, subsystem hardware and bus platforms) with
mass, power, cost and a per-subsystem efficiency metric, plus five reference spacecraft builds.
The [budget engine](../budget_engine/README.md) reads it to evaluate whole configurations.

## Build

```sh
./build.sh        # rebuilds cubesat.db from sql/ (requires the sqlite3 CLI)
```

`cubesat.db` is committed, so a rebuild is only needed after editing the SQL. The build runs
with `-bail`, so a broken file stops it rather than producing a partial database.

## Layout

```
build.sh          rebuild script
cubesat.db        built database
sql/              loaded in this order:
  schema.sql            tables
  seed.sql              45 original parts, form factors, subsystems, 5 reference builds
  additions.sql         11 manufacturer-sourced parts (ids 100-110)
  nasa_s3vi.sql         31 solar/EPS/battery/propulsion parts from NASA SoA 2026 (ids 200-230)
  nasa_gnss_antennas.sql  12 GNSS receivers, 62 antennas (ids 300-391)
  nasa_adcs_parts.sql   169 wheels, magnetorquers and attitude sensors (ids 400-608)
  views.sql             sorted views
docs/
  source-review.md      sources and qualifications for additions.sql
  nasa-s3vi-review.md   NASA import audit, discrepancies, SPOON access limits
  coverage-gaps.md      manufacturers and part categories still missing
```

## Tables

| Table | Contents |
|---|---|
| `form_factor` | 1U-12U envelopes and CubeSat Design Specification mass limits |
| `subsystem` | Each subsystem's segment (`payload`, `hardware`, `bus`) and its efficiency metric |
| `component` | One row per part: mass, cost, power, generation, efficiency, stored energy, propellant, source, notes |
| `component_source` | Extra source references per part (e.g. NASA table locators) |
| `configuration`, `configuration_item` | Reference builds and their parts/quantities |

## Efficiency metrics

Each subsystem has one metric so parts are compared like-for-like. `efficiency_score` (in the
views) is a 0-100 percentile **within the subsystem**, with direction already handled: 100 is always best.

| Subsystem | Parts | Metric |
|---|---|---|
| `structure` | 7 | Structure mass per U (kg/U, lower better) |
| `solar` | 11 | Specific power (W/kg, higher better) |
| `eps` | 14 | Power conversion efficiency (%, higher better) |
| `battery` | 14 | Energy density (Wh/kg, higher better) |
| `obc` | 3 | Power draw (W, lower better) |
| `comms` | 6 | Data rate per watt (kbps/W, higher better) |
| `antenna_uhf`, `antenna_l`, `antenna_s`, `antenna_x` | 62 | Gain (dBi, higher better) |
| `gnss` | 12 | Power draw (W, lower better) |
| `adcs` (integrated units) | 6 | Momentum storage per kg (mNms/kg, higher better) |
| `reaction_wheel` | 46 | Momentum storage per kg (mNms/kg, higher better) |
| `magnetorquer` | 37 | Dipole per watt (Am²/W, higher better) |
| `star_tracker` | 24 | Cross-axis accuracy (arcsec, lower better) |
| `sun_sensor` | 31 | Accuracy, 3σ (deg, lower better) |
| `horizon_sensor` | 4 | Accuracy (deg, lower better) |
| `magnetometer` | 10 | Resolution (nT, lower better) |
| `gyro` | 19 | Gyro bias stability (°/hr, lower better) |
| `propulsion` | 13 | Specific impulse (s, higher better) |
| `imager` | 7 | Ground sample distance at 500 km (m, lower better) |
| `platform` | 4 | Bus mass / CDS mass limit (lower better) |

Notes on comparing:
- Antennas are split by band because gain across bands isn't comparable. High gain also means a
  narrow beam, so an omnidirectional TT&C antenna scoring low is expected.
- Reaction-wheel `power_w` is the tabulated **peak**. The budget engine applies a 10% duty cycle.
- Scores are relative: adding parts to a subsystem shifts every other part's score in it.

## Data quality

Every mass, cost and efficiency value has a `*_basis` column:

| Basis | Meaning |
|---|---|
| `vendor` | Manufacturer datasheet, page or store |
| `catalog` | Aggregator (satcatalog, satsearch, satnow, wiki lists) |
| `literature` | Papers, NASA reports, mission spec sheets |
| `derived` | Calculated from sourced values (e.g. W/kg from W and kg) |
| `estimate` | Scaled from a sibling product or price range; verify before use |

- Most manufacturers don't publish prices: `cost_usd` is NULL for every OBC, imager, thruster,
  antenna and attitude sensor. Views sorted by cost leave out NULL rows rather than ranking them last.
- Values imported from NASA tables are stored as tabulated. Where the table gave a bound
  (`< 235 g`, `> 6.5 dBi`), the bound is stored and the note says so.
- Rows with misaligned source columns, reseller duplicates and units over ~2 kg were skipped.
  Each SQL file's header lists what was left out.

## Views and example queries

| View | Purpose |
|---|---|
| `v_component` | All parts with segment, metric and `efficiency_score` |
| `v_by_cost` | Priced parts, cheapest first within each subsystem |
| `v_by_weight` | Parts lightest first within each subsystem |
| `v_by_efficiency` | Parts best first within each subsystem |
| `v_configuration_totals` | Mass, known cost and power roll-up per reference build |

```sql
SELECT * FROM v_by_cost WHERE subsystem = 'comms';
SELECT * FROM v_by_weight WHERE segment = 'payload';
SELECT * FROM v_by_efficiency WHERE subsystem = 'star_tracker';
SELECT * FROM v_component WHERE cost_basis IN ('vendor', 'catalog');   -- sourced prices only
SELECT * FROM v_configuration_totals;
```

```sh
sqlite3 -header -column cubesat.db "SELECT name, vendor, efficiency, efficiency_score FROM v_by_efficiency WHERE subsystem = 'reaction_wheel' LIMIT 10;"
```

## Adding parts

1. Put new rows in a new file under `sql/`, using an unused id range. Follow the existing files'
   pattern: an explicit column list, a `*_basis` for every value, and a source URL and dated note on each row.
2. New part types need an `INSERT INTO subsystem` row with a metric and direction.
3. Add the file to the `cat` list in `build.sh` before `views.sql`, then run `./build.sh`.
4. If the budget engine should power the new subsystem differently, add it to `DEFAULT_DUTY_CYCLE`
   in `../budget_engine/budget_engine.py` (unlisted subsystems default to always on).
