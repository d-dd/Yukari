"""
Migrate Yukari's SQLite database to Postgres database
June 2017-ish

Reads settings.cfg

"""
import json
import time
from datetime import datetime

import psycopg2
from psycopg2 import IntegrityError

import sqlite3

from conf import config

#host = config['Database']['host']
dbname = config['Database']['dbname']
user = config['Database']['user']
#password = config['Database']['password']

pgcon = psycopg2.connect('dbname={} user={}'.format(
                            dbname, user))

pgcur = pgcon.cursor()

sqcon = sqlite3.connect('data.db')
sqcur = sqcon.cursor()

def migrateCyuser():
    sql = 'SELECT * FROM CyUser ORDER BY userid'
    insert = 'INSERT INTO CyUser VALUES(' + ', '.join(['%s']*8) + ');'
    for row in sqcur.execute(sql):
        row = list(row)
        row[2] = True if row[2] else False
        pgcur.execute(insert, row)
    pgcon.commit()
    print "migrated cyuser"

def migrateCyannouncement():
    sql = 'SELECT * FROM CyAnnouncement ORDER BY announceid'
    insert ='INSERT INTO CyAnnouncement VALUES(' + ', '.join(['%s']*5) + ');'
    for row in sqcur.execute(sql):
        row = list(row)
        row[1] = datetime.utcfromtimestamp(row[1]/100.00)
        pgcur.execute(insert, row)
    pgcon.commit()
    print "migrated cyannouncement"

def migrateCychat():
    sql = 'SELECT * FROM CyChat ORDER BY chatid'
    insert ='INSERT INTO Cychat VALUES(' + ', '.join(['%s']*7) + ');'
    for row in sqcur.execute(sql):
        row = list(row)
        row[2] = datetime.fromtimestamp(row[2]/100.00)
        pgcur.execute(insert, row)
    pgcon.commit()
    print "migrated cychat"

def migrateCypm():
    sql = 'SELECT * FROM CyPM ORDER BY chatid'
    insert ='INSERT INTO Cypm VALUES(' + ', '.join(['%s']*6) + ');'
    for row in sqcur.execute(sql):
        row = list(row)
        row[2] = datetime.fromtimestamp(row[2]/100.00)
        pgcur.execute(insert, row)
    pgcon.commit()
    print "migrated cypm"

def migrateCyprofile():
    sql = 'SELECT * FROM Cyprofile ORDER BY profileid'
    insert ='INSERT INTO Cyprofile VALUES(' + ', '.join(['%s']*4) + ');'
    for row in sqcur.execute(sql):
        pgcur.execute(insert, row)
    pgcon.commit()
    print "migrated Cyuser"

def migrateIrcuser():
    sql = 'SELECT * FROM Ircuser ORDER BY userid'
    insert ='INSERT INTO Ircuser VALUES(' + ', '.join(['%s']*6) + ');'
    for row in sqcur.execute(sql):
        pgcur.execute(insert, row)
    pgcon.commit()
    print "migrated Ircuser"

def migrateIrcchat():
    sql = 'SELECT * FROM Ircchat ORDER BY chatid'
    insert ='INSERT INTO Ircchat VALUES(' + ', '.join(['%s']*6) + ');'
    for row in sqcur.execute(sql):
        row = list(row)
        row[3] = datetime.fromtimestamp(row[3]/100.00)
        pgcur.execute(insert, row)
    pgcon.commit()
    print "migrated Ircchat"

def migrateMedia():
    sql = 'SELECT * FROM Media ORDER BY mediaid'
    insert ='INSERT INTO Media VALUES(' + ', '.join(['%s']*7) + ');'
    for row in sqcur.execute(sql):
        pgcur.execute(insert, row)
    pgcon.commit()
    print "migrated Media"

def migrateQueue():
    sql = 'SELECT * FROM Queue ORDER BY queueId'
    insert ='INSERT INTO Queue VALUES(' + ', '.join(['%s']*5) + ');'
    for row in sqcur.execute(sql):
        row = list(row)
        row[3] = datetime.fromtimestamp(row[3]/100.00)
        pgcur.execute(insert, row)
    pgcon.commit()
    print "migrated Queue"

def migrateLike():
    sql = 'SELECT * FROM Like ORDER BY queueId'
    insert ='INSERT INTO Liked VALUES(' + ', '.join(['%s']*5) + ');'
    for row in sqcur.execute(sql):
        row = list(row)
        row[3] = datetime.fromtimestamp(row[3]/100.00)
        pgcur.execute(insert, row)
    pgcon.commit()
    print "migrated Like"

def migrateSong():
    sql = 'SELECT * FROM Song'
    insert ='INSERT INTO Song VALUES(' + ', '.join(['%s']*3) + ');'
    for row in sqcur.execute(sql):
        row = list(row)
        if row[0] == -1:
            row[1] = json.dumps({'error': 'connection error'})
        elif row[0] == 0:
            row[1] = json.dumps({'data': 'no match'})
        row[2] = datetime.fromtimestamp(row[2]/100.00)
        pgcur.execute(insert, row)
    pgcon.commit()
    print "migrated song"

def migrateMediasong():
    sql = 'SELECT * FROM MediaSong'
    insert ='INSERT INTO MediaSong VALUES(' + ', '.join(['%s']*5) + ');'
    for row in sqcur.execute(sql):
        row = list(row)
        row[3] = datetime.fromtimestamp(row[3]/100.00)
        pgcur.execute(insert, row)
    pgcon.commit()
    print "migrated mediasong"

def migrateUserinout():
    sql = 'SELECT * FROM Userinout'
    insert ='INSERT INTO Userinout VALUES(' + ', '.join(['%s']*4) + ');'
    for row in sqcur.execute(sql):
        row = list(row)
        row[1] = datetime.fromtimestamp(row[1]/100.00)
        row[2] = datetime.fromtimestamp(row[2]/100.00)
        pgcur.execute(insert, row)
    pgcon.commit()
    print "migrated userinout"

def migrateUsercount():
    sql = 'SELECT * FROM usercount'
    insert ='INSERT INTO usercount VALUES(' + ', '.join(['%s']*3) + ');'
    for row in sqcur.execute(sql):
        row = list(row)
        row[0] = datetime.fromtimestamp(row[0]/100.00)
        pgcur.execute(insert, row)
    pgcon.commit()
    print "migrated usercount"

def setSerial():
    serials = [  ('cyuser', 'userid'),
                 ('ircuser', 'userid'),
                 ('cychat', 'chatid'),
                 ('cypm', 'chatid'),
                 ('ircchat', 'chatid'),
                 ('media', 'mediaid'),
                 ('queue', 'queueid'),
                 ('cyprofile', 'profileid'),
                 ('cyannouncement', 'announceid'),
               ]

    for t in serials:
        sql = ("SELECT pg_catalog.setval(pg_get_serial_sequence('{}', '{}'), "
              "(SELECT MAX({}) FROM {})+1);").format(t[0], t[1], t[1], t[0])
        print sql
        pgcur.execute(sql)
    pgcon.commit()

#migrateCyuser()
#migrateCyannouncement()
#migrateCychat()
#migrateCyprofile()
#migrateIrcuser()
#migrateIrcchat()
#migrateMedia()
#migrateQueue()
#migrateLike()
#migrateSong()
#migrateMediasong()
#migrateUsercount()
#migrateUserinout()
migrateCypm()

setSerial()


pgcur.close()
pgcon.close()
sqcur.close()
sqcon.close()

