# Standard Library
import json
import os
import sys
import time
import zlib

# Twisted Libraries
from twisted.application import service
from twisted.logger import Logger
from twisted.internet import reactor, defer, task
from twisted.internet.error import AlreadyCalled, AlreadyCancelled
from twisted.internet.protocol import ReconnectingClientFactory
from autobahn.twisted.websocket import WebSocketClientProtocol,\
                                       WebSocketClientFactory
# Yukari
import database, tools
from tools import clog, getTime
from conf import config
from connections.discord import dcrestclient

syst = 'DiscordClient'
agent = config['UserAgent']['discord']

TOKEN = config['discord']['bot_token']
RELAY_CHANNEL_ID = config['discord']['relay_channel_id']

class DcProtocol(WebSocketClientProtocol):
    """Discord Gateway Client"""

    DISPATCH           = 0
    HEARTBEAT          = 1
    IDENTIFY           = 2
    PRESENCE           = 3
    VOICE_STATE        = 4
    VOICE_PING         = 5
    RESUME             = 6
    RECONNECT          = 7
    REQUEST_MEMBERS    = 8
    INVALIDATE_SESSION = 9
    HELLO              = 10
    HEARTBEAT_ACK      = 11
    GUILD_SYNC         = 12


    log = Logger()

    def __init__(self):
        super(DcProtocol, self).__init__()
        self.loops = []
        self.laters = []

        self.members = {}

    def errcatch(self, err):
        clog.error('caught something')
        err.printTraceback()
        self.err.append(err)

    def onConnect(self, response):
        self.log.info('(onConnect):{}'.format(response))

    def onOpen(self):
        self.log.info('(onOpen) - success)')
        self.factory.con = self
        self.factory.service.parent.dc = True
        self.factory.resetDelay()

    def onMessage(self, msg, binary):
        if binary:
            msg = zlib.decompress(msg).decode('utf-8')
            clog.debug('Binary received: {0} bytes'.format(len(msg)))

        #self.log.debug(u"{msg!s}", msg=msg)
    
        msg = json.loads(msg)
        op = msg.get('op')
        data = msg.get('d')
        seq = msg.get('s')
        t = msg.get('t')

        self.log.debug(u"Received a Discord Gateway frame: {op!s}", op=op)

        if seq:
            self.factory.series = seq

        if op == self.HEARTBEAT:
            heartbeat_interval_seconds = data['heartbeat_interval'] / 1000.0
            self.laters.append(reactor.callLater(heartbeat_interval_seconds,
                                                             self.beatHeart))

        elif op == self.HEARTBEAT_ACK:
       #     self.log.debug('Received HEARTBEAT_ACK')
            return

        elif op == self.HELLO:
            # start the heartbeat loop
            self.heart_beat_interval = data['heartbeat_interval']
            self.heart_beat_loop = task.LoopingCall(self.beatHeart)
            self.heart_beat_loop.start(self.heart_beat_interval/1000.0,
                                                               now=True)
            self.loops.append(self.heart_beat_loop)
            self.identify()

        elif op == self.DISPATCH:
            self.dispatch(t, data)

    def beatHeart(self):
        payload = {'op': self.HEARTBEAT,
                    'd': self.heart_beat_interval}
        self.sendMessage(json.dumps(payload))
        self.lastBeatHeart = time.time()

    def identify(self):
        payload = {
                'op': self.IDENTIFY,
                'd': {
                        'token': TOKEN,
                        'properties': {
                            '$os': sys.platform,
                            '$browser': 'Yukari',
                            '$device': 'Yukari',
                            '$referrer': '',
                            '$referring_domain': ''
                        },
                        'compress': True,
                        'large_threshold': 250,
                   }
               }
        self.sendMessage(json.dumps(payload))
        return

    def dispatch(self, t, data):
        if t == "READY":
            self.user = data['user']
            self.session_id = data['session_id']
            self.bulk_delete_loop = task.LoopingCall(self.bulk_delete_msg)
            self.bulk_delete_loop.start(60.0, now=False)
            self.loops.append(self.bulk_delete_loop)

        elif t == "MESSAGE_CREATE":
            content = data['content']
            channel_id = data['channel_id']
            self.saveDiscordMsg(data)

            if channel_id == RELAY_CHANNEL_ID:
                user_id = data['author']['id']
                username = data['author']['username']
                name = self.get_nickname(user_id)
                attachments = data['attachments']
                attachment_urls = []
                space = ' ' if content else ''
                for attachment in attachments:
                    content = '{}{}{}'.format(content, space,
                                              attachment.get('url', ''))
                self.factory.service.parent.recDcMsg(name, content)

        elif t == "MESSAGE_DELETE":
            msg_id = data['id']
            database.discordMsgFlagDeletion(msg_id)

        elif t == "MESSAGE_DELETE_BULK":
            msg_ids = data['ids']
            msg_ids = [int(x) for x in msg_ids]
            database.discordMsgFlagDeletionBulk(msg_ids)
            #for msg_id in msg_ids:
            #    database.discordMsgFlagDeletion(msg_id)
 
        elif t == "GUILD_CREATE":
            for member in data['members']:
                self.update_member(member)
                
        elif t == "GUILD_MEMBER_ADD":
            self.update_member(data)

        elif t == "GUILD_MEMBER_UPDATE":
            self.update_member(data)

    def saveDiscordMsg(self, data):
        msg_id = data['id']
        user_id = data['author']['id']
        channel_id = data['channel_id']
        timestamp = data['timestamp']
        database.insertDiscordMsg(msg_id, user_id, channel_id, 
                                    timestamp, json.dumps(data), False)

    def update_member(self, user):
        user_id = user['user']['id']
        username = user['user']['username']
        nick = user.get('nick', '')
        self.members[user_id] = {
                'username': username,
                'nick': nick
                }

    def get_nickname(self, user_id):
        user = self.members.get(user_id)
        return user['nick'] or user['username']

    def bulk_delete_msg(self):
        """
        Query the messages that need to be deleted, and 
        POST bulk delete to delete messages.
        Run this in a loop periodically.
        """
        d = database.queryDiscordMsgToBulkDelete(500)
        d.addCallback(lambda x: [msg[0] for msg in x])
        d.addCallback(dcrestclient.bulkDelete)
        return

    def onClose(self, wasClean, code, reason):
        clog.info('(onClose) Closed Protocol connection. wasClean:%s '
                  'code%s, reason%s' % (wasClean, code, reason), syst)
        self.factory.service.parent.dc = False

    def cleanUp(self):
        self.isLoggedIn = False
        tools.cleanLoops(self.loops)
        tools.cleanLaters(self.laters)
        cleanDeferredList = []
        # log unlogged chat
        #cleanDeferredList.append(self.bulkLogChat())
        return defer.DeferredList(cleanDeferredList).addCallback(self.factory.doneClean)

    def connectionLost(self, reason):
        self.factory.service.parent.ds = False
        clog.error("connection lost at protocol", syst)
        self._connectionLost(reason)
        self.cleanUp()
        try:
            if self.heartbeat.running:
                self.heartbeat.stop()
        except(AttributeError):
            pass
        if self.factory.service.parent.dcRestart:
            self.factory.service.checkChannelConfig(self.factory.ws)

        # The reconnecting factory just works on a exponential backoff timer,
        # so there is a chance that a new connection is established before
        # the old one is done cleaning up.
        # Setting initialDelay >= 3.0 should be fine. :~:

class WsFactory(WebSocketClientFactory, ReconnectingClientFactory):
    protocol = DcProtocol
    initialDelay = 0
    maxDelay = 60 * 2
    # instance number
    instanceId = 0

    def __init__(self, ws, service):
        super(WsFactory, self).__init__(ws)
        self.instanceId += 1
        self.prot = None
        self.ws= ws
        self.service = service
        self.series = 0

    def startedConnecting(self, connector):
        clog.debug('WsFactory started connecting to Discord..', syst)

    def doneClean(self, res):
        if self.service.parent.dcRestart:
            return
        else:
        # when we are shutting down
            self.service.parent.doneCleanup('dc')

class DcService(service.Service):
    log = Logger()
    def errCatch(self, err):
        self.log.error(err.getBriefTraceback())

    def checkChannelConfig(self, currentWsUrl):
        clog.debug("CHECKING CHANNEL CONFIG---------------------------", syst)
        d = self.getWsUrl()
        d.addCallbacks(self.cbGetWsUrl, self.errCatch)
        d.addCallbacks(self.cbMakeWsUrl, self.errCatch)
        d.addCallback(self.cbCompareWsUrls, currentWsUrl)

    def cbCompareWsUrls(self, newWsUrl, currentWsUrl):
        """
        Compare the ws url currently used by factory,
        to the one served at channel.json.
        If they are different, we restart the factory.
        Otherwise, if they are the same, or no response
        from the server, do nothing and let
        ReconnectingFactory try to reconnect.
        """

        self.log.info("comparing WSURLS!")
        if newWsUrl != currentWsUrl and newWsUrl is not None:
            self.log.info("The ws changed to %s!" % newWsUrl)
            self.f.maxRetries = 0
            self.f.stopTrying()
            self.f = None
            self.connectDc(newWsUrl)
        elif newWsUrl is None:
            self.log.info("Failed to retrieve servers from channel.json")
        else:
            self.log.info("The ws didn't change!")

    def startService(self):
        if self.running:
            self.log.error("Service is already running. Only one instance allowed.")
            return
        self.running = 1
        d = self.getchannelurl()
        d.addCallbacks(self.connectDc, self.errCatch)

    def getchannelurl(self):
        d = self.getWsUrl()
        d.addCallbacks(self.cbGetWsUrl, self.errCatch)
        d.addCallbacks(self.cbMakeWsUrl, self.errCatch)
        return d

    def connectDc(self, ws):
        self.log.info("the websocket address is %s" % ws)
        from autobahn.twisted.websocket import connectWS
        wsFactory = WsFactory(ws, self)
        self.f = wsFactory
        wsFactory.setProtocolOptions(
                perMessageCompressionOffers=None,
                perMessageCompressionAccept=None)
        connectWS(wsFactory)

    def stopService(self):
        self.running = 0

    def getWsUrl(self):
        url = "https://discordapp.com/api/v6/gateway"
        self.log.info("sending GET for discord ws servers url: " + url)
        from twisted.web.client import Agent, readBody
        from twisted.internet import reactor
        agent = Agent(reactor)
        d = agent.request('GET', url)
        return d

    def cbGetWsUrl(self, response):
        from twisted.web.client import readBody
        if response.code == 200:
            self.log.debug('200 response')
            return readBody(response)

    def cbMakeWsUrl(self, response, secure=True):
        """
        response : string json of server
        """
        if not response:
            return
        clog.debug(response)
        servers = json.loads(response)
        return servers['url']+'?v=5&encoding=json'

