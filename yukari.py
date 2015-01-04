# Standard Library
import random, re, time, subprocess, os, importlib
# Twisted Library
from twisted.internet import reactor, defer
from twisted.internet.defer import Deferred
from twisted.manhole import telnet
from ircClient import IrcFactory
from autobahn.twisted.websocket import connectWS
# Yukari
from ext.rinception import LineReceiver, LineReceiverFactory
from connections.cytube.cyClient import CyProtocol, WsFactory
from conf import config
import database, tools, apiClient, cyProfileChange
from tools import clog

sys = 'Yukari'
def importPlugins(path):
    try:
        files = os.listdir(path)
    except(OSError):
        clog.error('Error importing plugins. Invalid path.', sys)
        return []
    importPath = path.replace('/', '.')
    moduleNames = [importPath + i[:-3] for i in files
                   if not i.startswith('_') and i.endswith('.py')]
    print moduleNames
    modules = map(importlib.import_module, moduleNames)
    return modules

class Connections:
    """ Handles connections to a Cytube server and IRC, as well as
        any communication between them."""
    
    def __init__(self):
        # import plugins
        self._importPlugins()

        # False = Offline, True = Online, None = has shutdown
        self.irc = False
        self.cy = False

        #
        self.inIrcChan = False
        self.inIrcNp = False

        # Wether to restart when disconnected
        self.ircRestart = True
        self.cyRestart = True
        # Reconnect Timers
        self.cyRetryWait = 0
        self.cyLastConnect = 0
        self.cyLastDisconnect = 0

        self.startTime = time.time()

        # Remember the git-hash when this instance is created (non-atomic)
        self.version = subprocess.check_output(['git', 'rev-parse', 
                                                '--short', 'HEAD']).strip()

        # Users in IRC chat channel
        self.ircUserCount = 0

        self.ircChan = str(config['irc']['channel'])
        if not self.ircChan.startswith('#'):
            self.ircChan = '#' + self.ircChan
        self.cyName = str(config['Cytube']['username'])

    def _importPlugins(self):
        modules = importPlugins('plugins/')
        self.triggers = {'commands':{}}
        for module in modules:
            instance = module.setup()
            for method in dir(instance):
                # commands in cytube chat
                if method.startswith('_com_'):
                    trigger = '%s' % method[5:]
                    self.triggers['commands'][trigger] = getattr(instance, method)
                    clog.info('Imported %s!' % trigger, sys)

    def restartConnection(self):
        clog.error('restarting connection in %s' % self.cyRetryWait)
        msg = ('[status] Could not connect to server. Attempting to reconnect '
              'in %d seconds.' % self.cyRetryWait)
        #self.sendToIrc(msg)
        reactor.callLater(self.cyRetryWait, self.cyChangeProfile)
        self.cyRetryWait = (self.cyRetryWait+1)**(1+random.random())
        # return between 2 and 300
        return min(max(2, self.cyRetryWait), 300)

    def cyChangeProfile(self):
        """ Change Yukari's profile picture and text on CyTube """
        d = database.getCurrentAndMaxProfileId()
        d.addCallback(self.cbChangeProfile)
        if not self.cy:
            d.addBoth(self.connectCy)

    def cbChangeProfile(self, res):
        #clog.debug('(cbChangeProfile) %s' % res, sys)
        if len(res) < 2: # no flagged row
            clog.error('(cbChangeProfile) CyProfile table incorrect.', sys)
            return defer.fail(None)
        currentRow = res[0][0]
        maxRow = res[1][0]
        if currentRow == maxRow:
            nextRow = 1
        else:
            nextRow = currentRow + 1
        d = database.getProfile(nextRow)
        d.addCallback(self.setNewProfile, currentRow, nextRow)
        return d

    def setNewProfile(self, res, currentRow, nextRow):
        clog.debug('(setNewProfile) %s' % res, sys)
        name = config['Cytube']['username']
        password = config['Cytube']['password']
        text = res[0][1]
        imgurl = res[0][2]
        d = cyProfileChange.changeProfile(name, password, text, imgurl)
        d.addCallback(self.setProfileFlags, currentRow, nextRow)
        return d
    
    def setProfileFlags(self, ignored, currentRow, nextRow):
        # set/unset flags only after setNewProfile succeeds
        database.setProfileFlag(currentRow, 0) # unset current profile flag
        database.setProfileFlag(nextRow, 1) # set next profile flag

    def cyPostErr(self, err):
        clog.error(err, sys)
        return err

    def connectCy(self, ignored):
        host = config['Cytube']['domain']
        port = config['Cytube']['port']
        ws = 'ws://%s:%s/socket.io/?transport=websocket' % (host, port)
        clog.debug('(cySocketIo) Cytube ws uri: %s' % ws, sys)
        self.wsFactory = WsFactory(ws)
        self.wsFactory.handle = self
        connectWS(self.wsFactory)

    def ircConnect(self):
        if self.ircChan:
            self.ircFactory = IrcFactory(self.ircChan)
            self.ircFactory.handle = self
            reactor.connectTCP(config['irc']['url'], int(config['irc']['port']),
                               self.ircFactory)

    def rinstantiate(self, port):
        """ Start server for Rin (steam-bot) """
        clog.info('(rinstantiate) Starting server for Rin', sys)
        self.rinFactory = LineReceiverFactory()
        reactor.listenTCP(port, self.rinFactory)

    def recIrcMsg(self, user, channel, msg, modifier=None):
        user = user.split('!', 1)[0] # takes out the extra info in the name
        if self.cy:
            msgl = list(msg)
            # cytube char limit per line is 244, so break up into multiple lines
            while msgl:
                name = '( _%s_)' % user if modifier else '(%s)' % user
                cont = '[..]' if len(name) + len(msgl) > 235 else ''
                idx = 235 -len(name) - len(cont)
                line = '%s %s %s' % (name, ''.join(msgl[:idx]), cont)
                msgl = msgl[idx:]
                self.wsFactory.prot.relayToCyChat(line)
        # don't process commands from action (/me) messages
        if not modifier:
            if self.irc:
                prot = self.ircFactory.prot
                self.processCommand('irc', user, tools.returnUnicode(msg), 
                                    prot=prot)

    def recCyMsg(self, source, user, msg, needProcessing, action=False):
        if self.inIrcChan and user != self.cyName and source != 'pm':
            clog.debug('recCyMsg: %s' % msg, sys)
            if not action:
                cleanMsg = '(%s) %s' % (user, msg)
            else:
                cleanMsg = '( * %s) %s' % (user, msg)
            self.sendToIrc(cleanMsg)
        if needProcessing and not action and self.cy:
            self.processCommand(source, user, msg, prot=self.wsFactory.prot)

    def recCyChangeMedia(self, media):
        if self.inIrcNp and media:
            mType, mId, title = media
            if mType == 'yt':
                link = 'https://youtu.be/%s' % mId
                msg = '[Now Playing]: %s  %s' % (title, link)
            else:
                msg = '[Now Playing]: %s (%s, %s)' % (title, mType, mId)
            msg = tools.returnStr(msg)
            self.ircFactory.prot.sayNowPlaying(msg)

    def processCommand(self, source, user, msg, prot):
        if msg.startswith('$'):
            msg = tools.returnUnicode(msg)
            #msg = msg.encode('utf-8')
            command = msg.split()[0][1:]
            argsList = msg.split(' ', 1)
            if len(argsList) == 2:
                args = argsList[1]
            else:
                args = None
            if command in self.triggers['commands']:
                clog.info('triggered command: [%s] args: [%s]' %
                           (command, args), sys)
                self.triggers['commands'][command](self, user, args, source,
                                                   prot=prot)

    def reply(self, msg, source, username, modflair=False, action=False):
        # public chat: send to both
        if source == 'chat' or source == 'irc':
            self.sendChats(msg, modflair, action)
        elif source == 'pm' and self.cy:
            if action:
                # no /me in Cytube PM
                msg = '_* %s_' % msg
            self.wsFactory.prot.doSendPm(msg, username)

    def sendToIrc(self, msg, action=False):
        if not self.inIrcChan:
            return
        self.ircFactory.prot.sendChat(msg, action)

    def sendToCy(self, msg, modflair=False):
        if self.cy:
            self.wsFactory.prot.relayToCyChat(msg, modflair)

    def sendChats(self, msg, modflair=False, action=False):
        self.sendToIrc(msg, action)
        if action:
            self.sendToCy('/me %s' % msg, modflair)
        else:
            self.sendToCy(msg, modflair)

    def cyAnnouceLeftRoom(self):
        msg = ('[status] Left Cytube channel.')
        self.sendToIrc(msg)
        if self.irc:
            self.ircFactory.prot.setOfflineNick()

    def cyAnnounceConnect(self):
        msg = ('[status] Connected to Cytube.')
        self.sendToIrc(msg)
        if self.irc:
            self.ircFactory.prot.setOnlineNick()

    def cleanup(self):
        """ Prepares for shutdown """
        # Starts pre-shutdown cleanup
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
        clog.warning('(doneCleanup) CLEANUP FROM %s' % protocol, sys)
        if protocol == 'irc':
            self.irc = None
            clog.info('(doneCleanup) Done shutting down IRC.', sys)
        elif protocol == 'cy':
            self.cy = None
            clog.info('(doneCleanup) Done shutting down Cy.', sys)
        if not self.irc and not self.cy:
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
clog.warning('test custom log', 'cLog tester')

yukari = Connections()
yukari.cyChangeProfile()
yukari.ircConnect()
#yukari.rinstantiate(int(config['rinserver']['port']))
reactor.callWhenRunning(createShellServer, yukari)
reactor.addSystemEventTrigger('before', 'shutdown', yukari.cleanup)
reactor.run()
