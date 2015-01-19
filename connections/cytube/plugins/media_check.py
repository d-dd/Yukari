from collections import deque
import json
import re
from twisted.internet import reactor, defer
from twisted.internet.task import LoopingCall
from twisted.web.client import Agent, readBody
from twisted.web.http_headers import Headers
import database
from tools import clog

syst = 'MediaCheck(P)'
class MediaCheck(object):
    """ Checks Youtube videos to make sure they can be played back in a browser.
        Non-playable media (embedding disabled, private, deleted, etc) will be
        flagged (Media) and deleted from the Cytube playlist.
        Videos are checked on queue and on changeMedia."""

    def __init__(self):
        self.mediaToCheck = deque()
        self.ytLoop = LoopingCall(self.checkYoutube)

    def checkYoutube(self):
        if not self.mediaToCheck:
            self.ytLoop.stop()
        else:
            (cy, mType, mId, mTitle, uid) = self.mediaToCheck.popleft()
            d = self.checkVideoStatus(mId)
            d.addCallback(self.flagOrDelete, cy, mType, mId, mTitle, uid)

    def _pl_checkpl(self, cy, playlist):
        return
    # No need to check on playlist. We already check on queue and setCurrent

    def _q_checkMedia(self, cy, fdict):
        uid = fdict['args'][0]['item']['uid']
        media = fdict['args'][0]['item']['media']
        mType = media['type']
        if mType != 'yt':
            return
        mId = media['id']
        mTitle = media['title']
        self.mediaToCheck.append((cy, mType, mId, mTitle, uid))
        if not self.ytLoop.running:
            self.ytLoop.start(1.0)

    def _sc_checkMedia(self, cy, fdict):
        media = fdict['args'][0]
        uid = cy.nowPlayingUid
        title = media['title']
        mType = media['type']
        mId = media['id']
        if mType != 'yt':
            return
        d = self.checkVideoStatus(mId)
        d.addCallback(self.flagOrDelete, cy, mType, mId, title, uid)
        return d

    def checkVideoStatus(self, ytId):
        ytId = str(ytId)
        agent = Agent(reactor)
        url = ('http://gdata.youtube.com/feeds/api/videos/%s?v=2&alt=json'
               '&fields=yt:accessControl' % ytId)
        d = agent.request('GET', url, 
                          Headers({'Content-type':['application/json']}))
        d.addCallbacks(self.checkStatus, self.networkError, (ytId,))
        return d

    def checkStatus(self, response, ytId):
        d = readBody(response)
        if response.code == 403:
            return defer.succeed('Status403')
        elif response.code == 404:
            return defer.succeed('Status404')
        elif response.code == 503:
            return defer.succeed('Status503')
        else:
            d.addCallback(self.processYtCheck, ytId)
            return d

    def processYtCheck(self, body, ytId):
        try:
            res = json.loads(body)
        except(ValueError):
            clog.error('(processYtCheck) Error decoding JSON: %s' % body, syst)
            return 'BadResponse'

        actions = res['entry']['yt$accessControl']
        for action in actions:
            if action['action'] == 'embed':
                if action['permission'] == 'allowed':
                    clog.info('(processYtCheck) embed allowed for %s' % ytId)
                    return defer.succeed('EmbedOk')
        return defer.succeed('NoEmbed')

    def networkError(self, err):
        clog.error('Network Error: %s' % err.value, syst)
        return 'NetworkError'

    def flagOrDelete(self, res, cy, mType, mId, title, uid):
        if res == 'EmbedOk':
            clog.info('%s EmbedOk' % title, syst)
            database.unflagMedia(0b1, mType, mId)
        elif res in ('Status503', 'Status403', 'Status404', 'NoEmbed'):
            clog.warning('%s: %s' % (title, res), syst)
            cy.doDeleteMedia(uid)
            cy.uncache(mId)
            msg = 'Removing non-playable media %s' % title
            database.flagMedia(0b1, mType, mId)
            cy.sendCyWhisper(msg)

def setup():
    return MediaCheck()
