""" Test client for yukari's steam-bot server """
from twisted.internet import reactor
from twisted.internet.protocol import Protocol, ClientCreator
#from tools import clog

sys = 'RinClient'


class Prot(Protocol):
    def dataReceived(self, data):
        print data


c = ClientCreator(reactor, Prot)
c.connectTCP('localhost', 18914)
reactor.run()

