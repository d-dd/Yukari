from tools import commandThrottle
import re
from twisted.web.client import Agent, readBody

class Anagram(object):
    """ Anagram solver using anagram api """
    ### Need to move api to here
    @commandThrottle(5)
    def _com_anagram(self, yuka, user, args, source):
        if not args:
            return
        text = re.sub(r"[^a-zA-Z]", "", args)
        if len(text) < 7:
            yuka.sendChats('Anagram too short.')
            return
        elif len(text) >= 30:
            yuka.sendChats('Anagram too long.')
            return
        d = self.anagram(text)
        d.addCallback(self.sendAnagram, yuka, args)

    def anagram(self, text):
        url = 'http://anagramgenius.com/server.php?source_text=%s' % text
        url = url.encode('utf-8')
        from twisted.internet import reactor
        agent = Agent(reactor)
        d = agent.request('GET', url)
        d.addCallback(self.cbAnagramRequest)
        return d

    def cbAnagramRequest(self, response):
        d = readBody(response)
        d.addCallback(self.parseAnagramBody)
        return d

    def parseAnagramBody(self, body):
        m = re.match(r".*<span class=\"black-18\">'(.*)'</span>", body, re.DOTALL)
        if m:
            return m.groups()[0]

    def sendAnagram(self, res, yuka, args):
        if res:
            yuka.sendChats('[Anagram: %s] %s' % (args, res))

def setup():
    return Anagram()
