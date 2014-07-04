""" Creates the initial tables required for operation."""
import sqlite3, time
from conf import config
from sqlite3 import IntegrityError
con = sqlite3.connect('data.db')
con.execute('pragma foreign_keys=ON')

ircNick = config['irc']['nick']
cyName = config['Cytube']['username']

#con.execute("DROP TABLE CyUser")
# CyUser table
con.execute("""
        CREATE TABLE IF NOT EXISTS CyUser(
        userId INTEGER PRIMARY KEY,
        nameLower TEXT NOT NULL,
        registered INTEGER TEXT NOT NULL,
        nameOriginal TEXT NOT NULL,
        level INTEGER NOT NULL DEFAULT 0,
        flag INTEGER NOT NULL DEFAULT 0,
        profileText TEXT,
        profileImgUrl TEXT,
        UNIQUE (nameLower, registered));""")

# insert server
try:
    con.execute("INSERT INTO CyUser VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (1, cyName.lower(), 1, cyName, 3, 1, None, None))
    con.execute("INSERT INTO CyUser VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (2, '[server]', 1, '[server]', 0, 2, None, None))
    con.execute("INSERT INTO CyUser VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (3, '[anonymous]', 0, '[anonymous]', 0, 4, None, None))
except(IntegrityError):
    pass

# User in/out
con.execute("""
        CREATE TABLE IF NOT EXISTS UserInOut(
        userId INTEGER NOT NULL,
        enter INTEGER NOT NULL,
        leave INTEGER NOT NULL,
        flag DEFAULT 0 NOT NULL,
        FOREIGN KEY(userId) REFERENCES CyUser(userId));""")

# IRC User table
con.execute("""
        CREATE TABLE IF NOT EXISTS IrcUser(
        userId INTEGER PRIMARY KEY,
        nickLower TEXT NOT NULL,
        username TEXT NOT NULL,
        host TEXT NOT NULL,
        nickOriginal TEXT NOT NULL,
        flag INTEGER NOT NULL DEFAULT 0,
        UNIQUE (nickLower, username, host));""")
try:
    con.execute("INSERT INTO IrcUser VALUES (?, ?, ?, ?, ?, ?)",
                (1, ircNick.lower(), 'cybot', 'Yuka.rin.rin', ircNick, 1))
except(IntegrityError):
    pass
# Cy Chat table
con.execute("""
        CREATE TABLE IF NOT EXISTS CyChat(
        chatId INTEGER PRIMARY KEY,
        userId INTEGER NOT NULL,
        chatTime INTEGER NOT NULL,
        chatCyTime INTEGER NOT NULL,
        chatMsg TEXT NOT NULL,
        modflair INTEGER,
        flag INTEGER DEFAULT 0 NOT NULL,
        FOREIGN KEY(userId) REFERENCES CyUser(userId));""")

# Cy PM table
con.execute("""
        CREATE TABLE IF NOT EXISTS CyPm(
        chatId INTEGER PRIMARY KEY,
        userId INTEGER NOT NULL,
        pmTime INTEGER NOT NULL,
        pmCyTime INTEGER NOT NULL,
        pmMsg TEXT NOT NULL,
        flag INTEGER NOT NULL DEFAULT 0,
        FOREIGN KEY(userId) REFERENCES CyUser(userId));""")
        
# IRC Chat table
con.execute("""
        CREATE TABLE IF NOT EXISTS IrcChat(
        chatId INTEGER PRIMARY KEY,
        userId INTEGER NOT NULL,
        status INTEGER,
        chatTime INTEGER NOT NULL,
        chatMsg TEXT,
        flag INTEGER DEFAULT 0 NOT NULL,
        FOREIGN KEY(userId) REFERENCES IrcUser(userId));""")

# Song (VocaDB) table
con.execute("""
        CREATE TABLE IF NOT EXISTS Song(
        songId INTEGER PRIMARY KEY,
        data TEXT NOT NULL,
        lastUpdate INTEGER NOT NULL);""")

# Put a row for -1 and 0
# -1 is server (connection) error
# 0 is null/invalid response
try:
    con.execute('INSERT INTO Song VALUES (?, ?, ?)', (-1, 'connection error', 0))
    con.execute('INSERT INTO Song VALUES (?, ?, ?)', (0, 'null', 0))
except(IntegrityError):
    pass

# media table
con.execute("""
        CREATE TABLE IF NOT EXISTS Media(
        mediaId INTEGER PRIMARY KEY,
        type TEXT NOT NULL,
        id TEXT NOT NULL,
        dur INTEGER NOT NULL,
        title TEXT NOT NULL,
        by TEXT NOT NULL,
        flag INTEGER DEFAULT 0 NOT NULL,
        UNIQUE (type, id),
        FOREIGN KEY (by) REFERENCES CyUser(userId));""")

title = ('\xe3\x80\x90\xe7\xb5\x90\xe6\x9c\x88\xe3\x82\x86\xe3\x81\x8b\xe3'
         '\x82\x8a\xe3\x80\x91Mahou \xe9\xad\x94\xe6\xb3\x95\xe3\x80\x90\xe3'
         '\x82\xab\xe3\x83\x90\xe3\x83\xbc\xe3\x80\x91')
title = title.decode('utf-8')
try:
    con.execute("INSERT INTO media VALUES (?, ?, ?, ?, ?, ?, ?)",
           (None, 'yt', '01uN4MCsrCE', 248, title, 1, 0))
except(IntegrityError):
    pass
# like table
# mediaId column breaks normalization but it is very convenient for queries
con.execute("""
        CREATE TABLE IF NOT EXISTS Like(
        mediaId INTEGER NOT NULL,
        queueId INTEGER NOT NULL,
        userId INTEGER NOT NULL,
        time INTEGER NOT NULL,
        value INTEGER NOT NULL,
        UNIQUE (queueId, userId),
        FOREIGN KEY (mediaId) REFERENCES Media(mediaId),
        FOREIGN KEY (userId) REFERENCES CyUser(userId),
        FOREIGN KEY (queueId) REFERENCES Queue(queueId));""")

# MediaSong table
# A junction table between Media and Song. Although the relationship
# between Media and Song is Many-to-One, VocaDB data can get complex
# and separating it from Media could be useful later when modularizing
# the program, and usable for rooms that don't need the VocaDB feature.

con.execute("""
        CREATE TABLE IF NOT EXISTS MediaSong(
        mediaId INTEGER NOT NULL,
        songId INTEGER NOT NULL,
        userId INTEGER NOT NULL,
        time INTEGER NOT NULL,
        method  INTEGER NOT NULL,
        UNIQUE (mediaId),
        FOREIGN KEY (mediaId) REFERENCES Media(mediaId),
        FOREIGN KEY (songId) REFERENCES Song(songId),
        FOREIGN KEY (userId) REFERENCES CyUser(userId));""")

# queue table
con.execute("""
        CREATE TABLE IF NOT EXISTS Queue(
        queueId INTEGER PRIMARY KEY,
        mediaId INTEGER NOT NULL,
        userId INTEGER NOT NULL,
        time INTEGER NOT NULL,
        flag INTEGER DEFAULT 0 NOT NULL,
        FOREIGN KEY (userId) REFERENCES CyUser(userId),
        FOREIGN KEY (mediaId) REFERENCES media(mediaId));""")


# Usercount
con.execute("""
        CREATE TABLE IF NOT EXISTS Usercount(
        time INTEGER NOT NULL,
        usercount INTEGER NOT NULL,
        anoncount INTEGER NOT NULL)
        """)


con.execute("""
        CREATE TABLE IF NOT EXISTS CyProfile(
        profileId INTEGER PRIMARY KEY,
        text TEXT,
        imgUrl TEXT,
        flag INTEGER DEFAULT 0 NOT NULL);""")

con.execute("""
        CREATE TABLE IF NOT EXISTS CyAnnouncement(
        announceId INTEGER PRIMARY KEY,
        announceTime INTEGER NOT NULL,
        setBy TEXT,
        title TEXT,
        text TEXT);""")

con.commit()
print "Tables created."

con.close()
