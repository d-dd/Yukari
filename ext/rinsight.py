""" Test client for yukari's steam-bot server """
from twisted.internet import reactor
from twisted.internet.protocol import Protocol, ClientCreator
#from tools import clog
import json

sys = 'RinClient'


class Prot(Protocol):
    def connectionMade(self):
        req = {'callType':'mediaById', 'args':{'mediaId':99}}
        reqs = json.dumps(req) + '\r\n'
        reactor.callLater(1, self.transport.write, reqs)

    def dataReceived(self, data):
        print type(data)
        print data
        try:
            print json.loads(data)
        except(ValueError):
            print 'could not parse %s' % data
       # reactor.callLater(1, self.transport.write,'t')
       # reactor.callLater(1, self.transport.write,'\r\n')


c = ClientCreator(reactor, Prot)
c.connectTCP('localhost', 18914)
reactor.run()

