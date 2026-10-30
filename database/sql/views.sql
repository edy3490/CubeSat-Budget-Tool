-- Efficiency is normalized to a 0-100 score WITHIN each subsystem (percentile rank),
-- since Isp, W/kg, kbps/W etc. aren't comparable across subsystems.
CREATE VIEW v_component AS
SELECT c.id, s.segment, c.subsystem, c.name, c.vendor, c.form_factor,
       c.cost_usd, c.cost_basis, c.mass_kg, c.mass_basis,
       c.power_w, c.power_gen_w,
       c.efficiency, s.efficiency_unit, s.efficiency_metric, c.efficiency_basis,
       CASE WHEN c.efficiency IS NULL THEN NULL
            WHEN COUNT(c.efficiency) OVER w = 1 THEN 100.0
            ELSE ROUND(100.0 * PERCENT_RANK() OVER (
                   PARTITION BY c.subsystem, c.efficiency IS NULL
                   ORDER BY CASE WHEN s.higher_is_better = 1 THEN c.efficiency ELSE -c.efficiency END), 1)
       END AS efficiency_score,
       c.trl, c.source_url, c.notes
FROM component c JOIN subsystem s ON s.code = c.subsystem
WINDOW w AS (PARTITION BY c.subsystem);

-- Sorted views (cheapest / lightest / most efficient first, unknowns last)
CREATE VIEW v_by_cost AS
SELECT segment, subsystem, name, vendor, cost_usd, cost_basis, mass_kg, efficiency_score,
       RANK() OVER (PARTITION BY subsystem ORDER BY cost_usd) AS cost_rank_in_subsystem
FROM v_component WHERE cost_usd IS NOT NULL
ORDER BY subsystem, cost_usd;

CREATE VIEW v_by_weight AS
SELECT segment, subsystem, name, vendor, mass_kg, mass_basis, cost_usd, efficiency_score,
       RANK() OVER (PARTITION BY subsystem ORDER BY mass_kg) AS mass_rank_in_subsystem
FROM v_component WHERE mass_kg IS NOT NULL
ORDER BY subsystem, mass_kg;

CREATE VIEW v_by_efficiency AS
SELECT segment, subsystem, name, vendor, efficiency, efficiency_unit, efficiency_metric,
       efficiency_basis, efficiency_score, cost_usd, mass_kg
FROM v_component WHERE efficiency IS NOT NULL
ORDER BY subsystem, efficiency_score DESC;

-- Roll-up of each reference build: mass/power budgets against CDS limits
CREATE VIEW v_configuration_totals AS
SELECT cf.id, cf.name, cf.form_factor,
       ROUND(SUM(ci.quantity * c.mass_kg), 3)                       AS total_mass_kg,
       ff.max_mass_kg,
       ROUND(ff.max_mass_kg - SUM(ci.quantity * c.mass_kg), 3)      AS mass_margin_kg,
       SUM(ci.quantity * c.cost_usd)                                AS known_cost_usd,
       SUM(CASE WHEN c.cost_usd IS NULL THEN ci.quantity ELSE 0 END) AS items_without_price,
       ROUND(SUM(ci.quantity * COALESCE(c.power_gen_w, 0)), 1)      AS solar_gen_w,
       ROUND(SUM(ci.quantity * COALESCE(c.power_w, 0)), 1)          AS peak_draw_w
FROM configuration cf
JOIN form_factor ff ON ff.code = cf.form_factor
JOIN configuration_item ci ON ci.configuration_id = cf.id
JOIN component c ON c.id = ci.component_id
GROUP BY cf.id;
