""" Creates the initial tables required for operation."""
import getpass
import json

import psycopg2
import time
from tools import getTime
from conf import config
from psycopg2 import IntegrityError

user = getpass.getuser()
now = getTime()

#host = config['Database']['host']
dbname = config['Database']['dbname']
user = config['Database']['user']
#password = config['Database']['password']

con = psycopg2.connect('dbname={} user={}'.format(
                            dbname, user))
cur = con.cursor()

ircNick = config['irc']['nick']
cyName = config['Cytube']['username']

#con.execute("DROP TABLE CyUser")
# CyUser table
cur.execute("""
        CREATE TABLE IF NOT EXISTS CyUser(
        userId SERIAL PRIMARY KEY,
        nameLower TEXT NOT NULL,
        registered boolean NOT NULL,
        nameOriginal TEXT NOT NULL,
        level INTEGER NOT NULL DEFAULT 0,
        flag INTEGER NOT NULL DEFAULT 0,
        profileText TEXT,
        profileImgUrl TEXT,
        UNIQUE (nameLower, registered));""")
con.commit()

# User in/out
cur.execute("""
        CREATE TABLE IF NOT EXISTS UserInOut(
        userId INTEGER NOT NULL,
        enter TIMESTAMPTZ NOT NULL,
        leave TIMESTAMPTZ NOT NULL,
        flag INTEGER DEFAULT 0 NOT NULL,
        FOREIGN KEY(userId) REFERENCES CyUser(userId));""")

# IRC User table
cur.execute("""
        CREATE TABLE IF NOT EXISTS IrcUser(
        userId SERIAL PRIMARY KEY,
        nickLower TEXT NOT NULL,
        username TEXT NOT NULL,
        host TEXT NOT NULL,
        nickOriginal TEXT NOT NULL,
        flag INTEGER NOT NULL DEFAULT 0,
        UNIQUE (nickLower, username, host));""")

# Cy Chat table
cur.execute("""
        CREATE TABLE IF NOT EXISTS CyChat(
        chatId SERIAL PRIMARY KEY,
        userId INTEGER NOT NULL,
        chatTime TIMESTAMPTZ NOT NULL,
        chatCyTime BIGINT NOT NULL,
        chatMsg TEXT NOT NULL,
        modflair INTEGER,
        flag INTEGER DEFAULT 0 NOT NULL,
        FOREIGN KEY(userId) REFERENCES CyUser(userId));""")

# Cy PM table
cur.execute("""
        CREATE TABLE IF NOT EXISTS CyPm(
        chatId SERIAL PRIMARY KEY,
        userId INTEGER NOT NULL,
        pmTime TIMESTAMPTZ NOT NULL,
        pmCyTime BIGINT NOT NULL,
        pmMsg TEXT NOT NULL,
        flag INTEGER NOT NULL DEFAULT 0,
        FOREIGN KEY(userId) REFERENCES CyUser(userId));""")
        
# IRC Chat table
cur.execute("""
        CREATE TABLE IF NOT EXISTS IrcChat(
        chatId SERIAL PRIMARY KEY,
        userId INTEGER NOT NULL,
        status INTEGER,
        chatTime TIMESTAMPTZ NOT NULL,
        chatMsg TEXT,
        flag INTEGER DEFAULT 0 NOT NULL,
        FOREIGN KEY(userId) REFERENCES IrcUser(userId));""")

# Song (VocaDB) table
cur.execute("""
        CREATE TABLE IF NOT EXISTS Song(
        songId INTEGER PRIMARY KEY,
        data JSONB NOT NULL,
        lastUpdate TIMESTAMPTZ NOT NULL);""")


# media table
cur.execute("""
        CREATE TABLE IF NOT EXISTS Media(
        mediaId SERIAL PRIMARY KEY,
        type TEXT NOT NULL,
        id TEXT NOT NULL,
        dur INTEGER NOT NULL,
        title TEXT NOT NULL,
        by INTEGER NOT NULL,
        flag INTEGER DEFAULT 0 NOT NULL,
        UNIQUE (type, id),
        FOREIGN KEY (by) REFERENCES CyUser(userId));""")
con.commit()



# queue table
cur.execute("""
        CREATE TABLE IF NOT EXISTS Queue(
        queueId SERIAL PRIMARY KEY,
        mediaId INTEGER NOT NULL,
        userId INTEGER NOT NULL,
        time TIMESTAMPTZ NOT NULL,
        flag INTEGER DEFAULT 0 NOT NULL,
        FOREIGN KEY (userId) REFERENCES CyUser(userId),
        FOREIGN KEY (mediaId) REFERENCES Media(mediaId));""")

# like table
# mediaId column breaks normalization but it is very convenient for queries
cur.execute("""
        CREATE TABLE IF NOT EXISTS Liked(
        mediaId INTEGER NOT NULL,
        queueId INTEGER NOT NULL,
        userId INTEGER NOT NULL,
        time TIMESTAMPTZ NOT NULL,
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

cur.execute("""
        CREATE TABLE IF NOT EXISTS MediaSong(
        mediaId INTEGER NOT NULL,
        songId INTEGER NOT NULL,
        userId INTEGER NOT NULL,
        time TIMESTAMPTZ NOT NULL,
        method  INTEGER NOT NULL,
        UNIQUE (mediaId),
        FOREIGN KEY (mediaId) REFERENCES Media(mediaId),
        FOREIGN KEY (songId) REFERENCES Song(songId),
        FOREIGN KEY (userId) REFERENCES CyUser(userId));""")
# Usercount
cur.execute("""
        CREATE TABLE IF NOT EXISTS Usercount(
        time TIMESTAMPTZ NOT NULL,
        usercount INTEGER NOT NULL,
        anoncount INTEGER NOT NULL)
        """)


cur.execute("""
        CREATE TABLE IF NOT EXISTS CyProfile(
        profileId SERIAL PRIMARY KEY,
        text TEXT,
        imgUrl TEXT,
        flag INTEGER DEFAULT 0 NOT NULL);""")

cur.execute("""
        CREATE TABLE IF NOT EXISTS CyAnnouncement(
        announceId SERIAL PRIMARY KEY,
        announceTime TIMESTAMPTZ NOT NULL,
        setBy TEXT,
        title TEXT,
        text TEXT);""")

cur.execute("""
        CREATE TABLE IF NOT EXISTS DiscordMsg(
        msg_id BIGINT NOT NULL,
        user_id BIGINT NOT NULL,
        channel_id BIGINT NOT NULL,
        timestamp TIMESTAMPTZ NOT NULL,
        data JSONB NOT NULL,
        deleted boolean NOT NULL,
        UNIQUE (msg_id)
        );""")

con.commit()
print "Tables created."

def insertDefaults():
    try:
        cur.execute("INSERT INTO CyUser VALUES (default, %s, %s, %s, %s, %s, %s, %s)",
                (cyName.lower(), True, cyName, 3, 1, None, None))
        cur.execute("INSERT INTO CyUser VALUES (default, %s, %s, %s, %s, %s, %s, %s)",
                ('[server]', True, '[server]', 0, 2, None, None))
        cur.execute("INSERT INTO CyUser VALUES (default, %s, %s, %s, %s, %s, %s, %s)",
                ('[anonymous]', True, '[anonymous]', 0, 4, None, None))
        con.commit()
    except IntegrityError as e:
        print e
        print "IntegrityError 1"
        con.rollback()

    try:
        cur.execute("INSERT INTO IrcUser VALUES (default, %s, %s, %s, %s, %s)",
                    (ircNick.lower(), 'cybot', 'Yuka.rin.rin', ircNick, 1))
        con.commit()
    except IntegrityError as e:
        print e
        print "IntegrityError 2"
        con.rollback()

    # Put a row for -1 and 0
    # -1 is server (connection) error
    # 0 is null/invalid response
    err = json.dumps({'error': 'connection error'})
    nul = json.dumps({'null': None})
    try:
        pass
        cur.execute('INSERT INTO Song VALUES (%s, %s, %s)', (-1, err, now))
        nomatch = {'data': 'no match'}
        cur.execute('INSERT INTO Song VALUES (%s, %s, %s)', (0, json.dumps(nomatch), now))
        con.commit()
    except IntegrityError as e:
        print e
        print "IntegrityError 3"
        con.rollback()

    title = ('\xe3\x80\x90\xe7\xb5\x90\xe6\x9c\x88\xe3\x82\x86\xe3\x81\x8b\xe3'
             '\x82\x8a\xe3\x80\x91Mahou \xe9\xad\x94\xe6\xb3\x95\xe3\x80\x90\xe3'
             '\x82\xab\xe3\x83\x90\xe3\x83\xbc\xe3\x80\x91')
    title = title.decode('utf-8')
    try:
        pass
        cur.execute("INSERT INTO media VALUES (default, %s, %s, %s, %s, %s, %s)",
               ('yt', '01uN4MCsrCE', 248, title, 1, 0))
        con.commit()
    except IntegrityError as e:
        print e
        print "IntegrityError 4"
        con.rollback()

#insertDefaults()
cur.close()
con.close()
