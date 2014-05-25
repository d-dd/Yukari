from twisted.internet import defer
from twisted.enterprise import adbapi
from tools import clog
sys = 'database'


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
#    print 'dbquery', sql, binds
    return query(sql, binds)

def queryResult(res):
    """
    Returns single row (list) from a query. If None, returns NoRowException.
    """
    if not res:
        #clog.debug('(queryResult) No match found', sys)
        return defer.fail(NoRowException)
    else:
        clog.debug('(queryResult) match found %s' % res, sys)
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
        
    
def updateCyUser(timeNow, timeStayed, userId):
    sql = ('UPDATE CyUser SET lastSeen=?, accessTime=accessTime+? '
           'WHERE userId=?')
    binds = (timeNow, timeStayed, userId)
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

def insertMedia(media):
    return dbpool.runInteraction(_insertMedia, media)

def _insertMedia(txn, media):
    sql = ('INSERT OR IGNORE INTO Media VALUES (?, ?, ?, ?, ?, ?, ?);'
           'UPDATE Media SET mediaId=mediaId WHERE type=? AND id=?')
    txn.executemany(sql, media)
    return [txn.lastrowid]

def insertQueue(mediaId, userId, timeNow, flag):
    sql = 'INSERT INTO Queue VALUES (?, ?, ?, ?, ?)'
    binds = (None, mediaId, userId, timeNow, flag)
    clog.debug('(insertQueue) binds: %s, %s, %s, %s' % 
               (mediaId, userId, timeNow, flag), sys)
    return operate(sql, binds)

def insertSong(res, lastUpdate):
    if res == 0:
        clog.error('(insertSong) VocaDB returned null. Skipping.', sys)
        return defer.succeed([0])
    return dbpool.runInteraction(_insertSong, res, lastUpdate)

def _insertSong(txn, res, lastUpdate):
    clog.debug('(insertSong)', sys)
    sql = 'INSERT OR REPLACE INTO Song VALUES (?, ?, ?)'
    data, songId = res
    binds = (songId, data, lastUpdate)
    txn.execute(sql, binds)
    return [txn.lastrowid]

def insertMediaSong(res, mType, mId, songId, userId, timeNow, method):
    clog.debug('(insertMediaSong)', sys)
    sql = ('INSERT OR REPLACE INTO MediaSong VALUES'
           ' ((SELECT mediaId FROM Media WHERE type=? AND id=?), ?, ?, ?, ?)')
    binds = (mType, mId, songId, userId, timeNow, method)
    return operate(sql, binds)
    
def insertMediaSongPv(songIdl, mType, mId, userId, timeNow, method):
    clog.debug('(insertMediaSongPv)', sys)
    sql = ('INSERT OR REPLACE INTO MediaSong VALUES'
           ' ((SELECT mediaId FROM Media WHERE type=? AND id=?), ?, ?, ?, ?)')
    binds = (mType, mId, songIdl[0], userId, timeNow, method)
    return operate(sql, binds)


def queryMediaSongRow(mType, mId):
    clog.debug('(queryMediaSongData)', sys)
    sql = ('SELECT * FROM MediaSong WHERE mediaId IS'
           ' (SELECT mediaId FROM Media WHERE type=? AND id=?)')
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
        txn.execute(sql, media)
        row = txn.fetchone()
        if not row:
            songlessMedia.append(media)
    clog.info(songlessMedia, sys)
    return songlessMedia

# media flags
# 1<<0: invalid media
# 1<<1: omitted media
# 1<<2: blacklisted media

def getMediaFlag(mType, mId):
    sql = 'SELECT flag FROM media WHERE type=?, id=?'
    binds = (mTYpe, mId)
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

def addByUserQueue(nameLower, limit):
    """selects up to n (limit) random non-flagged media that was ever
       queued by registered user (nameLower)"""
    sql = ('SELECT type, id FROM Media WHERE mediaId IN '
           '(SELECT DISTINCT Media.mediaId FROM Media, Queue WHERE '
           'Media.mediaId = Queue.mediaId AND Queue.userId= '
           '(SELECT userId FROM CyUser WHERE nameLower=? AND registered=?) '
           'AND Media.flag=0 ORDER BY RANDOM() limit ?)')
    binds = (nameLower, 1, limit)
    clog.info(sql, 'sql')
    return query(sql, binds)


dbpool = adbapi.ConnectionPool('sqlite3', 'data.db', check_same_thread=False,
                               cp_max=1) # one thread max; avoids db locks
dbpool.runInteraction(turnOnFK)
