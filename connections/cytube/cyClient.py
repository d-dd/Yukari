# Standard Library
import json, time, re, argparse, random, urlparse
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

def wisp(msg):
    """Decorate msg with system-whisper trigger"""
    return '@3939%s#3939' % msg

class CyProtocol(WebSocketClientProtocol):
    start_init = []

    def __init__(self):
        self.name = config['Cytube']['username']
        self.unloggedChat = []
        self.chatLoop = task.LoopingCall(self.bulkLogChat)
        self.lastChatLogTime = 0
        self.receivedChatBuffer = False
        self.queueMediaList = deque()
        self.burstCounter = 0
        self.lastQueueTime = time.time() - 20 #TODO
        self.nowPlayingMedia = {}
        self.currentLikes = []
        self.err = []
        self.currentVocadb = ''
        self.currentLikeJs = ''
        self.currentOmitted = False
        ### Need to imporve this regex, it matches non-videos
        # ie https://www.youtube.com/feed/subscriptions
        self.ytUrl = re.compile(
                (r'(https?://)?(www\.)?(youtube|youtu|youtube-nocookie)\.'
                  '(com|be)/(watch\?v=|embed/|v/|.+\?v=)?([^&=%\?]{11})'))
        self.ytq = deque()
        self.activePoll = None
        self.pollState = {}
        self.usercount = 0
        self.willReplay = False
        self.mediaRemainingTime = 0
        for fn in CyProtocol.start_init:
            fn(self)

    def errcatch(self, err):
        clog.error('caught something')
        err.printTraceback()
        self.err.append(err)

    def onOpen(self):
        clog.info('(onOpen) Connected to Cytube!', syst)
        self.connectedTime = time.time()
        self.lastUserlistTime = 0
        self.factory.prot = self
        self.factory.handle.cy = True
        self.initialize()

    def onMessage(self, msg, binary):
        if msg == '2::':
            self.sendMessage(msg) # return heartbeat
        elif msg.startswith('5:::{'):
            fstr = msg[4:]
            fdict = json.loads(fstr)
            #if fdict['name'] in ('chatMsg', 'userlist', 'addUser', 'userLeave'):
                #print fstr
            self.processFrame(fdict)

    def onClose(self, wasClean, code, reason):
        clog.info('(onClose) Closed Protocol connection: %s' % reason, syst)

    def sendf(self, dict): # 'sendFrame' is a WebSocket method name
        frame = json.dumps(dict)
        frame = '5:::' + frame
        clog.debug('(sendf) [->] %s' % frame, syst)
        self.sendMessage(frame)

    def doSendChat(self, msg, source='chat', username=None, modflair=False,
                   toIrc=True):
        clog.debug('(doSendChat) msg:%s, source:%s, username:%s' % (msg, 
                   source, username), syst)
        if source == 'chat':
            if modflair:
                modflair = 3 ### TODO remove hardcode rank
                msg = '+' + msg
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
        pass

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
            reactor.callLater(10, self.factory.handle.sendToIrc, msg)
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
        self.checkCommands(username, msg, shadow, action)

    def logChatMsg(self, username, chatCyTime, msg, modflair, flag, timeNow):
        # logging chat to database
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
    def checkCommands(self, username, msg, shadow, action):
        # check for commands
        # strip HTML tags
        thunk = None
        msg = tools.strip_tag_entity(msg)
        if msg.startswith('$') and not shadow:
            # unescape to show return value properly ([Ask: >v<] Yes.)
            msg = tools.unescapeMsg(msg)
            thunk, args, source = self.checkCommand(username, msg, 'chat')
            # send to yukari.py
        if username != self.name and username != '[server]' and not shadow:
            needProcessing = not thunk
            if thunk is False: # non-ascii command
                needProcessing = False
            #clog.debug('Sending chat to IRC, username: %s' % username)
            self.factory.handle.recCyMsg(username, msg, needProcessing, 
                                                         action=action)
            # send to IRC before executing the command
            # to maintain proper chat queue (user command before Yukari's reply)
            if thunk:
                thunk(username, args, 'chat')

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
        self.processPm(username, msg)

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

    def processPm(self, username, msg):
        if msg.startswith('%%'):
            if msg == '%%subscribeLike':
                clog.debug('Received subscribeLike from %s' % username, syst)
                if username in self.userdict:
                    self.userdict[username]['subscribeLike'] = True
                    # send value for current media
                    if username in self.currentLikes:
                        msg = '%%%%%s' % self.currentLikes[username]
                        self.doSendPm(msg, username)
            elif msg == '%%like':
                self._com_like(username, None, 'ppm')
            elif msg == '%%unlike':
                self._com_unlike(username, None, 'ppm')
            elif msg == '%%dislike':
                self._com_dislike(username, None, 'ppm')

        elif msg.startswith('$') and username != self.name:
            thunk, args, source = self.checkCommand(username, msg, 'pm')
            if thunk:
                thunk(username, args, 'pm')

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
                self.actPollResults(pollState)

    def actPollResults(self, pollState):
        if pollState['type'] == 'replay':
            order = pollState['order']
            counts = pollState.get('counts', None)
            if not counts:
                return
            if order == 0:
                yes = counts[1]
                no = counts[0]
            elif order == 1:
                yes = counts[0]
                no = counts[1]
            if not no and not yes:
                # no votes at all; happens when users rejoin, losing their vote
                return
            elif not no and yes:
                self.setToReplay()
            else:
                if yes/no >= 3:
                    self.setToReplay()

    def ignorePollResults(self):
        msg = 'Poll has been interrupted by a user. Disregarding results.'
        self.doSendChat(wisp(msg), toIrc=False)

    def _cyCall_mediaUpdate(self, fdict):
        currentTime = fdict['args'][0]['currentTime']
        totalTime = self.nowPlayingMedia['seconds']
        self.mediaRemainingTime = totalTime - currentTime

    def checkCommand(self, username, msg, source):
        command = msg.split()[0][1:]
        try:
            clog.info('(checkCommand) received %s command %s from %s' %
                        (source, command, username), syst)
        except(UnicodeDecodeError):
            clog.warning('(checkCommand) received non-ascii command', syst)
            return False, None, source

        argsList = msg.split(' ', 1)
        if len(argsList) == 2:
            args = argsList[1]
        else:
            args = None
        try:
            thunk = getattr(self, '_com_%s' % (command,), None)
        except(UnicodeEncodeError):
            clog.warning('(checkCommand) received non-ascii command(2)', syst)
            return False, None, source

        return thunk, args, source
            
        
    def _com_replay(self, username, args, source):
        if source != 'chat':
            return
        rank = self._getRank(username)
        if rank < 2:
            return
        if self.willReplay:
            self.doSendChat(wisp('Cancelled replay.'), toIrc=False)
            self.willReplay = False
            return

        # if there is a replay poll, end it
        if self.pollState.get('type', None) == 'replay':
            self.doClosePoll()
        self.setToReplay()

    def setToReplay(self):
        title = self.nowPlayingMedia['title']
        self.willReplay = (self.nowPlayingMedia['type'], 
                          self.nowPlayingMedia['id'], title)
        self.doSendChat(wisp('%s has been set to replay once.' % title),
                                                            toIrc=False)

    def _com_repeat(self, username, args, source):
        # alias to replay
        self._com_replay(username, args, source)

    def _com_vote(self, username, args, source):
        if source != 'chat':
            return
        rank = self._getRank(username)
        if rank < 2:
            return
        if not args:
            return
        if self.activePoll:
            self.doSendChat('There is an active poll. Please end it first.',
                            toIrc=False)
            return
        if args == 'replay':
            if self.willReplay:
                msg = wisp('This is already set to replay.')
                self.doSendChat(msg, toIrc=False)
            elif self.mediaRemainingTime > 30:
                self.makeReplayPoll()
            elif self.mediaRemainingTime <= 30:
               self.doSendChat('There is no time left for a poll.', toIrc=False)

    def makeReplayPoll(self):
        """ Make a poll asking users if they would like the current video
        to be replayed """
        boo = random.randint(0, 1)
        pollTime = min(int(self.mediaRemainingTime - 12), 100)
        opts = ('Yes!', 'No!') if boo else ('No!', 'Yes!')
        target = '3:1' if boo else '1:3'
        self.doMakePoll('Replay %s? (%s to replay, vote time: %s seconds)' % 
                        (self.nowPlayingMedia['title'], target, pollTime), 
                                                    False, False, opts)

        self.pollTimer = reactor.callLater(max(pollTime-5, 0), 
                                                      self.announceTimer)

    def doMakePoll(self, title, obscured, timer, *args):
        self.sendf({'name': 'newPoll', 'args': {'title': title,
                    'opts': args[0], 'obscured': obscured}})

    def announceTimer(self):
        self.pollTimer = reactor.callLater(5, self.doClosePoll)
        self.doSendChat('Poll is ending in 5 seconds!', toIrc=False)

    def doClosePoll(self):
        self.sendf({'name': 'closePoll'})

    def _com_vocadb(self, username, args, source):
        if not vdb:
            return
        if args is None:
            mType = self.nowPlayingMedia['type']
            mId = self.nowPlayingMedia['id']
            d = database.getSongId(mType, mId)
            d.addCallback(self.checkVocadbCommand, mType, mId)
            return
        try:
            songId = int(args)
        except IndexError:
            clog.warning('(_com_vocadb) Index Error by %s' % username, syst)
            return
        except ValueError:
            clog.warning('(_com_vocadb) Value Error by %s' % username, syst)
            return
        userId = self.userdict[username]['keyId']
        timeNow = getTime()
        mType = self.nowPlayingMedia['type']
        mId = self.nowPlayingMedia['id']
        d = vdbapi.requestSongById(mType, mId, songId, userId, timeNow, 4)
        # method 4 = manual set
        d.addCallback(self.loadVocaDb, mType, mId)

    def checkVocadbCommand(self, res, mType, mId):
        # no match or connection error
        #clog.debug('checkVdbCommand: %s' % res[0][0], syst)
        if res[0][0] < 1:
            # TODO do a full request 
            return
        else:
            d = vdbapi.requestApiBySongId(None, res[0][0], getTime())
            d.addCallback(self.loadVocaDb, mType, mId)

    def parseTitle(self, command):
        # argparse doesn't support spaces in arguments, so we search
        # and parse the -t/ --title values in msg ourselves
        tBeg = command.find('-t ')
        if tBeg == -1:
            return None, command
        tBeg += 3
        tEnd = command.find(' -', tBeg)
        if tEnd == -1:
            tEnd = len(command)
        shortMsg = command[:tBeg-3] + command[tEnd+1:]
        title = tools.returnUnicode(command[tBeg:tEnd])
        return title, shortMsg

    def _com_add(self, username, args, source):
        if source != 'chat':
            return
        rank = self._getRank(username)
        if not rank:
            return
        elif rank < 2:
            maxAdd = 5
        else:
            maxAdd = 20
        if args is None:
            args = '-n 3'
        #clog.info(args, syst)
        title, arguments = self.parseTitle(args)
        args = arguments.split()

        # shortcut in case people want to $add #
        # of course this can't be combined with other args
        try:
            num = int(args[0])
            args = ['-n', str(num)]

        except(ValueError, IndexError):
            pass
        
        parser = argparse.ArgumentParser()
        parser.add_argument('-s', '--sample', default='queue', 
                            choices=('queue', 'q', 'add', 'a', 'like', 'l'))
        parser.add_argument('-u', '--user', default='Anyone')
        parser.add_argument('-g', '--guest', default=False, type=bool)
        parser.add_argument('-n', '--number', default=3, type=int)
        parser.add_argument('-a', '--artist', default='') #TODO
        parser.add_argument('-T', '--temporary', default=False, type=bool)
        parser.add_argument('-N', '--next', default=False, type=bool)
        parser.add_argument('-o', '--omit', default=False, type=bool)

        try:
            args = parser.parse_args(args)
        except(SystemExit):
            self.doSendChat('Invalid arguments.')
            return

        args.number = min(args.number, maxAdd)
        if rank < 2:
            args.omit = False

        info = ('Quantity:%s, sample:%s, user:%s, guest:%s, temp:%s, '
                'pos:%s, title:%s, include ommited:%s'
                % (args.number, args.sample, args.user, args.guest,
                   args.temporary, args.next, title, args.omit))
        #self.doSendChat(reply)
        clog.debug('(_com_add) %s' % info, syst)
        isRegistered = not args.guest

        if args.next:
            args.next = 'next'
        else:
            args.next = 'end'
        args.user = args.user.lower()
        if args.user == 'anyone':
            args.user = None
        
        self.getRandMedia(args.sample, args.number, args.user, isRegistered,
                          title, args.temporary, args.next)

    def _com_omit(self, username, args, source):
        self._omit(username, args, 'flag', source)

    def _com_unomit(self, username, args, source):
        self._omit(username, args, 'unflag', source)

    def _com_blacklist(self, username, args, source):
        rank = self._getRank(username)
        clog.info('(_com_blacklist) %s' % args)
        if rank < 3:
            return
        parsed = self._omit_args(args)
        if not parsed:
            self.doSendChat('Invalid parameters.')
        elif parsed:
            mType, mId = parsed
            database.flagMedia(4, mType, mId)
            self.doDeleteMedia(mType, mId)

    def _com_greet(self, username, args, source):
        isReg = self.checkRegistered(username)
        d = database.getUserFlag(username.lower(), isReg)
        d.addCallback(self.greet, username, isReg, source)
        d.addErrback(self.errcatch)

    def _com_points(self, username, args, source):
        if source != 'pm':
            return
        querier = username
        # if admin+ pm's $points user, yukari will pm back user's points
        if args and source == 'pm':
            if self._getRank(username) >= 3:
               username = args
        reg = self.checkRegistered(username)
        if reg is None:
            # assume registered
            reg = 1
        d1 = self.calculatePoints(username, reg)
        d2 = self.calculateStats(username, reg)
        dl = defer.DeferredList([d1, d2])
        dl.addCallback(self.returnPoints, querier, username, source)
        dl.addErrback(self.errcatch)

    def _com_read(self, username, args, source):
        if source != 'pm':
            return
        # people who read the readme/this
        if self.checkRegistered(username):
            d = database.flagUser(2, username.lower(), 1)

    def _com_enroll(self, username, args, source):
        if source != 'pm':
            return
        if self.checkRegistered(username):
            d = database.flagUser(4, username.lower(), 1)

    def _com_like(self, username, args, source):
        if source == 'pm' or source == 'ppm':
            self._likeMedia(username, args, source, 1)

    def _com_dislike(self, username, args, source):
        if source == 'pm' or source == 'ppm':
            self._likeMedia(username, args, source, -1)

    def _com_unlike(self, username, args, source):
        if source == 'pm' or source == 'ppm':
            self._likeMedia(username, args, source, 0)

    def _likeMedia(self, username, args, source, value):
        if not self.nowPlayingMedia:
            return
        if args is not None:
            mType, mId = args.split(', ')
        else:
            mType = self.nowPlayingMedia['type']
            mId = self.nowPlayingMedia['id']
        clog.info('(_com_like):type:%s, id:%s' % (mType, mId), syst) 
        uid = self.getUidFromTypeId(mType, mId) 
        i = self.getIndexFromUid(uid)
        if i is None:
            return
        userId = self.userdict[username]['keyId']
        qid = self.playlist[i]['qid']
        d = database.queryMediaId(mType, mId)
        d.addCallback(self.processResult)
        d.addCallback(database.insertReplaceLike, qid, userId, 
                       getTime(), value)
        d.addCallback(self.updateCurrentLikes, username, value)

    def updateCurrentLikes(self, res, username, value):
         self.currentLikes[username] = value
         score = sum(self.currentLikes.itervalues())
         self.currentLikeJs = 'yukariLikeScore = %d' % score
         self.updateJs()

    def updateJs(self):
        omit = 'yukariOmit=' + str(self.currentOmitted).lower()
        try:
            ircUserCount = 'yukarIRC=' + str(self.factory.handle.ircUserCount)
        except(NameError):
            ircUserCount = '0'
        js = '%s;%s;%s;%s;' % (self.currentVocadb, self.currentLikeJs, omit,
                               ircUserCount)
        self.doSendJs(js)

    def doSendJs(self, js):
        self.sendf({'name': 'setChannelJS', 'args': {'js': js}})

    def processResult(self, res):
        return defer.succeed(res[0][0])

    def _com_who(self, username, args, source):
        if args is None or source != 'chat':
            return
        msg = '[Who: %s] %s' % (args, random.choice(self.userdict.keys()))
        self.doSendChat(msg, source)

    def greet(self, res, username, isReg, source):
        flag = res[0][0]
        if flag & 1: # user has greeted us before
            d = self.calculatePoints(username, isReg)
            d.addCallback(self.returnGreeting, username, source)
            d.addErrback(self.errcatch)
        elif not flag & 1:
            database.flagUser(1, username.lower(), isReg)
            reply = 'Nice to meet you, %s!' % username
            self.doSendChat(reply, source, username)
    
    def returnGreeting(self, points, username, source):
        clog.info('(returnGreeting) %s: %d points' % (username, points), syst)
        modflair = False
        if not points or points < 0:
            reply = 'Hello %s.' % username
        elif points < 999:
            reply = 'Hi %s.' % username
        elif points < 2000:
            reply = 'Hi %s!' % username
        else:
            reply = 'Hi %s! <3' % username
        self.doSendChat(reply, source, username, modflair)

    def returnPoints(self, stats, querier, username, source):
        # e.g. [(True, 1401.87244), (True, [(True, [(19,)]), (True, [(96,)]),
        # (True, [(22,)]), (True, [(3,)]), (True, [(23,)]), (True, [(2,)])])]
        points = stats[0][1]
        adds = stats[1][1][0][1][0][0]
        queues = stats[1][1][1][1][0][0]
        likes = stats[1][1][2][1][0][0]
        dislikes = stats[1][1][3][1][0][0]
        liked = stats[1][1][4][1][0][0]
        disliked = stats[1][1][5][1][0][0]

        clog.info('(returnPoints) %s has %d points.' %(username, points), syst)
        self.doSendChat('[%s] points:%d (a%d / q%d / l%d / d%d / L%d / D%d)' %
           (username, points, adds, queues, likes, dislikes, liked, disliked),
            source=source, username=querier)

    def calculatePoints(self, username, isRegistered):
        d1 = database.calcUserPoints(None, username.lower(), isRegistered)
        d2 = database.calcAccessTime(None, username.lower(), isRegistered)
        dl = defer.DeferredList([d1, d2])
        dl.addCallback(self.sumPoints, username, isRegistered)
        return dl

    def sumPoints(self, res, username, isRegistered):
        # sample res [(True, [(420,)]), (True, [(258.7464,)])]
        # [(True, [(0,)]), (True, [(None,)])] # no add/queue, no userinoutrow
        clog.debug('(sumPoints %s)' % res, syst)
        try:
            points = res[0][1][0][0] + res [1][1][0][0]
        except(TypeError):
            points = res[0][1][0][0]
        return points

    def calculateStats(self, username, isRegistered):
        user = (username.lower(), isRegistered)
        dAdded = database.getUserAddSum(*user)
        dQueued = database.getUserQueueSum(*user)
        dLikes = database.getUserLikesReceivedSum(*user, value=1)
        dDislikes = database.getUserLikesReceivedSum(*user, value=-1)
        dLiked = database.getUserLikedSum(*user, value=1)
        dDisliked = database.getUserLikedSum(*user, value=-1)
        dl = defer.DeferredList([dAdded, dQueued, dLikes, dDislikes,
                                 dLiked, dDisliked])
        return dl
    
    def _omit(self, username, args, dir, source):
        rank = self._getRank(username)
        clog.info('(_com_omit) %s' % args)
        if rank < 2 or not self.nowPlayingMedia:
            return
        parsed = self._omit_args(args)
        if not parsed:
            self.doSendChat('Invalid parameters.')
        elif parsed:
            mType, mId = parsed
            # check existence and retrieve title
            d = database.getMediaByTypeId(mType, mId)
            d.addCallback(self.cbOmit, mType, mId, username, dir, source)

    def cbOmit(self, res, mType, mId, username, dir, source):
        if not res:
            st = '' if dir == 'flag' else 'un'
            self.doSendChat('Cannot %somit media not in database'
                            % st, source, username, toIrc=False)

        elif dir == 'flag' and res[0][6] & 2: # already omitted
            self.doSendChat('%s is already omitted' % res[0][4], 
                            source, username, toIrc=False)

        elif dir == 'unflag' and not res[0][6] & 2: # not omitted
            self.doSendChat('%s is not omitted' % res[0][4], source,
                            username, toIrc=False)
        else:
            np = self.nowPlayingMedia
            title = res[0][4]
            if dir == 'flag':
                database.flagMedia(2, mType, mId)
                if (mType, mId) == (np['type'], np['id']):
                    self.currentOmitted = True
                    self.updateJs()
                self.doSendChat(wisp('Omitted %s') % title, source, 
                                username, toIrc=False)

            elif dir == 'unflag':
                database.unflagMedia(2, mType, mId)
                if (mType, mId) == (np['type'], np['id']):
                    self.currentOmitted = False
                    self.updateJs()
                self.doSendChat(wisp('Unomitted %s') % title, source,
                                username, toIrc=False)

    def _omit_args(self, args):
        if not args:
            if self.nowPlayingMedia:
                return self.nowPlayingMedia['type'], self.nowPlayingMedia['id']
            else:
                return False
        elif args:
            if ',' in args:
                argl = args.split(',')
            elif ' ' in args:
                argl = args.split()
            else:
                return 'yt', args
            try:
                return argl[1], argl[0]
            except(IndexError):
                return False

    def _getRank(self, username):
        try:
            return int(self.userdict[username]['rank'])
        except(KeyError):
            clog.error('(_getRank) %s not found in userdict' % username, syst)

    def bulkLogChat(self):
        if self.chatLoop.running:
            #clog.debug('(bulkLogChat) stopping chatLoop', syst)
            self.chatLoop.stop()
        chatlist = self.unloggedChat[:]
        self.unloggedChat = []
        # don't return a deferred here! bad things will happen
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
        user['keyId'] = None
        user['timeJoined'] = timeNow
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
        clog.debug('(userLeave) userId %s left: %d' % (keyId, timeNow), syst)
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
            clog.info('(_cy_userlist) Duplicate userlist detected', syst)
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
        self.playlist = []
        self.nowPlayingMedia = {}
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
                reactor.callLater(i, vdbapi.requestSongByPv, None ,mType, mId, 1, timeNow, 0)
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

        # Announce queue
        msg = wisp('%s added %s!' % (queueby, title))
        self.doSendChat(msg, source='chat', toIrc=False)

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
        dq = defer.Deferred()
        self.splitResults(d, dq) # fired in parallel when d has result
        d.addCallback(lambda res: res[0])
        dq.addCallback(self.writeQueue, userId, timeNow, flag, uid)
        i = self.getIndexFromUid(uid)
        self.playlist[i]['qDeferred'] = dq

        dCheck = self.checkMedia(mType, mId)
        dCheck.addCallback(self.flagOrDelete, media, mType, mId)

        if mType == 'yt' and vdb:
            timeNow = getTime()
            # since this callback is added after checkMedia which has a delay,
            # this also gets delayed
            dCheck.addCallback(vdbapi.requestSongByPv ,mType, mId, 1, timeNow, 0)
            dCheck.addErrback(self.errcatch)

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

        # if there is a replay-poll active, end it
        if self.pollState.get('type', None) == 'replay':
            self.doClosePoll()

        if self.willReplay:
            if self.mediaRemainingTime > 6:
                msg = ('(_cyCall_changeMedia) Detected user activity.'
                      ' Cancelling replay.')
                clog.warning(msg, syst)
                self.doSendChat(wisp('Cancelling replay - user intervention.'),
                                toIrc=False)
            else:
                mType, mId, title = self.willReplay
                uid = self.getUidFromTypeId(mType, mId)
                if uid:
                    self.doSendChat(wisp('Replaying %s!' % title), toIrc=False)
                    self.jumpToMedia(uid)
                else:
                    # uid is None when media was set to temporary.
                    # A workaround by "untemp, replay, temp"
                    # is not worth implementing
                    self.doSendChat(wisp('%s not found.' % title), toIrc=False)

            self.willReplay = False
        
        else:
            # set remaining time to the duration of the media
            # otherwise this will be outdated until the first mediaUpdate tick
            self.mediaRemainingTime = media['seconds']

            # send now playing info to seconday IRC channel
            self.factory.handle.recCyChangeMedia(nps)

            d = self.checkMedia(mType, mId)
            d.addErrback(self.errcatch)
            d.addCallback(self.flagOrDelete, media, mType, mId)
            d.addErrback(self.errcatch)
            d.addCallback(self.loadLikes, mType, mId)
            d.addCallback(self.loadVocaDb, mType, mId)

    def jumpToMedia(self, uid):
        clog.debug('(jumpToMedia) Playing uid %s' % uid, syst)
        self.sendf({'name': 'jumpTo', 'args': [uid]})

    def loadLikes(self, res, mType, mId):
        if res != 'EmbedOk':
            return
        uid = self.getUidFromTypeId(mType, mId)
        i = self.getIndexFromUid(uid)
        try:
            queueId = self.playlist[i]['qid']
            d = database.getLikes(queueId)
        except(KeyError):
            clog.error('(loadLikes) Key is not ready!', syst)
            d = self.playlist[i]['qDeferred']
            d.addCallback(database.getLikes)
        # result  [(userId, 1), (6, 1)]
        d.addCallback(self.sendLikes)

    def sendLikes(self, res):
        self.currentLikes, likes = dict(res), dict(res)
        for username in likes:
            if username in self.userdict:
                if self.userdict[username]['subscribeLike']:
                    if likes[username]: # don't send if 0
                        msg = '%%%%%s' % likes[username]
                        self.doSendPm(msg, username)

        score = sum(self.currentLikes.itervalues())
        self.currentLikeJs = 'yukariLikeScore = %d' % score
        self.updateJs()

    def loadVocaDb(self, res, mType, mId):
        d = database.queryVocaDbInfo(mType, mId)
        d.addCallback(self.processVocadb, mType, mId)
        #d.addCallback(lambda x: clog.info(x, 'loadvcaodb'))

    def processVocadb(self, res, mType, mId):
        if not res:
            clog.info('(processVocadb) Vocadb db query returned []')
            self.currentVocadb = 'vocapack =' + json.dumps({'res': False})
        else:
            setby = res[0][0]
            mediaId = res[0][1]
            vocadbId = res[0][2]
            method = res[0][3]
            vocadbData = res[0][4]
            if vocadbId == 0:
                self.currentVocadb = 'vocapack =' + json.dumps({'res': False})
            else:
                vocadbInfo = self.parseVocadb(vocadbData)
                vocapack = {'setby': setby, 'vocadbId': vocadbId, 'method': method,
                            'vocadbInfo': vocadbInfo, 'res': True}
                vocapackjs = json.dumps(vocapack)
                self.currentVocadb = 'vocapack =' + vocapackjs
        self.updateJs()

    def parseVocadb(self, vocadbData):
        artists = []
        data = json.loads(vocadbData)
        for artist in data['artists']:
            artistd = {}
            artistd['name'] = artist['name']
            try:
                artistd['id'] = artist['artist']['id']
            except(KeyError): # Some Artists do not have entries and thus no id
                artistd['id'] = None
            artistd['isSup'] = artist['isSupport']
            artistd['role'] = artist['effectiveRoles']
            if artistd['role'] == 'Default':
                artistd['role'] = artist['categories']
            artists.append(artistd)
        titles = []
        for title in data['names']:
            if title['language'] in ('Japanese', 'Romaji', 'English'):
                titles.append(title['value'])

        songType = data['songType']
        return {'titles': titles, 'artists': artists, 'songType': songType}

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
            sustainedLoop.start(2.05, now=True)
        
    def doAddSustained(self, pos, temp):
        mType, mId = self.queueMediaList.popleft()
        self.sendf({'name': 'queue', 'args': {'type': mType, 
                                    'id': mId, 'pos': pos, 'temp': temp}})
        self.lastQueueTime = time.time()

    def getRandMedia(self, sample, quantity, username, isRegistered, title,
                     temp, pos):
        """ Queues up to quantity number of media to the playlist """
        if sample == 'queue' or sample == 'q':
            d = database.addByUserQueue(username, isRegistered, title, quantity)
        elif sample == 'add' or sample == 'a':
            d = database.addByUserAdd(username, isRegistered, title, quantity)
        
        elif sample == 'like' or sample == 'l':
            d = database.addByUserLike(username, isRegistered, quantity)
        else:
            return
        d.addCallback(self.doAddMedia, temp, pos)
        d.addErrback(self.errcatch)

    def doDeleteMedia(self, mType, mId):
        """ Delete media """
        uid = self.getUidFromTypeId(mType, mId)
        clog.info('(doDeleteMedia) Deleting media uid %s' % uid)
        self.sendf({'name': 'delete', 'args': uid})

class WsFactory(WebSocketClientFactory):
    protocol = CyProtocol

    def __init__(self, arg):
        WebSocketClientFactory.__init__(self, arg)

    def startedConnecting(self, connector):
        clog.debug('WsFactory...started Connecting')
        self.handle.cyLastConnect = time.time()
        self.handle.cyAnnounceConnect()

    def clientConnectionLost(self, connector, reason):
        self.handle.cy = False
        if time.time() - self.handle.cyLastDisconnect > 60:
            self.handle.cyRetryWait = 0
        self.handle.cyLastDisconnect = time.time()
        clog.warning('(clientConnectionLost) Connection lost to Cyutbe. %s'
                     % reason, syst)
        try:
            self.prot.logUserInOut()
        except(AttributeError):
            # prot doesn't exist yet
            pass
        self.handle.cyAnnouceLeftRoom()
        if self.handle.cyRestart:
            clog.error('clientConnectionLost! Reconnecting in %d seconds'
                       % self.handle.cyRetryWait, syst)
            # reconnect
            reactor.callLater(self.handle.cyRetryWait,
                                                    self.handle.cyChangeProfile)

    def clientConnectionFailed(self, connector, reason):
        clog.error('(clientConnectionFailed) Connection failed to Cytube. %s'
                    % reason, syst)

# add methods here
#from connections.cytube.commands import _com_smiley
#setattr(CyProtocol, '_com_smiley', _com_smiley)
