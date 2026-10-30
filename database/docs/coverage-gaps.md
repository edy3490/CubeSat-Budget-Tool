# Manufacturer coverage gaps

Checked 2026-10-30 against the product tables of NASA's *State-of-the-Art of Small Spacecraft
Technology* (NASA/TP-20260003140, May 2026; [copy hosted by Vectronic Aerospace](https://www.vectronic-aerospace.com/wp-content/uploads/2026/05/soa-2026-1_260515_235945.pdf)).
Names were read from the report's tables after text extraction. Where a table wrapped across lines,
only the manufacturer is listed, not the model. These are manufacturers that appear in the report
and have **no rows** in `cubesat.db`. No specifications were imported.

The report covers SmallSats generally, so some listed products are larger than CubeSat class.
Imaging payloads are outside its scope.

## Subsystems in the schema, with missing manufacturers

| Subsystem | In DB | Missing manufacturers (SoA table) |
|---|---|---|
| Structures | EnduroSat, ISISPACE | AAC Clyde Space (ZAPHOD), C3S, Cervos Space, Exobotics, German Orbital Systems, GomSpace, Gran Systems, GUMUSH (n-ART), Ishitoshi Machining, NanoAvionics, Nara Space, NPC Spacemind, Pumpkin (Supernova), SatRev, Space Inventor (6-2) |
| Solar arrays | EnduroSat, 2NDSpace | AAC Clyde Space (Photon), Airbus (Sparkwing), Blue Canyon, DHV Technology, Emxys, Exobotics (XO-PANEL), ExoTerra, GomSpace (P110), ISISPACE, Lockheed Martin, MMA Design (HaWK, zHawk), NPC Spacemind (SP3X/SP4X), Pumpkin, Redwire (ROSA), SatRev, Sierra Space, Space Dynamics Lab, Spacemanic (3-2) |
| EPS | 11 vendors | Aerospacelab, Argotec, Berlin Space Technologies, Bradford Space, C3S, DHV Technology, Dragonfly Aerospace, Ecarver, Emxys, EnduroSat (EPS II/IV), Space Inventor, SatRev (3-8); GomSpace P60/P80 and ISIS ICEPS2 A/B/C are missing models |
| Batteries | 7 vendors | Aerospacelab, Astro Digital, Argotec (ELEKTRA), Berlin Space Technologies, Dragonfly Aerospace, EaglePicher, EnduroSat, Ibeos, Saft, SatRev, SkyLabs, Space Dynamics Lab, Vectronic (3-5) |
| OBC | ISISPACE, GomSpace, German Orbital Systems | AAC Clyde Space (Kryten-M3, Sirius), Alén Space (DARA), Aitech, Aerospacelab, Argotec (FERMI), Berlin Space Technologies (CDH-110), Bradford Space, C3S, CesiumAstro, Emxys (ODALISS), EnduroSat (OBC I/II, GPC), GomSpace (NanoMind HP MK3), Ibeos (EDGE-1100), Innoflight (CFC-400), KP Labs (Antelope), and more; the table continues (8-4) |
| ADCS (integrated) | Blue Canyon, CubeSpace, Tensor Tech, Serenum | AAC Clyde Space (iADCS-200/400), Arcsec (Arcus), Berlin Space Technologies (iADCS-100); Blue Canyon XACT-50 is a missing model (5-2) |
| Comms (radios) | EnduroSat, ISISPACE, AAC Clyde Space | GomSpace (AX100, NanoCom SDR), AstroDev (Helium/Lithium/Beryllium), Alén Space (TOTEM, TREVO), NanoAvionics, SkyLabs, Spacemanic, Satlab (SRS-3/4), Syrlinks (EWC27/31), IQ Spacecom (HISPICO), Tethers Unlimited (SWIFT), Vulcan Wireless, CesiumAstro, Innoflight, Space Inventor, CUBECOM, Quasonix, Emxys, SatRev, SENyT, Orion Space, Dragonfly, L3Harris, Iridium/Globalstar modems (NAL Research, NearSpace Launch, sci_Zone) (9-3) |
| Propulsion | 8 vendors | Benchmark Space Systems, Dawn Aerospace, ECAPS, Stellar Exploration, Rubicon, NanoAvionics (EPSS), Tethers Unlimited, GomSpace (NanoProp), ThrustMe, T4i, Aurora Propulsion, Pale Blue, SteamJet, Bradford, Morpheus Space, Exotrail, ExoTerra, Orbion, Aliena, Phase Four, Comat, Hypernova, Mars Space, Neumann Space, Miles Space, Moog, Marotta; Busek BHT/BET/CMNT and Enpulsion Micro R3/Neo are missing models (4-2 to 4-12) |
| Bus platforms | EnduroSat, GomSpace | AAC Clyde Space, Blue Canyon, Deimos, Exobotics, FOSSA, German Orbital Systems, Gran Systems, GUMUSH, Harpy, HEX20, Hydra, Innova, ISISPACE, NanoAvionics, NearSpace Launch, NPC Spacemind, Orbital Astronautics, Orion Space, Pumpkin, Quub, SatRev, SFL Missions, Space Inventor, Spacemanic, U-Space (2-3); 6U adds Argotec, Astro Digital, Nara Space, Space Dynamics Lab, Terran Orbital (2-4) |
| Imagers | Dragonfly, Simera Sense, SATLANTIS | Not covered by the SoA report. Kuva Space (Hyperfield) appeared in earlier searches but is unverified here |

## Categories with no subsystem in the schema

Each needs a subsystem row and a comparison metric before it can be ranked.

| Category | Manufacturers in SoA | Suggested efficiency metric |
|---|---|---|
| Optical comms terminals (9-4) | AAC Clyde Space (CubeCat), DLR (OSIRIS4CubeSat), CACI, Mynaric, Emxys (ODALCOM), MIT (CLICK; research) | Data rate per W |
| Deployers (10-2) | Cal Poly, COMAT, Dhruva Space, Exolaunch, Gran Systems, ISISPACE, Maverick Space Systems, NPC Spacemind, Rocket Lab (CSD), Tyvak, UARX Space, Voyager/NanoRacks, Xterra | Launch hardware; affects launch cost, not the bus |
| Thermal control (7-x) | Coatings, MLI, straps, heaters, TECs | Usually mission-specific; low priority |
| Non-imaging payloads | AIS/ADS-B receivers, SDR payloads, IoT relays, radiation monitors | Not in SoA tables; needs a separate source |

## Data gaps inside existing rows

- Propulsion rows 225–230 (AIS, CHIPS) have no `propellant_kg`, so the budget engine gives them 0 delta-v.
- Most rows imported from NASA (200–224) have no mass. Solar rows 200–205 have no mass, so a build that uses them under-reports total mass.
- Prices are still missing for every OBC, imager, thruster and Blue Canyon ADCS row.

## Imported since this review

- **GNSS receivers** (`gnss`, ids 300-311): 12 of 16 Table 5-10 rows. Skipped: the GomSpace row (no model given) and
  GNSS-3, Mosaic-T and AsteRx SBi3 Pro+, whose manufacturer cell is split between Septentrio and Space Inventor.
- **Antennas** (`antenna_uhf`, `antenna_l`, `antenna_s`, `antenna_x`, ids 320-391): 62 Table 9-2 rows. Skipped:
  Ku/K/Ka antennas (no matching radios in the database), deployables over ~2 kg (MMA LAMBDA, MMA reflectarrays,
  Oxford C-band and Ka reflectors, CesiumAstro L-band phased array), and Anteral 2211-301-01 (no numeric data).
- **ADCS actuators and sensors** (ids 400-608, NASA Tables 5-3 to 5-9): 44 reaction wheels, 37 magnetorquers,
  24 star trackers, 31 sun sensors, 4 horizon sensors, 10 magnetometers, 19 gyros/IMUs. Existing CubeWheels
  (rows 54, 55) moved from `adcs` to `reaction_wheel`; row 54 is the CW0017. Skipped: units over ~2 kg;
  misaligned rows (NewSpace NRWA wheels, Trillian-1, Space Inventor MIST and IMU-P4); reseller duplicates
  (Space Inventor WHL wheels and ASTRO CL, NovAtel OEM-IMU-STIM300); spin-stabilized and accelerometer-only sensors.
- Still missing from GNC: Space Inventor reaction wheels (only reseller listings or >2 kg) and NewSpace Systems
  wheels (source columns misaligned).
- Row 75 (1U hydrazine module) is labelled "Rocket Lab (ex-L3Harris/Aerojet)"; NASA Table 4-2 lists the MPS-120
  under Aerojet Rocketdyne. Current ownership unverified.
