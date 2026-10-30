#!/bin/sh
# Rebuild cubesat.db from the SQL sources
set -e
cd "$(dirname "$0")"
rm -f cubesat.db
cat sql/schema.sql sql/seed.sql sql/additions.sql sql/nasa_s3vi.sql sql/nasa_gnss_antennas.sql sql/views.sql | sqlite3 -bail cubesat.db
echo "Built cubesat.db"
