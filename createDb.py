""" Creates the initial tables required for operation."""
import sqlite3
con = sqlite3.connect('data.db')

#con.execute("DROP TABLE CyUser")
con.execute("""
        CREATE TABLE CyUser(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nameLower TEXT NOT NULL,
        registered INTEGER TEXT NOT NULL,
        nameOriginal TEXT NOT NULL,
        level INTEGER NOT NULL DEFAULT 0,
        flag INTEGER NOT NULL DEFAULT 0,
        firstSeen INTEGER NOT NULL,
        lastSeen INTEGER NOT NULL,
        accessTime INTEGER,
        UNIQUE (nameLower, registered));""")

print "Table created."
con.close()
