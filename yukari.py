# Standard Library
import random, re, time, subprocess, os, importlib, ast
from datetime import timedelta
# Twisted Library
from twisted.internet import reactor, defer
from twisted.internet.defer import Deferred
from twisted.web.client import Agent, readBody
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
def import_commands(directory):
    """Import command modules found in commands directory"""
    # include / at the end of diretory
    try:
        files = os.listdir(directory)
    except(OSError):
        clog.error('(import_commands) Could not find commands directory', sys)
        return
    path = directory.replace('/', '.')
    moduleNames = [path + i[:-3] for i in files if i.endswith('.py') and 
                                                         i != '__init__.py']
    modules = map(importlib.import_module, moduleNames)
    return modules

class Connections:
    """ Handles connections to a Cytube server and IRC, as well as
        any communication between them."""
    
    def __init__(self):
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
        if config['irc']['channel']:
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
        user = user.split('!', 1)[0] # takes out the extra info in the name
        if self.cy:
            msgl = list(msg)
            # cytube char limit per line is 244, so break up into multiple lines
            while msgl:
                name = '(_%s_)' % user if modifier else '(%s)' % user
                cont = '[..]' if len(name) + len(msgl) > 235 else ''
                idx = 235 -len(name) - len(cont)
                line = '%s %s %s' % (name, ''.join(msgl[:idx]), cont)
                msgl = msgl[idx:]
                self.wsFactory.prot.relayToCyChat(line)
        # don't process commands from action (/me) messages
        if not modifier:
            self.processCommand(user, tools.returnUnicode(msg))

    def recCyMsg(self, user, msg, needProcessing, action=False):
        if self.inIrcChan and user != 'Yukarin':
            clog.debug('recCyMsg: %s' % msg, sys)
            cleanMsg = msg
            if not action:
                cleanMsg = '(%s) %s' % (user, cleanMsg)
            elif action:
                cleanMsg = '( * %s) %s' % (user, cleanMsg)
            self.sendToIrc(cleanMsg)

        clog.warning(msg, 'recCyMsg')
        if needProcessing:
            self.processCommand(user, msg)

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

    def processCommand(self, user, msg):
        if msg.startswith('$'):
            msg = tools.returnUnicode(msg)
            #msg = msg.encode('utf-8')
            command = msg.split()[0][1:]
            argsList = msg.split(' ', 1)
            if len(argsList) == 2:
                args = argsList[1]
            else:
                args = None
            try:
                thunk = getattr(self, '_com_%s' % (command,), None)
            except(UnicodeEncodeError):
                clog.warning('(processCommand) received non-ascii command', sys)
                thunk = False

            if thunk:
                thunk(user, args)


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

        self.sendChats('[status] UPTIME Yukari: %s, Cytube: %s, IRC: %s' %
                       (uptime, cyUptime, ircUptime))

    def _com_sql(self, user, args):
        if not args:
            return
        if 'drop table' in args.lower() and args.endswith(';'):
            tables = ('user', 'chat', 'song', 'media', 'video', 'song', 'music')
            if True in [c in args.lower() for c in tables]:
                nameLower = config['Cytube']['username'].lower()
                d = database.getUserFlag(nameLower, 1)
                d.addCallback(self.performSql, nameLower, args)
        else:
            self.sendChats('[sql: Invalid SQL.]')

    def _com_version(self, user, args):
        self.sendChats('[Version] %s' % self.version)

    def performSql(self, res, username, args):
        clog.debug(res)
        if res[0][0] & 16:
            return
        else:
            database.flagUser(16, username, 1)
            self.sendChats('[sql: %s executed successfuly.]' % args) 
            reactor.callLater(8, self.sendChats, '[warning] db read failed')
            reactor.callLater(8.7, self.sendChats, '[fatal] db read failed (20)')
            reactor.callLater(9, self.sendChats, '[fatal] db write failed (7)')

    def _com_help(self, user, args):
        msg =('Commands: https://github.com/d-dd/Yukari/blob/master/commands.md'
                ' Repo: https://github.com/d-dd/Yukari')
        self.sendChats(msg)

    def sendToIrc(self, msg):
        if self.inIrcChan:
            self.ircFactory.prot.sendChat(str(config['irc']['channel']), msg)

    def sendToCy(self, msg, modflair=False):
        if self.cy:
            self.wsFactory.prot.relayToCyChat(msg, modflair)

    def sendChats(self, msg, modflair=False):
        self.sendToIrc(msg)
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
# import modules and add the methods to the Connections class
commandsPaths = [('commands/', Connections), 
                 ('connections/cytube/commands/', CyProtocol)]

for path in commandsPaths:
    modules = import_commands(path[0])
    for module in modules:
        getattr(module, '__add_method', None)(path[1], dir(module), module)

yukari = Connections()
yukari.cyChangeProfile()
yukari.ircConnect()
#yukari.rinstantiate(int(config['rinserver']['port']))
reactor.callWhenRunning(createShellServer, yukari)
reactor.addSystemEventTrigger('before', 'shutdown', yukari.cleanup)
reactor.run()
