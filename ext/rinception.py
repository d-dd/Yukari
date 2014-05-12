""" Server for steam-bot """
from twisted.internet import protocol, reactor
from tools import clog

sys = 'RinServer'

class Messenger(protocol.Protocol):

    def __init__(self, factory):
        self.factory = factory

    def connectionMade(self):
        self.transport.write('Hi Rin!! -from Yukari\r\n')
        clog.info('(connectionMade) Connection established', sys)

    def dataReceived(self, data): # echo
        self.transport.write(data)

class MessengerFactory(protocol.Factory):

    def buildProtocol(self, addr):
        clog.info('(buildProtocol) Building protocol', sys)
        return Messenger()
