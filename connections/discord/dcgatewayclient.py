"""
Receives Discord chat
For Websocket (Gateway) API, we use discord.py, a python 3 library.
We spawn a subprocess, which is a gateway client and TCP server.
Yukari connects to TCP server to receive the gateway messages

Really bad way to do this - maybe write Twisted compatible 
Gateway connection in the future. 

For sending, we must use REST API's.
"""
import json

from twisted.application import service

from twisted.internet import protocol
from twisted.internet import reactor
from tools import clog
from conf import config

PORT = int(config['discord']['gateway_relay_port'])

class DCProcessProtocol(protocol.ProcessProtocol):
    """
    subprocess spawner
    """
    def connectionMade(self):
        clog.debug("connection made to DC Protocol")

    def outReceived(self, data):
        clog.debug( "out - {}".format(data))

    def errReceived(self, err):
        clog.debug("err - {}".format(err))

    def processEnded(self, reason):
        clog.debug("process ended - {}".format(reason))


class DCListenerClient(protocol.Protocol):

    def connectionMade(self):
        self.factory.con = self

    def dataReceived(self, data):
        clog.debug(data)
        clog.debug(json.loads(data))
        self.factory.service.parent.recDcMsg(json.loads(data))

class DCListenerFactory(protocol.ReconnectingClientFactory):
    protocol = DCListenerClient
    initialDelay = 2

    def __init__(self, service):
    #    super(DCListenerFactory, self).__init__(service)
        self.service = service

    def clientConnectionFailed(self, connector, reason):
        clog.error("Connection failed - DCListener: {} : {}".format(connector,
                                                                      reason))

    def clientConnectionLost(self, connector, reason):
        clog.error("Connection lost - DCListener: {} : {}".format(connector,
                                                                      reason))

class DCListenerService(service.Service):
    def startService(self):
        if self.running:
            clog.error("DCListenerService is already running")
        else:
            self.f = DCListenerFactory(self)
            self._port = reactor.callLater(3, 
                          reactor.connectTCP,"localhost", PORT, 
                                             self.f)

    def stopService(self):
        return

        
