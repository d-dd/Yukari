import database
from twisted.internet import defer
from tools import clog, getTime, commandThrottle

syst = 'Likes'
class Likes(object):
    
    def __init__(self):
        self.jsName = 'likeScore'
        self.currentLikes = {}

    def _scjs_loadLikes(self, cy, fdict):
        media = fdict['args'][0]
        mType = media['type']
        mId = media['id']
        d = self.loadLikes(cy, mType, mId)
        return d

    def _like(self, cy, username, args, source):
        if source == 'pm' or source == 'ppm':
            self._likeMedia(cy, username, args, source, 1)

    def _dislike(self, cy,username, args, source):
        if source == 'pm' or source == 'ppm':
            self._likeMedia(cy, username, args, source, -1)

    def _unlike(self, cy,username, args, source):
        if source == 'pm' or source == 'ppm':
            self._likeMedia(cy, username, args, source, 0)

    def _ppm_subscribeLike(self, cy, username, args, source):
        clog.debug('Received subscribeLike from %s' % username, syst)
        if username in cy.userdict:
            cy.userdict[username]['subscribeLike'] = True
            # send value for current media
            if username in self.currentLikes:
                msg = '%%%%%s' % self.currentLikes[username]
                cy.doSendPm(msg, username)

    def _ppm_like(self, cy, username, args, source):
        self._like(cy, username, None, 'ppm')

    def _ppm_unlike(self, cy, username, args, source):
        self._unlike(cy, username, None, 'ppm')
    
    def _ppm_dislike(self, cy, username, args, source):
        self._dislike(cy, username, None, 'ppm')

    def loadLikes(self, cy, mType, mId):
        uid = cy.getUidFromTypeId(mType, mId)
        i = cy.getIndexFromUid(uid)
        if i is None:
            clog.error('Got None for index getIndexFromUid', syst)
        try:
            queueId = cy.playlist[i]['qid']
            d = database.getLikes(queueId)
        except(KeyError):
            clog.error('(loadLikes) Key is not ready!', syst)
            d = cy.playlist[i]['qDeferred']
            d.addCallback(database.getLikes)
        # result  [(userId, 1), (6, 1)]
        d.addCallback(self.sendLikes, cy)
        return d

    def sendLikes(self, res, cy):
        self.currentLikes = dict(res)
        for username in self.currentLikes:
            if username in cy.userdict and self.currentLikes[username]:
                if cy.userdict[username]['subscribeLike']:
                    msg = '%%%%%s' % self.currentLikes[username]
                    cy.doSendPm(msg, username)

        score = sum(self.currentLikes.itervalues())
        self.currentLikeJs = 'yukariLikeScore=%d' % score
        return defer.succeed((self.jsName, self.currentLikeJs))

    def _likeMedia(self, cy, username, args, source, value):
        if not cy.nowPlayingMedia:
            return
        if args is not None:
            mType, mId = args.split(', ')
        else:
            mType = cy.nowPlayingMedia['type']
            mId = cy.nowPlayingMedia['id']
        clog.info('(_com_like):type:%s, id:%s' % (mType, mId), syst) 
        uid = cy.getUidFromTypeId(mType, mId) 
        if uid is None:
            clog.error('Got None for UID _likeMedia', syst)
        i = cy.getIndexFromUid(uid)
        userId = cy.userdict[username]['keyId']
        qid = cy.playlist[i]['qid']
        d = database.queryMediaId(mType, mId)
        d.addCallback(self.processResult)
        d.addCallback(database.insertReplaceLike, qid, userId, 
                       getTime(), value)
        d.addCallback(self.updateCurrentLikes, cy, username, value)

    def updateCurrentLikes(self, res, cy, username, value):
         self.currentLikes[username] = value
         score = sum(self.currentLikes.itervalues())
         cy.currentJs[self.jsName] = 'yukariLikeScore=%d' % score
         #cy.currentLikeJs = 'yukariLikeScore = %d' % score
         cy.updateJs()

    def processResult(self, res):
        return defer.succeed(res[0][0])

def setup():
    return Likes()
