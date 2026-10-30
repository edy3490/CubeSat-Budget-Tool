# NASA S3VI source audit

Reviewed 2026-10-30. Catalog before this import: 56 parts. After: 87 parts.

## Existing NASA coverage

Two existing propulsion rows (72 PUC and 73 BGT-X5) cite a paper hosted in the S3VI SSRI Knowledge Base. Row 70 cites a NASA NTRS report. These are NASA-hosted references, not verified records from the SmallSat Parts On Orbit Now (SPOON) database.

[S3VI](https://www.nasa.gov/smallsat-institute/) provides a federated search across SPOON and other databases. Its [search homepage](https://s3vi.ndc.nasa.gov/) was accessible, but direct SPOON access redirected in a loop, and the search endpoint returned Forbidden. No SPOON records were downloaded or represented as verified. This import uses S3VI's public [2026 State-of-the-Art report](https://www.nasa.gov/smallsat-institute/sst-soa/), a separate S3VI resource. Direct SPOON reconciliation remains incomplete.

## Incorporated parts

| IDs | Count | Subsystem | Source |
| --- | --- | --- | --- |
| 200–205 | 6 | Solar panels: 2NDSpace DROP and CORE variants | [Power, Table 3-2](https://www.nasa.gov/smallsat-institute/sst-soa/power-subsystems/) |
| 206–215 | 10 | EPS: 2NDSpace, AAC Clyde Space, GUMUSH, Ibeos, NPC SPACEMIND, Pumpkin, SkyLabs, Spacemanic | Power, Table 3-8 |
| 216–224 | 9 | Batteries: GomSpace BP4/BP8, ISISPACE PBP variants, KANON, n-ART BAT, Space Inventor packs | Power, Table 3-5 |
| 225–230 | 6 | Propulsion: AIS-SWAG1 variants and CU Aerospace CHIPS variants | [Propulsion, Table 4-7](https://www.nasa.gov/smallsat-institute/sst-soa/in-space_propulsion/) |

Values copied from the NASA tables use `literature` basis. Each row includes its table locator, review date, operational conditions and source URL. No numerical TRL was inferred from NASA's PMI letter statuses. Unknown prices, mass, stored Wh and propellant load remain NULL. In particular, Ah capacity was not treated as Wh, EPS output power was not treated as consumption, and solar peak BOL output was not treated as orbit-average generation. Solar mass was not reverse-calculated from rounded specific power.

The tables survey SmallSats more broadly than CubeSats. No host form factor was asserted for these additions; payload or component volume does not establish mechanical/electrical compatibility with a host.

## Deduplication and discrepancies

Additional NASA evidence is attached to existing rows rather than inserting aliases or generic product families:

- 20 NanoAvionics EPS 1.0: NASA maximum conversion efficiency 96%.
- 23 GomSpace P31U: NASA mass 0.1 kg, maximum efficiency 96%; original efficiency estimate is 90%.
- 101 OPTIMUS-40: NASA's generic Optimus entry has approximately the same specific energy; no fourth generic Optimus part was added.
- 72 PUC: NASA lists 70 s Isp versus the existing paper's 72 s. Original values retained.
- 76 Enpulsion NANO: NASA distinguishes alpha/gamma performance. Existing row retained.

Legacy BPX and modern 100 Wh BPX were not combined or duplicated. Ambiguous ISISPACE iEPS/ICEPS2 revisions were not assumed to be distinct products. Parts with ambiguous column alignment or unspecified performance ranges were not converted into exact values. Approximately 90% Amun efficiency was left in notes, not stored as an exact scalar. EPS efficiencies that are stored are explicitly maximum values and should not be interpreted as nominal across all loads.

`component_source` stores 39 references for 38 distinct components (31 new, five corroborated, and two additional existing parts with NASA-hosted references). This table permits future SPOON records to be linked separately when accessible.

```sql
SELECT c.id, c.subsystem, c.name, cs.source_locator, cs.notes
FROM component c JOIN component_source cs ON cs.component_id = c.id
WHERE cs.source_collection = 'nasa_s3vi_soa_2026'
ORDER BY c.subsystem, c.name;
```

This is a reviewed subset of the public SoA tables, not a complete import of S3VI, SPOON, or the entire report. Payload imagery is outside this report's scope. Availability and mission compatibility require manufacturer confirmation.
