
# Standard Library
from collections import deque
import importlib
import json
import os
import random
import re
import subprocess
import textwrap
import time
# Twisted Library
from twisted.application import service, strports
from twisted.conch import manhole, manhole_tap, telnet
from twisted.conch.insults import insults
from twisted.cred import portal, checkers
from twisted.internet import reactor, defer, protocol
from twisted.internet.defer import Deferred
from autobahn.twisted.websocket import connectWS
# Yukari
from ext.rinception import LineReceiver, LineReceiverFactory
from connections import apiClient
from connections.cytube.cyClient import CyProtocol, WsFactory
import connections.cytube.cyProfileChange as cyProfileChange
from connections.ircClient import IrcFactory
from conf import config
import database, tools
from tools import clog

sys = 'Yukari'
def importPlugins(path):
    return []
    try:
        files = os.listdir(path)
    except(OSError):
        clog.error('Error importing plugins. Invalid path.', sys)
        return []
    importPath = path.replace('/', '.')
    moduleNames = [importPath + i[:-3] for i in files
                   if not i.startswith('_') and i.endswith('.py') and not i.startswith('test')]
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

        self.cyUserdict = {}
        #
        self.inIrcChan = False
        self.inIrcNp = False
        self.inIrcStatus = False

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
        if self.ircChan and not self.ircChan.startswith('#'):
            self.ircChan = '#' + self.ircChan
        self.cyName = str(config['Cytube']['username'])
        self.lastIrcChat = 0

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

    def restartConnection(self, *args):
        clog.error('restarting connection in %s' % self.cyRetryWait, sys)
        msg = ('[status] Could not connect to server. Attempting to reconnect '
              'in %d seconds.' % self.cyRetryWait)
        #self.sendToIrc(msg)
        reactor.callLater(self.cyRetryWait, self.startCytubeClient)
        self.cyRetryWait = min((self.cyRetryWait+1)**(1+random.random()), 300)

    def startCytubeClient(self):
        """Change the profile and GET the socket io address"""
        dl = defer.DeferredList([apiClient.getCySioClientConfig(),
                                 self.cyChangeProfile()],
                                 consumeErrors=True)
        dl.addCallbacks(self.connectCy, self.failedStartCytube)

    def failedStartCytube(self, result):
        clog.error(result)
        self.restartConnection()

    def cyChangeProfile(self):
        """ Change Yukari's profile picture and text on CyTube """
        d = database.getCurrentAndMaxProfileId()
        d.addCallback(self.cbChangeProfile)
        return d

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
        d = cyProfileChange.changeProfileInfo(text, imgurl)
        d.addCallback(self.setProfileFlags, currentRow, nextRow)
        return d
    
    def setProfileFlags(self, ignored, currentRow, nextRow):
        # set/unset flags only after setNewProfile succeeds
        database.setProfileFlag(currentRow, 0) # unset current profile flag
        database.setProfileFlag(nextRow, 1) # set next profile flag

    def cyPostErr(self, err):
        clog.error(err, sys)
        return err

    def connectCy(self, startresults):
        if not startresults[0][0]:
            clog.error('Failed to retrieve server socket.io configuration')
            self.restartConnection()
        else:
            sioClientConfig = json.loads(startresults[0][1])
            host = config['Cytube']['domain']
            s = sioClientConfig['servers'][1]['url']
            ws = 'ws://{0}/socket.io/?transport=websocket'.format(s[s.find('//')+2:])
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

    def recIrcMsg(self, user, channel, msg, modifier=None):
        self.lastIrcChat = time.time()
        user = user.split('!', 1)[0] # takes out the extra info in the name
        # cytube char limit per line is 244
        pre = ''
        if self.cy:
            max_width = 244 - (len(user) + len('[..]')*2 + 10)
            msgd = deque(textwrap.wrap(msg, max_width))
            while msgd:
                cont = '[..]' if len(msgd) > 1 else ''
                line = '(%s) %s %s %s' % (user, pre, msgd.popleft(), cont)
                if modifier:
                    line = '_%s _' % line
                self.wsFactory.prot.relayToCyChat(line)
                pre = '[..]'
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

    def recCyUserlist(self, userdict):
        # called from cyClient, when cyCall userlist
        self.cyUserdict = userdict
        if self.inIrcStatus:
            self.ircFactory.prot.sendCyNames()

    def recCyUserJoin(self, user, rank):
        if self.inIrcStatus:
            self.ircFactory.prot.sendCyUserJoin(user, rank)

    def recCyUserLeave(self, user):
        if self.inIrcStatus:
            self.ircFactory.prot.sendCyUserLeave(user)

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
        # if nothing has started, shutdown immediately.
        if not self.irc and not self.cy:
            clog.info('(cleanup) Nothing to clean!', sys)
            self.done.callback(None)
        if self.irc:
            self.ircFactory.prot.partLeave('Shutting down.')
        if self.cy:
            self.cyRestart = False
            self.wsFactory.prot.sendClose()
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

def createShellServer(namespace):
    """ Creates an interactive shell interface to send and receive output 
    while the program is running. Connection's instance yukari is named y.
    e.g. dir(y), will list all of yukari's names"""

    # These are taken from manhole_tap module
    checker = checkers.FilePasswordDB('telnet.pw')
    telnetRealm = manhole_tap._StupidRealm(telnet.TelnetBootstrapProtocol,
                                           insults.ServerProtocol,
                                           manhole.ColoredManhole,
                                           {"y":namespace})
    telnetPortal = portal.Portal(telnetRealm, [checker])
    telnetFactory = protocol.ServerFactory()
    telnetFactory.protocol = manhole_tap.makeTelnetProtocol(telnetPortal)
    clog.info('Creating shell server instance...', sys)
    port = reactor.listenTCP(int(config['telnet']['port']), telnetFactory)
    return port

def main():
    clog.error('test custom log', 'cLog tester')
    clog.warning('test custom log', 'cLog tester')

    yukari = Connections()
    yukari.startCytubeClient()
    yukari.ircConnect()
    reactor.callWhenRunning(createShellServer, yukari)
    reactor.addSystemEventTrigger('before', 'shutdown', yukari.cleanup)
    reactor.run()

if __name__ == '__main__':
    main()
