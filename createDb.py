""" Creates the initial tables required for operation."""
import sqlite3, time
from conf import config
con = sqlite3.connect('data.db')

ircNick = config['irc']['nick']
cyName = config['Cytube']['username']

#con.execute("DROP TABLE CyUser")
# User table
con.execute("""
        CREATE TABLE CyUser(
        userId INTEGER PRIMARY KEY AUTOINCREMENT,
        nameLower TEXT NOT NULL,
        registered INTEGER TEXT NOT NULL,
        nameOriginal TEXT NOT NULL,
        level INTEGER NOT NULL DEFAULT 0,
        flag INTEGER NOT NULL DEFAULT 0,
        firstSeen INTEGER NOT NULL,
        lastSeen INTEGER NOT NULL,
        accessTime INTEGER,
        UNIQUE (nameLower, registered));""")

# insert server
t = int(time.time())
con.execute("INSERT INTO CyUser VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (1, cyName.lower(), 1, cyName, 3, 1, t, t, 0))
con.execute("INSERT INTO CyUser VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (None, '[server]', 1, '[server]', 0, 2, t, t, 0))

# IRC User table
con.execute("""
        CREATE TABLE IrcUser(
        userId INTEGER PRIMARY KEY AUTOINCREMENT,
        nickLower TEXT NOT NULL,
        username TEXT,
        host TEXT NOT NULL,
        nickOriginal TEXT NOT NULL,
        flag INTEGER NOT NULL DEFAULT 0,
        UNIQUE (nickLower, username, host));""")
con.execute("INSERT INTO IrcUser VALUES (?, ?, ?, ?, ?, ?)",
            (1, ircNick.lower(), 'cybot', 'Yuka.rin.rin', ircNick, 1))
# Cy Chat table
con.execute("""
        CREATE TABLE CyChat(
        chatId INTEGER PRIMARY KEY AUTOINCREMENT,
        userId INTEGER,
        chatTime INTEGER,
        chatCyTime INTEGER,
        chatMsg TEXT,
        modflair INTEGER,
        flag INTEGER,
        FOREIGN KEY(userId) REFERENCES CyUser(userId));""")

# IRC Chat table
con.execute("""
        CREATE TABLE IrcChat(
        chatId INTEGER PRIMARY KEY AUTOINCREMENT,
        userId INTEGER,
        status INTEGER,
        chatTime INTEGER,
        chatMsg TEXT,
        flag INTEGER,
        FOREIGN KEY(userId) REFERENCES IrcUser(userId));""")

con.commit()
print "Tables created."
con.close()
