import json
import time

import treq

from twisted.internet import reactor
from twisted.web.http_headers import Headers

from tools import clog
from conf import config

bot_token = str(config['discord']['bot_token'])
base = 'https://discordapp.com/api/v6/'
CHANNEL = str(config['discord']['channel_id'])

syst = 'dcREST'

class DiscordRestMessenger(object):
    def __init__(self):
        self.rate_limit_reset = 0
        self.ratelimit_remaining = 5
        self.linelist = []
        self.is_queueing = False

    def onMessage(self, source, user, msg, action=False):
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
        line = "({}{}): {}".format(from_prefix, user, msg)
        self.linelist.append(line)
        if self.ratelimit_remaining > 2:
            self.post_to_discord(CHANNEL)
        else:
            if not self.is_queueing:
                reactor.callLater(max(self.rate_limit_reset-time.time()+1,0), 
                                  self.post_to_discord, CHANNEL)
                self.is_queueing = True

    def post_to_discord(self, channel):
        lines = '\n'.join(self.linelist)
        self.linelist = []
        url = '{}channels/{}/messages'.format(base, channel)
        headers = Headers({
            'Authorization': ['Bot {}'.format(bot_token)],
            'User-Agent': ['Yukari/Twisted'],
            'Content-Type': ['application/json'],
            })
        content = json.dumps({"content": lines})
        d = treq.post(url, content, headers=headers)
        d.addCallback(self.print_response)
        self.is_queueing = False

    def print_response(self, response):
        print response.code, response.phrase
        print response.headers
        h = response.headers
        self.rate_limit_reset = int(h.getRawHeaders('x-ratelimit-reset')[0])
        self.ratelimit_remaining = int(h.getRawHeaders('x-ratelimit-remaining')[0])

