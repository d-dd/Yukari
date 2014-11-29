from twisted.internet import defer
import json
import database
class FirstQueued(object):
    def __init__(self):
        self.jsName = 'firstQueued'

    def _cmjs_firstAdded(self, cy, fdict):
        media = fdict['args'][0]
        mType = media['type']
        mId = media['id']
        d = self._getFirstQueuedByTime(mType, mId)
        d.addCallback(self._cbFirstQueued, cy)
        return d

    def _cbFirstQueued(self, results, cy):
        time = results[0][0]/100
        username = results[0][1]
        strjs = 'first_queued=' + json.dumps({'time':time, 'username':username})
        return defer.succeed((self.jsName, strjs))

    def _getFirstQueuedByTime(self, mType, mId):
        """ time, username of user who queued media mType, mId """
        sql = ('SELECT Queue.time, CyUser.nameOriginal FROM Queue, CyUser, '
               'Media WHERE Queue.mediaId = Media.mediaId AND Queue.userId = '
               'CyUser.userId AND Media.mediaId =(SELECT mediaId FROM Media '
               'WHERE type=? AND id=?);')
        binds = (mType, mId)
        return database.query(sql, binds)

def setup():
    return FirstQueued()
