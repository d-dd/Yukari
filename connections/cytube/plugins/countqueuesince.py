"""
Count how many times a media has been queued recently.
"""
import pytz
import datetime
from twisted.internet import defer
import database

syst = 'countqueue'

class CountQueue(object):
    
    def _scjs_countQueue(self, cy, fdict):
        media = fdict['args'][0]
        mType = media['type']
        mId = media['id']
        ninetyDays = datetime.timedelta(days=90)
        ninetyDaysAgo = datetime.datetime.now(pytz.utc) - ninetyDays
        return self._countQueue(mType, mId, ninetyDaysAgo)

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

