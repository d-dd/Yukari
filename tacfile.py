# Standard Library
from collections import deque
import importlib
import os
import subprocess
import sys
import textwrap
import time
# Twisted Library
from twisted.application import service
from twisted.conch import manhole_tap
from twisted.internet import reactor, defer
from twisted.internet.defer import Deferred
# Yukari
# add home directory to sys.path
sys.path.append(os.getcwd())
from connections.cytube.cyClient import WSService
import connections.cytube.cyProfileChange as cyProfileChange
from connections.ircClient import IrcService
from conf import config
import database, tools
from tools import clog

sys = 'Yukari'
def importPlugins(path):
    try:
        files = os.listdir(path)
    except(OSError):
        clog.error('Error importing plugins. Invalid path.', sys)
    importPath = path.replace('/', '.')
    moduleNames = [importPath + i[:-3] for i in files
                   if not i.startswith('_') and i.endswith('.py') and not i.startswith('test')]
    modules = map(importlib.import_module, moduleNames)
    return modules

class Yukari(service.MultiService):
    """ Handles connections to a Cytube server and IRC, as well as
        any communication between them."""
    
    def __init__(self):
        super(Yukari, self).__init__()

        # import plugins
        self._importPlugins()

        # False = Offline, True = Online, None = has shutdown
        self.irc = False
        self.cy = False

        self.cyUserdict = {}
        self.inIrcChan = False
        self.inIrcNp = False
        self.inIrcStatus = False

        # Wether to restart when disconnected
        self.ircRestart = True
        self.cyRestart = True

        self.cyLastConnect = 0

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

    def cyAnnounceLeftRoom(self):
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
        #self.done.callback(None)
       # return self.done
        # if nothing has started, shutdown immediately.
        if not self.irc and not self.cy:
            clog.info('(cleanup) Nothing to clean!', sys)
            self.done.callback(None)
        if self.irc:
            self.ircFactory.prot.partLeave('Shutting down.')
        if self.cy:
            self.cyRestart = False
            self.wsFactory.prot.sendClose()
            self.wsFactory.stopTrying()
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

application = service.Application("app")
yukService = Yukari()
yukService.setServiceParent(application)

from twisted.conch import manhole_tap
manhole_service = manhole_tap.makeService({
    "telnetPort": "tcp:{}".format(config['telnet']['port']),
    "sshPort": None,
    "namespace": {"y": yukService},
    "passwd": "telnet.pw",
    })
manhole_service.setName("manhole")
manhole_service.setServiceParent(yukService)

# cytube
ws_service = WSService()
ws_service.setName("cy")
ws_service.setServiceParent(yukService)

# irc
irc_service = IrcService()
irc_service.setName("irc")
irc_service.setServiceParent(yukService)

reactor.addSystemEventTrigger('before', 'shutdown', yukService.cleanup)

