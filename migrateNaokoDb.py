"""Migrates Media data from CyNaoko's database to Yukari's"""
# Add by : All Yukari
# Queue by : All Yukari


import sqlite3, time
from conf import config
from sqlite3 import IntegrityError
conY = sqlite3.connect('data.db')
curY = conY.cursor()
conN = sqlite3.connect('naoko.db')
curN = conN.cursor()
timeNow = int(time.time()*100)

cyName = config['Cytube']['username']
sql = ('SELECT userId FROM CyUser WHERE nameLower=? AND registered=1')
binds = (cyName.lower(),)
curY.execute(sql, binds)
cyId = curY.fetchone()[0]
print cyId

sql = ('SELECT type, id, duration_ms, title, flags FROM videos')
In = 'INSERT INTO Media VALUES (?, ?, ?, ?, ?, ?, ?)'
for row in curN.execute(sql):
    mType = row[0]
    mId = row[1]
    dur = row[2]/1000
    title = row[3]
    flag = row[4]
    InBinds = (None, mType, mId, dur, title, cyId, flag)
    conY.execute(In, InBinds)
conY.commit()

sql = 'SELECT * FROM Media'
In = 'INSERT INTO Queue VALUES (?, ?, ?, ?, ?)'
for row in curY.execute(sql):
    mediaId = row[0]
    binds = (None, mediaId, cyId, timeNow, 4)
    conY.execute(In, binds)
conY.commit()
