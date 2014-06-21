from ircClient import IrcProtocol, IrcFactory
from cyClient import CyProtocol, WsFactory
from ext.rinception import LineReceiver, LineReceiverFactory
from twisted.web.server import Site
from conf import config
import database, tools, apiClient
from tools import clog
import random, re, time
from datetime import timedelta
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

        # Wether to restart when disconnected
        self.ircRestart = True
        self.cyRestart = True
        # Reconnect Timers
        self.cyRetryWait = 0
        self.cyLastConnect = 0
        self.cyLastDisconect = 0

        self.startTime = time.time()

    def restartConnection(self, method, waitTime):
        clog.error('restarting connection in %s' % waitTime)
        msg = ('[status] Could not connect to server. Attempting to reconnect '
              'in %d seconds.' % waitTime)
        self.sendToIrc(msg)
        reactor.callLater(waitTime, method)
        waitTime = waitTime**(1+random.random())
        # return between 2 and 300
        return min(max(2, waitTime), 300)

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
        self.cyRetryWait = self.restartConnection(self.cyPost, self.cyRetryWait)

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
        reactor.listenTCP(port, self.rinFactory)

    def recIrcMsg(self, user, channel, msg, modifier=None):
        if self.cy:
            user = user.split('!', 1)[0] # takes out the extra info in the name
            if not modifier:
                msgf = '(%s) %s' % (user, msg)
                self.wsFactory.prot.relayToCyChat(msgf)
                self.processCommand(user, msg)
            elif modifier == 'action':
                msgf = '_(%s)_ %s' % (user, msg)
                self.wsFactory.prot.relayToCyChat(msgf)
                # don't process action for commands

    def recCyMsg(self, user, msg, needProcessing, action=False):
        if self.irc and user != 'Yukarin':
            #s = TagStrip()
            clog.debug('recCyMsg: %s' % msg, sys)
            tools.chatFormat.feed(msg)
            cleanMsg = tools.chatFormat.get_text()
            # reset so we can use the same instance
            tools.chatFormat.close()
            tools.chatFormat.result = []
            tools.chatFormat.reset()
            if not action:
                cleanMsg = '(%s) %s' % (user, cleanMsg)
            elif action:
                cleanMsg = '( * %s) %s' % (user, cleanMsg)
            self.sendToIrc(cleanMsg)
        if needProcessing:
            self.processCommand(user, msg)

    def processCommand(self, user, msg):
        if msg.startswith('$'):
            msg = msg.encode('utf-8')
            command = msg.split()[0][1:]
            argsList = msg.split(' ', 1)
            if len(argsList) == 2:
                args = argsList[1]
            else:
                args = None
            thunk = getattr(self, '_com_%s' % (command,), None)
            if thunk is not None:
                thunk(user, args)

    def _com_greet(self, user, args):
        msg = 'Hi, %s.' % user
        reactor.callLater(0.00, self.sendChats, msg)

    def _com_bye(self, user, args):
        msg = 'Goodbye, %s.' % user
        self.sendChats(msg)

    def _com_ask(self, user, args):
        if not args:
            return
        if len(args) > 227:
            args = args[:224] + '(...)'
        msg = '[Ask: %s] %s' % (args, random.choice(('Yes', 'No')))
        self.sendChats(msg)

    def _com_choose(self, user, args):
        if not args:
            return
        choices = self.getChoices(args)
        if choices:
            msg = '[Choose: %s] %s' % (args, random.choice(choices))
            self.sendChats(msg)

    def _com_permute(self, user, args):
        if not args:
            return
        choices = self.getChoices(args)
        if choices:
            random.shuffle(choices)
            msg = '[Permute: %s] %s' % (args, ', '.join(choices))
            self.sendChats(msg)

    def getChoices(self, args):
        if len(args) > 230:
            return
        if ',' in args:
            choices = args.split(',')
        else:
            choices = args.split()
        if len(choices) < 1:
            return
        return choices
    
    def _com_8ball(self, user, args):
        if not args:
            return
        choices = ('It is certain', 'It is decidedly so', 'Without a doubt',
                   'Yes - definitely', 'You may rely on it', 'As I see it, yes',
                   'Most likely', 'Outlook good', 'Signs point to yes', 'Yes',
                   'Reply hazy, try again', 'Ask again later',
                   'Better not tell you now', 'Cannot predict now',
                   'Concentrate and ask again', "Don't count on it",
                   'My reply is no', 'My sources say no','Outlook not so good',
                   'Very doubtful')
        msg = '[8ball: %s] %s' % (args, random.choice(choices))
        self.sendChats(msg)

    def _com_dice(self, user, args):
        msg = '[dice: ???]: Dice Key!!'
        self.sendChats(msg)

    def _com_anagram(self, user, args):
        if not args:
            return
        text = re.sub(r"[^a-zA-Z]", "", args)
        if len(text) < 7:
            self.sendChats('Anagram too short.')
            return
        elif len(text) >= 30:
            self.sendChats('Anagram too long.')
            return
        d = apiClient.anagram(text)
        d.addCallback(self.sendAnagram, args)

    def sendAnagram(self, res, args):
        if res:
            self.sendChats('[Anagram: %s] %s' % (args, res))

    def _com_status(self, user, args):
        pass ## TODO

    def _com_uptime(self, user, args):
        uptime = time.time() - self.startTime
        uptime = str(timedelta(seconds=round(uptime)))
        cyUptime = time.time() - self.cyLastConnect
        cyUptime = str(timedelta(seconds=round(cyUptime)))
        ircUptime = time.time() - self.ircFactory.prot.ircConnect
        ircUptime = str(timedelta(seconds=round(ircUptime)))

        self.sendChats('[status] UPTIME Yukari: %s; Cytube: %s, IRC: %s' %
                       (uptime, cyUptime, ircUptime))

    def sendToIrc(self, msg):
        if self.irc:
            self.ircFactory.prot.sendChat(str(config['irc']['channel']), msg)

    def sendToCy(self, msg, modflair=False):
        if self.cy:
            self.wsFactory.prot.relayToCyChat(msg, modflair)

    def sendChats(self, msg, modflair=False):
        self.sendToIrc(msg)
        self.sendToCy(msg, modflair)

    def cyAnnouceLeftRoom(self):
        msg = ('[status] Left Cytube channel. Rejoin attempt in '
              '%d seconds.' % self.cyRetryWait)
        self.sendToIrc(msg)

    def cyAnnounceConnect(self):
        msg = ('[status] Connected to Cytube.')
        self.sendToIrc(msg)

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
    return port

clog.error('test custom log', 'cLog tester')
yukari = Connections()
yukari.cyPost()
yukari.ircConnect()
yukari.rinstantiate(int(config['rinserver']['port']))
reactor.callWhenRunning(createShellServer, yukari)
reactor.addSystemEventTrigger('before', 'shutdown', yukari.cleanup)
reactor.run()
