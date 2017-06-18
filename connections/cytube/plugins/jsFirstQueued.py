from twisted.internet import defer
import time
import json
from datetime import datetime
import database

class FirstQueued(object):
    def __init__(self):
        self.jsName = 'firstQueued'

    def _scjs_firstAdded(self, cy, fdict):
        media = fdict['args'][0]
        mType = media['type']
        mId = media['id']
        d = self._getFirstQueuedByTime(mType, mId)
        d.addCallback(self._cbFirstQueued, cy)
        return d

    def _cbFirstQueued(self, results, cy):
        dt = results[0][0] # datetime obj
        # utc time = local time              - utc offset
        # https://stackoverflow.com/questions/8777753
        utc_naive  = dt.replace(tzinfo=None) - dt.utcoffset()
        timestamp = (utc_naive - datetime(1970, 1, 1)).total_seconds()
        username = results[0][1]
        strjs = 'first_queued=' + json.dumps({'time':timestamp, 'username':username})
        return defer.succeed((self.jsName, strjs))

    def _getFirstQueuedByTime(self, mType, mId):
        """ time, username of user who queued media mType, mId """
        sql = ('SELECT Queue.time, CyUser.nameOriginal FROM Queue, CyUser, '
               'Media WHERE Queue.mediaId = Media.mediaId AND Queue.userId = '
               'CyUser.userId AND Media.mediaId =(SELECT mediaId FROM Media '
               'WHERE type=%s AND id=%s) ORDER BY time LIMIT 1;')
        binds = (mType, mId)
        return database.query(sql, binds)

def setup():
    return FirstQueued()
