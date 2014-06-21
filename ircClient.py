import database
import time
from tools import clog
from tools import getTime
from conf import config
from collections import deque
from twisted.words.protocols import irc
from twisted.internet import reactor, defer, task
from twisted.internet.protocol import ClientFactory

# on Rizon networks, the optional part/quit message rarely works.
class NoRowException(Exception):
    pass

sys = 'IrcClient'
class IrcProtocol(irc.IRCClient):
    lineRate = None # use our own throttle methods
    nickname = str(config['irc']['nick'])

    def __init__(self):
        self.nickname = str(config['irc']['nick'])
        self.channelName = str(config['irc']['channel'])
        self.chatQueue = deque()
        self.bucketToken = int(config['irc']['bucket'])
        self.bucketTokenMax = int(config['irc']['bucket'])
        self.throttleLoop = task.LoopingCall(self.addToken)
        self.underSpam = False
        self.nicklist = []
        self.nickdict = {} # {('nick','user','host'): id}
        self.ircConnect = time.time()

    def addQueue(self, msg):
        if not self.underSpam and self.bucketToken != 0:
            self.chatQueue.append(msg)
            self.popQueue()
        elif self.underSpam:
            clog.warning('(addQueue) chat is throttled', sys)
            return

        elif self.bucketToken == 0:
            clog.warning('(addQueue) blocking messages from CyTube', sys)
            msg = '[Hit throttle: Dropping messages %s.]'
            self.say(self.channelName, msg % 'from Cytube')
            self.factory.handle.sendToCy(msg % 'to IRC', modflair=True)
            self.underSpam = True

    def addToken(self):
        if self.bucketToken < self.bucketTokenMax:
            clog.debug('(addToken) +1, token: %s' % self.bucketToken, sys)
            self.bucketToken += 1
        if self.underSpam and self.bucketToken > 10:
            self.underSpam = False
            self.say(self.channelName, 
                    '[Resuming relay from Cytube.]')
            self.factory.handle.sendToCy('[Resuming relay to IRC.]',
                                  modflair=True)
        elif self.bucketToken == self.bucketTokenMax:
            self.throttleLoop.stop()

    def popQueue(self):
        clog.debug('(popQueue) sending chat from IRC chat queue', sys)
        self.bucketToken -= 1
        self.logSay(self.channelName, self.chatQueue.popleft())
        if not self.throttleLoop.running:
            self.throttleLoop.start(2, now=False)

    def logSay(self, channel, msg):
        """ Log and send out message """
        sql = 'INSERT INTO IrcChat VALUES(?, ?, ?, ?, ?, ?)'
        msgd = msg.decode('utf-8')
        binds = (None, 1, 3, getTime(), msgd, 1)
        d = database.operate(sql, binds) # must be in unicode
        self.say(channel, msg) # must not be in unicode
        
    def irc_RPL_NAMREPLY(self, prefix, params):
        channel = params[2]
        nicks = params[3].split(' ')
        self.nicklist.extend(nicks)
        clog.debug('(irc_RPL_NAMREPLY) nicklist:%s' % self.nicklist, sys)

    def irc_RPL_ENDOFNAMES(self, prefix, params):
        clog.debug('(irc_RPL_ENDOFNAMES) prefix::%s, params %s.' 
                    % (prefix, params), sys)

    def connectionMade(self):
        irc.IRCClient.connectionMade(self)

    def signedOn(self):
        self.join(self.channelName)
        self.factory.prot = self

    def userJoined(self, user, channel):
        clog.info('%s has joined %s' % (user, channel), sys)

    def userLeft(self, user, channel):
        clog.info('%s has left the %s' % (user, channel), sys)
        
    def userRenamed(self, oldname, newname):
        clog.info('%s is now known as %s' % (oldname, newname), sys)

    def nickChanaged(self, nick):
        self.nickname = nick

    def joined(self, channel):
        clog.info('Joined IRC channel: %s' % channel, sys)
        self.factory.handle.irc = True

    def left(self, channel):
        clog.info('Left IRC channel: %s' % channel, sys)
        self.factory.handle.irc = False

    def kickedFrom(self, channel, kicker, message):
        clog.info('kickedFrom %s by %s: %s' % (channel, kicker, message), sys)
        self.join(self.channelName)

    def privmsg(self, user, channel, msg):
        clog.debug('priv message from %s' % user, sys)
      #  if msg == '$test':
      #      self.test_module()
        self.factory.handle.recIrcMsg(user, channel, msg)
        flag = 0
        self.logProcess(user, msg, flag)

    def action(self, user, channel, data):
        clog.debug('action %s by %s' % (data, user) , sys)
        self.factory.handle.recIrcMsg(user, channel, data, modifier='action')
        flag = 2 #action
        self.logProcess(user, data, flag)

    def sendChat(self, channel, msg):
        if isinstance(msg, unicode):
            msg = msg.encode('utf-8')
        self.addQueue(msg)

    def partLeave(self, reason='Goodbye!'):
        self.leave(self.channelName, reason)
        self.quit(message='Shutting down...!')

    def logProcess(self, user, msg, flag):
        timeNow = getTime()
        nickname = user.split('!')[0]
        i = user.find('~')
        j = user.find('@')
        username = user[i+1:j]
        host = user[j+1:]
        if nickname in self.nickdict:
            keyId = self.nickdict[nickname]['keyId']
            if keyId is None:
                # a callback for the keyId must already be registered
                clog.error('(logProcess) key None for user %s' % nickname, sys)
                dd = self.nickdict[nickname]['deferred']
                dd.addCallback(self.logChat, 3, timeNow, msg, flag)
            if keyId:
                d = self.logChat(keyId, 3, timeNow, msg, flag)
                
        else:
            self.nickdict[nickname] = {'keyId': None, 'deferred': None}
            clog.debug('(logProcess) added %s to nickdict' % nickname, sys)
            dd = self.queryOrAddUser(nickname, username, host)
            dd.addCallback(self.logChat, 3, timeNow, msg, flag)
            self.nickdict[nickname]['deferred'] = dd

    def queryOrAddUser(self, nickname, username, host):
        clog.debug('(queryOrAddUser) Quering %s:%s:%s' % (nickname, username, host), sys)
        d = database.dbQuery(('userId', 'flag'), 'ircUser',
               nickLower=nickname.lower(), username=username, host=host)
        d.addCallback(database.queryResult)
        values = (None, nickname.lower(), username, host, nickname, 0)
        d.addErrback(database.dbInsertReturnLastRow, 'ircUser', *values)
        clog.debug('(queryOrAddUser) Adding %s' % username, sys)
        d.addErrback(self.dbErr)
        d.addCallback(self.cacheKey, nickname)
        d.addErrback(self.dbErr)
        return d
        
    def dbErr(self, err):
        clog.error('(dbErr): %s' % err.value, sys)
        clog.error('(dbErr): %s' % dir(err), sys)
        clog.error('(dbErr): %s' % err.printTraceback(), sys)

    def returnKey(self, key):
        return defer.succeed(key)

    def cacheKey(self, res, nickname):
        clog.error('the key is %s:' % res[0], sys)
        assert res, 'no res at cacheKey'
        if res:
            clog.info("(cacheKey) cached %s's key %s" % (nickname, res[0]))
            self.nickdict[nickname]['keyId'] = res[0]
            return defer.succeed(res[0])

    def logIrcUser(self, nickname, username, host):
        """ logs IRC chat to IrcChat table """
        sql = 'INSERT OR IGNORE INTO IrcUser VALUES(?, ?, ?, ?, ?, ?)'
        binds = (None, nickname.lower(), username, host, nickname, 0)
        return database.operate(sql, binds)

    def queryUser(self, response, nickname, username, host):
        if nickname in self.nickdict:
            pass
        sql = 'SELECT userId FROM IrcUser WHERE nickLower=? AND username=? AND host=?'
        binds = (nickname.lower(), username, host)
        return database.query(sql, binds)

    def checkStatus(self, response, nickname):
        msg = 'STATUS %s' % nickname
        self.msg('NickServ', msg)
        
    def logChat(self, result, status, timeNow, msg, flag):
        status = 0 # we don't really need this
        msg = msg.decode('utf-8')
        sql = 'INSERT INTO IrcChat VALUES(?, ?, ?, ?, ?, ?)'
        binds = (None, result, status, timeNow, msg, flag)
        return database.operate(sql, binds)

    def test_makeChat(self, i):
        """ Test user + chat logging functionality """
        user = 'testo%s!~dd@pon.pon.pata.pon' % i
        channel = '#mikumonday'
        msg = '%s_test' % i
        self.privmsg(user, channel, msg)

    def test_module(self):
       self.test_makeChat(1)
       self.test_makeChat(2)
       self.test_makeChat(3)
       self.test_makeChat(4)
    
class IrcFactory(ClientFactory):
    protocol = IrcProtocol

    def __init__(self, channel):
        self.channel = channel

    def clientConnectionLost(self, connector, reason):
        clog.warning('Connection Lost to IRC. Reason: %s' % reason, sys)
        self.handle.doneCleanup('irc')

    def clientConnectionFailed(self, connector, reason):
        clog.warning('Connection Failed to IRC. Reason: %s' % reason, sys)
