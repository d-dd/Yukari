from conf import config
from twisted.words.protocols import irc
from twisted.internet.protocol import ClientFactory

# on Rizon networks, the optional part/quit message rarely works.

class IrcProtocol(irc.IRCClient):
    lineRate = None
    nickname = str(config['irc']['nick'])

    def __init__(self):
        self.nickname = str(config['irc']['nick'])

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

    def sendm(self, channel, msg):
        if isinstance(msg, unicode):
            msg = msg.encode('utf-8')
        self.say(channel, msg)

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

