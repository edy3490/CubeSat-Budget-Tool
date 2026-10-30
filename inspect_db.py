import sqlite3
c = sqlite3.connect("database/cubesat.db")

print("Subsystems and part counts:")
for r in c.execute("select subsystem, count(*) from component group by subsystem"):
    print("  ", r)

print()
print("Payload-type parts (id, subsystem, name, cost):")
for r in c.execute("select id, subsystem, name, cost_usd from component "
                   "where subsystem in ('imager','gnss','comms') order by subsystem, id"):
    print("  ", r)