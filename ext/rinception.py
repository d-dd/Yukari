""" Server for steam-bot """
from twisted.internet import protocol, reactor
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

    def lineReceived(self, line):
        clog.info(line, sys)
        d = checkLine(line)
        if not d:
            clog.error('at linerec')
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
            clog.error('no request')

    
    def _rin_mediaById(self, args):
        if 'mediaId' not in args:
            response = {'callType': 'mediaById', 'result': 'badargs'}
            self.sendLineAndLog(json.dumps(response))
            return
        mediaId = args['mediaId']
        d = database.getMediaById(mediaId)
        d.addCallback(self.sendOneMedia, args)

    def sendOneMedia(self, res, args):
        if res:
            mRow = res[0]
            mediaDict = {'mediaId': mRow[0], 'type': mRow[1], 'id': mRow[2],
                         'dur': mRow[3], 'title': mRow[4], 'flag': mRow[5]}
            response = {'callType': 'mediaById', 'result':'ok',
                        'resource': mediaDict}
        else:
            response = {'callType': 'mediaById', 'result':'nomatch',
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
        clog.debug(line)
        self.sendLine(line)

def checkLine(line):
    try:
        return json.loads(line)
    except(ValueError):
        return False
