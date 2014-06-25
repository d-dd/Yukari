""" Test client for yukari's steam-bot server """
from twisted.internet import reactor
from twisted.internet.protocol import Protocol, ClientCreator
#from tools import clog
import json

sys = 'RinClient'

class Prot(Protocol):
    def connectionMade(self):
        req = {'callType':'mediaById', 'args':{'mediaId':9}}
        reqs = json.dumps(req) + '\r\n'
        #reactor.callLater(1, self.transport.write, reqs)
        userlistM = {'callType':'usersByMediaId', 'args':{'mediaId':'4'}}
        userlistM = json.dumps(userlistM) + '\r\n'
        #reactor.callLater(2, self.transport.write, userlist)
        mRange = {'callType': 'mediaByIdRange', 'args':{'mediaIdRange':'1, 4'}}
        mRange = json.dumps(mRange) + '\r\n'
        #reactor.callLater(3, self.transport.write, mRange)
        userInfo = {'callType': 'userSummaryByUsername', 'args':
                    {'username':'Yukari', 'registered': True}}
        userInfo = json.dumps(userInfo) + '\r\n'
        #reactor.callLater(0, self.transport.write, userInfo)
        popularMedia = {'callType': 'popularMedia', 'args': {'limit': 5, 'direction':'adown'}}
        popularMedia = json.dumps(popularMedia) + '\r\n'
        #reactor.callLater(0, self.transport.write, popularMedia)
        userlist = {'callType':'userlist', 'args':None}
        userlist = json.dumps(userlist) + '\r\n'
        reactor.callLater(0, self.transport.write, userlist)

    def dataReceived(self, data):
        try:
            print json.loads(data)
        except(ValueError):
            print 'could not parse %s' % data
       # reactor.callLater(1, self.transport.write,'t')
       # reactor.callLater(1, self.transport.write,'\r\n')
    
    def connectionLost(self, reason):
        print 'Connection Lost!'
        if reactor.running:
            reactor.stop()

c = ClientCreator(reactor, Prot)
c.connectTCP('localhost', 18001)
reactor.run()

