import json
import re
import time
import urllib
from collections import deque

import treq

from twisted.internet import task, reactor
from twisted.internet.error import AlreadyCalled, AlreadyCancelled
from twisted.web.http_headers import Headers

import database

from tools import clog, EscapedLogger
from conf import config

bot_token = str(config['discord']['bot_token'])
HOST = 'https://discordapp.com/api/v6'
SERVER = str(config['discord']['server_id'])
CHANNEL = str(config['discord']['relay_channel_id'])
STATUS_CHANNEL = str(config['discord']['status_channel_id'])
STATUS_MSG_NP = str(config['discord']['np_msg_id'])
STATUS_MSG_USERLIST = str(config['discord']['userlist_msg_id'])
HEADERS = Headers({
    'Authorization': ['Bot {}'.format(bot_token)],
    'User-Agent': ['Yukari/Twisted'],
    'Content-Type': ['application/json'],
    })

syst = 'dcREST'
pattern = re.compile(':\w{2,20}:')


def convert_emoji(text, pattern, emoji):
    """
    Look through text and replace :emote: with proper
    Discord <:emote:emote_id> formatting.
    """
    matches = set(re.findall(pattern, text))
    while matches:
        emoji_name_colon = matches.pop()
        emoji_name = emoji_name_colon[1:-1]
        try:
            d = next(item for item in emoji if item["name"] == emoji_name)
        except StopIteration:
            pass
        else:
            dc_emoji = '<:{}:{}>'.format(emoji_name, d.get('id'))
            text = re.sub(emoji_name_colon, dc_emoji, text)
    return text

class DiscordRestApiLoop(object):
    """
    A loop handler that dispatches requests to discord server,
    accounting for per route rate-limiting.

        https://discordapp.com/developers/docs/topics/rate-limits

    Message sent by stack_queue will be sent within the rate limit
    restrictions.
    """

    log = EscapedLogger()
    global_wait = time.time()
    
    def __init__(self, channel_id, loop_now=False):

        self.channel_id = channel_id
        self.loop_now = loop_now
        self.rate_limit = 5
        # set to 3 initially, before we have received any response headers
        self.rate_remaining = 3
        self.rate_reset = 0
        self.queue = deque()
        self.request_loop = task.LoopingCall(self._send_request)

    def stack_queue(self, method, url, content):
        self.queue.appendleft({'method': method,
                               'url': url,
                                'content': content})
        if not self.request_loop.running:
            self.request_loop.start(2.0, now=self.loop_now)

    def _send_request(self):
        if not self.queue:
            if self.request_loop.running:
                self.request_loop.stop()
            return
        now = time.time() - 1  # 1 second buffer
        if (self.rate_remaining < 1+1 and self.rate_reset > now or 
                DiscordRestApiLoop.global_wait > now):
            self.log.warn("Rate limited: {}".format(self.channel_id))
            return
        payload = self.queue.pop()
        method = payload['method']
        url = payload['url']
        content = payload['content']
       # url = '{}/channels/{}/messages'.format(HOST, self.channel_id)
        content = json.dumps({"content": content})
        self.log.debug('at _send_request: {} url {}'.format(self.channel_id,
                                                            url))
        if method == 'post':
            d = treq.post(url, content, headers=HEADERS)
        elif method == 'patch':
            d = treq.patch(url, content, headers=HEADERS)
        elif method == 'delete':
            d = treq.delete(url, headers=HEADERS)
        elif method == 'get':
            d = treq.get(url, headers=HEADERS)
        d.addCallback(self.update_rate_limits)
        if not self.queue:
            self.request_loop.stop()

    def update_rate_limits(self, response):
        if response.code == 429:
            self.log.error('----------429 TOO MANY REQUESTS!!!!!!!!!!!!!!!', )
            treq.json_content(response).addCallback(self.handle_too_many_req)
        elif response.code == 404:
            self.log.error('Received 404')
            return
        h = response.headers
        try:
            self.rate_limit = int(h.getRawHeaders('x-ratelimit-limit')[0])
            self.rate_remaining = int(h.getRawHeaders('x-ratelimit-remaining')[0])
            self.rate_reset = int(h.getRawHeaders('x-ratelimit-reset')[0])
        except(TypeError):
            self.log.debug('header values were empty')
            self.rate_remaining = 0
            self.rate_reset = time.time() + 10
        self.log.debug('response:{} channel:{} remaining: {} reset:{}'.format(
                        response.code, self.channel_id, self.rate_remaining,
                        self.rate_reset))
        if not self.request_loop.running:
            self.request_loop.start(2.0, now=self.loop_now)

    def handle_too_many_req(self, body):
        retry_after_ms = body.get('retry_after', 5000)/1000
        # set remaining to zero just in case
        self.rate_remaining = 0
        self.rate_reset = time.time() + retry_after_ms
        self.log.debugz(repr(body))
        DiscordRestApiLoop.global_wait = time.time() + retry_after_ms
        if body.get('global') is True:
            DiscordRestApiLoop.global_wait = time.time() + retry_after_ms
        
class DiscordHttpRelay(DiscordRestApiLoop):
    log = EscapedLogger()

    def __init__(self, channel_id, loop_now=False):
        super(DiscordHttpRelay, self).__init__(channel_id, loop_now)
        self.linelist = []
        self._is_collecting = False
        self.emoji = []
        self.get_server_emoji(SERVER)

    def get_server_emoji(self, serverid):
        """
        https://discordapp.com/developers/docs/resources/emoji#list-guild-emojis

        The emoji list is used to translate :emote: message from source to
        the appropriate <:emote:emote_id> for Discord.
        """
        url = '{host}/guilds/{server_id}/emojis'.format(host=HOST, server_id=SERVER)
        d = treq.get(url, headers=HEADERS).addCallback(treq.json_content)
        d.addCallback(self.done_emoji)

    def done_emoji(self, json_response):
        self.emoji = json_response
        if json_response.get('code'):
            self.log.error("Error retreiving Emoji list: {}".format(self.emoji))
            self.emoji = []

    def onMessage(self, source, user, msg, action=False):
        """
        Format and post message from elsewhere (cytube, irc)
        to Discord relay channel.

        If the current rate-limit-remaining is less than 2,
        it will "collect" additional messages for 1.5 seconds, where messages
        received during that time will be combined and sent to the stack
        as one message.
        """

        url = '{}/channels/{}/messages'.format(HOST, self.channel_id)
        try:
            msg = msg.encode('utf8')
        except(UnicodeDecodeError):
            # probably already unicode... i know..
            pass
        if source == 'chat':
            from_prefix = 'cyt>'
        elif source == 'irc':
            from_prefix = 'irc>' 
        elif source == 'pm':
            return
        else:
            from_prefix = source+'>'
        msg = convert_emoji(msg, pattern, self.emoji)
        line = "**`{}{}:`** {}".format(from_prefix, user, msg)
        if self.rate_remaining > 2:
            self.stack_queue('post', url, line)
        else:
            self.linelist.append(line)
            if not self._is_collecting:
                reactor.callLater(1.5, self.delayed_relay, url)
                self._is_collecting = True

    def delayed_relay(self, url):
        lines = '\n'.join(self.linelist)
        self.linelist = []
        self.stack_queue('post', url, lines)
        self._is_collecting = False

class DiscordNowPlaying(DiscordRestApiLoop):
    log = EscapedLogger()

    def onChangeMedia(self, np):
        url = '{}/channels/{}/messages/{}'.format(HOST, STATUS_CHANNEL,
                                                         STATUS_MSG_NP)
        content = "Now playing: {}".format(np)
        self.stack_queue('patch', url, content)

    def patch_userlist_msg(self, user, action):
        # not implemented yet
        url = '{}/channels/{}/messages/{}'.format(HOST, STATUS_CHANNEL,
                                                   STATUS_MSG_USERLIST)

class DiscordSearchUnsavedMessages(DiscordRestApiLoop):
    """
    Perform message search with parameter `after=0` to 
    get the earliest messages in the channel.
    Insert them into the database, so they can be deleted in discord.

    Change loop timer depending on the timestamp of the oldest
    messages. (not implemented)

    # TODO - put in rate limits.
    # currently we are not doing this because 
    # the DiscordRestApiLoop does not handle HTTP content responses
    """
    log = EscapedLogger()
    def __init__(self, channel_id, loop_now=False):
        super(DiscordSearchUnsavedMessages, self).__init__(channel_id,
                                                            loop_now)
        self.dbquery_loop = task.LoopingCall(self._getDiscordMsgs)
        self.dbquery_loop.start(60*60, now=loop_now)

    def _getDiscordMsgs(self):
        url = '{}/channels/{}/messages?'.format(HOST, self.channel_id)
        args = {'after': 0,
                'limit': 100,}
        url += urllib.urlencode(args)
        d = treq.get(url, headers=HEADERS)
        d.addCallback(treq.json_content)
        d.addCallback(self._insertMsgs)

    def _insertMsgs(self, results):
        self.log.debug('API returned {} messages'.format(len(results)))
        for msg in results:
            self.saveDiscordMsg(msg)

    def saveDiscordMsg(self, data):
        msg_id = data['id']
        user_id = data['author']['id']
        channel_id = data['channel_id']
        timestamp = data['timestamp']
        d = database.insertDiscordMsg(msg_id, user_id, channel_id, 
                                   timestamp, json.dumps(data), False)
        d.addCallback(self._printres)

    def _printres(self, results):
        if not results:
            pass
        else:
            self.log.debug('message saved. msg_id: {}'.format(results))

    def _cbtreqget(response):
        return treq.json_content(response)
                

class DiscordSingleDelete(DiscordRestApiLoop):
    log = EscapedLogger()

    def __init__(self, channel_id, loop_now=False):
        super(DiscordSingleDelete, self).__init__(channel_id, loop_now)
        self.dbquery_loop = task.LoopingCall(self._queryDiscordMsg)
        self.dbquery_loop.start(60*10, now=loop_now)

    def stack_queue(self, method, url, content):
        url_in_stack = next((di for di in self.queue if di['url'] == url), None)
        if url_in_stack:
            self.log.debug('url {} is already in the stack'.format(url))
            return
        self.queue.appendleft({'method': method,
                               'url': url,
                                'content': content})
        if not self.request_loop.running:
            self.request_loop.start(2.0, now=self.loop_now)

    def _queryDiscordMsg(self):
        d = database.queryOldDiscordMsg(self.channel_id)
        d.addCallback(self.cbQueryDiscordMsg)

    def cbQueryDiscordMsg(self, results):
        if not results:
            return
        self.log.debug('msg to delete: {}'.format(results))
        for tmsg_id in results:
            self.delete_msg_id(tmsg_id[0])

    def delete_msg_id(self, msg_id):
        url = '{}/channels/{}/messages/{}'.format(HOST, self.channel_id,
                                                   msg_id)
        self.stack_queue('delete', url, msg_id)

def bulkDelete(msg_ids):
    """
    bulk delete messages
    msg_ids: list of msg_ids
 https://discordapp.com/developers/docs/resources/channel#bulk-delete-messages
    """
    #TODO - put in rate limiting pool
    if len(msg_ids) <= 1:
        # Can't use Bulk delete for just one message
        #clog.info('no messages to bulk delete', 'dcresclient')
        return
    clog.info('bulk deleting %s messages' % json.dumps(msg_ids), 'dcrestclient')
    payload = {'messages': msg_ids}
    url = '{}/channels/{}/messages/bulk-delete'.format(HOST, CHANNEL)
    d = treq.post(url, json.dumps(payload), headers=HEADERS)
    return d
