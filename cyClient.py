import database, apiClient, tools, vdbapi
from tools import clog
from conf import config
import json, time, re, argparse
from collections import deque
from twisted.internet import reactor, defer, task
from twisted.internet.error import AlreadyCalled, AlreadyCancelled
from autobahn.twisted.websocket import WebSocketClientProtocol,\
                                       WebSocketClientFactory

sys = 'CytubeClient'
vdb = config['UserAgent']['vocadb']

class CyProtocol(WebSocketClientProtocol):

    def __init__(self):
        self.votes = 0
        self.unloggedChat = []
        self.lastChatLogTime = 0
        self.receivedChatBuffer = False
        self.queueMediaList = deque()
        self.canBurst = False
        self.lastQueueTime = time.time() - 20 #TODO
        ### Need to imporve this regex, it matches non-videos
        # ie https://www.youtube.com/feed/subscriptions
        self.ytUrl = re.compile(
                (r'(https?://)?(www\.)?(youtube|youtu|youtube-nocookie)\.'
                  '(com|be)/(watch\?v=|embed/|v/|.+\?v=)?([^&=%\?]{11})'))
        self.ytq = deque()

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

    def doSendChat(self, msg, modflair=False):
        if modflair:
            modflair = 3 ### TODO remove hardcode rank
        self.sendf({'name': 'chatMsg',
                   'args': {'msg': msg, 'meta': {'modflair': modflair}}})

    def initialize(self):
        self.sendf({'name': 'initChannelCallbacks'})
        name = config['Cytube']['username']
        pw = config['Cytube']['password']
        self.sendf({'name': 'login',
                    'args': {'name': name, 'pw': pw}})

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

    def _cyCall_login(self, fdict):
        if fdict['args'][0]['success']:
            self.joinRoom()

    def _cyCall_setMotd(self, fdict):
        # setMotd comes after the chat buffer when joining a channel
        self.receivedChatBuffer = True

    def _cyCall_pm(self, fdict):
        return # TODO
        clog.info(fdict, sys)
        username = fdict['args'][0]['username']
        msg = fdict['args'][0]['msg']
        if msg == '$down':
            self.votes -= 1
        elif msg == '$up':
            self.votes += 1
        else:
            return
        self.sendCss()

    def sendCss(self):
        return # TODO
        hor = -16 * self.votes
        css = '#votebg{background-position: %spx 0px;}' % hor
        self.sendf({'name':'setChannelCSS', 'args':{'css':css}})

    def _cyCall_chatMsg(self, fdict):
        if not self.receivedChatBuffer:
            return
        args = fdict['args'][0]
        timeNow = round(time.time(), 2)
        username = args['username']
        msg = tools.unescapeMsg(args['msg'])
        chatCyTime = round((args['time'])/1000.0, 2)
        if 'modflair' in args['meta']:
            modflair = args['meta']['modflair']
        else:
            modflair = None
        if username == '[server]':
            keyId = 2
        elif username in self.userdict:
            keyId = self.userdict[username]['keyId']
        if keyId:
            self.unloggedChat.append((None, keyId, timeNow, chatCyTime, msg,
                                          modflair, 0))
            if time.time() - self.lastChatLogTime < 3:
                self.cancelChatLog()
                self.dChat = reactor.callLater(3, self.bulkLogChat,
                                               self.unloggedChat)
            else:
                self.cancelChatLog()
                self.bulkLogChat(self.unloggedChat)
                self.lastChatLogTime = time.time()
        else:
            assert keyId is None
            chatArgs = (timeNow, chatCyTime, msg, modflair, 0)
            self.userdict[username]['deferred'].addCallback(self.deferredChat,
                                                                chatArgs)
                
        if username != config['Cytube']['username'] and username != '[server]':
            # comment line below for test. #TODO make proper test
            self.factory.handle.recCyMsg(username, msg)
            self.searchYoutube(msg)

        # check for commands
        if msg.startswith('$'):
            command = msg.split()[0][1:]
            clog.debug('received command %s from %s' % (command, username), sys)
            args = tuple(msg.split()[1:])
            thunk = getattr(self, '_com_%s' % (command,), None)
            if thunk is not None:
                thunk(username, msg)

    def _com_vocadb(self, username, msg):
        if not vdb:
            return
        try:
            songId = int(msg.split()[1])
        except IndexError:
            clog.error('(_com_vocadb) Index Error by %s' % username, sys)
            return
        except ValueError:
            clog.error('(_com_vocadb) Value Error by %s' % username, sys)
            return
        userId = self.userdict[username]['keyId']
        timeNow = round(time.time(), 2)
        mType, mId, mTitle  = self.nowPlaying
        d = vdbapi.requestSongById(mType, mId, songId, userId, timeNow, 4)
        # method 4 = manual set

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

    def _com_add(self, username, msg):
        rank = self._getRank(username)
        clog.info('rank is %s' % rank, 'RANK')
        if not rank:
            return
        elif rank < 2:
            maxAdd = 5
        else:
            maxAdd = 20
        clog.info(msg, sys)
        args = msg[len('$add '):]
        clog.info(args, 'sent to parseTitle')
        title, arguments = self.parseTitle(args)
        args = arguments.split()
        clog.info(args, 'args args')

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
        try:
            args = parser.parse_args(args)
        except(SystemExit):
            self.doSendChat('Invalid arguments.')
            return

        args.number = min(args.number, maxAdd)
        reply = ('Quantity:%s, sample:%s, user:%s, guest:%s, temp:%s, '
                 'pos:%s, title%s'
                % (args.number, args.sample, args.user, args.guest,
                   args.temporary, args.next, title))
        self.doSendChat(reply)

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

    def _com_omit(self, username, msg):
        rank = self._getRank(username)
        if rank < 2:
            return

    def _getRank(self, username):
        try:
            return int(self.userdict[username]['rank'])
        except(KeyError):
            clog.error('(_getRank) %s not found in userdict' % username, sys)

    def cancelChatLog(self):
        try:
            self.dChat.cancel()
            clog.debug('(cancelChatLog) Cancelled log timer', sys)
        except AttributeError as e:
            clog.debug('(cancelChatLog): %s' % e, sys)
        except AlreadyCancelled as e:
            clog.debug('(cancelChatLog): %s' % e, sys)
        except AlreadyCalled as e:
            clog.debug('(cancelChatLog): %s' % e, sys)
        except NameError as e:
            clog.error('(cancelChatLog): %s' % e, sys)

    def bulkLogChat(self, chatlist):
        assert self.unloggedChat == chatlist
        self.unloggedChat = []
        #print 'Logging %s !!' % chatlist
        return database.bulkLogChat('cyChat', chatlist)

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

    def deferredChatRes(self, res, key):
        if not res:
            clog.info('(deferredChatRes): wrote chat to database!', sys)
            return defer.succeed(key)
        else:
            clog.err('(deferredChatRes): error writing to database!', sys)
            return defer.fail(key)

    def _cyCall_addUser(self, fdict):
        user = fdict['args'][0]
        timeNow = int(time.time())
        if user['name'] not in self.userdict:
            self.userJoin(user, timeNow)
        self.userdict[user['name']]['inChannel'] = True

    def userJoin(self, user, timeNow):
        user['keyId'] = None
        user['timeJoined'] = timeNow
        self.userdict[user['name']] = user
        reg = self.checkRegistered(user['name'])
        d = database.dbQuery(('userId', 'flag', 'lastSeen'), 'cyUser',
                         nameLower=user['name'].lower(), registered=reg)
        d.addCallback(database.queryResult)
        values = (None, user['name'].lower(), reg, user['name'], 0, 0,
                 timeNow, timeNow, 0)
        d.addErrback(database.dbInsertReturnLastRow, 'cyUser', *values)
        d.addCallback(self.cacheKey, user)
        # add a reference to the deferred to the userdict
        self.userdict[user['name']]['deferred'] = d
        
    def cacheKey(self, res, user):
        assert res, 'no res at cacheKey'
        if res:
            clog.info("(cacheKey) cached %s's key %s" % (user['name'], res[0]),
                      sys)
            self.userdict[user['name']]['keyId'] = res[0]

    def _cyCall_userLeave(self, fdict):
        username = fdict['args'][0]['name']
        if not username:
            return # when anon leaves, might be sync bug
        self.userdict[username]['inChannel'] = False
        d = self.userdict[username]['deferred']
        clog.debug('_cyCall_userLeave) user %s has left. Adding callbacks' 
                   % username, sys)
        leftUser = self.userdict[username]
        d.addCallback(self.clockUser, leftUser,
                      int(time.time()))
        d.addErrback(self.dbErr)
        d.addCallback(self.removeUser, username)
        d.addErrback(self.dbErr)

    def removeUser(self, res, username):
        clog.debug('(removeUser) Removing user', sys)
        try:
            if not self.userdict[username]['inChannel']:
                del self.userdict[username]
                clog.debug('(removeUser) deleted %s' % username, sys)
            else:
                clog.error('(removeUser) skipping: user %s in channel' % username, sys)
        except(KeyError):
            clog.error('(removeUser) Failed: user %s not in userdict' % username, sys)
            return KeyError

    def _cyCall_userlist(self, fdict):
        if time.time() - self.lastUserlistTime < 3: # most likely the same userlist
             # with ip/aliases if mod+
            clog.info('(_cy_userlist) Duplicate userlist detected', sys)
            return
        self.lastUserlistTime = time.time()
        userlist = fdict['args'][0]
        timeNow = int(time.time())

        # make a dictonary of users
        self.userdict = {}
        for user in userlist:
            user['timeJoined'] = timeNow
            self.userdict[user['name']] = user
            self.userJoin(user, timeNow)

    def _cyCall_playlist(self, fdict):
        """ Cache the playlist in memory, and write them to the media table """
        # Don't add this to the queue table, since it'll end up adding
        # multiple times each join/restart and also during shuffle and clear.
        self.playlist = []
        pl = fdict['args'][0]
        clog.debug('(_cyCall_playlist) received playlist from Cytube', sys)
        dbpl, qpl = [], []
        for entry in pl:
            self.playlist.append(entry)
            if entry['media']['type'] != 'cu': # custom embed
                dbpl.append((None, entry['media']['type'], entry['media']['id'],
                            entry['media']['seconds'], entry['media']['title'],
                            1, 0))
                            #'introduced by' Yukari
                if entry['media']['type'] == 'yt':
                    qpl.append((entry['media']['type'], entry['media']['id']))
        d = database.bulkLogMedia(dbpl)
        d.addCallback(self.bulkCheckPlaylist, self.playlist)

        if vdb:
            d.addCallback(database.bulkQueryMediaSong, qpl)
            d.addCallback(self.bulkCheckVocaDb)

    def bulkCheckPlaylist(self, res, playlist):
        for media in playlist:
            mType = media['media']['type']
            mId = media['media']['id']
            d = self.checkMedia(0, mType, mId)
            d.addCallback(self.flagOrDelete, media['media'], mType, mId)

    def bulkCheckVocaDb(self, songlessMedia):
        timeNow = round(time.time(), 4)
        clog.info('(bulkCheckVocaDb)', sys)
        for i, (mType, mId) in enumerate(songlessMedia):
            # 0.5s delay between each call
            reactor.callLater(i * 0.5, vdbapi.requestSongByPv, None, mType, mId,
                              1, timeNow, 4)

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
            clog.debug('(getIndexFromUid) Looking up uid %s, index is %s' % (uid, index), sys)
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
        timeNow = round(time.time(), 2)
        item = fdict['args'][0]['item']
        isTemp = item['temp']
        media = item['media']
        queueby = item['queueby']
        afterUid = fdict['args'][0]['after']
        mType = media['type']
        mId = media['id']
        self.addToPlaylist(item, afterUid)
        if queueby: # anonymous add is an empty string
            userId = self.userdict[queueby]['keyId']
        else:
            userId = 3
        if userId:
            d = self.queryOrInsertMedia(media, userId)
        else:
            clog.error('(_cyCall_queue) user id not cached.', sys)
            return
        if isTemp:
            flag = 1
        else:
            flag = None
        d.addCallback(self.writeQueue, userId, timeNow, flag)
        d.addCallback(self.checkMedia, mType, mId)
        d.addCallback(self.flagOrDelete, media, mType, mId)

        if mType == 'yt' and vdb:
            timeNow = round(time.time(), 2)
            # since this callback is added after checkMedia which has a delay,
            # this also gets delayed
            d.addCallback(vdbapi.requestSongByPv ,mType, mId, 1, timeNow, 0)

    def checkMedia(self, res, mType, mId):
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
            msg = 'Removing non-playable media %s' % mediaTitle
            database.flagMedia(0b1, mType, mId)
            self.doSendChat(msg)
            clog.info(msg)

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
        d = database.dbQuery(('mediaId',) , 'Media', type=media['type'], id=media['id'])
        d.addCallback(database.queryResult)
        values = (None, media['type'], media['id'], media['seconds'],
                  media['title'], userId, 0)
        d.addErrback(database.dbInsertReturnLastRow, 'Media', *values)
        return d

    def writeQueue(self, res, userId, timeNow, flag):
        """ Insert queue into Queue. """
        # res is the [mediaId]
        return database.insertQueue(res[0], userId, timeNow, flag)
        
    def printRes(self, res):
        clog.info('(printRes) %s' % res, sys)
        return defer.succeed(res)
        
    def errYtInfo(self, err):
        clog.error('(errYtInfo) %s' % err, sys)

    def dbErr(self, err):
        clog.error('(dbErr): %s' % err.value, sys)

    def _cyCall_changeMedia(self, fdict):
        # set self.nowPlaying
        mType = fdict['args'][0]['type']
        mId = fdict['args'][0]['id']
        mTitle = fdict['args'][0]['title']
        self.nowPlaying = (mType, mId, mTitle) # these are unicode
        # everything has to be encoded to utf-8 or it errors
        s = mTitle.encode('utf-8') + ' (%s, %s)' % (mType.encode('utf-8'),
            mId.encode('utf-8'))
        clog.info('(_cyCall_changeMedia) %s' % s, sys)

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
        timeNow = int(time.time())
        for name, user in self.userdict.iteritems():
            user['deferred'].addCallback(self.clockUser, user, timeNow)
        self.cyRestart = False

    def clockUser(self, res, leftUser, timeNow):
        """ Clock out a user, by updating their accessTime """
        username = leftUser['name']
        clog.info('(clockUser) Clocking out %s!' % username, sys)
        timeJoined = leftUser['timeJoined']
        timeStayed = timeNow - timeJoined
        userId = leftUser['keyId']
        return database.updateCyUser(timeNow, timeStayed, userId)

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
            d = database.addByUserAdd(username, quantity)
        else:
            return
        d.addCallback(self.doAddMedia, temp, pos)

    def doDeleteMedia(self, mType, mId):
        """ Delete media """
        uid = self.getUidFromTypeId(mType, mId)
        clog.info('(doDeleteMedia) Deleting media uid %s' % uid)
        self.sendf({'name': 'delete', 'args': uid})

class WsFactory(WebSocketClientFactory):
    protocol = CyProtocol

    def __init__(self, arg):
        WebSocketClientFactory.__init__(self, arg)

    def clientConnectionLost(self, connector, reason):
        clog.warning('(clientConnectionLost) Connection lost to Cyutbe. %s'
                     % reason, sys)
        if not self.handle.cyRestart:
            self.handle.doneCleanup('cy')
        else:
            #self.handle.cyPost() # reconnect
            self.handle.doneCleanup('cy')

    def clientConnectionFailed(self, connector, reason):
        clog.error('(clientConnectionFailed) Connection failed to Cytube. %s'
                    % reason, sys)
