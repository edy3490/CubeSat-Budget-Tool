# Additional source review

Checked 2026-10-30. This is a targeted expansion, not an exhaustive supplier inventory or a revalidation of the original 45 rows. Added 11 distinct products without changing the five reference builds. All additions have a source URL and dated notes. Prices and TRL remain NULL because the reviewed specifications do not establish them.

| New IDs | Products | Manufacturer source | Data used |
| --- | --- | --- | --- |
| 100–102 | OPTIMUS-30, -40, -80 | [AAC datasheet](https://www.aac-clyde.space/wp-content/uploads/2021/10/AAC_DataSheet_Optimus.pdf) | 30/40/80 Wh; typical masses 268/335/670 g; Wh/kg calculated from these pairs |
| 103 | NanoPower BPX 100 Wh | [GomSpace comparison](https://gomspace.com/UserFiles/NanoPower_BPX_100_Wh_compare.pdf), [current battery catalog](https://gomspace.com/products/power-systems/battery-packs/) | 100 Wh, approximately 508 g; calculated 196.85 Wh/kg |
| 104–106 | ISISPACE 1U, 2U, 6U structures | [2021 manufacturer brochure](https://www.isispace.nl/wp-content/uploads/2021/08/ISISPACE-Products-brochure-2021.pdf) | Primary plus secondary masses 200/390/1100 g; kg/U calculated |
| 107 | TriScape100 | [Manufacturer page](https://simera-sense.com/products/triscape100/) | 1.26 kg ±5%; imaging power 6.75 W; GSD 4.75 m at 500 km |
| 108 | HyperScape100 | [Manufacturer page](https://simera-sense.com/products/hyperscape100/) | 1.26 kg ±5%; imaging power 7.75 W; GSD 4.75 m at 500 km |
| 109–110 | GomSpace 6U, 12U nanosatellite platforms | [Manufacturer comparison](https://gomspace.com/satellite-platforms/) | Approximate platform masses 6/8 kg; ratios calculated using existing form-factor limits |

## Qualifications

- AAC's source is a legacy datasheet released in 2020. Confirm availability and revision before procurement. Quiescent power upper bounds are documented in notes, not represented as nominal power.
- BPX has multiple cell revisions. The added 100 Wh product must not be compared using the older 86 Wh product's mass/capacity pair.
- Current Simera pages supersede older catalog masses of 1.1/1.2 kg for these added variants. Their 1.5U payload volume does not imply compatibility with a 1.5U host; host form_factor is NULL.
- ISISPACE 6U structure envelope in the brochure differs from the database's reference envelope. Fit and deployer compatibility need configuration-specific review.
- Bus masses are approximate. A bus-mass fraction is an allocation indicator, not a complete measure of platform performance; launch mass allowances and configuration boundaries vary.
- Efficiency scores are relative percentiles within each subsystem. Adding products changes existing scores. GSD alone does not capture spectral capability; OBC power alone does not capture computing performance. Integrated ADCS and individual wheels also have different functional boundaries.
- The original entries still contain estimated masses, prices, and efficiency figures, including old price anchors. This expansion does not validate those values. The cost/weight/efficiency views exclude rows with missing values rather than displaying them last.

## Further candidates and coverage gaps

The [current GomSpace product catalog](https://gomspace.com/products/) also lists BP8 100 Wh, NanoPower P80, NanoMind HP MK3, and NanoCom Link SX. [ISISPACE](https://www.isispace.nl/product/platforms/) offers additional integrated platforms. These merit follow-up with configuration-specific datasheets and quotes; no specifications were inferred for them here.

The schema currently represents payloads only as imagers. GNSS receivers, antennas, star/sun sensors, magnetorquers, deployment devices, thermal hardware, and non-imaging payloads need suitable subsystem definitions and comparison metrics before they can be ranked meaningfully. These gaps remain open.
