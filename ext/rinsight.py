""" Test client for yukari's steam-bot server """
from twisted.internet import reactor
from twisted.internet.protocol import Protocol, ClientCreator
#from tools import clog
import json

sys = 'RinClient'


class Prot(Protocol):
    def connectionMade(self):
        req = {'callType':'mediaById', 'args':{'mediaId':999}}
        reqs = json.dumps(req) + '\r\n'
        reactor.callLater(1, self.transport.write, reqs)
        userlist = {'callType':'usersByMediaId', 'args':{'mediaId':'4'}}
        userlist = json.dumps(userlist) + '\r\n'
        #reactor.callLater(2, self.transport.write, userlist)
        mRange = {'callType': 'mediaByIdRange', 'args':{'mediaIdRange':'12, 999'}}
        mRange = json.dumps(mRange) + '\r\n'
        #reactor.callLater(3, self.transport.write, mRange)

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
c.connectTCP('localhost', 18000)
reactor.run()

