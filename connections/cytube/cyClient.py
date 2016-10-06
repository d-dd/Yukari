# Standard Library
import importlib
import json
import os
import random
import re
import time
from collections import deque

# Twisted Libraries
from twisted.internet import reactor, defer, task
from twisted.internet.error import AlreadyCalled, AlreadyCancelled
from autobahn.twisted.websocket import WebSocketClientProtocol,\
                                       WebSocketClientFactory
# Yukari
import database, tools
from tools import clog, getTime
from conf import config

syst = 'CytubeClient'
vdb = config['UserAgent']['vocadb']

def importPlugins(paths):
    """ Imports .py files in paths[0] as plugins"""
    try:
        files = os.listdir(paths[0])
        clog.info(str(files), 'files')
    except(OSError):
        clog.error('Plugin import error! Check that %s exists.' % paths[0],syst)
        return []
    moduleNames = []
    for path in paths:
        moduleNames.extend([path + i[:-3] for i in os.listdir(path)
                        if not i.startswith('_') and not i.startswith('test') and i.endswith('.py')])
    moduleNames = [p.replace('/', '.') for p in moduleNames]
    modules = map(importlib.import_module, moduleNames)
    clog.warning(str(modules), 'modules')
    return modules


def wisp(msg):
    """Decorate msg with system-whisper trigger"""
    return '@3939%s#3939' % msg

class CyProtocol(WebSocketClientProtocol):
    start_init = []

    def __init__(self):
        super(WebSocketClientProtocol, self).__init__()
        self.importCyModules()
        self.loops = []
        self.laters = []

        # Wether to run scJs methods
        # Set this to True for media that is not going to be played
        # and there is no need to lookup information on it.
        # e.g. blacklisted, unplayable, replay, etc.
        self.cancelSetCurrentJs = False
        self.underSpam = False
        self.underHeavySpam = False
        # how long to wait for heartbeat reply
        self.hearttime = 20 
        self.spamCount = 0
        self.name = config['Cytube']['username']
        self.unloggedChat = []
        self.chatLoop = task.LoopingCall(self.bulkLogChat)
        self.loops.append(self.chatLoop)
        self.lastChatLogTime = 0
        self.receivedChatBuffer = False
        self.queueMediaList = deque()
        self.burstCounter = 0
        self.lastQueueTime = time.time() - 20 #TODO
        self.nowPlayingMedia = {}
        self.nowPlayingUid = -1
        self.err = []
        self.currentJs = {}
        self.currentLikeJs = ''
        ### Need to imporve this regex, it matches non-videos
        # ie https://www.youtube.com/feed/subscriptions
        self.ytUrl = re.compile(
                (r'(https?://)?(www\.)?(youtube|youtu|youtube-nocookie)\.'
                  '(com|be)/(watch\?v=|embed/|v/|.+\?v=)?([^&=%\?]{11})'))
        self.ytq = deque()

        # Polls
        self.myPollState = None
        self.activePoll = None
        self.pollFn = None

        self.usercount = 0
        self.willReplay = False
        self.mediaRemainingTime = 0
        for fn in CyProtocol.start_init:
            fn(self)

    def importCyModules(self):
        paths = ['connections/cytube/plugins/']
        modules = importPlugins(paths)
        self.triggers = {
                         'setCurrent': {},
                         'scJs': {},
                         'commands':{},
                         'delete': {},
                         'playlist': {},
                         'ppm': {},
                         'queue': {},
                         'qfail': {},
                         'replay': {},
                         'temp': {},
                         'userjoin': {},
                         'userleave': {},
                         'vote': {},
                                         }

        for module in modules:
            try:
                instance = module.setup()
            except(AttributeError):
                clog.error('Error importing %s!' % module.__name__, syst)
                instance = None
            for method in dir(instance):
                # commands in cytube chat
                if method.startswith('_com_'):
                    trigger = '$%s' % method[5:]
                    self.triggers['commands'][trigger] = getattr(instance, method)
                elif method.startswith('_del_'):
                    self.triggers['delete'][method] = getattr(instance, method)

                elif method.startswith('_sc_'):
                    self.triggers['setCurrent'][method] = getattr(instance, method)
                elif method.startswith('_q_'):
                    self.triggers['queue'][method] = getattr(instance, method)
                elif method.startswith('_qfail_'):
                    self.triggers['qfail'][method] = getattr(instance, method)
                elif method.startswith('_re_'):
                    self.triggers['replay'][method] = getattr(instance, method)
                elif method.startswith('_scjs_'):
                    self.triggers['scJs'][method] = getattr(instance, method)
                elif method.startswith('_temp_'):
                    self.triggers['temp'][method] = getattr(instance, method)
                elif method.startswith('_pl_'):
                    self.triggers['playlist'][method] = getattr(instance, method)
                elif method.startswith('_ppm_'):
                    trigger = '%%%%%s' % method[5:]
                    self.triggers['ppm'][trigger] = getattr(instance, method)
                elif method.startswith('_uj_'):
                    self.triggers['userjoin'][method] = getattr(instance, method)
                elif method.startswith('_ul_'):
                    self.triggers['userleave'][method] = getattr(instance, method)
                elif method.startswith('_vote_'):
                    self.triggers['vote'][method] = getattr(instance, method)

    def errcatch(self, err):
        clog.error('caught something')
        err.printTraceback()
        self.err.append(err)

    def onConnect(self, response):
        clog.info('(onConnect) Connected to Cytube: %s' % response, syst)

    def onOpen(self):
        clog.info('(onOpen) Handshake successful!', syst)
        self.factory.handle.cyLastConnect = time.time()
        self.factory.handle.cyAnnounceConnect()
        self.connectedTime = time.time()
        self.lastUserlistTime = 0
        self.factory.prot = self
        self.factory.handle.cy = True
        self.heartbeat = task.LoopingCall(self.sendHeartbeat)
        self.loops.append(self.heartbeat)
        self.lifeline = None
        self.heartbeat.start(20.0, now=True)
        self.finalHeartbeat = None
	# wait one second before logging in
        # to make sure rank is properly initialized
        # eventually check for "rank" frame
	reactor.callLater(1.5, self.initialize)

    def abandon(self):
        """
        Leave the Cytube server because we did not receive a heartbeat reponse
        in time.
        """
        clog.error('No heartbeat response... Sending last heartbeat.', syst) 
        self.sendMessage('2')
        self.finalHeartbeat = reactor.callLater(5, self.doSendClose)

    def doSendClose(self):
        clog.error('No final heartbeat response. Disconnecting.', syst)
        self.sendClose()

    def sendHeartbeat(self):
        self.sendMessage('2')
        #clog.debug('Sent Heartbeat!', syst)
        # Remember that heavy load on the machine often causes
        # schedules to fall behind greatly

        #first heartbeat
        if self.lifeline is None:
            self.lifeline = reactor.callLater(self.hearttime, self.abandon)
            return

        # was not cancelled (did not receive prior heartbeat response)
        if self.lifeline.active():
            self.lifeline.cancel()
            self.lifeline = None
        # If we're under spam, it's most likley that spam is builing up a long
        # queue and the heartbeat has yet to be processed
            if self.underSpam or self.underHeavySpam:
                clog.warning('(sendHeartbeat) Under spam - skipping abandon',
                                                                        syst)
                return
            self.abandon()

        else:
            self.lifeline = None
            self.lifeline = reactor.callLater(self.hearttime, self.abandon)

    def receiveHeartbeat(self):
        #clog.debug('Received Heartbeat!', syst)
        if self.lifeline:
            try:
                self.lifeline.cancel()
                #self.laters.remove(self.lifeline)
            except(AlreadyCalled, AlreadyCancelled):
                clog.warning('(lifeline reset) alreadycalled/cancelled', syst)
        if self.finalHeartbeat:
            finalHeartbeat, self.finalHeartbeat = self.finalHeartbeat, None
            try:
                finalHeartbeat.cancel()
            except(AlreadyCalled, AlreadyCancelled):
                clog.warning('Could not cancel finalHeartbeat.', syst)

    def onMessage(self, msg, binary):
        clog.debug(msg, '** ')
        msg = msg.decode('utf8')
        if binary:
            clog.warning('Binary received: {0} bytes'.format(len(msg)))
            return
        if msg == '3':
            self.receiveHeartbeat()
            return
        elif msg.startswith('42'):
            try:
                msg = json.loads(msg[2:])
            except(ValueError):
                clog.error('(onMessage) Received non-JSON frame!', syst)
                raise ValueError
                return
            name = msg[0]
            if self.underHeavySpam and name == 'chatMsg':
                self.spamCount += 1
                return
            try:
                args = msg[1]
            except(IndexError):
                args = {}
            fdict = {'name': name, 'args': [args]}
            #clog.debug(fdict, 'fdict:%s' % name)
            self.processFrame(fdict)

    def onClose(self, wasClean, code, reason):
        clog.info('(onClose) Closed Protocol connection. wasClean:%s '
                  'code%s, reason%s' % (wasClean, code, reason), syst)

    def sendf(self, fdict):
        l = '["%s",%s]' % (fdict["name"], 
            json.dumps(fdict.get("args", None)).encode('utf8'))
        frame = "42"+ l
        clog.debug("(sendf) [->] %s" % frame, syst)
        self.sendMessage(str(frame))

    def doSendChat(self, msg, source='chat', username=None, modflair=False,
                   toIrc=True):
        clog.debug('(doSendChat) msg:%s, source:%s, username:%s' % (msg, 
                   source, username), syst)
        if not toIrc:
            msg = '^' + msg
        if source == 'chat':
            if modflair:
                modflair = 3 ### TODO remove hardcode rank
            self.sendf({'name': 'chatMsg',
                       'args': {'msg': msg, 'meta': {'modflair': modflair}}})
        elif source == 'pm':
            toIrc = False
            self.sendf({'name': 'pm',
                        'args': {'msg': msg, 'to': username}})
        if toIrc:
            self.factory.handle.sendToIrc(msg)

    def relayToCyChat(self, msg, modflair=False):
            self.sendf({'name': 'chatMsg',
                       'args': {'msg': msg, 'meta': {'modflair': modflair}}})

    def sendCyWhisper(self, msg, source='chat', username=None, modflair=False, 
                      toIrc=False):
        msg = wisp(msg)
        self.doSendChat(msg, source, username, modflair, toIrc)

    def doSendPm(self, msg, username):
        self.sendf({'name': 'pm',
                   'args': {'msg': msg, 'to': username}})

    def initialize(self):
        pw = config['Cytube']['password']
        self.sendf({'name': 'login',
                   'args': {'name': self.name, 'pw': pw}})

    def processFrame(self, fdict):
        name = fdict['name']
        # send to the appropriate methods
        thunk = getattr(self, '_cyCall_%s' % (name,), None)
        if thunk is not None:
            thunk(fdict)

    def joinRoom(self):
        channel = config['Cytube']['channel']
        self.sendf({'name': 'joinChannel', 'args': {'name':channel}})
        self.sendf({'name': 'initUserPLCallbacks', 'args': {}})
        self.sendf({'name': 'listPlaylists', 'args': {}})
                
    def _cyCall_kick(self, fdict):
        reason = fdict['args'][0].get('reason')
        clog.error('Kicked from channel! Reason: %s' % reason, syst)
        self.sendClose()

    def _cyCall_login(self, fdict):
        if fdict['args'][0]['success']:
            self.joinRoom()

    def _cyCall_setMotd(self, fdict):
        self.receivedChatBuffer = True

    def _cyCall_usercount(self, fdict):
        usercount = fdict['args'][0]
        self.usercount = usercount
        anoncount = usercount - len(self.userdict)
        database.insertUsercount(getTime(), usercount, anoncount)

    def _cyCall_announcement(self, fdict):
        d = database.getLastAnnouncement()
        d.addCallback(self.compareAnnoucements, fdict)

    def compareAnnoucements(self, res, fdict):
        args = fdict['args'][0]
        by = args.get('from', '')
        title = args.get('title', '')
        text = args.get('text', '')
        if res:
            bySaved = res[0][2]
            titleSaved = res[0][3]
            textSaved = res[0][4]

            if bySaved == by and titleSaved == title and textSaved == text:
                clog.debug('Received same annoucement', syst)
                return

        d = database.insertAnnouncement(by, title, text, getTime())
        d.addCallback(self.relayAnnoucement, by, title, text)

    def relayAnnoucement(self, ignored, by, title, text):
        text = tools.strip_tags(text)
        msg = '[Announcement: %s] %s (%s)' % (title, text, by)
        
        if not self.factory.handle.irc: # wait a bit for join
            # wait a little bit in case Yukari needs to join the IRC channel
            # announcements are often related to Cytube server reboots
            self.laters.append(reactor.callLater(10, 
                                 self.factory.handle.sendToIrc, msg))
        else:
            self.factory.handle.sendToIrc(msg)

    def _cyCall_chatMsg(self, fdict):
        if not self.receivedChatBuffer:
            return
        args = fdict['args'][0]
        timeNow = getTime()
        username = args['username']
        msg = args['msg']
        chatCyTime = int((args['time'])/10.0)
        meta = args['meta']
        modflair = meta.get('modflair', None)
        action = meta.get('action', None)
        # shadowmute is effective to control chat but is hard to keep it hidden:
        # -Yukari will ignore shadowmuted commands
        # -Shadowmute messages will not relay to IRC
        shadow = meta.get('shadow', None)
        flag = 1 if shadow else 0
        self.logChatMsg(username, chatCyTime, msg, modflair, flag, timeNow)
        if not self.underSpam:
            self.checkCommands(username, msg, action, shadow, 'chat')
        else:
            # don't process at yukari either, when under spam
            self.factory.handle.recCyMsg('chat', username, msg, False, action)

    def logChatMsg(self, username, chatCyTime, msg, modflair, flag, timeNow):
        # logging chat to database
        keyId = None
        if username == '[server]':
            keyId = 2
        elif username in self.userdict:
            keyId = self.userdict[username]['keyId']
        else:
            keyId = None
        if keyId:
            self.unloggedChat.append((None, keyId, timeNow, chatCyTime, msg,
                                          modflair, flag))
            if not self.chatLoop.running:
                clog.debug('(_cy_chatMsg) starting chatLoop', syst)
                self.chatLoop.start(3, now=False)
        else:
            chatArgs = (timeNow, chatCyTime, msg, modflair, flag)
            self.userdict[username]['deferred'].addCallback(self.deferredChat,
                                                                chatArgs)
    def checkCommands(self, username, msg, action, shadow, source):
        if username == self.name or username == '[server]':
            return
       # needProcessing = False if action else True
        method = None
        # check for commands
        # strip HTML tags
        msg = tools.strip_tag_entity(msg)
        msg = tools.unescapeMsg(msg)
        if not msg:
            return
        if msg.startswith('$') and not shadow:
            # unescape to show return value properly ([Ask: >v<] Yes.)
            #msg = tools.unescapeMsg(msg)
            try:
                command = msg.split()[0]
            except(IndexError):
                clog.error('(checkCommands) No command', syst)
                return
            index = msg.find(' ')
            if index != -1:
                commandArgs = msg[index+1:]
            else:
                commandArgs = ''

            # special case for $vote
            if command == '$vote':
                clog.warning('%s, %s' % (command, commandArgs), syst)
                method = self.triggers['vote'].get('_vote_' + commandArgs, None)
            
            else:
                method = self.triggers['commands'].get(command, None)

        needProcessing = False if method or action else True
        # send chat first
        self.factory.handle.recCyMsg(source, username, msg, needProcessing,
                                                                    action) 
        # run command
        if method:
            clog.info('Command triggered: %s;%s' % (command, commandArgs), syst)
            method(self, username, commandArgs, source, prot=self)


    def _cyCall_pm(self, fdict):
        args = fdict['args'][0]
        pmTime = args['time']
        pmCyTime = int((args['time'])/10.0)
        timeNow = getTime()
        fromUser = args['username']
        toUser = args['to']
        msg = tools.unescapeMsg(args['msg'])
        if toUser == self.name:
            # Yukari received PM
            flag = 0
            username = fromUser
            
        elif fromUser == self.name:
            # Yukari sent the PM
            flag = 1
            username = toUser
        self.logPmChat(username, msg, pmTime, pmCyTime, timeNow, flag)
        if msg.startswith('%%'):
            source = 'ppm'
            command = msg
            # TODO args
            commandArgs = None
            if command in self.triggers['ppm']:
                self.triggers['ppm'][command](self, username, 
                                                   commandArgs, source)
                clog.info('ppm triggered: %s ; %s' % (command, commandArgs),
                    syst)
            return
        action = False
        self.checkCommands(username, msg, action, False, 'pm')

    def logPmChat(self, username, msg, pmTime, pmCyTime, timeNow, flag):
        if username in self.userdict:
            keyId = self.userdict[username]['keyId']
            if keyId is not None:
                clog.debug('(_cyCall_pm) key for %s:%s' % (username, keyId), syst)
                database.insertPm(keyId, pmTime, pmCyTime, msg, flag)
            else:
                # This happens frequently on join
                # Skips PM log but otherwise okay
                clog.warning('(_cyCall_pm) no key for %s' % username, syst)
        else:
            clog.error('(_cyCall_pm) %s sent phantom PM: %s' % (username, msg))

    def _cyCall_newPoll(self, fdict):
        poll = fdict['args'][0]
        self.activePoll = poll
        # initialize self.myPollState if it's Yukari's poll with non-empty dict
        if poll['initiator']  == self.name:
            self.myPollState = {'myPoll': True}
        else:
            self.myPollState = {'myPoll': False}

    def _cyCall_updatePoll(self, fdict):
        try:
            self.myPollState['counts'] = fdict['args'][0]['counts']
        except(TypeError):
            pass

    def _cyCall_closePoll(self, fdict):
        # on join, Cytube first sends a closePoll followed by a newPoll
        # if there is an active poll
        if self.activePoll is None:
            return
        self.activePoll = None
        clog.info('Poll was closed.', syst)
        if self.myPollState['myPoll']:
            myPollState, self.myPollState = self.myPollState, {}
            # the timer is active but poll ended
            # must have been user intervention
            try:
                self.pollTimer.active()
            # Yukari made poll but disconnected so there is no
            # pollstate
            except(AttributeError):
                clog.warning('Abandoned poll.', syst)
                return
            if self.pollTimer.active():
                clog.warning('Poll was ended  early.', syst)
            try:
                self.pollTimer.cancel()
                self.pollTimer = None
                self.ignorePollResults()
            except(NameError, TypeError, AttributeError):
                clog.warning('No polltimer found', syst)
                self.ignorePollResults()
            except(AlreadyCalled, AlreadyCancelled):
                clog.warning('Poll timer already called/cancelled', syst)
                # Poll finished cleanly
                # (plugin, fn, opts)
                if self.pollFn:
                    fn = self.pollFn[1]
                    fn(self, self.pollFn[2], myPollState)

    def ignorePollResults(self):
        msg = 'Poll has been interrupted by a user. Disregarding results.'
        self.pollFn[1](self, self.pollFn[2], False)
        self.doSendChat(wisp(msg), toIrc=False)

    def _cyCall_mediaUpdate(self, fdict):
        currentTime = fdict['args'][0]['currentTime']
        totalTime = self.nowPlayingMedia['seconds']
        self.mediaRemainingTime = totalTime - currentTime

    def doMakePoll(self, plugin, fn, opts, subject, title, choices, dur, 
                                     obscured=False, timer=False):
        """
        Make a poll with
        plugin: reference of the plugin
        fn: function to callback when poll is done
        opts: this will be sent back to fn
        subject: used for "`subject` is ending soon!" message
        title: title of the poll
        choices: tuple of poll choices
        dur: duration of the poll
        obscured: Cytube hidden poll results
        timer: Cytube poll timer
        """
        self.sendf({'name': 'newPoll', 'args': {'title': title,
                    'opts': choices, 'obscured': obscured}})
        self.pollFn = (plugin, fn, opts)
        self.pollTimer = reactor.callLater(max(dur-5, 0), 
                                          self.announceTimer, subject)
        self.laters.append(self.pollTimer)

    def announceTimer(self, subject):
        self.pollTimer = reactor.callLater(5, self.doClosePoll)
        self.laters.append(self.pollTimer)
        self.doSendChat('%s is ending in 5 seconds!' % subject, toIrc=False)

    def doClosePoll(self):
        self.sendf({'name': 'closePoll'})

    def updateJs(self):
        try:
            ircUserCount = 'yukarIRC=' + str(self.factory.handle.ircUserCount)
        except(NameError):
            ircUserCount = '0'
        js = [ircUserCount]
        for strjs in self.currentJs.itervalues():
            js.append(strjs)
        self.doSendJs((';'.join(js)+';'))

    def doSendJs(self, js):
        self.sendf({'name': 'setChannelJS', 'args': {'js': js}})

    def uncache(self, mId):
        """ Sends uncache frame to Cytube, which removes the media from the
        library. Cytube library only uses id (and not type). A second video
        with the same id (and different type) can never be added to the
        library. Trying to uncache nonexistent video 2 will inadvertently 
        uncache video 1. Chance of this happening is close to 0."""
        self.sendf({'name': 'uncache', 'args': {'id': mId}})
        clog.info('(uncache) uncached %s' % mId, syst)

    def processResult(self, res):
        return defer.succeed(res[0][0])

    def _getRank(self, username):
        try:
            return int(self.userdict[username]['rank'])
        except(KeyError):
            clog.error('(_getRank) %s not found in userdict' % username, syst)

    def changeLogLevel(self, level):
        from tools import logger
        import logging
        if level == 'debug':
            logger.logLevel = logging.DEBUG
        elif level == 'warning':
            logger.logLevel = logging.WARNING

    def bulkLogChat(self):
        if self.chatLoop.running:
            #clog.debug('(bulkLogChat) stopping chatLoop', syst)
            self.chatLoop.stop()
        chatlist = self.unloggedChat[:]
        if 30 < len(chatlist) <= 300:
            clog.warning('We are under spam! Blocking commands and relaxing '
                         'heartbeat timeout.', syst)
            self.underSpam = True
            self.changeLogLevel('warning')
            self.hearttime = 60
        elif len(chatlist) > 300:
            clog.warning('We are under HEAVY SPAM! Blocking all subsequent '
                         'chatMsg frames from being processed. They will not '
                         'be logged to the database. Heartbeat timeout has '
                         'been relaxed.', syst)
            self.underSpam = True
            self.underHeavySpam = True
            self.changeLogLevel('warning')
            self.hearttime = 90 
            timeNow = getTime()
            # add a line in chat db
            msg = '***[SPAM BLOCK]*** trigger length = %s' % len(chatlist)
            chatlist.append((None, 1, timeNow, timeNow, msg, None, 2))
            # we need to call this later here since we blocked chat processing
            reactor.callLater(5, self.bulkLogChat)
        else:
            if self.underHeavySpam and self.spamCount > 100:
                clog.warning('We are still experiencing heavy spam.', syst)
                self.spamCount = 0
                reactor.callLater(5, self.bulkLogChat)
            elif (self.underSpam or self.underHeavySpam) and self.spamCount<=99:
                self.spamCount = 0
                self.underSpam = False
                self.underHeavySpam = False
                self.changeLogLevel('debug')
                self.hearttime = 20 
                clog.warning('Spam seems to have subsided. Returning to normal'
                             ' operations.', syst)
        self.unloggedChat = []
        # don't return a deferred here! bad things will happen
        if chatlist:
            return database.bulkLogChat('CyChat', chatlist)
        else:
            return defer.succeed(None)

    def deferredChat(self, res, chatArgs):
        """ Logs chat to database. Since this will be added to the userAdd
        deferred chain, we ensure that the user is given a keyId before database
        insert. This will rarely be triggered since a user must join and
        immediatly chat before they are queried or written to the user database.
        res is the key id from lastrowid or itself"""
        keyId = res
        dd = database.insertChat(None, keyId, *chatArgs)
        # this inner deferred ensures that the outer deferred's response
        # is always a keyId, in case we need to keep chaining more chat log
        # callbacks.
        dd.addCallback(self.deferredChatRes, keyId)
        dd.addErrback(self.errcatch)

    def deferredChatRes(self, res, key):
        if not res:
            clog.info('(deferredChatRes): wrote chat to database!', syst)
            return defer.succeed(key)
        else:
            clog.err('(deferredChatRes): error writing to database!', syst)
            return defer.fail(key)

    def _cyCall_addUser(self, fdict):
        user = fdict['args'][0]
        timeNow = getTime()
        if user['name'] not in self.userdict:
            self.userJoin(user, timeNow)
        for key, method in self.triggers['userjoin'].iteritems():
            method(self, fdict)
        self.factory.handle.recCyUserJoin(user['name'], user['rank'])

    def userJoin(self, user, timeNow):
        clog.info(user, syst)
        user['keyId'] = None
        user['timeJoined'] = timeNow
        # command throttle
        user['cthrot'] = {'net': 9, 'max':min(user['rank']*12+5,30), 
                          'last': time.time()}
        user['lastCommand'] = time.time()
        self.userdict[user['name']] = user
        self.userdict[user['name']]['subscribeLike'] = False
        reg = self.checkRegistered(user['name'])
        d = database.dbQuery(('userId',), 'cyUser',
                         nameLower=user['name'].lower(), registered=reg)
        d.addCallback(database.queryResult)
        values = (None, user['name'].lower(), reg, user['name'], 0, 0,
                  None, None)
        d.addErrback(database.dbInsertReturnLastRow, 'cyUser', *values)
        d.addCallback(self.cacheKey, user)
        d.addErrback(self.errcatch)
        # add a reference to the deferred to the userdict
        self.userdict[user['name']]['deferred'] = d

	profileText, profileImgUrl = (None, None)
        if user.get('profile'):
            profileText = user['profile'].get('text')
            profileImgUrl = user['profile'].get('image')
        d.addCallback(self.updateProfile, profileText, profileImgUrl)
        
    def updateProfile(self, userId, profileText, profileImgUrl):
        d = database.updateProfile(userId, profileText, profileImgUrl)
        d.addCallback(lambda __: defer.succeed(userId))
        return d

    def cacheKey(self, res, user):
        assert res, 'no res at cacheKey'
        if res[0]:
            clog.debug("(cacheKey) cached %s's key %s" % (user['name'], res[0]),
                      syst)
            self.userdict[user['name']]['keyId'] = res[0]
        return defer.succeed(res[0])

    def userLeave(self, keyId, leftUser, timeNow):
        userId = leftUser['keyId']
        assert userId == keyId, ('KeyId mismatch at userleave! %s, %s' %
                                                        (userId, keyId))
        timeJoined = leftUser['timeJoined']
        clog.debug('(userLeave) userId %s left: %d. Logging to database' %
                                                         (keyId, timeNow), syst)
        d = database.insertUserInOut(keyId, timeJoined, timeNow)
        d.addCallback(lambda __: defer.succeed(keyId))
        d.addErrback(self.errcatch)
        return d

    def _cyCall_userLeave(self, fdict):
        timeNow = getTime()
        username = fdict['args'][0]['name']
        if not username:
            return # when anon leaves, might be sync bug
        try:
            d = self.userdict[username]['deferred']
        except(KeyError):
            # when long staying users leave sometimes we get 
            # more than one userLeave frame
            clog.error('_cyCall_userLeave %s does not exist!' % username)
            return
        except(AttributeError):
            clog.error('userLeave called before initialization! %s' % username)
            return
        clog.debug('_cyCall_userLeave) user %s has left. Adding callbacks' 
                   % username, syst)
        leftUser = self.userdict[username]
        d.addCallback(self.userLeave, leftUser, timeNow)
        d.addErrback(self.errcatch)
        self.removeUser(None, username) # remove user immediatley
        self.factory.handle.recCyUserLeave(username)

        for key, method in self.triggers['userleave'].iteritems():
            method(self, fdict)

    def removeUser(self, res, username):
        clog.debug('(removeUser) Removing user', syst)
        try:
            del self.userdict[username]
            clog.debug('(removeUser) deleted %s' % username, syst)
        except(KeyError):
            clog.error('(removeUser) Failed: user %s not in userdict' % username, syst)

    def _cyCall_userlist(self, fdict):
        if time.time() - self.lastUserlistTime < 3: # most likely the same userlist
             # with ip/aliases if mod+
            clog.error('(_cy_userlist) Duplicate userlist detected', syst)
            return
        self.lastUserlistTime = time.time()
        userlist = fdict['args'][0]
        timeNow = getTime()

        # make a dictonary of users
        self.userdict = {}
        for user in userlist:
            user['timeJoined'] = timeNow
            self.userdict[user['name']] = user
            self.userJoin(user, timeNow)

        # send userlist info to status IRC channel
        self.factory.handle.recCyUserlist(self.userdict)

    def _cyCall_playlist(self, fdict):
        """ Cache the playlist in memory, and write them to the media table """
        # For each item in the playlist, assign a queueId. If no queue can be
        # found, (media added while bot was not online), then Yukari adds a
        # queue and uses that queueId.
        # We don't add all media to the queue table automatically since it'll
        # end up adding multiple times each join/restart during shuffle.
        # Cytube also re-sends the playlist when the permission is changed
        self.playlist = []
        pl = fdict['args'][0]
        if not pl:
            clog.warning('(_cyCall_playlist) The playlist was cleared!', syst)
            self.nowPlayingUid = -1
            self.nowPlayingMedia = {}
        else:
            clog.debug('(_cyCall_playlist) received playlist from Cytube', syst)
            dbpl, qpl = [], []
            for entry in pl:
                entry['qDeferred'] = defer.Deferred()
                self.playlist.append(entry)
                if entry['media']['type'] != 'cu': # custom embed
                    dbpl.append((None, entry['media']['type'],
                                 entry['media']['id'],entry['media']['seconds'],
                                 entry['media']['title'], 1, 0))
                                #'introduced by' Yukari
                    qpl.append((entry['media']['type'], entry['media']['id'],
                                entry['uid']))
            d = database.bulkLogMedia(dbpl)
            self.findQueueId(qpl)

        # for playlist plugins
        for key, method in self.triggers['playlist'].iteritems():
            method(self, pl)

    def findQueueId(self, qpl):
        for mType, mId, uid in qpl:
            d = database.queryLastQueue(mType, mId)
            i = self.getIndexFromUid(uid)
            self.playlist[i]['qDeferred'] = d
            d.addCallback(self.obtainQueueId, mType, mId)
            d.addCallback(self.assignQueueId, uid)
            #d.addCallback(lambda x: clog.info('obtained queueId %s' % x, syst))

    def obtainQueueId(self, res, mType, mId):
        clog.debug('(checkQueueId) res is %s' % res, syst)
        if not res: # there is no queue history
            d = database.queryMediaId(mType, mId)
            # 1 = Yukari, 2 = flag for this type of queue
            d.addCallback(lambda x: defer.succeed(x[0][0]))
            d.addCallback(database.insertQueue, 1, getTime(), 2)
            return d
        elif res:
            return defer.succeed(res[0])

    def assignQueueId(self, res, uid):
        queueId = res[0]
        i = self.getIndexFromUid(uid)
        self.playlist[i]['qid'] = queueId 
        return defer.succeed(queueId)

    def addToPlaylist(self, item, afterUid):
        if afterUid == 'prepend':
            index = 0
        else:
            index = self.getIndexFromUid(afterUid)
        self.playlist.insert(index + 1, item)
        clog.debug('(addToPlaylist) Inserting uid %s %s after index %s' %
                   (item['uid'], item['media']['title'], index), syst)

    def movePlaylistItems(self, beforeUid, afterUid):
        # 'before' is just the uid of the video that is going to move
        clog.info('(movePlaylistItems) move uid:%s, after uid%s' %
                  (beforeUid, afterUid), syst)
        if afterUid == 'prepend':
            indexAfter = 0
        else:
            indexAfter = self.getIndexFromUid(afterUid)
        indexBefore = self.getIndexFromUid(beforeUid)
        if indexBefore > indexAfter and afterUid != 'prepend':
            indexAfter += 1
        self.playlist.insert(indexAfter, self.playlist.pop(indexBefore))

    def getIndexFromUid(self, uid):
        """ Return video index of self.playlist given an UID """
        try:
            media = (i for i in self.playlist if i['uid'] == uid).next()
            index =  self.playlist.index(media)
            #clog.debug('(getIndexFromUid) Looking up uid %s, index is %s'
            #            % (uid, index), syst)
            return index
        except StopIteration as e:
            clog.error('(getIndexFromUid) media UID %s not found' % uid, syst)

    def getUidFromTypeId(self, mType, mId):
        # TODO deal with duplicate media
        for media in self.playlist:
            if media['media']['id'] == mId:
                if media['media']['type'] == mType:
                    return media['uid']

    def _cyCall_queue(self, fdict):
        timeNow = getTime()
        item = fdict['args'][0]['item']
        isTemp = item['temp']
        media = item['media']
        queueby = item['queueby']
        title = media['title']
        afterUid = fdict['args'][0]['after']
        mType = media['type']
        mId = media['id']
        uid = item['uid']
        self.addToPlaylist(item, afterUid)

        flag = 0
        # Optional: return flag value
        for key, method in self.triggers['queue'].iteritems():
            bit = method(self, fdict)
            if bit:
                flag += bit

        if queueby: # anonymous add is an empty string
            userId = self.userdict[queueby]['keyId']
        else:
            userId = 3
        if userId:
            d = self.queryOrInsertMedia(media, userId)
        else:
            clog.error('(_cyCall_queue) user id not cached.', syst)
            return
        if isTemp:
            flag += 1
        d.addCallback(self.writeQueue, userId, timeNow, flag, uid)
        i = self.getIndexFromUid(uid)
        self.playlist[i]['qDeferred'] = d

    def splitResults(self, defer1, defer2):
        """ Results of defer1 are sent to defer2 """
        def split(val):
            # pass val to defer2 chain
            defer2.callback(val)
            # return val to defer1 chain
            return val
        defer1.addCallback(split)

    def _cyCall_delete(self, fdict):
        for key, method in self.triggers['delete'].iteritems():
            method(self, fdict)
        uid = fdict['args'][0]['uid']
        index = self.getIndexFromUid(uid)
        deletedMedia = self.playlist.pop(index)
        clog.info('(_cyCall_delete) Removed uid %s, index %s from my playlist' %
                  (uid, index), syst)
        assert uid == deletedMedia['uid'], 'Deleted media not correct!'

        # if there is a replay-poll active, and its media gets deleted,
        # it will automatically changeMedia, so we don't need to do anything
        
        # edge case of last media being deleted
        if not self.playlist:
            self.nowPlayingUid = -1
            self.nowPlayingMedia = None

    def queryOrInsertMedia(self, media, userId):
        d = database.dbQuery(('mediaId',) , 'Media', type=media['type'],
                             id=media['id'])
        d.addCallback(database.queryResult)
        values = (None, media['type'], media['id'], media['seconds'],
                  media['title'], userId, 0)
        d.addErrback(database.dbInsertReturnLastRow, 'Media', *values)
        return d

    def writeQueue(self, res, userId, timeNow, flag, uid):
        """ Insert queue into Queue. """
        mediaId = res[0]
        dd = database.insertQueue(mediaId, userId, timeNow, flag)
        dd.addCallback(self.saveQueueId, mediaId, uid)
        return dd

    def saveQueueId(self, res, mediaId, uid):
        queueId = res[0]
        clog.info('(saveQueueId) QId of uid %s is %s' % (uid, queueId), syst)
        i = self.getIndexFromUid(uid)
        if i is not None:
              # None when media is already gone from Yukari's playlist
              # ie autodelete from blacklist
            self.playlist[i]['qid'] = queueId 
        return defer.succeed(queueId)
        
    def printRes(self, res):
        clog.info('(printRes) %s' % res, syst)
        return defer.succeed(res)
        
    def errYtInfo(self, err):
        clog.error('(errYtInfo) %s' % err, syst)

    def dbErr(self, err):
        clog.error('(dbErr): %s' % err.value, syst)

    def emitBulkJs(self, results):
        js = []
        for result in results:
            if result[0]: # True if deferred succeeded
                resultname = result[1][0]
                strjs = result[1][1]
                self.currentJs[resultname] = strjs
                js.append(strjs)
        #self.doSendChat((';'.join(js)+';'))
        self.doSendJs((';'.join(js)+';'))

    def _cyCall_setCurrent(self, fdict):
        """ Lets us know which media is being played, by its uid.
        We use this instead of changeMedia because it is the only way to know
        which media is playing if there are duplicates. setCurrent is sometimes
        called when media is not changed, such as when the permission is 
        updated """
        uid = fdict['args'][0]
        self.nowPlayingUid = uid
        i = self.getIndexFromUid(uid)
        if i is None:
            return
        media = self.playlist[i]['media']
        mType = media['type']
        mId = media['id']
        mTitle = media['title']

        self.nowPlayingUid = fdict['args'][0]
        ## fix later, recreate fdict for now
        fdict = {'args':[media]}

        # Reset cancelSetCurrentJs
        # Plugins that use scjs may change it to True
        self.cancelSetCurrentJs= False

        # Check self.playlist for the media's qDeferred.
        # if it shows a value (qId), then we can proceed
        # If it does not have a value yet, that means the
        # media and queue db writes are not ready- We must add a callback
        # for our changeMedia triggers
        qD = self.playlist[i]['qDeferred']
        try:
            qId = qD.result
        except(AttributeError, ValueError):
            clog.warning('qId for %s, %s is not ready yet. '
                    'Adding as callback' % (mType, mId), syst)
            qD.addCallback(self.cbSetCurrent, fdict) #mType, mId, mTitle, seconds)
            return
        self.cbSetCurrent(None, fdict)

    def cbSetCurrent(self, qid, fdict):
        l = list()
        for method in self.triggers['setCurrent'].itervalues():
            d = method(self, fdict)
            if d:
                l.append(d)
        #clog.error('list is %s' % l, syst)
        scDeferredList = defer.DeferredList(l)
        scDeferredList.addCallback(self.setCurrentJs, fdict)#mType, mId, mTitle) 
        if qid: # came as a deferred, give back the qId
            return qid

    def _cyCall_changeMedia(self, fdict):
        """ Called when the media is changed. This is different from setCurrent
        in that it only provides the media information (and no uid).
        Thus, it should only be used for tracking media related changes, such
        as time left. """
        # set self.nowPlayingMedia
        media = fdict['args'][0]
        mType = media['type']
        mId = media['id']
        mTitle = media['title']
        self.nowPlayingMedia = fdict['args'][0]
        nps = (mType, mId, mTitle) # these are unicode
        # everything has to be encoded to utf-8 or it errors
        s = mTitle.encode('utf-8') + ' (%s, %s)' % (mType.encode('utf-8'),
                          mId.encode('utf-8'))
        clog.debug('(cy_changeMedia): %s' %s, syst)

        # reset remaining time
        self.mediaRemainingTime = fdict['args'][0]['seconds']

    def setCurrentJs(self, ignored, fdict):# mType, mId, mTitle):
        if self.cancelSetCurrentJs:
            clog.error('setCurrentJs was cancelled.', syst)
            return

        # run setCurrentJs methods
        l = []
        for key, method in self.triggers['scJs'].iteritems():
            l.append(method(self, fdict))#mType, mId))
        jsDeferredList = defer.DeferredList(l)
        jsDeferredList.addCallback(self.emitBulkJs)

        media = fdict['args'][0]
        mType = media['type']
        mId = media['id']
        mTitle = media['title']
        # send now playing info to seconday IRC channel
        self.factory.handle.recCyChangeMedia((mType, mId, mTitle))

    def jumpToMedia(self, uid):
        clog.debug('(jumpToMedia) Playing uid %s' % uid, syst)
        self.sendf({'name': 'jumpTo', 'args': uid})

    def _cyCall_moveVideo(self, fdict):
        beforeUid = fdict['args'][0]['from']
        afterUid = fdict['args'][0]['after']
        self.movePlaylistItems(beforeUid, afterUid)

    def _cyCall_queueFail(self, fdict):
        for key, method in self.triggers['qfail'].iteritems():
            method(self, fdict)
        args = fdict['args'][0]
        msg = args.get('msg', '')
        link = args.get('link', '')
        clog.warning('(_cyCall_queueFail) %s: %s' % (msg, link), syst)
        # Flag videos when CyTube rejects them.
        # This usually doesn't happen becuase CyTube caches videos to the
        # channel library, and will only check against the service API once.
        # This could happen if the channel is changed or library items are
        # removed which forces CyTube to re-check the video.
        if 'Private video' in msg or 'Video not found' in msg and link:
            if 'http://youtu' in link:
                mType = 'yt'
                m = self.ytUrl.search(link)
                ytId = m.group(6)
                d = database.flagMedia(1, mType, ytId)
                d.addCallback(lambda ignored:
                    clog.warning('Flagged invalid media %s %s' % (mType, ytId)))
    def _cyCall_setTemp(self, fdict):
        for key, method in self.triggers['temp'].iteritems():
            method(self, fdict)

    def cleanUp(self):
        tools.cleanLoops(self.loops)
        tools.cleanLaters(self.laters)
        cleanDeferredList = []
        # log unlogged chat
        cleanDeferredList.append(self.bulkLogChat())
        # log everyone's access time before shutting down
        self.logUserInOut(cleanDeferredList)
        return defer.DeferredList(cleanDeferredList)

    def logUserInOut(self, l):
        """Add user login logout database writes deferreds to 
        cleanDeferredList"""
        timeNow = getTime() 
        for name, user in self.userdict.iteritems():
            l.append(user['deferred'].addCallback(self.userLeave, user, timeNow))
        # no need to return anything since it is manipulating a list

    def checkRegistered(self, username):
        """ Return wether a Cytube user is registered (1) or a guest (0) given
        a username. Checks self.userdict for rank information."""
        if username == '[server]':
            return 1
        else:
            try:
                user = self.userdict[username]
            except KeyError as e:
                clog.error('(checkRegistered): %s' % e, syst)
                return
            if user['rank'] == 0:
                return 0
            else:
                return 1

    def doAddMedia(self, media, temp, pos):
        # Cytube has a throttle for queueing media
        # burst: 10,
        # sustained: 2
        
        lenBefore = len(self.queueMediaList)
        self.queueMediaList.extend(media)
        if time.time() - self.lastQueueTime > 20:
            self.burstCounter = 10
        # burst!
        if self.burstCounter and self.queueMediaList:
            for i in range(min(len(self.queueMediaList), self.burstCounter)):
                mType, mId = self.queueMediaList.popleft()
                self.sendf({'name': 'queue', 'args': {'type': mType, 
                                    'id': mId, 'pos': pos, 'temp': temp}})
                self.burstCounter -= 1
            self.lastQueueTime = time.time()

        def sustainQueue(pos, temp):
            clog.debug('sustainQueue looped', syst)
            if time.time() - self.lastQueueTime < 2: # Prevent queueing too quickly
                return
            else:
                mType, mId = self.queueMediaList.popleft()
                self.sendf({'name': 'queue', 'args': {'type': mType, 
                                            'id': mId, 'pos': pos, 'temp': temp}})
                self.lastQueueTime = time.time()
                if not self.queueMediaList:
                    sustainedLoop.stop()


        # sustain
        if self.queueMediaList:
            sustainedLoop = task.LoopingCall(sustainQueue, pos, temp)
            self.loops.append(sustainedLoop)
            sustainedLoop.start(2.05, now=True)
        
#    def doDeleteMedia(self, mType, mId):
    def doDeleteMedia(self, uid):
        """ Delete media """
        clog.info('(doDeleteMedia) Deleting media uid %s' % uid)
        self.sendf({'name': 'delete', 'args': uid})

class WsFactory(WebSocketClientFactory):
    protocol = CyProtocol

    def __init__(self, arg):
        super(WebSocketClientFactory, self).__init__(arg)
        self.prot = None

    def startedConnecting(self, connector):
        clog.debug('WsFactory started connecting to Cytube..', syst)

    def clientConnectionLost(self, connector, reason):
        clog.warning('(clientConnectionLost) Connection lost. %s' % reason, syst)
        self.handle.cy = False
        self.reconnect(connector, reason)
        self.handle.cyAnnouceLeftRoom()


    def clientConnectionFailed(self, connector, reason):
        self.handle.cy = False
        self.reconnect(connector, reason)
        clog.error('(clientConnectionFailed) Connection failed to Cytube. %s'
                    % reason, syst)

    def doneClean(self, res):
        if self.handle.cyRestart:
        # service interruption - reconnect
            self.handle.restartConnection()
        else:
        # when we are shutting down
            self.handle.doneCleanup('cy')

    def reconnect(self, connector, reason):
        if time.time() - self.handle.cyLastDisconnect > 60:
            self.handle.cyRetryWait = 0
        self.handle.cyLastDisconnect = time.time()
        if self.prot:
            d = self.prot.cleanUp()
            d.addCallback(self.doneClean)
        else: # d/c before establishing protocol
            if self.handle.cyRestart:
                self.handle.restartConnection()
