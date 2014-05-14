""" Creates the initial tables required for operation."""
import sqlite3, time
from conf import config
con = sqlite3.connect('data.db')
con.execute('pragma foreign_keys=ON')

ircNick = config['irc']['nick']
cyName = config['Cytube']['username']

#con.execute("DROP TABLE CyUser")
# CyUser table
con.execute("""
        CREATE TABLE CyUser(
        userId INTEGER PRIMARY KEY,
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
        (2, '[server]', 1, '[server]', 0, 2, t, t, 0))
con.execute("INSERT INTO CyUser VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (3, '[anonymous]', 1, '[anonymous]', 0, 4, t, t, 0))

# IRC User table
con.execute("""
        CREATE TABLE IrcUser(
        userId INTEGER PRIMARY KEY,
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
        chatId INTEGER PRIMARY KEY,
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
        chatId INTEGER PRIMARY KEY,
        userId INTEGER,
        status INTEGER,
        chatTime INTEGER,
        chatMsg TEXT,
        flag INTEGER,
        FOREIGN KEY(userId) REFERENCES IrcUser(userId));""")

# VocaDB table
con.execute("""
        CREATE TABLE VocaDB(
        songId INTEGER PRIMARY KEY,
        data TEXT NOT NULL,
        lastUpdate INTEGER NOT NULL);""")

# media table
con.execute("""
        CREATE TABLE Media(
        mediaId INTEGER PRIMARY KEY,
        type TEXT NOT NULL,
        id TEXT NOT NULL,
        dur INTEGER NOT NULL,
        title TEXT NOT NULL,
        by TEXT NOT NULL,
        flag INTEGER,
        UNIQUE (type, id),
        FOREIGN KEY (by) REFERENCES CyUser(userId));""")

title = ('\xe3\x80\x90\xe7\xb5\x90\xe6\x9c\x88\xe3\x82\x86\xe3\x81\x8b\xe3'
         '\x82\x8a\xe3\x80\x91Mahou \xe9\xad\x94\xe6\xb3\x95\xe3\x80\x90\xe3'
         '\x82\xab\xe3\x83\x90\xe3\x83\xbc\xe3\x80\x91')
title = title.decode('utf-8')
con.execute("INSERT INTO media VALUES (?, ?, ?, ?, ?, ?, ?)",
           (None, 'yt', '01uN4MCsrCE', 248, title, 1, None))

# MediaSong table
# A junction table between Media and VocaDB. Although the relationship
# between Media and VocaDB is Many-to-One, VocaDB data can get complex
# and separating it from Media could be useful later when modularizing
# the program, and usable for rooms that don't need the VocaDB feature.

con.execute("""
        CREATE TABLE MediaSong(
        mediaId INTEGER NOT NULL,
        songId INTEGER NOT NULL,
        userId INTEGER NOT NULL,
        time INTEGER NOT NULL,
        method  INTEGER NOT NULL,
        UNIQUE (mediaId),
        FOREIGN KEY (mediaId) REFERENCES Media(mediaId),
        FOREIGN KEY (songId) REFERENCES VocaDB(songId),
        FOREIGN KEY (userId) REFERENCES CyUser(userId));""")

# queue table
con.execute("""
        CREATE TABLE Queue(
        queueId INTEGER PRIMARY KEY,
        mediaId INTEGER NOT NULL,
        userId INTEGER NOT NULL,
        time INTEGER NOT NULL,
        flag INTEGER,
        FOREIGN KEY (userId) REFERENCES CyUser(userId),
        FOREIGN KEY (mediaId) REFERENCES media(mediaId));""")

con.commit()
print "Tables created."

con.close()
