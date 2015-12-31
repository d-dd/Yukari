import json
import re

from twisted.internet import reactor, defer
from twisted.web.client import Agent, readBody
from twisted.web.http_headers import Headers
from twisted.internet.ssl import ClientContextFactory

from tools import clog
from conf import config

class WebClientContextFactory(ClientContextFactory):
    def getContext(self, hostname, port):
        return ClientContextFactory.getContext(self)

KEY = config['api']['youtubev3'].encode('utf8')

syst = 'ApiClient'
def requestYtApi(ytId, content):
    """ Request video information from Youtube API.
    ytId : string of Youtube video ID
    content:
        check - embed and playback ability
        desc - video description 
    """
    # ytId is unicode, so needs to be changed to str/bytes
    ytId = str(ytId)
    agent = Agent(reactor, WebClientContextFactory())
    if content == 'check':
        part = 'status'
    elif content == 'desc':
        part = 'snippet'
    url = ('https://www.googleapis.com/youtube/v3/videos?'
           'part=%s&id=%s&key=%s'% (part, ytId, KEY))
    clog.info(url, syst)
    d = agent.request('GET', url, 
            Headers({'Content-type':['application/json']}))
    d.addCallbacks(checkStatus, networkError, (ytId,))
    return d

def checkStatus(response, ytId):
    d = readBody(response)
    if response.code == 403:
        return defer.succeed('Status403')
    elif response.code == 404:
        return defer.succeed('Status404')
    elif response.code == 503:
        return defer.succeed('Status503')
    else:
        d.addCallback(processJsonResponse, ytId)
        return d

def processJsonResponse(response, ytid):
    try:
        j = json.loads(response)
    except(ValueError):
        clog.error('ProcessJsonResponse: Error decoding JSON: %s' %
                response, syst)
    return j

def networkError(err):
    clog.error('Network Error %s' % err.value)
    return 'NetworkError'

def anagram(text):
    url = 'http://anagramgenius.com/server.php?source_text=%s' % text
    url = url.encode('utf-8')
    agent = Agent(reactor)
    d = agent.request('GET', url)
    d.addCallback(cbAnagramRequest)
    return d

def cbAnagramRequest(response):
    d = readBody(response)
    d.addCallback(parseAnagramBody)
    return d

def parseAnagramBody(body):
    m = re.match(r".*<span class=\"black-18\">'(.*)'</span>", body, re.DOTALL)
    if m:
        return m.groups()[0]

def getCySioClientConfig():
    """GET Socket.IO client configuration for the server we are trying
    to connect to.
    Make a GET request to /socketconfig/<channelname>.json

    https://github.com/calzoneman/sync/blob/3.0/docs/socketconfig.md
    """
    t = (config['Cytube']['domain'], config['Cytube']['channel'])
    url = 'http://{0}/socketconfig/{1}.json'.format(*t)
    url = url.encode('utf-8')
    agent = Agent(reactor)
    clog.warning(url, '~~~')
    d = agent.request('GET', url)
    d.addCallback(cbGetCySioClientConfig)
    return d

def cbGetCySioClientConfig(response):
    d = readBody(response)
    return d
    

#d = requestYtApi('Dxt3OonUmFY', 'check')
#d = requestYtApi('kMhBHBYHqus', 'check')
#d.addCallback(printres)
#from twisted.internet import reactor
#reactor.run()
