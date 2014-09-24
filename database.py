from twisted.internet import defer
from twisted.enterprise import adbapi
from tools import clog
sys = 'database'
_USERIDSQL = '(SELECT userId FROM CyUser WHERE nameLower=? AND registered=?)'

def turnOnFK(txn):
    txn.execute('pragma foreign_keys=ON')

class NoRowException(Exception):
    pass

def operate(sql, binds):
    return dbpool.runOperation(sql, binds)

def query(sql, binds):
    return dbpool.runQuery(sql, binds)

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
        where.append('%s=?' % key)
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

def _makeInsert(table, *args):
    sql = 'INSERT INTO %s VALUES (' + ('?,' * (len(args)-1)) + '?)'
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
        if key.endswith('+?'):
            key = key[:-2]
            set.append('%s=%s+?' % (key, key))
        else:
            set.append('%s=?' % key)
        binds.append(value)
    sql += ','.join(set)
    sql += 'WHERE'
    sql += ','.join(where)
    return sql, tuple(binds)
    
def updateProfile(userId, profileText, profileImgUrl):
    sql = 'UPDATE CyUser SET profileText=?, profileImgUrl=? WHERE userId=?'
    binds = (profileText, profileImgUrl, userId)
    return operate(sql, binds)

def bulkLogChat(table, chatList):
    return dbpool.runInteraction(_bulkLogChat, table, chatList)

def _bulkLogChat(txn, table, chatList):
    #TODO generalize
    sql = 'INSERT INTO %s VALUES (?, ?, ?, ?, ?, ?, ?)' % table
    txn.executemany(sql, chatList)

def insertChat(*args):
    sql = 'INSERT INTO CyChat VALUES(?, ?, ?, ?, ?, ?, ?)'
    return dbpool.runOperation(sql, args)

def bulkLogMedia(playlist):
    return dbpool.runInteraction(_bulkLogMedia, playlist)

def _bulkLogMedia(txn, playlist):
    sql = 'INSERT OR IGNORE INTO Media VALUES (?, ?, ?, ?, ?, ?, ?)'
    txn.executemany(sql, playlist)

def bulkLogMediaSong(playlist):
    return dbpool.runInteraction(_bulkLogMediaSong, playlist)

def _bulkLogMediaSong(txn, playlist):
    sql = 'INSERT OR IGNORE INTO Media VALUES ('

def insertMedia(media):
    return dbpool.runInteraction(_insertMedia, media)

def _insertMedia(txn, media):
    sql = ('INSERT OR IGNORE INTO Media VALUES (?, ?, ?, ?, ?, ?, ?);'
           'UPDATE Media SET mediaId=mediaId WHERE type=? AND id=?')
    txn.executemany(sql, media)
    return [txn.lastrowid]

def insertQueue(mediaId, userId, timeNow, flag):
    return dbpool.runInteraction(_insertQueue, mediaId, userId, timeNow, flag)

def _insertQueue(txn, mediaId, userId, timeNow, flag):
    sql = 'INSERT INTO Queue VALUES (?, ?, ?, ?, ?)'
    binds = (None, mediaId, userId, timeNow, flag)
    clog.debug('(insertQueue) binds: %s, %s, %s, %s' % 
               (mediaId, userId, timeNow, flag), sys)
    txn.execute(sql, binds)
    return [txn.lastrowid]

def queryMediaId(mType, mId):
    sql = 'SELECT mediaId FROM Media WHERE type=? AND id=?'
    binds = (mType, mId)
    return query(sql, binds)

def queryLastQueue(mType, mId):
    """ Return the last (most recent) queueId of a mediaId """
    sql = ('SELECT queueId FROM Queue WHERE mediaId = (SELECT mediaId FROM '
           'Media WHERE type=? AND id=?) ORDER BY queueId DESC LIMIT 1')
    binds = (mType, mId)
    return query(sql, binds)

def insertSong(res, lastUpdate):
    if res == 0:
        clog.warning('(insertSong) VocaDB returned null. Skipping.', sys)
        return defer.succeed([0])
    return dbpool.runInteraction(_insertSong, res, lastUpdate)

def _insertSong(txn, res, lastUpdate):
    sql = 'INSERT OR REPLACE INTO Song VALUES (?, ?, ?)'
    data, songId = res
    binds = (songId, data, lastUpdate)
    txn.execute(sql, binds)
    return [txn.lastrowid]

def insertMediaSong(res, mType, mId, songId, userId, timeNow, method):
    sql = ('INSERT OR REPLACE INTO MediaSong VALUES'
           ' ((SELECT mediaId FROM Media WHERE type=? AND id=?), ?, ?, ?, ?)')
    binds = (mType, mId, songId, userId, timeNow, method)
    return operate(sql, binds)
    
def insertMediaSongPv(songIdl, mType, mId, userId, timeNow):
    if songIdl:
        #clog.debug('(insertMediaSongPv)', sys)
        sql = ('INSERT OR REPLACE INTO MediaSong VALUES'
               ' ((SELECT mediaId FROM Media WHERE type=? AND id=?), ?, ?, ?, ?)')
        binds = (mType, mId, songIdl[1], userId, timeNow, songIdl[0])
        #clog.debug('%s, %s' % (sql, binds), sys)
        return operate(sql, binds)

def queryMediaSongRow(mType, mId):
    clog.debug('(queryMediaSongData)', sys)
    sql = ('SELECT * FROM MediaSong WHERE mediaId IS'
           ' (SELECT mediaId FROM Media WHERE type=? AND id=?)')
    binds = (mType, mId)
    return query(sql, binds)

def queryVocaDbInfo(mType, mId):
    clog.debug('(queryVocaDbInfo)', sys)
    sql = ('SELECT CyUser.nameOriginal, MediaSong.mediaId, Song.songId, '
           'MediaSong.method, Song.data FROM CyUser, MediaSong, Song WHERE '
           'MediaSong.songId=Song.songId AND CyUser.userId=MediaSong.userId '
           'AND MediaSong.mediaId = (SELECT mediaId FROM Media WHERE type=? '
           'AND id=?)')
    binds = (mType, mId)
    return query(sql, binds)
    
def getSongId(mType, mId):
    sql = ('SELECT songId FROM MediaSong WHERE mediaId = (SELECT mediaId '
            'FROM MEDIA WHERE type=? AND id=?)')
    binds = (mType, mId)
    return query(sql, binds)

def bulkQueryMediaSong(res, playlist):
    return dbpool.runInteraction(_bulkQueryMediaSong, playlist)

def _bulkQueryMediaSong(txn, playlist):
    clog.debug('(_queryBulkMediaSong)', sys)
    songlessMedia = []
    for media in playlist:
        sql = ('SELECT songId FROM MediaSong WHERE mediaId IS'
               ' (SELECT mediaId FROM Media WHERE type=? AND id=?)')
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
    sql = 'SELECT flag FROM media WHERE type=? AND id=?'
    binds = (mType, mId)
    return query(sql, binds)

def flagMedia(flag, mType, mId):
    clog.debug('Adding flag %s to %s, %s' % (bin(flag), mType, mId), sys)
    sql = 'UPDATE media SET flag=(flag|?) WHERE type=? AND id=?'
    binds = (flag, mType, mId)
    return operate(sql, binds)
            
def unflagMedia(flag, mType, mId):
    clog.debug('Removing flag %s to %s, %s' % (bin(flag), mType, mId), sys)
    sql = 'UPDATE media SET flag=(flag&?) WHERE type=? AND id=?'
    binds = (~flag, mType, mId)
    return operate(sql, binds)

def getUserFlag(nameLower, isRegistered):
    sql = 'SELECT flag FROM CyUser WHERE nameLower=? AND registered=?'
    binds = (nameLower, isRegistered)
    return query(sql, binds)

def flagUser(flag, nameLower, isRegistered):
    clog.debug('Adding flag %s to %s, %s'
               % (bin(flag), nameLower, isRegistered), sys)
    sql = 'UPDATE CyUser SET flag=(flag|?) WHERE nameLower=? AND registered=?'
    binds = (flag, nameLower, isRegistered)
    return operate(sql, binds)
            
def unflagUser(flag, nameLower, isRegistered):
    clog.debug('Removing flag %s to %s, %s'
               % (bin(flag), nameLower, isRegistered), sys)
    sql = 'UPDATE CyUser SET flag=(flag|?) WHERE nameLower=? AND registered=?'
    binds = (~flag, nameLower, isRegistered)
    return operate(sql, binds)

def insertReplaceLike(mediaId, queueId, userId, timeNow, value):
    sql = 'INSERT OR REPLACE INTO Like VALUES (?, ?, ?, ?, ?)'
    binds = (mediaId, queueId, userId, timeNow, value)
    return operate(sql, binds)

def getLikes(queueId):
    sql = ('SELECT nameOriginal, like.value FROM CyUser JOIN Like ON '
          'CyUser.userId = Like.userId WHERE Like.queueId=?')
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
    sql = ('SELECT (SELECT (SELECT SUM(leave) FROM userinout WHERE userid=%s)'
           '- (SELECT SUM(enter) FROM userinout WHERE userid = %s)) * 0.00002'
        % ((_USERIDSQL,) * 2))
    binds = (nameLower, isRegistered) * 2
    return query(sql, binds)

def addByUserQueue(nameLower, registered, words, limit):
    """selects up to n (limit) random non-flagged media that was ever
       queued by registered user (nameLower)"""
    binds, sql = [], []
    if nameLower:
        name = ('AND Queue.userId = %s' % _USERIDSQL)
        binds.extend((nameLower, int(registered)))
    else:
        name = ''
    if words:
        title = 'AND Media.title LIKE ? '
        binds.append('%%%s%%' % words) # %% is escaped %
    else:
        title = ''
    sql = ('SELECT type, id FROM Media WHERE mediaId IN '
           '(SELECT DISTINCT Media.mediaId FROM Media, Queue WHERE '
           'Media.mediaId = Queue.mediaId AND Media.flag=0 %s %s'
           'ORDER BY RANDOM() LIMIT ?)') % (name, title)
    binds.append(limit)
    binds = tuple(binds)
    #clog.info(sql, 'sql')
    #clog.info(binds, 'sql')
    return query(sql, binds)

def addByUserAdd(nameLower, registered, words, limit):
    """selects up to n (limit) random non-flagged media that was 
       added first (introduced) by registered user (nameLower)"""
    binds = []
    if nameLower:
        name = ('AND by = %s' % _USERIDSQL)
        binds.extend((nameLower, registered))
    else:
        name = ''
    if words:
        title = 'AND title LIKE ?'
        binds.append('%%%s%%' % words)
    else:
         title = ''
    sql = ('SELECT type, id FROM Media WHERE flag=0 %s %s'
          'ORDER BY RANDOM() LIMIT ?') % (name, title)
    binds.append(limit)
    binds = tuple(binds)
    #clog.info(sql, 'sql')
    #clog.info(binds, 'sql')
    return query(sql, binds)

def addByUserLike(nameLower, registered, limit):
    """selects up to n (limit) random non-flagged media that is
    liked by user"""
    sql = ('SELECT Media.type, Media.id FROM Media CROSS JOIN LIKE '
           'ON Media.mediaId = Like.mediaId AND Like.userId=%s AND '
           'Like.value=1 ORDER BY RANDOM() LIMIT ?' % _USERIDSQL)
    binds = (nameLower, registered, limit)
    return query(sql, binds)

def getMediaById(mediaId):
    sql = 'SELECT * FROM Media WHERE mediaId=?'
    return query(sql, (mediaId,))

def getMediaByTypeId(mType, mId):
    sql = 'SELECT * FROM Media WHERE type=? and id=?'
    binds = (mType, mId)
    return query(sql, binds)

def getMediaByIdRange(fromId, limit):
    sql = 'SELECT * FROM Media LIMIT ?, ?'
    return query(sql, (fromId, limit))

def getMediaLastRowId():
    sql = 'SELECT COUNT(*) FROM Media'
    return query(sql, tuple())

def getUserlistQueue(mediaId):
    sql = ('SELECT DISTINCT CyUser.nameOriginal FROM CyUser JOIN Queue ON '
           'CyUser.userId = Queue.userId WHERE Queue.mediaId=?')
    return query(sql, (mediaId,))

def getUserAdd(mediaId):
    sql = ('SELECT CyUser.nameOriginal FROM CyUser JOIN Media ON '
           'CyUser.userId = Media.by WHERE Media.mediaId=?')
    return query(sql, (mediaId,))

def getUserProfile(nameLower, isRegistered):
    sql = ('SELECT nameOriginal, profileText, profileImgUrl FROM CyUser '
           'WHERE nameLower=? AND registered=?')
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
    sql = ('SELECT COUNT(*) FROM (SELECT Queue.queueId, Like.userId '
           'FROM Queue JOIN Like ON Queue.queueId = Like.queueId WHERE '
           'Queue.userId = %s AND Like.value=?)' % _USERIDSQL)
    binds = (nameLower, isRegistered, value)
    return query(sql, binds)

def getUserLikedSum(nameLower, isRegistered, value):
    sql = 'SELECT COUNT(*) FROM LIKE WHERE userId=%s AND value=?' % _USERIDSQL
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
           'ORDERY BY Queue.queueId DESC LIMIT ?' % _USERIDSQL)
    binds = (nameLower, isRegistered, limit)
    return query(sql, binds)

def getUserRecentAdds(nameLower, isRegistered, limit):
    limit = min(limit, 100)
    sql = ('SELECT * FROM Media, QUEUE '
           'WHERE Media.mediaId = Queue.mediaId AND Queue.userId = %s '
           'ORDERY BY Queue.queueId DESC LIMIT ?' % _USERIDSQL)
    binds = (nameLower, isRegistered, limit)
    return query(sql, binds)

def getChannelPopularMedia(limit, direction):
    limit = min(limit, 100)
    if direction == 'up':
        _sub = ('>', 'DESC')
    else:
        _sub = ('<', 'ASC')
    sql = ('SELECT * FROM (SELECT Queue.mediaId AS mid, '
           'SUM(Like.value) AS agg FROM Queue INNER JOIN Like ON Queue.queueId '
           '= Like.queueId WHERE Queue.queueId IN (SELECT queueId FROM Like) '
           'GROUP BY Queue.MediaId HAVING agg %s 0 ORDER BY agg %s LIMIT ?) '
           'JOIN Media ON Media.mediaId = mid' % _sub)
    binds = (limit,)
    # mid|agg|mediaId|type|id|dur|title|by|flag
    return query(sql, binds)

def getUserlist():
    sql = ('SELECT nameOriginal, registered, profileText, profileImgUrl '
            'FROM CyUser')
    return query(sql, tuple())

def insertUsercount(timeNow, usercount, anoncount):
    sql = 'INSERT INTO Usercount VALUES (?, ?, ?)'
    binds = (timeNow, usercount, anoncount)
    return operate(sql, binds)

def insertUserInOut(userId, enterTime, leaveTime):
    sql = 'INSERT INTO UserInOut VALUES (?, ?, ?, ?)'
    binds = (userId, enterTime, leaveTime, 0)
    return operate(sql, binds)

def insertPm(userId, pmTime, pmCyTime, msg, flag):
    sql = 'INSERT INTO CyPM VALUES (?, ?, ?, ?, ?, ?)'
    binds = (None, userId, pmTime, pmCyTime, msg, flag)
    return operate(sql, binds)

def getCurrentAndMaxProfileId():
    sql = ('SELECT profileId FROM CyProfile WHERE flag=1 UNION ALL '
           'SELECT MAX(profileId) FROM CyProfile')
    return query(sql, tuple())

def getProfile(profileId):
    sql = 'SELECT profileId, text, imgUrl FROM CyProfile WHERE profileId=?'
    return query(sql, (profileId,))

def setProfileFlag(profileId, flag):
    sql = 'UPDATE CyProfile SET flag=? WHERE profileId=?'
    return operate(sql, (flag, profileId))

def insertAnnouncement(setBy, title, text, timeNow):
    sql = 'INSERT INTO CyAnnouncement VALUES (?, ?, ?, ?, ?)'
    binds = (None, timeNow, setBy, title, text)
    return operate(sql, binds)

def getLastAnnouncement():
    sql = 'SELECT * FROM CyAnnouncement ORDER BY announceId DESC LIMIT 1'
    return query(sql, tuple())


dbpool = adbapi.ConnectionPool('sqlite3', 'data.db', check_same_thread=False,
                               cp_max=1) # one thread max; avoids db locks
dbpool.runInteraction(turnOnFK)
