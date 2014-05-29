from ircClient import IrcProtocol, IrcFactory
from cyClient import CyProtocol, WsFactory
from ext.rinception import LineReceiver, LineReceiverFactory
from ext.apiserver import GetMedia
from twisted.web.server import Site
from conf import config
import database, tools
from tools import clog
import time, sys
from twisted.internet import reactor
from twisted.internet.defer import Deferred
from twisted.web.client import Agent, readBody
from twisted.manhole import telnet
from autobahn.twisted.websocket import connectWS

sys = 'Yukari'
class Connections:
    """ Handles connections to a Cytube server and IRC, as well as
        any communication between them."""
    
    def __init__(self):
        # False = Offline, True = Online, None = has shutdown
        self.irc = False
        self.cy = False
        self.rin = False

        # Wether to restart when disconnected
        self.ircRestart = True
        self.cyRestart = True
        self.rinRestart = True

    def cyPost(self):
        """ Send a POST request to Cytube for a server session id
        and start the connection process """
        agent = Agent(reactor)
        url = 'http://%s:%s/socket.io/1/' % (config['Cytube']['url'],
                                             config['Cytube']['port'])
        d = agent.request('POST', str(url))
        d.addCallbacks(readBody, self.cyPostErr) # POST response
        d.addCallback(self.processBody)
        d.addCallback(self.cySocketIo)

    def cyPostErr(self, err):
        clog.error(err, sys)

    def processBody(self, body):
        clog.debug('(processBody) Received session string %s ' % body, sys)

        msg = body.split(',')
        sid = msg[0][:msg[0].find(':')]
        ws = 'ws://%s:%s/socket.io/1/websocket/%s/' % (config['Cytube']['url'],
              int(config['Cytube']['port']), sid)
        return ws

    def cySocketIo(self, url):
        clog.debug('(cySocketIo) Cytube ws uri: %s' % url, sys)
        self.wsFactory = WsFactory(url)
        self.wsFactory.handle = self
        connectWS(self.wsFactory)

    def ircConnect(self):
        self.ircFactory = IrcFactory(config['irc']['channel'])
        self.ircFactory.handle = self
        reactor.connectTCP(config['irc']['url'], int(config['irc']['port']),
                           self.ircFactory)

    def rinstantiate(self, port):
        """ Start server for Rin (steam-bot) """
        clog.info('(rinstantiate) Starting server for Rin', sys)
        self.rinFactory = LineReceiverFactory()
        reactor.listenTCP(18914, self.rinFactory)

    def recIrcMsg(self, user, channel, msg):
        if self.cy:
            user = user.split('!', 1)[0] # takes out the extra info in the name
            msgf = '(%s) %s' % (user, msg)
            self.wsFactory.prot.doSendChat(msgf)
        self.processCommand(user, msg)

    def recCyMsg(self, user, msg):
        if self.irc:
            #s = TagStrip()
            tools.chatFormat.feed(msg)
            cleanMsg = tools.chatFormat.get_text()
            # reset so we can use the same instance
            tools.chatFormat.close()
            tools.chatFormat.result = []
            tools.chatFormat.reset()
            cleanMsg = '(%s) %s' % (user, cleanMsg)
            self.sendToIrc(cleanMsg)
        self.processCommand(user, msg)

    def processCommand(self, user, msg):
        if msg.startswith('$'):
            msg = msg.encode('utf-8')
            command = msg.split('$')[1]
            thunk = getattr(self, '_com_%s' % (command,), None)
            if thunk is not None:
                thunk(user, msg)

    def _com_greet(self, user, msg):
        #msg = 'Nice to meet you, %s!' % user
        #reactor.callLater(0.05, self.sendChats, msg)
        pass

    def sendToCy(self, msg, modflair=False):
        if self.cy:
            self.wsFactory.prot.doSendChat(msg, modflair)

    def sendToIrc(self, msg):
        if self.irc:
            self.ircFactory.prot.sendChat(str(config['irc']['channel']), msg)

    def sendChats(self, msg, modflair=False):
        self.sendToIrc(msg)
        self.sendToCy(msg, modflair)

    def cleanup(self):
        """ Prepares for shutdown """
        clog.info('(cleanup) Cleaning up for shutdown!', sys)
        self.done = Deferred()
        if self.irc:
            self.ircFactory.prot.partLeave('Shutting down.')
        if self.cy:
            self.wsFactory.prot.cleanUp()
        return self.done

    def doneCleanup(self, protocol):
        """ Fires the done deferred, which unpauses the shutdown sequence """
        # If the application is stuck after Ctrl+C due to a bug,
        # use telnet(manhole) to manually fire the 'done' deferred.
        if protocol == 'irc':
            self.irc = None
            clog.info('(doneCleanup) Done shutting down IRC.', sys)
        elif protocol == 'cy':
            self.cy = None
            clog.info('(doneCleanup) Done shutting down Cy.', sys)
        if self.irc is not True and self.cy is not True:
            self.done.callback(None)

def createShellServer(obj):
    """ Creates an interactive shell interface to send and receive output 
    while the program is running. Connection's instance yukari is named y.
    e.g. dir(y), will list all of yukari's names"""

    clog.info('Creating shell server instance...', sys)
    factory = telnet.ShellFactory()
    port = reactor.listenTCP(int(config['telnet']['port']), factory)
    factory.namespace['y'] = obj
    factory.username = config['telnet']['username']
    factory.password = config['telnet']['password']
    #log.msg('starting shell server...', Loglevel=logging.ERROR, system='Shell')
    return port


clog.error('test custom log', 'cLog tester')
yukari = Connections()
yukari.cyPost()
yukari.ircConnect()
yukari.rinstantiate(39393939)
reactor.callWhenRunning(createShellServer, yukari)
reactor.addSystemEventTrigger('before', 'shutdown', yukari.cleanup)

webRoot = GetMedia()
reactor.listenTCP(39394, Site(webRoot))
reactor.run()
