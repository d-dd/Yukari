# Standard Library
import json, time, re, random, os, importlib
from collections import deque
# Twisted Libraries
from twisted.internet import reactor, defer, task
from twisted.internet.error import AlreadyCalled, AlreadyCancelled
from autobahn.twisted.websocket import WebSocketClientProtocol,\
                                       WebSocketClientFactory
# Yukari
import database, apiClient, tools, vdbapi
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
                        if not i.startswith('_') and i.endswith('.py')])
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
        self.importCyModules()
        self.loops = []
        self.laters = []

        # Wether to run cmJs methods
        # Set this to True for media that is not going to be played
        # and there is no need to lookup information on it.
        # e.g. blacklisted, unplayable, replay, etc.
        self.cancelChangeMediaJs = False
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
        self.activePoll = None
        self.pollState = {}
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
                         'changeMedia': {},
                         'cmJs': {},
                         'commands':{},
                         'playlist': {},
                         'ppm': {},
                         'queue': {},
                         'replay': {},
                         'vote': {},
                                         }

        for module in modules:
            instance = module.setup()
            for method in dir(instance):
                # commands in cytube chat
                if method.startswith('_com_'):
                    trigger = '$%s' % method[5:]
                    self.triggers['commands'][trigger] = getattr(instance, method)
                elif method.startswith('_cm_'):
                    self.triggers['changeMedia'][method] = getattr(instance, method)
                elif method.startswith('_q_'):
                    self.triggers['queue'][method] = getattr(instance, method)
                elif method.startswith('_re_'):
                    self.triggers['replay'][method] = getattr(instance, method)
                elif method.startswith('_cmjs_'):
                    self.triggers['cmJs'][method] = getattr(instance, method)
                elif method.startswith('_ppm_'):
                    trigger = '%%%%%s' % method[5:]
                    self.triggers['ppm'][trigger] = getattr(instance, method)
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
        self.lifeline = reactor.callLater(self.hearttime, self.abandon)
        self.laters.append(self.lifeline)
        self.heartbeat.start(20.0)
        self.initialize()

    def abandon(self):
        """
        Leave the Cytube server because we did not receive a heartbeat reponse
        in time.
        """
        # If we're under spam, it's most likley that spam is builing up a long
        # queue and the heartbeat has yet to be processed
        if self.underSpam or self.underHeavySpam:
            self.lifeline = reactor.callLater(self.hearttime, self.abandon)
            self.laters.append(self.lifeline)
            return
        clog.error('No heartbeat response... Closing Cytube connection.', syst)
        self.sendClose()

    def sendHeartbeat(self):
        self.sendMessage('2')
        # Wait for server's heartbeat response after sendHeartbeat
        # Put the amount of time Yukari should wait for the response
        # Remember that heavy load on the machine often causes
        # schedules to fall behind greatly
        try:
            self.lifeline.reset(self.hearttime - 10)
        # this catches the leftover heartbeat from a disconnected instance
        # (when Yukari reconnects)
        except(AlreadyCalled, AlreadyCancelled):
            pass

    def onMessage(self, msg, binary):
        msg = msg.decode('utf8')
        if binary:
            clog.warning('Binary received: {0} bytes'.format(len(msg)))
            return
        if msg == '3':
            try:
                self.lifeline.reset(self.hearttime + 10)
            except(AlreadyCalled, AlreadyCancelled):
                pass
        if msg.startswith('42'):
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
                
    def searchYoutube(self, msg):
        m = self.ytUrl.search(msg)
        if m:
            ytId = m.group(6)
            clog.debug('(searchYoutube) matched: %s' % ytId, syst)
            d = apiClient.requestYtApi(ytId)
            d.addCallbacks(self.doSendChat, self.errYtInfo)
            d.addErrback(self.errcatch)

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
            self.factory.handle.recCyMsg(username, msg, False, action)

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
        needProcessing = False if action else True
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
                needProcessing = False
                mthd = self.triggers['vote'].get('_vote_' + commandArgs, None)
                if mthd:
                    mthd(self, username, '', source, prot=self)

            elif command in self.triggers['commands']:
                needProcessing = False
                clog.info('Command triggered: %s ; %s' % (command, commandArgs),
                        syst)
                self.triggers['commands'][command](self, username, commandArgs,
                                                   source, prot=self)

        self.factory.handle.recCyMsg(source, username, msg, needProcessing,
                                                                        action) 

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
        # initialize self.pollState if it's Yukari's poll
        if poll['initiator']  == self.name:
            if poll['title'].startswith('Replay'):
                self.pollState = {'type':'replay'}
                if poll['options'] == ['No!', 'Yes!']:
                    self.pollState['order'] = 0
                elif poll['options'] == ['Yes!', 'No!']:
                    self.pollState['order'] = 1

    def _cyCall_updatePoll(self, fdict):
        pollType = self.pollState.get('type', None)
        if pollType == 'replay':
            self.pollState['counts'] = fdict['args'][0]['counts']

    def _cyCall_closePoll(self, fdict):
        self.activePoll = None
        if self.pollState:
            pollState, self.pollState = self.pollState, {}
            try:
                self.pollTimer.cancel()
                self.pollTimer = None
                self.ignorePollResults()
            except(NameError, TypeError, AttributeError):
                clog.warning('No polltimer found', syst)
                self.ignorePollResults()
            except(AlreadyCalled, AlreadyCancelled):
                clog.info('Poll timer already called/cancelled', syst)
                # Poll finished cleanly
                # (plugin, fn, opts)
                fn = self.pollFn[1]
                fn(self, self.pollFn[2], pollState)

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
            database.bulkLogChat('CyChat', chatlist)

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

        profileText = user['profile']['text']
        profileImgUrl = user['profile']['image']
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
        clog.debug('_cyCall_userLeave) user %s has left. Adding callbacks' 
                   % username, syst)
        leftUser = self.userdict[username]
        d.addCallback(self.userLeave, leftUser, timeNow)
        d.addErrback(self.errcatch)
        self.removeUser(None, username) # remove user immediatley

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

    def _cyCall_playlist(self, fdict):
        """ Cache the playlist in memory, and write them to the media table """
        # For each item in the playlist, assign a queueId. If no queue can be
        # found, (media added while bot was not online), then Yukari adds a
        # queue and uses that queueId.
        # We don't add all media to the queue table automatically since it'll
        # end up adding multiple times each join/restart during shuffle.
        # Cytube also re-sends the playlist when the permission is changed
        self.playlist = []
        self.nowPlayingUid = -1
        pl = fdict['args'][0]
        clog.debug('(_cyCall_playlist) received playlist from Cytube', syst)
        dbpl, qpl = [], []
        for entry in pl:
            entry['qDeferred'] = defer.Deferred()
            self.playlist.append(entry)
            if entry['media']['type'] != 'cu': # custom embed
                dbpl.append((None, entry['media']['type'], entry['media']['id'],
                            entry['media']['seconds'], entry['media']['title'],
                            1, 0))
                            #'introduced by' Yukari
                qpl.append((entry['media']['type'], entry['media']['id'], entry['uid']))
        d = database.bulkLogMedia(dbpl)
        self.findQueueId(qpl)
        self.findSonglessMedia(dbpl)

        # if there is a replay-poll active, end it
        if self.pollState.get('type', None) == 'replay':
            self.doClosePoll()

    def findSonglessMedia(self, playlist):
        if vdb:
            d = database.bulkQueryMediaSong(None, playlist)
            d.addCallback(self.requestEmptySongs)

    def requestEmptySongs(self, res):
        timeNow = getTime()
        i = 0
        for media in res:
            mType, mId = media
            if mType == 'yt':
                self.laters.append(reactor.callLater(i, vdbapi.requestSongByPv,
                                    None ,mType, mId, 1, timeNow, 0))
                i += 0.5

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

        for key, method in self.triggers['queue'].iteritems():
            method(self, fdict)

        if queueby: # anonymous add is an empty string
            userId = self.userdict[queueby]['keyId']
        else:
            userId = 3
        if userId:
            d = self.queryOrInsertMedia(media, userId)
        else:
            clog.error('(_cyCall_queue) user id not cached.', syst)
            return
        flag = 1 if isTemp else 0
        d.addCallback(self.writeQueue, userId, timeNow, flag, uid)
       # dq = defer.Deferred()
       # self.splitResults(d, dq) # fired in parallel when d has result
       # d.addCallback(lambda res: res[0])
       # dq.addCallback(self.writeQueue, userId, timeNow, flag, uid)
        i = self.getIndexFromUid(uid)
        self.playlist[i]['qDeferred'] = d

       # dCheck = self.checkMedia(mType, mId)
       # dCheck.addCallback(self.flagOrDelete, media, mType, mId)
       # dCheck = defer.succeed(0)
       # self.verifyMedia(mType, mId)

       # if mType == 'yt' and vdb:
       #     timeNow = getTime()
            # since this callback is added after checkMedia which has a delay,
            # this also gets delayed
       #     dCheck.addCallback(vdbapi.requestSongByPv ,mType, mId, 1, timeNow, 0)
       #     dCheck.addErrback(self.errcatch)

    def splitResults(self, defer1, defer2):
        """ Results of defer1 are sent to defer2 """
        def split(val):
            # pass val to defer2 chain
            defer2.callback(val)
            # return val to defer1 chain
            return val
        defer1.addCallback(split)

    def checkFlag(self, res, mType, mId):
        """ Check flag for omit or blacklist """
        return self.verifyMedia(mType, mId)
    ###
        if not res:
            clog.error('(continueBlacklist) Media not found!', syst)
        else:
            if res[0][0] & 4: # blacklisted
                self.doDeleteMedia(mType, mId)
                return
            elif res[0][0] & 2: # omitted
                self.currentOmitted = True
            else:
                self.currentOmitted = False
            return self.verifyMedia(mType, mId)

    def checkMedia(self, mType, mId):
        d = database.getMediaFlag(mType, mId)
        d.addCallback(self.checkFlag, mType, mId)
        return d

    def verifyMedia(self, mType, mId):
        if mType == 'yt':
            self.ytq.append(mId)
            d = task.deferLater(reactor, 1 * (len(self.ytq)-1), 
                                self.collectYtQueue, mId)
            clog.debug('(checkMedia) Length of ytq %s' % len(self.ytq), syst)
            return d
        else:
            return defer.succeed('EmbedOk') # TODO

    def flagOrDelete(self, res, media, mType, mId):
        if res == 'EmbedOk':
            database.unflagMedia(0b1, mType, mId)

        elif res == 'Status503':
            clog.error('(flagOrDelete) Youtube service unavailable.', syst)

        elif res == 'NetworkError':
            clog.error('(flagOrDelete) There was a network error.', syst)

        elif res in ('NoEmbed', 'Status403', 'Status404'):
            self.doDeleteMedia(media['type'], media['id'])
            mediaTitle = media['title'].encode('utf-8')
            msg = wisp('Removing non-playable media %s' % mediaTitle)
            database.flagMedia(0b1, mType, mId)
            self.doSendChat(msg, toIrc=False)
            clog.info(msg)

        return res

    def collectYtQueue(self, mId):
        # need another function because popleft() evaluates immediatly
        return apiClient.requestYtApi(self.ytq.popleft(), 'check')

    def _cyCall_delete(self, fdict):
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
        clog.warning(fdict)
        self.nowPlayingUid = fdict['args'][0]

    def _cyCall_changeMedia(self, fdict):
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

        clog.info('(_cyCall_changeMedia) %s' % s, syst)
        
        # Reset cancelChangeMediaJs
        # Plugins that use cmjs may change it to True
        self.cancelChangeMediaJs = False

        # Check self.playlist for the media's qDeferred.
        # if it shows a value (qId), then we can proceed
        # If it does not have a value yet, that means the
        # media and queue db writes are not ready- We must add a callback
        # for our changeMedia triggers
        index = self.getIndexFromUid(self.nowPlayingUid)
        if self.playlist[index]['media']['id'] != mId:
            clog.error('changeMedia setCurrent mismatch!', syst)
        qD = self.playlist[index]['qDeferred']
        try:
            qId = qD.result
           # clog.error('qDresult: %d' % int(qD.result), syst)
        except(AttributeError, ValueError):
            clog.error('qId is not ready yet. Adding as callback', syst)
            qD.addCallback(self.changeMedia, fdict) #mType, mId, mTitle, seconds)
            return
        self.changeMedia(None, fdict) #mType, mId, mTitle, seconds)

    def changeMedia(self, qid, fdict):#qid, mType, mId, mTitle, seconds):
        l = list()
        for method in self.triggers['changeMedia'].itervalues():
            l.append(method(self, fdict)) # mType, mId, mTitle))
        clog.error('list is %s' % l, syst)
        cmDeferredList = defer.DeferredList(l)
        cmDeferredList.addCallback(self.changeMediaJs, fdict)#mType, mId, mTitle) 
        cmDeferredList.addCallback(self.resetRemainingTime, fdict) #seconds)
        if qid: # came as a deferred, give back the qId
            return qid

    def resetRemainingTime(self, ignored, fdict):
        # set remaining time to the duration of the media
        # otherwise this will be outdated until the first mediaUpdate tick
        # do this here instead of changeMedia to give $replay a chance to 
        # check time before the it is reset.
        self.mediaRemainingTime = fdict['args'][0]['seconds']

    def changeMediaJs(self, ignored, fdict):# mType, mId, mTitle):
        if self.cancelChangeMediaJs:
            clog.error('changeMediaJs was cancelled.', syst)
            return

        # run changeMedia JS methods
        l = []
        for key, method in self.triggers['cmJs'].iteritems():
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

    def cleanUp(self):
        # set restart to False
        self.factory.handle.cyRestart = False
        # disconnect first so we don't get any more join/leaves
        self.sendClose()
        # log unlogged chat
        self.bulkLogChat()
        # log everyone's access time before shutting down
        dl = self.logUserInOut()
        dl.addCallback(self.doneClean)

    def doneClean(self, res):
        self.factory.handle.doneCleanup('cy')

    def logUserInOut(self):
        timeNow = getTime() 
        l = []
        for name, user in self.userdict.iteritems():
            l.append(user['deferred'].addCallback(self.userLeave, user, timeNow))
        return defer.DeferredList(l)

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
        WebSocketClientFactory.__init__(self, arg)

    def startedConnecting(self, connector):
        clog.debug('WsFactory started connecting to Cytube..', syst)

    def clientConnectionLost(self, connector, reason):
        clog.warning('(clientConnectionLost) Connection lost. %s' % reason, syst)
        self.reconnect(connector, reason)
        self.handle.cyAnnouceLeftRoom()


    def clientConnectionFailed(self, connector, reason):
        self.reconnect(connector, reason)
        clog.error('(clientConnectionFailed) Connection failed to Cytube. %s'
                    % reason, syst)

    def reconnect(self, connector, reason):
        self.handle.cy = False
        if time.time() - self.handle.cyLastDisconnect > 60:
            self.handle.cyRetryWait = 0
        self.handle.cyLastDisconnect = time.time()
        try:
            self.prot.logUserInOut()
            tools.cleanLoops(self.prot.loops)
            tools.cleanLaters(self.prot.laters)
        except(AttributeError):
            clog.warning(('clientConnectionLost: cannot logUserInOut().'
                         ' "prot" does not exist.', syst))
            # prot doesn't exist yet
        if self.handle.cyRestart:
            clog.error('clientConnectionLost! Reconnecting in %d seconds'
                       % self.handle.cyRetryWait, syst)
            # reconnect
            self.handle.restartConnection()
