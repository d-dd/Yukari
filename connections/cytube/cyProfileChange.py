"""Log on to CyTube and change the profile text and image url"""
# Standard Library
import urllib
from cookielib import CookieJar
from StringIO import StringIO
# Twisted Library
from twisted.internet import reactor, defer
from twisted.web.client import Agent, FileBodyProducer, readBody, CookieAgent
from twisted.web.http_headers import Headers
from twisted.internet.ssl import ClientContextFactory
# Yukari
from conf import config
from tools import clog

syst = 'cyProfileChange'
NAME = config['Cytube']['username']
PASSWORD = config['Cytube']['password']
URL = str(config['Cytube']['loginurl'])

if URL.endswith('/'):
    URL = url[:-1]

class WebClientContextFactory(ClientContextFactory):
    def getContext(self, hostname, port):
        return ClientContextFactory.getContext(self)

def cbRequest(response):
    if response.code == 200:
        clog.debug('Received OK response: %s' % response.code, syst)
        d = readBody(response)
        d.addCallback(cbBody)
        return d
    else:
        clog.error('Received bad response: %s' % response.code, syst)
        return defer.fail(response)

def cbBody(body):
    if 'Welcome, %s' % str(NAME) in body: # The top banner ('Welcome, Yukari')
        clog.debug('Accessed page with authentication successfully', syst)
        return
    else:
        clog.warning('Failed to login or format changed.', syst)
        return defer.fail(None)

def setProfile(response, agent, profileText, profileImgUrl):
    d = agent.request(
            'POST',
            '%s/account/profile' % URL,
            Headers({'content-type': ['application/x-www-form-urlencoded']}),
            FileBodyProducer(StringIO(urllib.urlencode(dict(text=profileText,
                              image=profileImgUrl, action='account/profile')))))
    d.addCallbacks(cbRequest, lambda x:
                clog.error('Connection error: %s' % x, syst))

def changeProfile(username, password, profileText, profileImgUrl):
    profileText = profileText.encode('utf-8')
    cookieJar = CookieJar()
    contextFactory = WebClientContextFactory()
    agent = CookieAgent(Agent(reactor, contextFactory), cookieJar)
    d = agent.request(
            'POST',
            '%s/login' % URL,
            Headers({'content-type': ['application/x-www-form-urlencoded']}),
            FileBodyProducer(StringIO(urllib.urlencode(dict(name=NAME, 
                                               password=PASSWORD)))))

    d.addCallbacks(cbRequest, lambda x:
                clog.error('Connection error: %s' % x, syst))
    d.addCallback(setProfile, agent, profileText, profileImgUrl)
    return d
