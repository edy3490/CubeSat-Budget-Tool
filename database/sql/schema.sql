-- CubeSat component catalog schema (SQLite)
PRAGMA foreign_keys = ON;

-- CubeSat Design Specification form factors and their mass limits
CREATE TABLE form_factor (
    code          TEXT PRIMARY KEY,          -- '1U', '3U', '6U', ...
    units         REAL NOT NULL,
    max_mass_kg   REAL NOT NULL,             -- CDS limit
    envelope_mm   TEXT NOT NULL
);

-- segment: 'payload' | 'hardware' (subsystem parts) | 'bus' (integrated platforms)
-- Each subsystem has ONE efficiency metric so parts are compared like-for-like.
CREATE TABLE subsystem (
    code              TEXT PRIMARY KEY,
    segment           TEXT NOT NULL CHECK (segment IN ('payload','hardware','bus')),
    name              TEXT NOT NULL,
    efficiency_metric TEXT NOT NULL,
    efficiency_unit   TEXT NOT NULL,
    higher_is_better  INTEGER NOT NULL CHECK (higher_is_better IN (0,1))
);

-- *_basis records where each number came from:
--   vendor     = manufacturer page/datasheet/store
--   catalog    = aggregator (satcatalog, satsearch, satnow, wiki lists)
--   literature = papers, NASA reports, mission spec sheets
--   estimate   = derived from a sibling product / price sheet range; verify before use
CREATE TABLE component (
    id              INTEGER PRIMARY KEY,
    subsystem       TEXT NOT NULL REFERENCES subsystem(code),
    name            TEXT NOT NULL,
    vendor          TEXT NOT NULL,
    form_factor     TEXT REFERENCES form_factor(code),   -- NULL = fits any / unit-agnostic
    mass_kg         REAL,
    mass_basis      TEXT CHECK (mass_basis IN ('vendor','catalog','literature','estimate')),
    cost_usd        REAL,                                 -- NULL = no public price found
    cost_basis      TEXT CHECK (cost_basis IN ('vendor','catalog','literature','estimate')),
    power_w         REAL,                                 -- nominal/peak consumption
    power_gen_w     REAL,                                 -- generation (solar only)
    efficiency      REAL,                                 -- value in subsystem's metric
    efficiency_basis TEXT CHECK (efficiency_basis IN ('vendor','catalog','literature','estimate','derived')),
    trl             INTEGER,
    source_url      TEXT,
    notes           TEXT,
    energy_wh       REAL,                                 -- stored energy (batteries / EPS w/ battery)
    propellant_kg   REAL                                  -- loaded propellant (propulsion)
);

-- Reference spacecraft builds
CREATE TABLE configuration (
    id           INTEGER PRIMARY KEY,
    name         TEXT NOT NULL,
    form_factor  TEXT NOT NULL REFERENCES form_factor(code),
    mission      TEXT
);

CREATE TABLE configuration_item (
    configuration_id INTEGER NOT NULL REFERENCES configuration(id),
    component_id     INTEGER NOT NULL REFERENCES component(id),
    quantity         INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (configuration_id, component_id)
);

CREATE INDEX idx_component_subsystem ON component(subsystem);

-- Additional evidence may corroborate an existing part without duplicating it.
-- Collection identifies provenance; NASA-hosted papers do not imply SPOON membership.
CREATE TABLE component_source (
    component_id      INTEGER NOT NULL REFERENCES component(id),
    source_collection TEXT NOT NULL,
    source_url        TEXT NOT NULL,
    source_locator    TEXT NOT NULL,
    reviewed_on       TEXT NOT NULL,
    notes             TEXT,
    PRIMARY KEY (component_id, source_collection, source_url, source_locator)
);
