import database, apiClient, tools, vdbapi
from tools import clog
from tools import getTime
from conf import config
import json, time, re, argparse, random
from collections import deque
from twisted.internet import reactor, defer, task
from twisted.internet.error import AlreadyCalled, AlreadyCancelled
from autobahn.twisted.websocket import WebSocketClientProtocol,\
                                       WebSocketClientFactory

sys = 'CytubeClient'
vdb = config['UserAgent']['vocadb']

class CyProtocol(WebSocketClientProtocol):

    def __init__(self):
        self.name = config['Cytube']['username']
        self.unloggedChat = []
        self.chatLoop = task.LoopingCall(self.bulkLogChat)
        self.lastChatLogTime = 0
        self.receivedChatBuffer = False
        self.queueMediaList = deque()
        self.canBurst = False
        self.lastQueueTime = time.time() - 20 #TODO
        self.nowPlayingMedia = None
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

    def errcatch(self, err):
        clog.error('caught something')
        self.err.append(err)

    def onOpen(self):
        clog.info('(onOpen) Connected to Cytube!', sys)
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
        clog.info('(onClose) Closed Protocol connection: %s' % reason, sys)

    def sendf(self, dict): # 'sendFrame' is a WebSocket method name
        frame = json.dumps(dict)
        frame = '5:::' + frame
        clog.debug('(sendf) [->] %s' % frame, sys)
        self.sendMessage(frame)

    def doSendChat(self, msg, source='chat', username=None, modflair=False,
                   toIrc=True):
        clog.debug('(doSendChat) msg:%s, source:%s, username:%s' % (msg, source,
                    username), sys)

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
        else:
            pass
            #print 'No method defined for %s.' % name

    def joinRoom(self):
        channel = config['Cytube']['channel']
        self.sendf({'name': 'joinChannel', 'args': {'name':channel}})

    def searchYoutube(self, msg):
        m = self.ytUrl.search(msg)
        if m:
            ytId = m.group(6)
            clog.debug('(searchYoutube) matched: %s' % ytId, sys)
            d = apiClient.requestYtApi(ytId)
            d.addCallbacks(self.doSendChat, self.errYtInfo)
            d.addErrback(self.errcatch)

    def _cyCall_login(self, fdict):
        if fdict['args'][0]['success']:
            self.joinRoom()

    def _cyCall_setMotd(self, fdict):
        # setMotd comes after the chat buffer when joining a channel
        self.receivedChatBuffer = True

    def _cyCall_usercount(self, fdict):
        usercount = fdict['args'][0]
        anoncount = usercount - len(self.userdict)
        database.insertUsercount(getTime(), usercount, anoncount)

    def _cyCall_chatMsg(self, fdict):
        if not self.receivedChatBuffer:
            return
        args = fdict['args'][0]
        timeNow = getTime()
        username = args['username']
        msg = args['msg']
        msg = tools.unescapeMsg(msg)
        chatCyTime = int((args['time'])/10.0)
        if 'modflair' in args['meta']:
            modflair = args['meta']['modflair']
        else:
            modflair = None
        action = True if 'action' in args['meta'] else False
        if username == '[server]':
            keyId = 2
        elif username in self.userdict:
            keyId = self.userdict[username]['keyId']
        if keyId:
            self.unloggedChat.append((None, keyId, timeNow, chatCyTime, msg,
                                          modflair, 0))
            if not self.chatLoop.running:
                clog.info('(_cy_chatMsg) starting chatLoop', sys)
                self.chatLoop.start(3, now=False)
        else:
            assert keyId is None
            chatArgs = (timeNow, chatCyTime, msg, modflair, 0)
            self.userdict[username]['deferred'].addCallback(self.deferredChat,
                                                                chatArgs)
        # check for commands
        isCyCommand = False
        thunk = None
        if msg.startswith('$'):
            thunk, args, source = self.checkCommand(username, msg, 'chat')
        if username != self.name and username != '[server]':
            #clog.debug('Sending chat to IRC, username: %s' % username)
            self.factory.handle.recCyMsg(username, msg, not thunk, action=action)
        # send to IRC before executing the command
        # to maintain proper chat queue (user command before Yukari's reply)
        if thunk is not None:
            thunk(username, args, 'chat')

    def _cyCall_pm(self, fdict):
        args = fdict['args'][0]
        pmTime = args['time']
        pmCyTime = int((args['time'])/10.0)
        timenow = getTime()
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
        
        if username in self.userdict:
            keyId = self.userdict[username]['keyId']
            if keyId is not None:
                clog.debug('(_cyCall_pm) key for %s:%s' % (username, keyId), sys)
                database.insertPm(keyId, pmTime, pmCyTime, msg, flag)
            else:
                clog.error('(_cyCall_pm) no key for %s' % username, sys)
        else:
            clog.error('(_cyCall_pm) %s sent phantom PM: %s' % (username, msg))
            return

        if msg.startswith('%%'):
            if msg == '%%subscribeLike':
                clog.debug('Received subscribeLike from %s' % username, sys)
                if username in self.userdict:
                    if not self.userdict[username]['subscribeLike']:
                        self.userdict[username]['subscribeLike'] = True
                        # send value for current media
                        if username in self.currentLikes:
                            msg = '%%%%%s' % self.currentLikes[username]
                            self.doSendPm(msg, username)
                return
            elif msg == '%%like':
                self._com_like(username, None, 'ppm')
            elif msg == '%%unlike':
                self._com_unlike(username, None, 'ppm')
            elif msg == '%%dislike':
                self._com_dislike(username, None, 'ppm')

        if msg.startswith('$') and fromUser != self.name:
            thunk, args, source = self.checkCommand(username, msg, 'pm')
            if thunk is not None:
                thunk(username, args, 'pm')

    def checkCommand(self, username, msg, source):
        command = msg.split()[0][1:]
        clog.debug('(checkCommand) received %s command %s from %s' %
                    (source, command, username), sys)
        argsList = msg.split(' ', 1)
        if len(argsList) == 2:
            args = argsList[1]
        else:
            args = None
        thunk = getattr(self, '_com_%s' % (command,), None)
        return thunk, args, source
        if thunk is not None:
            thunk(username, args, source)
            return True
            
    def _com_vocadb(self, username, args, source):
        if not vdb:
            return
        if args is None:
            return # TODO refresh current song
        try:
            songId = int(args)
        except IndexError:
            clog.error('(_com_vocadb) Index Error by %s' % username, sys)
            return
        except ValueError:
            clog.error('(_com_vocadb) Value Error by %s' % username, sys)
            return
        userId = self.userdict[username]['keyId']
        timeNow = getTime()
        mType, mId, __  = self.nowPlayingMedia
        d = vdbapi.requestSongById(mType, mId, songId, userId, timeNow, 4)
        # method 4 = manual set
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
        return command[tBeg:tEnd], shortMsg

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
        clog.info(args, sys)
        clog.info(args, 'sent to parseTitle')
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
                            choices=('queue', 'q', 'add', 'a'))
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

        reply = ('Quantity:%s, sample:%s, user:%s, guest:%s, temp:%s, '
                'pos:%s, title:%s, include ommited:%s'
                % (args.number, args.sample, args.user, args.guest,
                   args.temporary, args.next, title, args.omit))
        #self.doSendChat(reply)
        clog.debug('(_com_add) %s' % reply, sys)
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
        self._omit(username, args, 'flag')

    def _com_unomit(self, username, args, source):
        self._omit(username, args, 'unflag')

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
        if self.checkRegistered(username):
            d = database.calcUserPoints(None, username.lower(), 1)
            d.addCallback(self.returnPoints, username, source)
            d.addErrback(self.errcatch)

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
            mType, mId, __ = self.nowPlayingMedia
        clog.info('(_com_like):type:%s, id:%s' % (mType, mId), sys) 
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
        js = '%s; %s; %s;' % (self.currentVocadb, self.currentLikeJs, omit)
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
            d = database.calcUserPoints(None, username.lower(), isReg)
            d.addCallback(self.returnGreeting, username, source)
            d.addErrback(self.errcatch)
        elif not flag & 1:
            database.flagUser(1, username.lower(), isReg)
            reply = 'Nice to meet you, %s!' % username
            self.doSendChat(reply, source, username)
    
    def returnGreeting(self, res, username, source):
        points = res[0][0]
        # When a row is empty (most commonly for the userinout for a new user),
        # it returns None. A new user who hasn't left (to be
        # logged in userinout) may have enough points to warrant a better
        # greeting, but that is very unlikely.
        if points is None:
            clog.info('(returnGreeting) %s has ?? points.' % username, sys)
        else:
            clog.info('(returnGreeting) %s has %d points.'
                       % (username, points), sys)
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

    def returnPoints(self, res, username, source):
        points = res[0][0]
        clog.info('(returnPoints) %s has %d points.' %(username, points), sys)
        self.doSendChat('%s: %d' % (username, points), source=source,
                         username=username)

    def _omit(self, username, args, dir):
        rank = self._getRank(username)
        clog.info('(_com_omit) %s' % args)
        if rank < 2 or not self.nowPlayingMedia:
            return
        parsed = self._omit_args(args)
        if not parsed:
            self.doSendChat('Invalid parameters.')
        elif parsed:
            mType, mId = parsed
            if dir == 'flag':
                database.flagMedia(2, mType, mId)
                if (mType, mId) == self.nowPlayingMedia[:2]:
                    self.currentOmitted = True
                    self.updateJs()
            elif dir == 'unflag':
                database.unflagMedia(2, mType, mId)
                if (mType, mId) == self.nowPlayingMedia[:2]:
                    self.currentOmitted = False
                    self.updateJs()

    def _omit_args(self, args):
        if not args:
            if self.nowPlayingMedia:
                mType, mId, mTitle = self.nowPlayingMedia
                return mType, mId
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
            clog.error('(_getRank) %s not found in userdict' % username, sys)

    def bulkLogChat(self):
        if self.chatLoop.running:
            clog.info('(bulkLogChat) stopping chatLoop', sys)
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
            clog.info('(deferredChatRes): wrote chat to database!', sys)
            return defer.succeed(key)
        else:
            clog.err('(deferredChatRes): error writing to database!', sys)
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
            clog.info("(cacheKey) cached %s's key %s" % (user['name'], res[0]),
                      sys)
            self.userdict[user['name']]['keyId'] = res[0]
        return defer.succeed(res[0])

    def userLeave(self, keyId, leftUser, timeNow):
        userId = leftUser['keyId']
        assert userId == keyId, 'KeyId mismatch at userleave!'
        timeJoined = leftUser['timeJoined']
        clog.debug('(userLeave) userId %s left: %d' % (keyId, timeNow), sys)
        d = database.insertUserInOut(keyId, timeJoined, timeNow)
        d.addCallback(lambda __: defer.succeed(keyId))
        d.addErrback(self.errcatch)

    def _cyCall_userLeave(self, fdict):
        timeNow = getTime()
        username = fdict['args'][0]['name']
        if not username:
            return # when anon leaves, might be sync bug
        d = self.userdict[username]['deferred']
        clog.debug('_cyCall_userLeave) user %s has left. Adding callbacks' 
                   % username, sys)
        leftUser = self.userdict[username]
        d.addCallback(self.userLeave, leftUser, timeNow)
        d.addErrback(self.errcatch)
        self.removeUser(None, username) # remove user immediatley

    def removeUser(self, res, username):
        clog.debug('(removeUser) Removing user', sys)
        try:
            del self.userdict[username]
            clog.debug('(removeUser) deleted %s' % username, sys)
        except(KeyError):
            clog.error('(removeUser) Failed: user %s not in userdict' % username, sys)

    def _cyCall_userlist(self, fdict):
        if time.time() - self.lastUserlistTime < 3: # most likely the same userlist
             # with ip/aliases if mod+
            clog.info('(_cy_userlist) Duplicate userlist detected', sys)
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
        self.nowPlayingMedia = None
        pl = fdict['args'][0]
        clog.debug('(_cyCall_playlist) received playlist from Cytube', sys)
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

    def findSonglessMedia(self, playlist):
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
            #d.addCallback(lambda x: clog.info('obtained queueId %s' % x, sys))

    def obtainQueueId(self, res, mType, mId):
        clog.debug('(checkQueueId) res is %s' % res, sys)
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
        # I want to print media['title'] but depending on the terminal
        # it fails to encode some characters (usually symbols)
        clog.debug('(addToPlaylist) Inserting uid %s %s after index %s' %
                   (item['uid'], item['media']['title'].encode('utf-8'),
                     index), sys)

    def movePlaylistItems(self, beforeUid, afterUid):
        # 'before' is just the uid of the video that is going to move
        clog.info('(movePlaylistItems) move uid:%s, after uid%s' %
                  (beforeUid, afterUid), sys)
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
            clog.debug('(getIndexFromUid) Looking up uid %s, index is %s'
                        % (uid, index), sys)
            return index
        except StopIteration as e:
            clog.error('(getIndexFromUid) media UID %s not found' % uid, sys)

    def getUidFromTypeId(self, mType, mId):
        for media in self.playlist:
            if media['media']['id'] == mId:
                if media['media']['type'] == mType:
                    return media['uid']

    def displaypl(self):
        for item in self.playlist:
            print item['media']['title'].encode('utf-8')

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
        msg = '@3939%s added %s!#3939' % (queueby, title)
        self.doSendChat(msg, source='chat', toIrc=False)

        if queueby: # anonymous add is an empty string
            userId = self.userdict[queueby]['keyId']
        else:
            userId = 3
        if userId:
            d = self.queryOrInsertMedia(media, userId)
        else:
            clog.error('(_cyCall_queue) user id not cached.', sys)
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
            clog.error('(continueBlacklist) Media not found!', sys)
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
            clog.debug('(checkMedia) Length of ytq %s' % len(self.ytq), sys)
            return d
        else:
            return defer.succeed('EmbedOk') # TODO

    def flagOrDelete(self, res, media, mType, mId):
        if res == 'EmbedOk':
            database.unflagMedia(0b1, mType, mId)

        elif res == 'Status503':
            clog.error('(flagOrDelete) Youtube service unavailable.', sys)

        elif res == 'NetworkError':
            clog.error('(flagOrDelete) There was a network error.', sys)

        elif res in ('NoEmbed', 'Status403', 'Status404'):
            self.doDeleteMedia(media['type'], media['id'])
            mediaTitle = media['title'].encode('utf-8')
            msg = '@3939Removing non-playable media %s#3939' % mediaTitle
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
                  (uid, index), sys)
        assert uid == deletedMedia['uid'], 'Deleted media not correct!'

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
        clog.info('(saveQueueId) QId of uid %s is %s' % (uid, queueId), sys)
        i = self.getIndexFromUid(uid)
        if i: # None when media is already gone from Yukari's playlist
              # ie autodelete from blacklist
            self.playlist[i]['qid'] = queueId 
        return defer.succeed(queueId)
        
    def printRes(self, res):
        clog.info('(printRes) %s' % res, sys)
        return defer.succeed(res)
        
    def errYtInfo(self, err):
        clog.error('(errYtInfo) %s' % err, sys)

    def dbErr(self, err):
        clog.error('(dbErr): %s' % err.value, sys)

    def _cyCall_changeMedia(self, fdict):
        # set self.nowPlayingMedia
        media = fdict['args'][0]
        mType = media['type']
        mId = media['id']
        mTitle = media['title']
        self.nowPlayingMedia = (mType, mId, mTitle) # these are unicode
        # everything has to be encoded to utf-8 or it errors
        s = mTitle.encode('utf-8') + ' (%s, %s)' % (mType.encode('utf-8'),
                          mId.encode('utf-8'))
        clog.info('(_cyCall_changeMedia) %s' % s, sys)
        d = self.checkMedia(mType, mId)
        d.addErrback(self.errcatch)
        d.addCallback(self.flagOrDelete, media, mType, mId)
        d.addErrback(self.errcatch)
        d.addCallback(self.loadLikes, mType, mId)
        d.addCallback(self.loadVocaDb, mType, mId)

    def loadLikes(self, res, mType, mId):
        if res != 'EmbedOk':
            return
        uid = self.getUidFromTypeId(mType, mId)
        i = self.getIndexFromUid(uid)
        try:
            queueId = self.playlist[i]['qid']
            d = database.getLikes(queueId)
        except(KeyError):
            clog.error('(loadLikes) Key is not ready!', sys)
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
            clog.error('(processVocadb) Vocadb db query returned []')
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
        msg = fdict['args'][0]['msg']
        clog.error('(_cyCall_queueFail) %s' % msg, sys)

    def cleanUp(self):
        # set restart to False
        self.factory.handle.cyRestart = False
        # disconnect first so we don't get any more join/leaves
        self.sendClose()
        # log everyone's access time before shutting down
        self.logUserInOut()
        self.cyRestart = False

    def logUserInOut(self):
        timeNow = getTime() 
        for name, user in self.userdict.iteritems():
            user['deferred'].addCallback(self.userLeave, user, timeNow)

    def checkRegistered(self, username):
        """ Return wether a Cytube user is registered (1) or a guest (0) given
        a username. Checks self.userdict for rank information."""
        if username == '[server]':
            return 1
        else:
            try:
                user = self.userdict[username]
            except KeyError as e:
                clog.error('(checkRegistered): %s' % e, sys)
                #raise
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
            self.canBurst = True
        # burst!
        bursted = 0
        if self.canBurst and self.queueMediaList:
            for i in range(min(len(self.queueMediaList), 10)):
                mType, mId = self.queueMediaList.popleft()
                self.sendf({'name': 'queue', 'args': {'type': mType, 
                                    'id': mId, 'pos': pos, 'temp': temp}})
                bursted += 1
            self.canBurst = False
            self.lastQueueTime = time.time()

        # sustain
        # we can't use enumerate here; the list gets shorter each iteration
        for i in range(len(media)-bursted):
            # add a little slower than 2/sec to account for network latency
            # and Twisted callLater time is not guaranteed
            wait = (i + lenBefore + 3)/1.7 
            d = reactor.callLater(wait, self.doAddSustained, pos, temp)
    
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
        clog.debug('WsFactory...startedConnecting')
        self.handle.cyLastConnect = time.time()
        self.handle.cyAnnounceConnect()

    def clientConnectionLost(self, connector, reason):
        self.handle.cyLastDisconnect = time.time()
        clog.warning('(clientConnectionLost) Connection lost to Cyutbe. %s'
                     % reason, sys)
        if not self.handle.cyRestart:
            self.handle.doneCleanup('cy')
        else:
            self.prot.logUserInOut()
            self.handle.cyAnnouceDisconnect()
            clog.error('clientConnectionLost! Reconnecting in %d seconds'
                       % self.handle.cyRetryWait, sys)
            # reconnect
            reactor.callLater(self.handle.cyRetryWait, self.handle.cyPost)
            self.handle.cyRetryWait += 2
            self.handle.cyRetryWait = self.handle.cyRetryWait**2
            if self.handle.cyRetryWait >= 5*60:
                self.handle.cyRetryWait = 5*60
            if self.handle.cyLastConnect - self.handle.cyLastDisconnect > 2*60:
                self.handle.cyRetryWait = 0

    def clientConnectionFailed(self, connector, reason):
        clog.error('(clientConnectionFailed) Connection failed to Cytube. %s'
                    % reason, sys)
