from conf import config
from collections import deque
from twisted.words.protocols import irc
from twisted.internet import reactor
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
        elif self.underSpam is True:# and self.bucketToken <= 6:
            print 'throttled'
            return

        elif self.bucketToken == 0:
            print "TOO FAST. Turning on spam block."
            msg = '[Hit throttle: Dropping messages %s.]'
            self.say(self.channelName, msg % 'from Cytube')
            self.factory.handle.sendToCy(msg % 'to IRC', modflair=True)
            self.underSpam = True

    def addToken(self):
        if self.bucketToken < 10:
            print "adding 1 token, token: %s" % self.bucketToken
            self.bucketToken += 1
        if self.underSpam is True and self.bucketToken > 10:
            self.underSpam = False
            self.say(self.channelName, 
                    '[Resuming relay from Cytube.]')
            self.factory.handle.sendToCy('[Resuming relay to IRC.]',
                                  modflair=True)

    def popQueue(self):
        print 'running POP QUEUE'
        self.bucketToken -= 1
        self.say(self.channelName, self.chatQueue.popleft())
        reactor.callLater(13-self.bucketToken, self.addToken)

    def connectionMade(self):
        irc.IRCClient.connectionMade(self)
        self.channelName = str(config['irc']['channel'])
        self.nickname = str(config['irc']['nick'])

    def signedOn(self):
        self.join(self.channelName)
        self.factory.prot = self

    def nickChanaged(self, nick):
        self.nickname = nick

    def joined(self, channel):
        print 'Joined IRC channel: %s' % channel
        self.factory.handle.irc = True

    def left(self, channel):
        print 'Left IRC channel: %s' % channel
        self.factory.handle.irc = False

    def privmsg(self, user, channel, msg):
        if user != self.nickname:
            self.factory.handle.recIrcMsg(user, channel, msg)

    def sendChat(self, channel, msg):
        if isinstance(msg, unicode):
            msg = msg.encode('utf-8')
        self.addQueue(msg)

    def partLeave(self, reason='Goodbye!'):
        self.leave(self.channelName, reason)
        self.quit(message='Shutting down...!')

class IrcFactory(ClientFactory):
    protocol = IrcProtocol

    def __init__(self, channel):
        self.channel = channel

    def clientConnectionLost(self, connector, reason):
        print 'Connection Lost to IRC. Reason: %s' % reason
        self.handle.doneCleanup('irc')

    def clientConnectionFailed(self, connector, reason):
        print 'Connection Failed to IRC. Reason: %s' % reason

