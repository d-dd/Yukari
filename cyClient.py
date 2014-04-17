import database, apiClient
from conf import config
import json, time, re
from sqlite3 import IntegrityError
from twisted.internet import reactor
from twisted.enterprise import adbapi
from twisted.python.util import InsensitiveDict
from autobahn.twisted.websocket import WebSocketClientProtocol,\
                                       WebSocketClientFactory

class CyProtocol(WebSocketClientProtocol):

    def onOpen(self):
        print "Connected to Cytube!"
        self.connectedTime = time.time()
        self.isReady = False # wait 3 seconds for chat buffer
        reactor.callLater(3, self.doneReady)
        self.lastUserlist = 0
        self.factory.prot = self
        self.factory.handle.cy = True # put this in room join later
        self.initialize()

    def doneReady(self):
         self.isReady = True

    def initialize(self):
        self.sendf({'name': 'initChannelCallbacks'})
        name = config['Cytube']['username']
        pw = config['Cytube']['password']
        self.sendf({'name': 'login',
                    'args': {'name': name, 'pw': pw}})
        ### Need to imporve this regex, it matches non-videos
        # ie https://www.youtube.com/feed/subscriptions
        self.ytUrl = re.compile(
                (r'(https?://)?(www\.)?(youtube|youtu|youtube-nocookie)\.'
                  '(com|be)/(watch\?v=|embed/|v/|.+\?v=)?([^&=%\?]{11})'))

    def _cyCall_login(self, fdict):
        if fdict['args'][0]['success'] is True:
            self.joinRoom()

    def joinRoom(self):
            channel = config['Cytube']['channel']
            self.sendf({'name': 'joinChannel', 'args': {'name':channel}})

    def onMessage(self, msg, binary):
        # return heartbeat
        if msg == '2::':
            self.sendMessage(msg)
        elif msg.startswith('5:::{'):
            fstr = msg[4:]
            fdict = json.loads(fstr)
            if fdict['name'] in ('userlist', 'addUser', 'userLeave'):
                print fstr
            self.processFrame(fdict)

    def processFrame(self, fdict):
        name = fdict['name']
        # send to the appropriate methods
        thunk = getattr(self, '_cyCall_%s' % (name,), None)
        if thunk is not None:
            thunk(fdict)
        else:
            pass
            #print 'No method defined for %s.' % name

    def _cyCall_chatMsg(self, fdict):
        username = fdict['args'][0]['username']
        msg = fdict['args'][0]['msg']
        if self.isReady is not True:
            return
        if username != config['Cytube']['username']:
            self.factory.handle.recCyMsg(username, msg)
        m = self.ytUrl.search(msg)
        if m:
            ytId = m.group(6)
            d = apiClient.requestApi(ytId)
            d.addCallbacks(self.sendChat, self.errYtInfo)

    def errYtInfo(self, err):
        print err

    def _cyCall_addUser(self, fdict):
        d = self.dbAddCyUser(fdict['args'][0], int(time.time()))
        d.addBoth(self.dbAddCyUserResult)

    def _cyCall_userLeave(self, fdict):
        username = fdict['args'][0]['name']
        #leftUser = self.userdict.pop(username)InsensitiveDict has no pop method
        try:
            leftUser = self.userdict[username]
            del self.userdict[username]
        except KeyError as e:
            print type(e), e
            return
        d = self.clockUser(leftUser, int(time.time()))
        d.addBoth(self.dbAddCyUserResult)

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
            d = self.dbAddCyUser(user, timeNow)
            d.addBoth(self.dbAddCyUserResult)

    def dbAddCyUser(self, user, timeNow):
        registered = self.isRegistered(user)
        self.user = user
        user['timeJoined'] = timeNow
        name = user['name']
        rank = user['rank']
        self.userdict[name] = user

        sql = 'INSERT INTO CyUser VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)'
        binds = (None, name.lower(), registered, name,
                 0, 0, timeNow, timeNow, 0)
        return database.operate(sql, binds)

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

    def sendChat(self, msg, modflair=False):
        if modflair is True:
            modflair = 3 ### TODO remove hardcode rank
        self.sendf({'name': 'chatMsg',
                   'args': {'msg': msg, 'meta': {'modflair': modflair}}})

    def sendf(self, dict):
        frame = json.dumps(dict)
        frame = '5:::%s' % frame
        print '[->] %s' % frame
        self.sendMessage(frame)

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
        name = leftUser['name']
        print 'Clocking out %s!' % name
        timeJoined = leftUser['timeJoined']
        timeStayed = timeNow - timeJoined
        registered = self.isRegistered(leftUser)
        sql = ('UPDATE CyUser SET lastSeen=?, accessTime=accessTime+? '
               'WHERE nameLower=? AND registered=?')
        binds = (timeNow, timeStayed, name.lower(), registered)
        return database.operate(sql, binds)

    def isRegistered(self, user):
        if user['rank'] == 0 or user['rank'] == 1.5:
            return 0
        return 1

    def onClose(self, wasClean, code, reason):
        print 'Closed Protocol connection: %s' % reason

class WsFactory(WebSocketClientFactory):
    protocol = CyProtocol

    def __init__(self, arg):
        WebSocketClientFactory.__init__(self, arg)

    def clientConnectionLost(self, connector, reason):
        print 'Connection lost to Cyutbe. Reason: %s' % reason
        if self.handle.cyRestart is False:
            self.handle.doneCleanup('cy')
        else:
            self.handle.cyPost() # reconnect

    def clientConnectionFailed(self, connector, reason):
        print 'Connection failed to Cytube. Reason: %s' % reason
        
