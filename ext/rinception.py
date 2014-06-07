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
            return # if it's not a proper JSON don't reply
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

    def sendBadArgs(self, callType):
            response = {'callType': callType, 'result': 'badargs'}
            self.sendLineAndLog(json.dumps(response))

    def sendOneMedia(self, res, args):
        if res[0][0] and res[1][0]:
            mRow = res[0][1][0]
            mLastRowId = res[1][1][0][0] # 2deep4me
            mediaDict = {'mediaId': mRow[0], 'type': mRow[1], 'id': mRow[2],
                         'dur': mRow[3], 'title': mRow[4], 'flag': mRow[6]}
            response = {'callType': 'mediaById', 'result':'ok',
                        'resource': mediaDict, 'meta': {'isLastRow': False}}
            clog.info('lastrow %s %s' % (mRow[0], mLastRowId), sys)
            if mRow[0] == mLastRowId:
                response['meta']['isLastRow'] = True
        else:
            response = {'callType': 'mediaById', 'result':'nomatch',
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
