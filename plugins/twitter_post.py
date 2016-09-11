import json
import urllib
from unicodedata import normalize

from twisted.internet.ssl import ClientContextFactory
from twisted.web.client import Agent, readBody
from twisted.web.http_headers import Headers

from conf import config
from tools import clog
from tools import commandThrottle

from twitter_signature import twitter_sign as tw

syst = "tweeter"
keys = {
  "twitter_consumer_secret": str(config['twitter']['twitter_consumer_secret']),
  "twitter_consumer_key": str(config['twitter']['twitter_consumer_key']),
  "access_token": str(config['twitter']['access_token']),
  "access_token_secret": str(config['twitter']['access_token_secret'])
    }

URL = 'https://api.twitter.com/1.1/statuses/update.json'
class WebClientContextFactory(ClientContextFactory):
    def getContext(self, hostname, port):
        return ClientContextFactory.getContext(self)

class TweetPoster(object):
    """ Post statuses on Twitter """

    def __init__(self):
        self.allowed = self._load_allowed()

    def _load_allowed(self):
        # blocking
        try:
            with open('plugins/twitter.allowed') as f:
                return [x.strip('\n') for x in f.readlines()]
        except(IOError):
            clog.error("IOError", syst)
            return
        except:
            clog.error("Error loading allowed list!", syst)
            return

    @commandThrottle(4)
    def _com_tweet(self, yuka, user, args, source):
        if source != 'chat' or not self.allowed: #only cytube
            clog.info('tweet called from invalid source', syst)
            return
        if not args:
            return
        if args == 'reload' and self.allowed:
            # only the first person on the list can reload
            if self.allowed[0] == user:
                self._load_allowed()
                yuka.reply('[tweet] Reloaded allowed list.', source, user)
            else:
                yuka.reply("[tweet] You can't do that.", source, user)
            return

        if user not in self.allowed:
            yuka.reply('[tweet] You are not allowed to do that..', source, user)
            return
        if not self._count_tweet(user, args):
            yuka.reply('Tweet too long.', source, user)
            return
        try:
            status = self._create_status(user, args)
            headers = self._create_header(status)
        except Exception as e:
            clog.error(e, syst)
            self.last_error = e
            yuka.reply('Something went wrong!', source, user)
            return
        d = self.tweet(status, headers)
        d.addCallback(self.cbAnagramRequest)
        d.addCallback(self.parseTwitterResponse, yuka, source, user)
        d.addCallback(self.sendAnagram, yuka, args, source, user)

    def _count_tweet(self, username, text):
        allowed = 140 - len("[XCy]  ()") - len(username)
        norm = len(normalize("NFC", text))
        if allowed >= norm:
            return True
            
    def _create_status(self, username, text):
        microphone = u'\U0001f3a4'
        bubble = u'\U0001f4ac'
        status = '[CY%s] %s (%s)' % (bubble, text, username)
        status = status.encode('utf8')
        return status

    def _create_header(self, status):
        oauth_parameters = tw.get_oauth_parameters(
                keys['twitter_consumer_key'],
                keys['access_token'])
        method = 'post'
        url_parameters = {'status': status}
        oauth_parameters['oauth_signature'] = tw.generate_signature(
                method,
                URL,
                url_parameters,
                oauth_parameters,
                keys['twitter_consumer_key'],
                keys['twitter_consumer_secret'],
                keys['access_token_secret']
            )

        headers = tw.create_auth_header(oauth_parameters)
        return headers

    def tweet(self, status, headers):
        contextFactory= WebClientContextFactory()
        url = URL + '?' + urllib.urlencode({'status': status})
        from twisted.internet import reactor
        agent = Agent(reactor, contextFactory)
        h = Headers({'Authorization':[headers]})
        d = agent.request('POST', url, h)
        return d

    def cbAnagramRequest(self, response):
        d = readBody(response)
        return d

    def parseTwitterResponse(self, body, yuka, source, user):
        try:
            res = json.loads(body)
        except(ValueError, TypeError):
            clog.error("Error decoding json", syst)
            return
        if res.get("errors"):
            clog.error("error from Twitter! %s" % body, syst)
            msg = "Something went wrong .. .."
        elif res.get("created_at") and res.get("id_str"):
            msg = "https://twitter.com/statuses/%s" % res.get("id_str")
        else:
            msg = "Something isn't right..."
        yuka.reply('[tweet] %s' % msg, source, user)

    def sendAnagram(self, res, yuka, args, source, user):
        if res:
            yuka.reply('[Anagram: %s] %s' % (args, res), source, user)

def setup():
    return TweetPoster()
