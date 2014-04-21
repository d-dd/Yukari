import database
import time
from conf import config
from collections import deque
from twisted.words.protocols import irc
from twisted.internet import reactor, defer
from twisted.internet.protocol import ClientFactory

# on Rizon networks, the optional part/quit message rarely works.

class IrcProtocol(irc.IRCClient):
    lineRate = None
    nickname = str(config['irc']['nick'])

    def __init__(self):
        self.nickname = str(config['irc']['nick'])
        self.chatQueue = deque()
        self.bucketToken = int(config['irc']['bucket'])
        self.underSpam = False

    def addQueue(self, msg):
        if self.underSpam is False and self.bucketToken != 0:
            self.chatQueue.append(msg)
            self.popQueue()
        elif self.underSpam:# and self.bucketToken <= 6:
            print 'throttled'
            return

        elif self.bucketToken == 0:
            print "TOO FAST. Turning on spam block."
            msg = '[Hit throttle: Dropping messages %s.]'
            self.say(self.channelName, msg % 'from Cytube')
            self.factory.handle.sendToCy(msg % 'to IRC', modflair=True)
            self.underSpam = True

    def addToken(self):
        if self.bucketToken < 13:
            print "adding 1 token, token: %s" % self.bucketToken
            self.bucketToken += 1
        if self.underSpam and self.bucketToken > 10:
            self.underSpam = False
            self.say(self.channelName, 
                    '[Resuming relay from Cytube.]')
            self.factory.handle.sendToCy('[Resuming relay to IRC.]',
                                  modflair=True)

    def popQueue(self):
        print 'running POP QUEUE'
        self.bucketToken -= 1
        self.logSay(self.channelName, self.chatQueue.popleft())
        reactor.callLater(17-self.bucketToken, self.addToken)

    def logSay(self, channel, msg):
        """ Log and send out message """
        sql = 'INSERT INTO IrcChat VALUES(?, ?, ?, ?, ?, ?)'
        msgd = msg.decode('utf-8')
        binds = (None, 1, 3, round(time.time(), 2), msgd, 1)
        d = database.operate(sql, binds) # must be in unicode
        self.say(channel, msg) # must not be in unicode
        
    def names(self, channel):
        d = defer.Deferred()
        self.sendLine('NAMES %s' % channel)
        return d

    def irc_RPL_NAMREPLY(self, prefix, params):
        channel = params[2]
        nicklist = params[3].split(' ')
        print nicklist
        #print prefix
        #print params

    #def irc_RPL_ENDOFNAMES(self, prefix, params):
    #     print prefix, params

    #def getNames(self):
    #     d = self.names(self.channelName)
    #   d.addCallback(self.gotNames)

    #def gotNames(self, response):
    #     print 'gotnames response: %s' % response



    def connectionMade(self):
        irc.IRCClient.connectionMade(self)
        self.channelName = str(config['irc']['channel'])
        self.nickname = str(config['irc']['nick'])

    def signedOn(self):
        self.join(self.channelName)
        self.factory.prot = self

    def userJoined(self, user, channel):
        print "%s has joined %s" % (user, channel)

    def userLeft(self, user, channel):
        print '%s has left the %s' % (user, channel)
        
    def userRenamed(self, oldname, newname):
        print '%s is now known as %s' % (oldname, newname)

    def nickChanaged(self, nick):
        self.nickname = nick

    def joined(self, channel):
        print 'Joined IRC channel: %s' % channel
        self.factory.handle.irc = True

    def left(self, channel):
        print 'Left IRC channel: %s' % channel
        self.factory.handle.irc = False

    def privmsg(self, user, channel, msg):
        print 'priv message from %s' % user
        self.factory.handle.recIrcMsg(user, channel, msg)
        self.logProcess(user, msg)

    def sendChat(self, channel, msg):
        if isinstance(msg, unicode):
            msg = msg.encode('utf-8')
        self.addQueue(msg)

    def partLeave(self, reason='Goodbye!'):
        self.leave(self.channelName, reason)
        self.quit(message='Shutting down...!')

    def logProcess(self, user, msg):
        timeNow = round(time.time(), 2)
        nickname = user.split('!')[0]
        i = user.find('~')
        j = user.find('@')
        username = user[i+1:j]
        host = user[j+1:]
        d = self.logIrcUser(nickname, username, host)
        d.addCallback(self.queryUser, nickname, username, host)
        d.addCallback(self.logChat, 3, timeNow, msg)

    def logIrcUser(self, nickname, username, host):
        """ logs IRC chat to IrcChat table """
        ### Since we're only interested in logging chat, it is sufficient to
        ### insert users to the IRC users table only after a message has been
        ### received. Users who join but do not chat will never be logged.
        ### STATUS (if user has identified) is only checked during join, but 
        ### users can logout, so the value may not be accuate, but this is fine 
        ### for our purposes since it will still be the same user.
        ### STATUS works on Rizon, but may not be available on other networks.
        # add user to IrcUser
        sql = 'INSERT OR IGNORE INTO IrcUser VALUES(?, ?, ?, ?, ?, ?)'
        binds = (None, nickname.lower(), username, host, nickname, 0)
        return database.operate(sql, binds)

    def queryUser(self, response, nickname, username, host):
        sql = 'SELECT userId FROM IrcUser WHERE nickLower=? AND username=? AND host=?'
        binds = (nickname.lower(), username, host)
        return database.query(sql, binds)

    def logChat(self, result, status, timeNow, msg):
        # use 3 for status for now
        msg = msg.decode('utf-8')
        sql = 'INSERT INTO IrcChat VALUES(?, ?, ?, ?, ?, ?)'
        binds = (None, result[0][0], 3, timeNow, msg, None)
        return database.operate(sql, binds)
    
class IrcFactory(ClientFactory):
    protocol = IrcProtocol

    def __init__(self, channel):
        self.channel = channel

    def clientConnectionLost(self, connector, reason):
        print 'Connection Lost to IRC. Reason: %s' % reason
        self.handle.doneCleanup('irc')

    def clientConnectionFailed(self, connector, reason):
        print 'Connection Failed to IRC. Reason: %s' % reason

