-- Seed data gathered 2026-10-30. Prices are often unpublished; see *_basis columns.
-- EUR converted at 1.08 USD.

INSERT INTO form_factor VALUES
 ('1U',  1,  2.00, '100 x 100 x 113.5'),
 ('1.5U',1.5,3.00, '100 x 100 x 170.2'),
 ('2U',  2,  4.00, '100 x 100 x 227'),
 ('3U',  3,  6.00, '100 x 100 x 340.5'),
 ('6U',  6, 12.00, '100 x 226.3 x 366'),
 ('12U',12, 24.00, '226.3 x 226.3 x 366');

INSERT INTO subsystem VALUES
 ('structure', 'hardware','Structure',                 'Structure mass per U',          'kg/U',    0),
 ('solar',     'hardware','Solar array',               'Specific power',                'W/kg',    1),
 ('eps',       'hardware','Electrical power system',   'Power conversion efficiency',   '%',       1),
 ('battery',   'hardware','Battery',                   'Energy density',                'Wh/kg',   1),
 ('obc',       'hardware','On-board computer',         'Power draw',                    'W',       0),
 ('adcs',      'hardware','Attitude determination & control','Momentum storage per kg','mNms/kg', 1),
 ('comms',     'hardware','Communications',            'Data rate per watt',            'kbps/W',  1),
 ('propulsion','hardware','Propulsion',                'Specific impulse',              's',       1),
 ('imager',    'payload', 'Imaging payload',           'Ground sample distance @500 km','m',       0),
 ('platform',  'bus',     'Integrated bus platform',   'Bus mass / CDS mass limit',     'ratio',   0);

-- id, subsystem, name, vendor, form_factor, mass_kg, mass_basis, cost_usd, cost_basis,
-- power_w, power_gen_w, efficiency, efficiency_basis, trl, source_url, notes
INSERT INTO component (id, subsystem, name, vendor, form_factor, mass_kg, mass_basis,
  cost_usd, cost_basis, power_w, power_gen_w, efficiency, efficiency_basis, trl, source_url, notes) VALUES
-- Structures
 (1,'structure','1U CubeSat Structure','EnduroSat','1U',0.120,'vendor',1550,'catalog',0,NULL,0.120,'derived',9,'https://endurosat.com/products/1u-cubesat-structure','Incl. fasteners, 2 kill switches, 2 sep springs. Cost = satcatalog FY2021 avg $1,500-1,600'),
 (2,'structure','3U CubeSat Structure','EnduroSat','3U',0.340,'vendor',3900,'estimate',0,NULL,0.113,'derived',9,'https://endurosat.com/products/1u-cubesat-structure','Cost scaled from 1U/1.5U catalog prices'),
 (3,'structure','6U CubeSat Structure','EnduroSat','6U',0.850,'vendor',8500,'estimate',0,NULL,0.142,'derived',9,'https://endurosat.com/products/1u-cubesat-structure','Cost scaled from 1U/1.5U catalog prices'),
 (4,'structure','3U CubeSat Structure','ISISPACE','3U',0.304,'vendor',4500,'estimate',0,NULL,0.101,'derived',9,'https://www.cubesatshop.com/wp-content/uploads/2016/06/ISIS-CubeSat-Structures-Brochure-v1.pdf','Primary 242.8 g + secondary = 304.3 g'),
-- Solar
 (10,'solar','3U Solar Panel (body-mounted)','EnduroSat','3U',0.147,'catalog',6900,'catalog',0,8.4,57.1,'derived',9,'https://satsearch.co/products/endurosat-3u-cubesat-solar-panel','7 triple-junction cells, >30% BOL / 29% EOL'),
 (11,'solar','3U Deployable Solar Array','EnduroSat','3U',0.285,'vendor',15300,'catalog',0,16.8,58.9,'derived',9,'https://www.endurosat.com/products/3u-deployable-solar-array','29.5% TJ cells; mass 285-468 g by config; cost = satcatalog FY2021 avg'),
 (12,'solar','3U Double Deployable Solar Array','EnduroSat','3U',0.468,'vendor',24000,'estimate',0,25.2,53.8,'derived',9,'https://endurosat.com/products/3u-double-deployable-solar-array-2','Cost scaled from single deployable'),
 (13,'solar','1U Solar Panel X/Y','EnduroSat','1U',0.050,'estimate',2900,'estimate',0,2.4,48.0,'derived',9,'https://www.endurosat.com/products/1u-solar-panel-x-y','2 TJ cells; mass/cost scaled from 3U panel'),
 (14,'solar','6U Solar Panel','EnduroSat','6U',0.270,'estimate',11000,'estimate',0,16.8,62.2,'derived',9,'https://endurosat.com/products/6u-solar-panel','Scaled from 3U panel'),
-- EPS
 (20,'eps','CubeSat EPS 1.0','NanoAvionics',NULL,0.160,'estimate',9150,'vendor',0.15,NULL,96,'estimate',9,'https://nanoavionics.com/cubesat-components/cubesat-electrical-power-system-eps/','Starting price EUR 8,470, min order 3'),
 (21,'eps','iEPS Type A (2-cell battery)','ISISPACE',NULL,0.184,'vendor',11000,'estimate',0.2,NULL,90,'estimate',9,'https://www.cubesatshop.com/wp-content/uploads/2019/06/ISIS-EPS-Brochure-web.pdf','Battery included'),
 (22,'eps','iEPS Type B (4-cell battery)','ISISPACE',NULL,0.310,'vendor',14000,'estimate',0.2,NULL,90,'estimate',9,'https://www.cubesatshop.com/wp-content/uploads/2019/06/ISIS-EPS-Brochure-web.pdf','Battery included'),
 (23,'eps','NanoPower P31U','GomSpace',NULL,0.100,'estimate',8000,'estimate',0.15,NULL,90,'estimate',9,'https://www.unisec-global.org/pdf/uniglo4/day3/01_gomspace.pdf','Up to 30 W, 1U-3U (2016 deck)'),
-- Battery
 (30,'battery','Battery Pack 2S2P','NanoAvionics',NULL,0.270,'estimate',2970,'vendor',0,NULL,181,'estimate',9,'https://nanoavionics.com/cubesat-components/cubesat-smallsat-battery-pack/','Starting price EUR 2,750; ~49 Wh assuming 3.4 Ah 18650 cells'),
-- OBC
 (40,'obc','iOBC','ISISPACE',NULL,0.094,'estimate',NULL,NULL,0.40,NULL,0.40,'estimate',9,'https://www.isispace.nl',NULL),
 (41,'obc','NanoMind A3200','GomSpace',NULL,0.024,'estimate',NULL,NULL,0.17,NULL,0.17,'estimate',9,'https://gomspace.com',NULL),
 (42,'obc','OBC (2016)','German Orbital Systems',NULL,0.071,'vendor',NULL,NULL,0.50,NULL,0.50,'estimate',8,'https://www.slideshare.net/slideshow/nanosatellite-components-catalogue-german-orbital-systems/71822162','96x91x14 mm'),
-- ADCS
 (50,'adcs','XACT-15','Blue Canyon Technologies',NULL,1.10,'catalog',NULL,NULL,2.8,NULL,13.6,'derived',9,'https://www.satnow.com/products/adcs-systems/blue-canyon-technologies/46-1186-xact-15','15 mNms, 5 mNm torque, 10x10x5 cm. Price widely reported as high; not public'),
 (51,'adcs','XACT-100','Blue Canyon Technologies','6U',1.38,'catalog',NULL,NULL,4.0,NULL,72.5,'derived',9,'https://satnow.com/products/adcs-systems/blue-canyon-technologies/46-1186-xact-100','100 mNms; another listing gives 1.813 kg'),
 (52,'adcs','CubeADCS 3-Axis','CubeSpace',NULL,0.600,'estimate',37000,'estimate',1.5,NULL,NULL,NULL,9,'https://satnow.com/products/adcs-systems/cubespace/46-1187-cubeadcs-3-axis','Price sheet range ~$2.3k-$37k; top of range assumed'),
 (53,'adcs','CubeADCS Y-Momentum','CubeSpace',NULL,0.400,'estimate',15000,'estimate',0.8,NULL,NULL,NULL,9,'https://satnow.com/products/adcs-systems/cubespace/46-1187-cubeadcs-3-axis','Single wheel on orbit normal; nadir pointing only'),
 (54,'adcs','CubeWheel Small (Gen1)','CubeSpace',NULL,0.060,'vendor',5000,'estimate',0.142,NULL,29.5,'estimate',9,'https://cubesatshop.com/?p=20808','Momentum ~1.77 mNms assumed'),
 (55,'adcs','CubeWheel Large (Gen1)','CubeSpace',NULL,0.225,'catalog',9000,'estimate',0.35,NULL,136.0,'estimate',9,'https://www.satcatalog.com/component/gen1-cubewheel-large/','Momentum ~30.6 mNms assumed'),
 (56,'adcs','ADCS100 (reaction sphere)','Tensor Tech',NULL,0.300,'catalog',NULL,NULL,1.0,NULL,NULL,NULL,NULL,'https://www.satcatalog.com/component/adcs100/',NULL),
 (57,'adcs','VAC02','Serenum Space',NULL,0.404,'catalog',NULL,NULL,0.96,NULL,NULL,NULL,NULL,'https://satsearch.co/products/serenumspace-vac02-adcs','384-424 g'),
-- Comms (efficiency = data rate / power_w)
 (60,'comms','UHF Transceiver II','EnduroSat',NULL,0.094,'literature',8600,'estimate',4.0,NULL,4.9,'estimate',9,'https://cta.ing.unlp.edu.ar/wp-content/uploads/2025/03/CUBESAT-6U-v5.pdf','Up to 19.6 kbps, 1 W RF'),
 (61,'comms','TRXVU UHF/VHF Duplex','ISISPACE',NULL,0.085,'catalog',9600,'catalog',4.0,NULL,2.4,'estimate',9,'https://ssi-wiki.stanford.edu/COTS_CubeSat_Radio','1.2-9.6 kbps downlink'),
 (62,'comms','S-Band Transmitter','ISISPACE',NULL,0.132,'catalog',15000,'estimate',9.0,NULL,1111,'estimate',9,'https://www.satnow.com/products/space-transmitters/isispace/142-1233-s-band-transmitter','Up to 10 Mbps, 2200-2290 MHz'),
 (63,'comms','S-Band Transmitter','EnduroSat',NULL,0.150,'estimate',14800,'vendor',6.0,NULL,333,'estimate',9,'https://endurosat.com/cubesat-store/page/4/','~2 Mbps assumed'),
 (64,'comms','X-Band Transmitter','EnduroSat',NULL,0.270,'literature',32300,'vendor',13.5,NULL,11111,'estimate',9,'https://endurosat.com/products/x-band-transmitter/','Up to 150 Mbps'),
 (65,'comms','PULSAR-XTX','AAC Clyde Space',NULL,0.300,'estimate',40000,'estimate',12.0,NULL,4167,'estimate',9,'https://www.aac-clyde.space/wp-content/uploads/2021/10/PULSAR-XTX.pdf','Up to 50 Mbps OQPSK/QPSK'),
-- Propulsion (mass = wet)
 (70,'propulsion','MEMS Cold Gas Module','NanoSpace',NULL,0.300,'literature',NULL,NULL,2.5,NULL,110,'literature',9,'https://ntrs.nasa.gov/api/citations/20160010571/downloads/20160010571.pdf','<4 mN, 50 g propellant'),
 (71,'propulsion','MiPS (cold gas)','VACCO',NULL,1.00,'estimate',NULL,NULL,5.0,NULL,40,'vendor',8,'https://www.vacco.com/images/uploads/pdfs/MiPS_standard_0714.pdf','10 mN'),
 (72,'propulsion','PUC electrothermal','CU Aerospace / VACCO',NULL,0.72,'literature',NULL,NULL,15.0,NULL,72,'literature',7,'https://s3vi.ndc.nasa.gov/ssri-kb/static/resources/aerospace-06-00091.pdf','5.4 mN; another source lists 1.2 kg'),
 (73,'propulsion','BGT-X5 class green monoprop (AF-M315E)','Busek',NULL,1.49,'literature',NULL,NULL,20.0,NULL,220,'literature',7,'https://s3vi.ndc.nasa.gov/ssri-kb/static/resources/aerospace-06-00091.pdf','425 mN'),
 (74,'propulsion','BIT-3 RF ion (iodine)','Busek',NULL,2.90,'estimate',NULL,NULL,75.0,NULL,2150,'estimate',7,'https://www.busek.com','~1.1 mN; values from Busek public specs, verify'),
 (75,'propulsion','1U Hydrazine Module','Rocket Lab (ex-L3Harris/Aerojet)','1U',1.60,'vendor',NULL,NULL,NULL,NULL,220,'estimate',7,'https://arsuppliernet.l3harris.com/sites/default/files/documents/CubeSat Mod Prop-2sided.pdf','6U green variant 11.2 kg wet'),
 (76,'propulsion','NANO (FEEP)','Enpulsion',NULL,0.90,'estimate',NULL,NULL,40.0,NULL,3000,'estimate',9,'https://www.enpulsion.com','Isp 2000-6000 s throttleable'),
-- Payloads
 (80,'imager','Chameleon (MS/HS)','Dragonfly Aerospace',NULL,1.60,'vendor',NULL,NULL,3.5,NULL,10.0,'catalog',9,'https://www.satcatalog.com/component/chameleon-imager','10 m RGB, 20 m MS, up to 150 HS bands'),
 (81,'imager','Mantis','Dragonfly Aerospace',NULL,0.50,'catalog',NULL,NULL,6.0,NULL,16.0,'catalog',9,'https://satnow.com/products/satellite-cameras/dragonfly-aerospace/113-1249-mantis','16 m PAN / 32 m MS'),
 (82,'imager','Caiman','Dragonfly Aerospace','6U',1.40,'catalog',NULL,NULL,10.0,NULL,3.25,'catalog',9,'https://www.satcatalog.com/component/caiman-imager/','3.25 m PAN / 6.5 m MS'),
 (83,'imager','MultiScape100 CIS','Simera Sense',NULL,1.26,'catalog',NULL,NULL,5.8,NULL,4.75,'estimate',9,'https://www.satnow.com/products/satellite-cameras/simera-sense/113-1295-multiscape100-cis','580 mm focal length'),
 (84,'imager','iSIM-90','SATLANTIS','12U',4.00,'catalog',NULL,NULL,NULL,NULL,NULL,NULL,9,'https://www.satnow.com/products/satellite-cameras/satlantis/113-1294-isim-90','<4 kg; PAN/VNIR/SWIR'),
-- Bus platforms (efficiency = mass / CDS limit)
 (90,'platform','1U CubeSat Platform','EnduroSat','1U',0.85,'vendor',NULL,NULL,NULL,NULL,0.425,'derived',9,'https://endurosat.com/wp-content/uploads/2022/02/Endurosat_Product_Catalogue_02_22.pdf',NULL),
 (91,'platform','3U CubeSat Platform','EnduroSat','3U',2.65,'vendor',NULL,NULL,NULL,NULL,0.442,'derived',9,'https://satsearch.co/products/endurosat-3u-platform','2.4-2.9 kg by config');

INSERT INTO configuration VALUES
 (1,'1U Tech Demo (minimal)','1U','Education / tech demonstration, UHF only'),
 (2,'3U Earth Observation (budget)','3U','Medium-res imaging, S-band downlink'),
 (3,'6U Earth Observation (high-res)','6U','3 m class imaging, X-band downlink'),
 (4,'6U Electric Propulsion Demo','6U','Orbit raising with ion thruster'),
 (5,'3U Green-Prop Maneuvering','3U','Formation flying / orbit maintenance');

INSERT INTO configuration_item VALUES
 (1,1,1),(1,13,4),(1,23,1),(1,30,1),(1,41,1),(1,61,1),
 (2,2,1),(2,11,2),(2,22,1),(2,40,1),(2,52,1),(2,60,1),(2,63,1),(2,81,1),
 (3,3,1),(3,14,2),(3,20,1),(3,30,2),(3,40,1),(3,51,1),(3,60,1),(3,64,1),(3,82,1),
 (4,3,1),(4,14,2),(4,20,1),(4,30,2),(4,41,1),(4,50,1),(4,61,1),(4,62,1),(4,74,1),
 (5,4,1),(5,12,2),(5,22,1),(5,42,1),(5,53,1),(5,61,1),(5,73,1);

-- Battery capacity and propellant load (needed by the budget engine). Mostly estimates.
UPDATE component SET energy_wh = 49   WHERE id = 30;  -- 2S2P 18650, est
UPDATE component SET energy_wh = 22.5 WHERE id = 21;  -- 2-cell, est
UPDATE component SET energy_wh = 45   WHERE id = 22;  -- 4-cell, est
UPDATE component SET propellant_kg = 0.05 WHERE id = 70;  -- literature
UPDATE component SET propellant_kg = 0.30 WHERE id = 71;  -- est
UPDATE component SET propellant_kg = 0.25 WHERE id = 72;  -- est
UPDATE component SET propellant_kg = 0.35 WHERE id = 73;  -- est
UPDATE component SET propellant_kg = 1.50 WHERE id = 74;  -- est, iodine
UPDATE component SET propellant_kg = 0.50 WHERE id = 75;  -- est
UPDATE component SET propellant_kg = 0.22 WHERE id = 76;  -- est, indium
