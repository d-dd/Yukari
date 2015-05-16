import json
from collections import deque

from twisted.internet import reactor, defer
from twisted.internet.task import LoopingCall

import database
from tools import clog
import apiClient

syst = 'MediaCheck(P)'
class MediaCheck(object):
    """ Checks Youtube videos to make sure they can be played back in a browser.
        Non-playable media (embedding disabled, private, deleted, etc) will be
        flagged (Media) and deleted from the Cytube playlist.
        Videos are checked on queue and on changeMedia.
        
        As of Youtube APIv3 we can't differentiate the reason why a video is
        unavailable.
        """

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
        d = apiClient.requestYtApi(ytId, 'check')
        return d.addCallback(self.processYtCheck, ytId)

    def processYtCheck(self, jsonResponse, ytId):
        items = jsonResponse['items']
        # if the video is unavailable (private, deleted, etc), Youtube
        # returns an empty list.
        if not items:
            return defer.succeed('NoVid')
        status = items[0].get('status')
        if not status:
            return defer.succeed('UnexpectedJson')
        if status.get('embeddable'):
            return defer.succeed('EmbedOk')
        else:
            return defer.succeed('NoEmbed')

    def flagOrDelete(self, res, cy, mType, mId, title, uid):
        if res == 'EmbedOk':
            clog.info('%s EmbedOk' % title, syst)
            database.unflagMedia(0b1, mType, mId)
        elif res in ('Status503', 'Status403', 'Status404', 'NoEmbed','NoVid'):
            clog.warning('%s: %s' % (title, res), syst)
            cy.doDeleteMedia(uid)
            cy.uncache(mId)
            msg = 'Removing non-playable media %s' % title
            database.flagMedia(0b1, mType, mId)
            cy.sendCyWhisper(msg)

def setup():
    return MediaCheck()
