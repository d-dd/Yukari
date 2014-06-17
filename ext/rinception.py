""" Server for steam-bot """
from twisted.internet import protocol, reactor, defer
from twisted.protocols.basic import LineReceiver
from tools import clog
import database
import json

sys = 'RinServer'

class LineReceiverFactory(protocol.Factory):
    def buildProtocol(self, addr):
        clog.info('(buildProtocol) Building protocol', sys)
        return LineReceiver(self)

class LineReceiver(LineReceiver):
    def __init__(self, factory):
        self.factory = factory

    def connectionMade(self):
        #self.sendLine('Hi Rin!! -from Yukari')
        clog.info('(connectionMade) Connection established', sys)

    def connectionLost(self, reason):
        clog.info('(connectionLost) %s' % reason, sys)

    def lineReceived(self, line):
        clog.info(line, sys)
        d = checkLine(line)
        if not d:
            self.sendBadArgs('Unknown', 'Invalid JSON')
            return
        request = self.parseDict(d)
        if request:
            callType, args = request
            thunk = getattr(self, '_rin_%s' % (callType,), None)
            if thunk is not None:
                thunk(args)
            elif thunk is None:
                response = {'callType': None, 'result': 'badname'}
                self.sendLineAndLog(json.dumps(response))
        else:
            clog.error('improper request', sys)
    
    def _rin_mediaById(self, args):
        if 'mediaId' not in args:
            self.sendBadArgs('mediaById')
            return
        mediaId = args['mediaId']
        try:
            int(mediaId)
        except(TypeError, ValueError):
            self.sendBadArgs('mediaById')
            return
        mediaId = args['mediaId']
        dMedia = database.getMediaById(mediaId)
        dLastRow = database.getMediaLastRowId()
        dl = defer.DeferredList([dMedia, dLastRow])
        dl.addCallback(self.sendOneMedia, args)
    
    def _rin_mediaByIdRange(self, args):
        limit = 1000
        if 'mediaIdRange' not in args:
            self.sendBadArgs('mediaByIdRange')
            return
        try:
            mediaIdRange = args['mediaIdRange']
            idRange = mediaIdRange.split(',') # AttributeError
            lower = int(idRange[0]) -1
            upper = int(idRange[1]) # IndexError
        except(AttributeError, IndexError):
            self.sendBadArgs('mediaByIdRange')
            return
        quantity = upper - lower
        if lower < 0 or quantity < 1:
            self.sendBadArgs('mediaByIdRange')
            return
        elif quantity > limit:
            self.sendBadArgs('mediaByIdRange',
                             'Request over maximum request size of %d' % limit)
            return
        d = database.getMediaByIdRange(lower, quantity)
        d.addCallback(self.sendManyMedia, quantity, args)

    def _rin_usersByMediaId(self, args):
        if 'mediaId' not in args:
            self.sendBadArgs('usersByMediaId')
            return
        mediaId = args['mediaId']
        try:
            int(mediaId)
        except(TypeError, ValueError):
            self.sendBadArgs('usersByMediaId')
            return
        dQueuedUsers= database.getUserlistQueue(mediaId)
        dAddedUser = database.getUserAdd(mediaId)
        dl = defer.DeferredList([dQueuedUsers, dAddedUser])
        dl.addCallback(self.sendUsersByMediaId, args)

    def _rin_userSummaryByUsername(self, args):
        if 'username' not in args or 'registered' not in args:
            self.sendBadArgs('userByUsername')
            return
        username = args['username']
        isRegistered = bool(args['registered'])
        binds = (username.lower(), isRegistered)
        dProfile = database.getUserProfile(*binds)
        dTime = database.getUserTotalTime(*binds)
        dFirstSeen = database.getUserFirstSeen(*binds)
        dLastSeen = database.getUserLastSeen(*binds)
        dQueue = database.getUserQueueSum(*binds)
        dAdd = database.getUserAddSum(*binds)
        dLikesReceived = database.getUserLikesReceivedSum(*binds, value=1)
        dDislikesReceived = database.getUserLikesReceivedSum(*binds, value=-1)
        dLiked = database.getUserLikedSum(*binds, value=1)
        dDisliked = database.getUserLikedSum(*binds, value=-1)
        dl = defer.DeferredList([dProfile, dTime, dFirstSeen, dLastSeen, dQueue,
                    dAdd, dLikesReceived, dDislikesReceived, dLiked, dDisliked])
        dl.addCallback(self.packUserSummary)

    def packUserSummary(self, res):
        if not res[0][1]:
            response = {'callType': 'userSummaryByUsername',
                                   'result': 'UserNotFound'}
        di = {}
        else:
            di['username'] = res[0][1][0][0]
            di['profileText'] = res[0][1][0][1]
            di['profileImgUrl'] = res[0][1][0][2]
            if res[1][1][0][0]:
                di['accessTime'] = int(res[1][1][0][0]/100)
                di['firstSeen'] = int(res[2][1][0][0]/100)
                di['lastSeen'] = int(res[3][1][0][0]/100)
            else: # no row in UserInOut
                di['accessTime'] = 0
                di['firstSeen'] = 0
                di['lastSeen'] = 0
            di['queueCount'] = res[4][1][0][0]
            di['addCount'] = res[5][1][0][0]
            di['likesReceived'] = res[6][1][0][0]
            di['dislikesReceived'] = res[7][1][0][0]
            di['likedCount'] = res[8][1][0][0]
            di['dislikedCount'] = res[9][1][0][0]
            response = {'callType': 'userSummaryByUsername', 'result': 'ok',
                        'resource': di}
        self.sendLineAndLog(json.dumps(response))

    def sendBadArgs(self, callType, reason=None):
        if reason:
            result = 'badargs: %s' % reason
        else:
            result = 'badargs'
        response = {'callType': callType, 'result': result}
        self.sendLineAndLog(json.dumps(response))

    def jsonifyMedia(self, mRow):
        mediaDict = {'mediaId': mRow[0], 'type': mRow[1], 'id': mRow[2],
                     'dur': mRow[3], 'title': mRow[4], 'flag': mRow[6]}
        return mediaDict

    def sendOneMedia(self, res, args):
        clog.info('sendonemedia %s' % res, sys)
        if res[0][0] and res[1][0] and res[0][1]: # not res[0][1] means no row
            mRow = res[0][1][0]
            mLastRowId = res[1][1][0][0] # 2deep4me
            mediaDict = self.jsonifyMedia(mRow)
            response = {'callType': 'mediaById', 'result':'ok',
                        'resource': mediaDict, 'meta': {'isLastRow': False}}
            clog.info('lastrow %s %s' % (mRow[0], mLastRowId), sys)
            if mRow[0] == mLastRowId:
                response['meta']['isLastRow'] = True
        else:
            response = {'callType': 'mediaById', 'result':'nomatch',
                         'args': args}
        self.sendLineAndLog(json.dumps(response))

    def sendManyMedia(self, res, quantity, args):
        if res:
            mediaList = []
            for media in res:
                mediaList.append(self.jsonifyMedia(media))
            clog.info('sendManyMedia %s' % mediaList, sys)
            fulfilled = True if len(mediaList) == quantity else False
            response = {'callType': 'mediaByIdRange', 'result':'ok',
                    'resource': mediaList, 'meta':{'fulfilled': fulfilled}}
        else:
            response = {'callType': 'mediaByIdRange', 'result':'nomatch',
                         'args': args}
        self.sendLineAndLog(json.dumps(response))

    def sendUsersByMediaId(self, res, args):
        if res[0][0] and res[1][0]:
           # example res: [(u'Yukari',), (u'Teto',)]
           queueUsers = [tup[0] for tup in res[0][1]] 
           addUser = res[1][1][0][0]
           response = {'callType': 'usersByMediaId', 'result': 'ok',
                       'resource': {'mediaId': args['mediaId'], 
                           'queuedUsers': queueUsers, 'addedUser': addUser}}
        else:
            response = {'callType': 'usersByMediaId', 'result':'nomatch',
                         'args': args}
        self.sendLineAndLog(json.dumps(response))

    def sendError(self, callType):
        errorDict = {'callType':callType, 'result':'error'}
        self.sendLineAndLog(json.dumps(errorDict))

    def parseDict(self, d):
        if 'callType' not in d or 'args' not in d:
            return False
        callType = d['callType']
        args = d['args']
        return (callType, args)

    def sendLineAndLog(self, line):
        clog.debug(line, sys)
        self.sendLine(line)

def checkLine(line):
    try:
        return json.loads(line)
    except(ValueError):
        return False
