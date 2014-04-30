import database, apiClient, tools
from conf import config
import json, time, re
from collections import deque
from sqlite3 import IntegrityError
from twisted.python.util import InsensitiveDict
from autobahn.twisted.websocket import WebSocketClientProtocol,\
                                       WebSocketClientFactory

class NoRowException(Exception):
    pass

class CyProtocol(WebSocketClientProtocol):

    def __init__(self):
        self.unloggedChat = deque()
        self.unloggedChatUsers = []
        self.testan = ''
        self.receivedChatBuffer = False
        ### Need to imporve this regex, it matches non-videos
        # ie https://www.youtube.com/feed/subscriptions
        self.ytUrl = re.compile(
                (r'(https?://)?(www\.)?(youtube|youtu|youtube-nocookie)\.'
                  '(com|be)/(watch\?v=|embed/|v/|.+\?v=)?([^&=%\?]{11})'))

    def onOpen(self):
        print "Connected to Cytube!"
        self.connectedTime = time.time()
        self.lastUserlist = 0
        self.factory.prot = self
        self.factory.handle.cy = True
        self.initialize()

    def onMessage(self, msg, binary):
        if msg == '2::':
            self.sendMessage(msg) # return heartbeat
        elif msg.startswith('5:::{'):
            fstr = msg[4:]
            fdict = json.loads(fstr)
            if fdict['name'] in ('chatMsg', 'userlist', 'addUser', 'userLeave'):
                print fstr
            self.processFrame(fdict)

    def onClose(self, wasClean, code, reason):
        print 'Closed Protocol connection: %s' % reason

    def sendf(self, dict): # 'sendFrame' is a WebSocket method name
        frame = json.dumps(dict)
        frame = '5:::' + frame
        print '[->] %s' % frame
        self.sendMessage(frame)

    def sendChat(self, msg, modflair=False):
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
            print ytId
            d = apiClient.requestApi(ytId)
            d.addCallbacks(self.sendChat, self.errYtInfo)

    def _cyCall_login(self, fdict):
        if fdict['args'][0]['success']:
            self.joinRoom()

    def _cyCall_setMotd(self, fdict):
        # setMotd comes after the chat buffer when joining a channel
        self.receivedChatBuffer = True

    def _cyCall_chatMsg(self, fdict):
        if not self.receivedChatBuffer:
            return
        timeNow = round(time.time(), 2)
        username = fdict['args'][0]['username']
        msg = fdict['args'][0]['msg']
        isRegistered = self.checkRegistered(username)
        if username != config['Cytube']['username'] and username != '[server]':
            self.factory.handle.recCyMsg(username, msg)
            self.searchYoutube(msg)
        # log everything, even the chat relays
        self.logChatnew(username, isRegistered, fdict, timeNow)

    def a__cyCall_addUser(self, fdict):
        user = fdict['args'][0]
        user['timeJoined'] = int(time.time())
        user['keyId'] = None
        self.userdict[user['name']] = user
        d = self.dbAddCyUser(user, user['timeJoined'])
        d.addBoth(self.dbAddCyUserResultadd, user['name'])

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
            print "cached %s's key %s" % (user['name'], res[0])
            self.userdict[user['name']]['keyId'] = res[0]
        #d = self.dbAddCyUser(user, user['timeJoined'])
        #d.addBoth(self.dbAddCyUserResultadd, user['name'])

    def _cyCall_userLeave(self, fdict):
        username = fdict['args'][0]['name']
        #leftUser = self.userdict.pop(username)InsensitiveDict has no pop method
        leftUser = self.userdict[username]
        d = self.clockUser(leftUser, int(time.time()))
        d.addBoth(self.dbAddCyUserResult)
        try:
           # leftUser = self.userdict[username]
            del self.userdict[username]
        except KeyError as e:
            print type(e), e
            return

    def _cyCall_userlist(self, fdict):
        if time.time() - self.lastUserlist < 3: # most likely the same userlist
            print "Duplicate userlist detected" # but with ip/aliases if mod+
            return
        self.lastUserlist = time.time()
        userlist = fdict['args'][0]
        timeNow = int(time.time())

        # make a dictonary of users
        self.userdict = InsensitiveDict() # Case insensitive
        for user in userlist:
            user['timeJoined'] = timeNow
            self.userdict[user['name']] = user
            self.userJoin(user, timeNow)

    def logChatnew(self, username, isRegistered, fdict, timeNow):
        dlog = self.queryUserId(username, isRegistered)
        dlog.addCallback(self.logChat, username, isRegistered, fdict, timeNow)

    def queryUserId(self, username, isRegistered):
        """ Query UserId to log chat to database """
        sql = 'SELECT userId FROM cyUser WHERE nameLower=? AND registered=?'
        binds = (username.lower()+self.testan, isRegistered)
        return database.query(sql, binds)
    
    def logChat(self, result, username, isRegistered, fdict, timeNow):
        args = fdict['args'][0]
        msg = args['msg']
        msg = tools.unescapeMsg(msg)
        chatCyTime = round((args['time'])/1000.0, 2)
        try:
            modflair = args['meta']['modflair']
        except KeyError:
            modflair = None

        # userId query returned nothing
        if not result:
            print "User isn't in the database yet. Putting aside msg for later."
            self.unloggedChat.append((username, isRegistered, fdict, timeNow))
            self.unloggedChatUsers.append(username)

        elif result:
            flag = None
            if 'addClass' in args['meta']: # seldom happens
                flag = args['meta']['addClass']
            #print 'user ID %s' % result[0]
            sql = 'INSERT INTO CyChat Values(?, ?, ?, ?, ?, ?, ?)'
            binds = (None, result[0][0], timeNow, chatCyTime, msg, modflair, flag)
            return database.operate(sql, binds)
    
    def errYtInfo(self, err):
        print err

    def dbAddCyUser(self, user, timeNow):
        #user['timeJoined'] = timeNow
        username = user['name']
        isRegistered = self.checkRegistered(username)
        sql = 'INSERT INTO CyUser VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)'
        binds = (None, username.lower(), isRegistered, username,
                 0, 0, timeNow, timeNow, 0)
        return database.operate(sql, binds)

    def dbAddCyUserResultadd(self, outcome, username):
        if outcome is None:
            print '[DB] cyUserAdd successful!'
            if username in self.unloggedChatUsers: # add unlogged chat
                self.logUnloggedChat()
                    
        elif outcome.type == IntegrityError: # row already exists
            print '[DB] cyUserAdd failed. Already in table: %s' % outcome.value
        else:
            print '[DB] AddCyUser: some other error: %s' % outcome
    
    def logUnloggedChat(self):
        for i in range(len(self.unloggedChat)):
            print 'attempting to save old chat!'
            args = self.unloggedChat.popleft()
            self.logChatnew(*args)
        self.unloggedChatUsers = []

    def dbAddCyUserResult(self, outcome):
        self.outcome = outcome
        if outcome is None:
            print '[DB] cyUserAdd successful!'
        elif outcome.type == IntegrityError: # row already exists
            print '[DB] cyUserAdd failed. Already in table: %s' % outcome.value
        else:
            print '[DB] AddCyUser: some other error: %s' % outcome

    def dbQueryCyUserErr(self, err):
        print '[DB] QueryCyUser Error: %s' % err.value

    def cleanUp(self):
        # set restart to False
        self.factory.handle.cyRestart = False
        # disconnect first so we don't get any more join/leaves
        self.sendClose()
        # log everyone's access time before shutting down
        timeNow = int(time.time())
        for name, user in self.userdict.iteritems():
            self.clockUser(user, timeNow)
        self.cyRestart = False

    def clockUser(self, leftUser, timeNow):
        """ Clock out a user, by updating their accessTime """
        username = leftUser['name']
        print 'Clocking out %s!' % username
        timeJoined = leftUser['timeJoined']
        timeStayed = timeNow - timeJoined
        isRegistered = self.checkRegistered(username)
        sql = ('UPDATE CyUser SET lastSeen=?, accessTime=accessTime+? '
               'WHERE nameLower=? AND registered=?')
        binds = (timeNow, timeStayed, username.lower(), isRegistered)
        return database.operate(sql, binds)

    def checkRegistered(self, username):
        """ Return wether a Cytube user is registered (1) or a guest (0) given
        a username. Checks self.userdict for rank information."""
        if username == '[server]':
            return 1
        else:
            try:
                user = self.userdict[username]
            except KeyError as e:
                print e
                #raise
            if user['rank'] == 0:
                return 0
            else:
                return 1

class WsFactory(WebSocketClientFactory):
    protocol = CyProtocol

    def __init__(self, arg):
        WebSocketClientFactory.__init__(self, arg)

    def clientConnectionLost(self, connector, reason):
        print 'Connection lost to Cyutbe. Reason: %s' % reason
        if not self.handle.cyRestart:
            self.handle.doneCleanup('cy')
        else:
            #self.handle.cyPost() # reconnect
            self.handle.doneCleanup('cy')

    def clientConnectionFailed(self, connector, reason):
        print 'Connection failed to Cytube. Reason: %s' % reason
