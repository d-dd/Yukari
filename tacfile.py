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
from twisted.logger import Logger
# Yukari
# add home directory to sys.path
sys.path.append(os.getcwd())
from connections.cytube.cyClient import WSService
import connections.cytube.cyProfileChange as cyProfileChange
from connections.ircClient import IrcService
from conf import config
import database, tools
from tools import clog
from connections.discord import dcrestclient
from connections.discord import dcclient


CHANNEL = str(config['discord']['relay_channel_id'])
STATUS_CHANNEL = str(config['discord']['status_channel_id'])
syst = 'Yukari'
def importPlugins(path):
    try:
        files = os.listdir(path)
    except(OSError):
        clog.error('Error importing plugins. Invalid path.', syst)
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

        # discord rest api
        self.dcr = dcrestclient.DiscordHttpRelay(CHANNEL, loop_now=True)
        self.dcnp = dcrestclient.DiscordNowPlaying(STATUS_CHANNEL)

        # discord single delete
        self.dcSingleDelete = dcrestclient.DiscordSingleDelete(CHANNEL,
                                                               loop_now=False)

        # discord log unlogged msgs
        self.dcMsgSearch = dcrestclient.DiscordSearchUnsavedMessages(CHANNEL)

        # False = Offline, True = Online, None = has shutdown
        self.irc = False
        self.cy = False
        self.dc = False

        self.cyUserdict = {}
        self.inIrcChan = False
        self.inIrcNp = False
        self.inIrcStatus = False

        # Wether to restart when disconnected
        self.ircRestart = True
        self.cyRestart = True
        self.dcRestart = True

        self.cyLastConnect = 0

        self.startTime = time.time()

        # Remember the git-hash when this instance is created (non-atomic)
        self.version = subprocess.check_output(['git', 'rev-parse', 
                                                '--short', 'HEAD']).strip()

        # DiscordRest
        self.discordRestEnabled = str(config['discord']['relay_channel_id'])

        # Users in IRC chat channel
        self.ircUserCount = 0

        self.ircChan = str(config['irc']['channel'])
        if self.ircChan and not self.ircChan.startswith('#'):
            self.ircChan = '#' + self.ircChan
        self.cyName = str(config['Cytube']['username'])
        self.dcName = str(config['discord']['username'])
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
                    clog.info('Imported %s!' % trigger, syst)


    def cyChangeProfile(self):
        """ Change Yukari's profile picture and text on CyTube """
        d = database.getCurrentAndMaxProfileId()
        d.addCallback(self.cbChangeProfile)
        return d

    def cbChangeProfile(self, res):
        #clog.debug('(cbChangeProfile) %s' % res, syst)
        if len(res) < 2: # no flagged row
            clog.error('(cbChangeProfile) CyProfile table incorrect.', syst)
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
        clog.debug('(setNewProfile) %s' % res, syst)
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
        clog.error(err, syst)
        return err

    def recIrcMsg(self, user, channel, msg, modifier=None):
        self.lastIrcChat = time.time()
        user = user.split('!', 1)[0] # takes out the extra info in the name
        # cytube char limit per line is 244
        pre = ''
        if self.cy:
            max_width = 244 - (len(user) + len('[..]')*2 + 10)
            msgd = deque(textwrap.wrap(msg, max_width,
                                        replace_whitespace=False,
                                        drop_whitespace=False))
            while msgd:
                cont = '[..]' if len(msgd) > 1 else ''
                line = '(%s) %s %s %s' % (user, pre, msgd.popleft(), cont)
                if modifier:
                    line = '_%s _' % line
                self.wsFactory.prot.relayToCyChat(line)
                pre = '[..]'

        if self.discordRestEnabled:
            self.dcr.onMessage('irc', user, msg, modifier)
        
        # don't process commands from action (/me) messages
        if not modifier:
            if self.irc:
                prot = self.ircFactory.prot
                self.processCommand('irc', user, tools.returnUnicode(msg), 
                                    prot=prot)

    def recCyMsg(self, source, user, msg, needProcessing, action=False):
        if user == self.cyName:
            return
        if self.inIrcChan and user != self.cyName and source != 'pm':
            clog.debug('recCyMsg: %s' % msg, syst)
            if not action:
                cleanMsg = '(%s) %s' % (user, msg)
            else:
                cleanMsg = '( * %s) %s' % (user, msg)
            self.sendToIrc(cleanMsg)

        if self.discordRestEnabled:
            self.dcr.onMessage(source, user, msg, action)

        if needProcessing and not action and self.cy:
            self.processCommand(source, user, msg, prot=self.wsFactory.prot)

    def recDcMsg(self, name, msg):
        if name == self.dcName:
            return

        pre = ''
        if self.cy:
            max_width = 244 - (len(name) + len('[..]')*2 + 10)

            # Although Cytube supports newlines, it's safer
            # to drop it, as it can be used for
            # spoofing username of messages

            msgd = deque(textwrap.wrap(msg, max_width,
                                        replace_whitespace=True,
                                        drop_whitespace=True))
            while msgd:
                cont = '[..]' if len(msgd) > 1 else ''
                line = '<%s>%s %s %s' % (name, pre, msgd.popleft(), cont)
                self.wsFactory.prot.relayToCyChat(line)
                pre = '[..]'

        pre = ''
        if self.inIrcChan and name != self.dcName:
            # TODO - IRC seems to count characters with bytes (?)
            # At least Rizon takes fewer JP 
            # and if we sendline a line that is too long,
            # the server will truncate it mid-character,
            # making the text unencodable - msg will be gibberish
            max_width = 500 - (len(name) + len('[..]')*2 + 10)
            # take out whitespace because IRC rate-limits
            msgd = deque(textwrap.wrap(msg, max_width,
                                        replace_whitespace=True,
                                        drop_whitespace=True))
            while msgd:
                cont = '[..]' if len(msgd) > 1 else ''
                line = '<%s>%s %s %s' % (name, pre, msgd.popleft(), cont)
                self.sendToIrc(line)
                pre = '[..]'

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

        if self.dc and media:
            mType, mId, title = media
            if mType == 'yt':
                link = 'https://youtu.be/{}'.format(mId)
                self.dcnp.onChangeMedia(link)

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
                           (command, args), syst)
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
        self.dcr.onMessage('yuk', 'Yukari', msg, action)
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
        clog.info('(cleanup) Cleaning up for shutdown!', syst)
        self.done = Deferred()
        #self.done.callback(None)
       # return self.done
        # if nothing has started, shutdown immediately.
        if not self.irc and not self.cy:
            clog.info('(cleanup) Nothing to clean!', syst)
            self.done.callback(None)
        if self.irc:
            self.ircFactory.prot.partLeave('Shutting down.')
        if self.cy:
            self.cyRestart = False
            self.wsFactory.prot.sendClose()
            self.wsFactory.stopTrying()
        if self.dc:
            self.dcRestart = False
            self.getServiceNamed('dc').f.con.sendClose()
            self.getServiceNamed('dc').f.stopTrying()
        return self.done

    def doneCleanup(self, protocol):
        """ Fires the done deferred, which unpauses the shutdown sequence """
        # If the application is stuck after Ctrl+C due to a bug,
        # use telnet(manhole) to manually fire the 'done' deferred.
        clog.warning('(doneCleanup) CLEANUP FROM %s' % protocol, syst)
        if protocol == 'irc': 
            self.irc = None
            clog.info('(doneCleanup) Done shutting down IRC.', syst)
        elif protocol == 'cy':
            self.cy = None
            clog.info('(doneCleanup) Done shutting down Cy.', syst)
        elif protocol == 'dc':
            self.dc = None
            clog.info('(doneCleanup) Done shutting down Discord.', syst)
        if not self.irc and not self.cy and not self.dc:
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

# discord
dc_service = dcclient.DcService()
dc_service.setName("dc")
dc_service.setServiceParent(yukService)

reactor.addSystemEventTrigger('before', 'shutdown', yukService.cleanup)

