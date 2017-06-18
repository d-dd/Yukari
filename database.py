import getpass
from twisted.internet import defer, reactor, task
from twisted.enterprise import adbapi
from tools import clog
#from psycopg2 import sql as psql
#from sqlite3 import OperationalError
sys = 'database'
_USERIDSQL = '(SELECT userId FROM CyUser WHERE nameLower=%s AND registered=%s)'
_MEDIASQL = '(SELECT mediaId FROM Media WHERE type=%s AND id=%s)'

#def turnOnFK(txn):
#    txn.execute('pragma foreign_keys=ON')

class NoRowException(Exception):
    pass

def operate(sql, binds, attempt=0):
    return dbpool.runOperation(sql, binds)
###
    d = task.deferLater(reactor, attempt * 1, dbpool.runOperation,  sql, binds)
    #d = task.deferLater(reactor, attempt * 1, raise_error, sql, binds)
    attempt += 1
    d.addErrback(retryDatabase, 'operate', sql, binds, attempt)
    return d

def query(sql, binds, attempt=0): 
    return dbpool.runQuery(sql, binds)
###
    d = task.deferLater(reactor, attempt * 1, dbpool.runQuery,  sql, binds)
    attempt += 1
    d.addErrback(retryDatabase, 'query', sql, binds, attempt)
    return d

def retryDatabase(error, operation, sql, binds, attempt):
    if attempt >= 5:
        clog.error(error.getBriefTraceback(), 
                'Reached max attempts: %s' % attempt)
        return
    clog.warning(error.getBriefTraceback(), 'retrying attempt: %s' % attempt)
    if operation == 'operate':
        return operate(sql, binds, attempt)
    elif operation == 'query':
        return query(sql, binds, attempt)


def dbQuery(columns, table, **kwargs):
    """
    A general function for building and executing a query statement.
    columns: SELECT, tuple of columns to return
    table: FROM table
    kwargs: WHERE columnName = value
    """
    sql = 'SELECT ' + ', '.join(columns) + ' FROM ' + table + ' WHERE '
    where, binds = [], []
    for key, value in kwargs.iteritems():
        where.append('%s=%%s' % key)
        binds.append(value)
    sql += ' AND '.join(where)
    binds = tuple(binds)
    return query(sql, binds)

def queryResult(res):
    """
    Returns single row (list) from a query. If None, returns NoRowException.
    """
    if not res:
        #clog.debug('(queryResult) No match found', sys)
        return defer.fail(NoRowException)
    else:
        #clog.debug('(queryResult) match found %s' % res, sys)
        return defer.succeed(res[0])

def queryMedia(mType, mId):
    clog.debug('(queryMedia) %s, %s)' % (mType, mId), sys)
    sql = 'SELECT type, id FROM Media WHERE type=%s AND id=%s'
    binds = (mType, mId)
    return query(sql, binds)

def insertMedia(ignored, mType, mId, dur, title, userId, flag):
    sql = "INSERT INTO Media VALUES (DEFAULT, %s, %s, %s, %s, %s, %s)"
    binds = (mType, mId, dur, title, userId, flag)
    return operate(sql, binds)

def _makeInsert(table, *args):
    sql = 'INSERT INTO %s VALUES (DEFAULT, ' + ('%%s,' * (len(args)-1)) + '%%s)'
    return sql % table, args

def dbInsertReturnLastRow(err, table, *args):
    #clog.debug('(dbInsertReturnLastRow) %s' % err, sys)
    return dbpool.runInteraction(_dbInsert, table, *args)

def _dbInsert(txn, table, *args):
    sql, args = _makeInsert(table, *args)
    #clog.debug('(_dbInsert) %s' % sql, sys)
    txn.execute(sql, args)
    return [txn.lastrowid]

def updateRow(table, setd, whered):
    sql = 'UPDATE ' + table + 'SET '
    set, where, binds = [], [], []
    for key, value in setd.iteritems():
        if key.endswith('+%s'):
            key = key[:-2]
            set.append('%s=%s+%%s' % (key, key))
        else:
            set.append('%s=%%s' % key)
        binds.append(value)
    sql += ','.join(set)
    sql += 'WHERE'
    sql += ','.join(where)
    return sql, tuple(binds)
    
def updateProfile(userId, profileText, profileImgUrl):
    sql = 'UPDATE CyUser SET profileText=%s, profileImgUrl=%s WHERE userId=%s'
    binds = (profileText, profileImgUrl, userId)
    return operate(sql, binds)

def bulkLogChat(table, chatList):
    return dbpool.runInteraction(_bulkLogChat, table, chatList)

def _bulkLogChat(txn, table, chatList):
    #TODO generalize
    sql = 'INSERT INTO %s VALUES (DEFAULT, %%s, %%s, %%s, %%s, %%s, %%s)' % table
   # print sql % chatList[0]
    txn.executemany(sql, chatList)

def insertChat(*args):
    sql = 'INSERT INTO CyChat VALUES(%s, %s, %s, %s, %s, %s, %s)'
    #return dbpool.runOperation(sql, args)
    return operate(sql, args)

def queryCyuser(nameLower, isRegistered):
    sql = 'SELECT userid FROM CyUser WHERE namelower=%s AND registered=%s'
    binds = (nameLower, isRegistered)
    return query(sql, binds)

def insertCyuser(nameLower, isRegistered, name, level, flag,
        profiletext, profileimgurl):
    sql = ('INSERT INTO CyUser VALUES(DEFAULT, %s, %s, %s, %s, %s, %s, %s) '
           'RETURNING userid')
    binds = (nameLower, isRegistered, name, level, flag, 
            profiletext, profileimgurl)
    return query(sql, binds)

def queryIrcuser(nickLower, username, host):
    sql = ('SELECT userid FROM ircuser WHERE nicklower=%s AND username=%s '
           'AND host=%s')
    binds = (nickLower, username, host)
    return query(sql, binds)

def insertIrcuser(nameLower, username, host, nick, flag):
    sql = ('INSERT INTO IrcUser VALUES(DEFAULT, %s, %s, %s, %s, %s) '
           'RETURNING userid')
    binds = (nameLower, username, host, nick, flag)
    return query(sql, binds)

def bulkLogMedia(playlist):
    return dbpool.runInteraction(_bulkLogMedia, playlist)

def _bulkLogMedia(txn, playlist):
    sql = ('INSERT INTO Media VALUES (DEFAULT, %s, %s, %s, %s, %s, %s) '
           ' ON CONFLICT (type,id) DO UPDATE SET '
           ' title=%s')
    clog.debug(sql, playlist)
    txn.executemany(sql, playlist)

def bulkLogMediaSong(playlist):
    return dbpool.runInteraction(_bulkLogMediaSong, playlist)

def _bulkLogMediaSong(txn, playlist):
    sql = 'INSERT OR IGNORE INTO Media VALUES ('

def insertQueueFromMedia(ignored, mType, mId, userId, timeNow, flag):
    sql = ('INSERT INTO Queue VALUES (DEFAULT, '
           '(SELECT mediaId FROM Media WHERE type=%s AND id=%s), '
           '%s, %s, %s) RETURNING queueid;')
    binds = (mType, mId, userId, timeNow, flag)
    # query because it returns an ID
    return query(sql, binds)

def insertQueue(mediaId, userId, timeNow, flag):
    return dbpool.runInteraction(_insertQueue, mediaId, userId, timeNow, flag)

def _insertQueue(txn, mediaId, userId, timeNow, flag):
    sql = 'INSERT INTO Queue VALUES (DEFAULT, %s, %s, %s, %s)'
    binds = (mediaId, userId, timeNow, flag)
    clog.debug('(insertQueue) binds: %s, %s, %s, %s' % 
               (mediaId, userId, timeNow, flag), sys)
    txn.execute(sql, binds)
    return [txn.lastrowid]

def queryMediaId(mType, mId):
    sql = 'SELECT mediaId FROM Media WHERE type=%s AND id=%s'
    binds = (mType, mId)
    return query(sql, binds)

def queryLastQueue(mType, mId):
    """ Return the last (most recent) queueId of a mediaId """
    sql = ('SELECT queueId FROM Queue WHERE mediaId = (SELECT mediaId FROM '
           'Media WHERE type=%s AND id=%s) ORDER BY queueId DESC LIMIT 1')
    binds = (mType, mId)
    return query(sql, binds)

def querySong(mType, mId):
    pass

def upsertSong(songId, data, timeNow):
    sql = ('INSERT INTO Song VALUES (%s, %s, %s) ON CONFLICT (songId) '
           'DO UPDATE SET songid=%s, data=%s, lastupdate=%s '
           'RETURNING songid')
    binds = (songId, data, timeNow) * 2
    return query(sql, binds).addCallback(returning)

def upsertMediaSong(songId, mType, mId, nameLower, registered, 
                                                timeNow, method):
    sql = ('INSERT INTO MediaSong VALUES ({}, %s, {}, %s, %s) '
           'ON CONFLICT (mediaid) DO UPDATE SET '
           'mediaid={}, songid=%s, userid={}, time=%s, method=%s'.format(
                   _MEDIASQL, _USERIDSQL, _MEDIASQL, _USERIDSQL))
    binds = (mType, mId, songId, nameLower, registered, timeNow, method) * 2
    return operate(sql, binds)

def insertSong(res, lastUpdate):
    if res == 0:
        clog.warning('(insertSong) VocaDB returned null. Skipping.', sys)
        return defer.succeed([0])
    return dbpool.runInteraction(_insertSong, res, lastUpdate)

def _insertSong(txn, res, lastUpdate):
    sql = ('INSERT INTO Song VALUES (%s, %s, %s) '
           'ON CONFLICT (songId) DO UPDATE SET songid=%s, data=%s, lastupdate=%s')
    data, songId = res
    binds = (songId, data, lastUpdate) * 2
    txn.execute(sql, binds)
    return [txn.lastrowid]

def insertMediaSong(res, mType, mId, songId, userId, timeNow, method):
    sql = ('INSERT INTO MediaSong VALUES'
           ' ((SELECT mediaId FROM Media WHERE type=%s AND id=%s), %s, %s, %s, %s) '
           'ON CONFLICT (mediaId) DO UPDATE SET '
           'mediaid=(SELECT mediaID FROM Media WHERE type=%s AND id=%s), '
           'songid=%s, userid=%s, time=%s, method=%s')
    binds = (mType, mId, songId, userId, timeNow, method) * 2
    return operate(sql, binds)
    
def insertMediaSongPv(songIdl, mType, mId, userId, timeNow):
    if songIdl:
        #clog.debug('(insertMediaSongPv)', sys)
        sql = ('INSERT INTO MediaSong VALUES'
             ' ((SELECT mediaId FROM Media WHERE type=%s AND id=%s), %s, %s, %s, %s) '
             'ON CONFLICT (mediaId) DO UPDATE SET '
              'mediaid=(SELECT mediaID FROM Media WHERE type=%s AND id=%s), '
              'songid=%s, userid=%s, time=%s, method=%s')
        binds = (mType, mId, songIdl[1], userId, timeNow, songIdl[0]) * 2
        #clog.debug('%s, %s' % (sql, binds), sys)
        return operate(sql, binds)

def queryMediaSongRow(mType, mId):
    clog.debug('(queryMediaSongData)', sys)
    sql = ('SELECT * FROM MediaSong WHERE mediaId ='
           ' (SELECT mediaId FROM Media WHERE type=%s AND id=%s)')
    binds = (mType, mId)
    return query(sql, binds)

def queryVocaDbInfo(mType, mId):
    clog.debug('(queryVocaDbInfo)', sys)
    sql = ('SELECT CyUser.nameOriginal, MediaSong.mediaId, Song.songId, '
           'MediaSong.method, Song.data FROM CyUser, MediaSong, Song WHERE '
           'MediaSong.songId=Song.songId AND CyUser.userId=MediaSong.userId '
           'AND MediaSong.mediaId = (SELECT mediaId FROM Media WHERE type=%s '
           'AND id=%s)')
    binds = (mType, mId)
    return query(sql, binds)
    
def getSongId(mType, mId):
    sql = ('SELECT songId FROM MediaSong WHERE mediaId = (SELECT mediaId '
            'FROM MEDIA WHERE type=%s AND id=%s)')
    binds = (mType, mId)
    return query(sql, binds)

def bulkQueryMediaSong(res, playlist):
    return dbpool.runInteraction(_bulkQueryMediaSong, playlist)

def _bulkQueryMediaSong(txn, playlist):
    clog.debug('(_queryBulkMediaSong)', sys)
    songlessMedia = []
    for media in playlist:
        sql = ('SELECT songId FROM MediaSong WHERE mediaId ='
               ' (SELECT mediaId FROM Media WHERE type=%s AND id=%s)')
        binds = (media[1], media[2])
        txn.execute(sql, binds)
        row = txn.fetchone()
        if not row:
            songlessMedia.append(binds)
    clog.info(songlessMedia, '[database] bulkquerymedia')
    return songlessMedia

# media flags
# 1<<0: invalid media
# 1<<1: omitted media
# 1<<2: blacklisted media

def getMediaFlag(mType, mId):
    sql = 'SELECT flag FROM media WHERE type=%s AND id=%s'
    binds = (mType, mId)
    return query(sql, binds)

def flagMedia(flag, mType, mId):
    clog.debug('Adding flag %s to %s, %s' % (bin(flag), mType, mId), sys)
    sql = 'UPDATE media SET flag=(flag|%s) WHERE type=%s AND id=%s'
    binds = (flag, mType, mId)
    return operate(sql, binds)
            
def unflagMedia(flag, mType, mId):
    clog.debug('Removing flag %s to %s, %s' % (bin(flag), mType, mId), sys)
    sql = 'UPDATE media SET flag=(flag&%s) WHERE type=%s AND id=%s'
    binds = (~flag, mType, mId)
    return operate(sql, binds)

def getUserFlag(nameLower, isRegistered):
    sql = 'SELECT flag FROM CyUser WHERE nameLower=%s AND registered=%s'
    binds = (nameLower, isRegistered)
    return query(sql, binds)

def flagUser(flag, nameLower, isRegistered):
    clog.debug('Adding flag %s to %s, %s'
               % (bin(flag), nameLower, isRegistered), sys)
    sql = 'UPDATE CyUser SET flag=(flag|%s) WHERE nameLower=%s AND registered=%s'
    binds = (flag, nameLower, isRegistered)
    return operate(sql, binds)
            
def unflagUser(flag, nameLower, isRegistered):
    clog.debug('Removing flag %s to %s, %s'
               % (bin(flag), nameLower, isRegistered), sys)
    sql = 'UPDATE CyUser SET flag=(flag|%s) WHERE nameLower=%s AND registered=%s'
    binds = (~flag, nameLower, isRegistered)
    return operate(sql, binds)

def insertReplaceLike(mediaId, queueId, userId, timeNow, value):
    sql = ('INSERT INTO Liked VALUES (%s, %s, %s, %s, %s) '
           'ON CONFLICT (queueId, userId) DO UPDATE SET value=%s')
    binds = (mediaId, queueId, userId, timeNow, value, value)
    return operate(sql, binds)

def getLikes(queueId):
    sql = ('SELECT nameOriginal, liked.value FROM CyUser JOIN Liked ON '
          'CyUser.userId = Liked.userId WHERE Liked.queueId=%s')
    binds = (queueId,) 
    return query(sql, binds)

def calcUserPoints(res, nameLower, isRegistered):
    sql = ('SELECT (SELECT (SELECT COUNT(*) FROM Media WHERE by = %s AND '
           'flag IN (0,1)) * 20) + (SELECT (SELECT COUNT(*) FROM Queue JOIN '
           'Media on Queue.mediaId = Media.mediaId WHERE Media.flag = 0 AND '
           'Queue.userId = %s) * 3)' % ((_USERIDSQL,) * 2))
    binds = (nameLower, isRegistered) * 2
    return query(sql, binds)

def calcAccessTime(res, nameLower, isRegistered):
    # seconds * 0.002
    sql = ("SELECT EXTRACT('epoch' FROM (SELECT SUM(leave-enter) FROM "
           "Userinout WHERE userid={})) * 0.002".format(_USERIDSQL))
 #   sql = ('SELECT (SELECT (SELECT SUM(leave) FROM userinout WHERE userid=%s)'
 #          '- (SELECT SUM(enter) FROM userinout WHERE userid = %s)) * 0.00002'
 #       % ((_USERIDSQL,) * 2))
    binds = (nameLower, isRegistered)
    return query(sql, binds)

#def addByUserQueue(sample, nameLower, registered, words, limit, isRecent):
def addMedia(sample, nameLower, registered, words, limit, isRecent):
    """selects up to n (limit) random non-flagged media that was ever
       queued by registered user (nameLower)"""
    limit = max(0, limit)
    binds, sql = [], []
    # only Youtube
    providers = "('yt')"
    if nameLower and sample == 'q':
        name = ('AND Queue.userId = %s' % _USERIDSQL)
        binds.extend((nameLower, int(registered)))
    elif nameLower and sample == 'a':
        name = ('AND by = %s' % _USERIDSQL)
        binds.extend((nameLower, int(registered)))
    elif nameLower and sample == 'l':
        name = ('AND Liked.userId = %s' % _USERIDSQL)
        binds.extend((nameLower, int(registered)))
    else:
        name = ''
    if words:
        title = 'AND Media.title LIKED %s '
        binds.append('%%%s%%' % words) # %% is escaped %
    else:
        title = ''
    if not isRecent: # by default exclude last 200 queued media from pool
        recent = ('AND Media.mediaId NOT IN (SELECT mediaId FROM Queue '
                'ORDER BY queueId DESC LIMIT 5)')
    else:
        recent = ''
    if sample == 'q':
        sql = ('SELECT type, id FROM Media WHERE type IN {} AND mediaId IN '
               '(SELECT DISTINCT Media.mediaId FROM Media, Queue WHERE '
               'Media.mediaId = Queue.mediaId AND Media.flag=0 {} {} {} '
               ')ORDER BY RANDOM() LIMIT %s'.format(providers, name, title, recent))
    elif sample == 'a':
        sql = ('SELECT type, id FROM Media WHERE type IN %s AND flag=0 %s %s %s'
              'ORDER BY RANDOM() LIMIT %s'.format(providers, name, title, recent))
    elif sample == 'l':
        sql = ('SELECT type, id FROM Media CROSS JOIN Liked ON Media.mediaId '
               '=Liked.mediaId GROUP BY Media.mediaId HAVING type IN {} AND '
               'value=1 {} {} {} ORDER BY RANDOM() LIMIT %s'.format(
               providers, name, title, recent))

    binds.append(limit)
    binds = tuple(binds)
    clog.info(sql, 'sql')
    clog.info(binds, 'sql')
    return query(sql, binds)

def getMediaById(mediaId):
    sql = 'SELECT * FROM Media WHERE mediaId=%s'
    return query(sql, (mediaId,))

def getMediaByTypeId(mType, mId):
    sql = 'SELECT * FROM Media WHERE type=%s and id=%s'
    binds = (mType, mId)
    return query(sql, binds)

def getMediaByIdRange(fromId, limit):
    sql = 'SELECT * FROM Media LIMIT %s, %s'
    return query(sql, (fromId, limit))

def getMediaLastRowId():
    sql = 'SELECT COUNT(*) FROM Media'
    return query(sql, tuple())

def getUserlistQueue(mediaId):
    sql = ('SELECT DISTINCT CyUser.nameOriginal FROM CyUser JOIN Queue ON '
           'CyUser.userId = Queue.userId WHERE Queue.mediaId=%s')
    return query(sql, (mediaId,))

def getUserAdd(mediaId):
    sql = ('SELECT CyUser.nameOriginal FROM CyUser JOIN Media ON '
           'CyUser.userId = Media.by WHERE Media.mediaId=%s')
    return query(sql, (mediaId,))

def getUserProfile(nameLower, isRegistered):
    sql = ('SELECT nameOriginal, profileText, profileImgUrl FROM CyUser '
           'WHERE nameLower=%s AND registered=%s')
    binds = (nameLower, isRegistered)
    return query(sql, binds)

def getUserTotalTime(nameLower, isRegistered):
    # sum of time left - sum of time entered = total access time
    sql = ('SELECT (SELECT (SELECT SUM(leave) FROM userinout WHERE userid = '
           '%s) - (SELECT SUM(enter) FROM UserInOut WHERE userId = %s))' 
           % (_USERIDSQL, _USERIDSQL))
    binds = (nameLower, isRegistered) * 2
    return query(sql, binds)

def getUserFirstSeen(nameLower, isRegistered):
    sql = ('SELECT enter FROM UserInOut WHERE userId = %s'
           ' ORDER BY enter ASC LIMIT 1' % _USERIDSQL)
    binds = (nameLower, isRegistered)
    return query(sql, binds)

def getUserLastSeen(nameLower, isRegistered):
    sql = ('SELECT leave FROM UserInOut WHERE userId = %s'
           ' ORDER BY leave DESC LIMIT 1' % _USERIDSQL)
    binds = (nameLower, isRegistered)
    return query(sql, binds)

def getUserQueueSum(nameLower, isRegistered):
    """ Queries the total number of queues by specified user """
    sql = 'SELECT COUNT(userId) FROM Queue WHERE userId= %s' % _USERIDSQL
    binds = (nameLower, isRegistered) 
    return query(sql, binds)

def getUserAddSum(nameLower, isRegistered):
    """ Queries the total number of adds by specified user """
    sql = 'SELECT COUNT(by) FROM Media WHERE by=%s' % _USERIDSQL
    binds = (nameLower, isRegistered) 
    return query(sql, binds)

def getUserLikesReceivedSum(nameLower, isRegistered, value):
    """ Queries the total number of Likes the user's queues received 
        For a list of those queues, use #####TODO """
    sql = ('SELECT COUNT(*) FROM (SELECT Queue.queueId, Liked.userId '
           'FROM Queue JOIN Liked ON Queue.queueId = Liked.queueId WHERE '
           'Queue.userId = {} AND Liked.value=%s) AS foo'.format(_USERIDSQL))
    binds = (nameLower, isRegistered, value)
    return query(sql, binds)

def getUserLikedSum(nameLower, isRegistered, value):
    sql = 'SELECT COUNT(*) FROM LIKED WHERE userId={} AND value=%s'.format(
            _USERIDSQL)
    binds = (nameLower, isRegistered, value)
    return query(sql, binds)

def getUserRecentQueues(nameLower, isRegistered, limit):
    limit = min(limit, 100)
    # We use ORDER BY queueId to retrieve the most recent queues.
    # Because database inserts are asynchronous, this query does not
    # guarantee that they are ordered correctly. However, it is
    # close enough for our purposes, and using the primary key is
    # orders of magnitude faster than sorting by the time column.
    sql = ('SELECT * FROM Media, QUEUE '
           'WHERE Media.mediaId = Queue.mediaId AND Queue.userId = %s '
           'ORDERY BY Queue.queueId DESC LIMIT %s' % _USERIDSQL)
    binds = (nameLower, isRegistered, limit)
    return query(sql, binds)

def getUserRecentAdds(nameLower, isRegistered, limit):
    limit = min(limit, 100)
    sql = ('SELECT * FROM Media, QUEUE '
           'WHERE Media.mediaId = Queue.mediaId AND Queue.userId = %s '
           'ORDERY BY Queue.queueId DESC LIMIT %s' % _USERIDSQL)
    binds = (nameLower, isRegistered, limit)
    return query(sql, binds)

def getChannelPopularMedia(limit, direction):
    limit = min(limit, 100)
    if direction == 'up':
        _sub = ('>', 'DESC')
    else:
        _sub = ('<', 'ASC')
    sql = ('SELECT * FROM (SELECT Queue.mediaId AS mid, '
           'SUM(Liked.value) AS agg FROM Queue INNER JOIN Liked ON Queue.queueId '
           '= Liked.queueId WHERE Queue.queueId IN (SELECT queueId FROM Liked) '
           'GROUP BY Queue.MediaId HAVING agg %s 0 ORDER BY agg %s LIMIT %s) '
           'JOIN Media ON Media.mediaId = mid' % _sub)
    binds = (limit,)
    # mid|agg|mediaId|type|id|dur|title|by|flag
    return query(sql, binds)

def getUserlist():
    sql = ('SELECT nameOriginal, registered, profileText, profileImgUrl '
            'FROM CyUser')
    return query(sql, tuple())

def insertUsercount(timeNow, usercount, anoncount):
    sql = 'INSERT INTO Usercount VALUES (%s, %s, %s)'
    binds = (timeNow, usercount, anoncount)
    return operate(sql, binds)

def insertUserInOut(userId, enterTime, leaveTime):
    sql = 'INSERT INTO UserInOut VALUES (%s, %s, %s, %s)'
    binds = (userId, enterTime, leaveTime, 0)
    return operate(sql, binds)

def insertPm(userId, pmTime, pmCyTime, msg, flag):
    sql = 'INSERT INTO CyPM VALUES (DEFAULT, %s, %s, %s, %s, %s)'
    binds = (userId, pmTime, pmCyTime, msg, flag)
    return operate(sql, binds)

def getCurrentAndMaxProfileId():
    sql = ('SELECT profileId FROM CyProfile WHERE flag=1 UNION ALL '
           'SELECT MAX(profileId) FROM CyProfile')
    return query(sql, tuple())

def getProfile(profileId):
    sql = 'SELECT profileId, text, imgUrl FROM CyProfile WHERE profileId=%s'
    return query(sql, (profileId,))

def setProfileFlag(profileId, flag):
    sql = 'UPDATE CyProfile SET flag=%s WHERE profileId=%s'
    return operate(sql, (flag, profileId))

def insertAnnouncement(setBy, title, text, timeNow):
    sql = 'INSERT INTO CyAnnouncement VALUES (DEFAULT, %s, %s, %s, %s)'
    binds = (timeNow, setBy, title, text)
    return operate(sql, binds)

def getLastAnnouncement():
    sql = 'SELECT * FROM CyAnnouncement ORDER BY announceId DESC LIMIT 1'
    return query(sql, tuple())

def countRecentQueuesSince(mediaType, mediaId, sinceTime):
    sql = ('SELECT COUNT(*) FROM Queue WHERE mediaId= '
           '(SELECT mediaId FROM Media WHERE type=%s AND id=%s) '
           'AND time > %s')
    binds = (mediaType, mediaId, sinceTime)
    return query(sql, binds)




#####
def getVocadbData(mType, mId):
    sql = ("SELECT data FROM Song WHERE songid="
           "(SELECT songid FROM Mediasong WHERE mediaid="
           "(SELECT mediaid FROM Media WHERE type=%s AND id=%s))")
    binds = (mType, mId)
    return query(sql, binds)

def getVocadbBySongId(songId):
    sql = "SELECT data FROM Song WHERE songid=%s"
    binds = (songId,)
    return query(sql, binds)

def returning(result):
    try:
        return result[0][0]
    except(IndexError, TypeError):
        return




user = getpass.getuser()
dbpool= adbapi.ConnectionPool('psycopg2', 'dbname=yukdb user={}'.format(user),
                      #         check_same_thread=False,
                               cp_max=1) # one thread max; avoids db locks
#dbpool.runInteraction(turnOnFK)
