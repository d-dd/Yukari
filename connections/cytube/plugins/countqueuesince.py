"""
Count how many times a media has been queued recently.
"""
import time
from twisted.internet import defer
import database

syst = 'countqueue'

class CountQueue(object):
    
    def _scjs_countQueue(self, cy, fdict):
        media = fdict['args'][0]
        mType = media['type']
        mId = media['id']
        thirtyDays = 60 * 60 * 24 * 30
        thirtyDaysAgo = (time.time() - thirtyDays) * 100
        return self._countQueue(mType, mId, thirtyDaysAgo)

    def _countQueue(self, mType, mId, sinceTime):
        d = database.countRecentQueuesSince(mType, mId, sinceTime)
        d.addCallback(self._processCount, mType, mId)
        return d
    
    def _processCount(self, result, mType, mId):
        if result:
            countJs = 'yukct=%s' % result[0]
        else:
            countJs = 'yukct=0'
        return defer.succeed(('qcount', countJs))

def setup():
    return CountQueue()

