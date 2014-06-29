"""Log on to CyTube and change the profile text and image url"""
import cProfile
from cookielib import CookieJar
from twisted.internet import reactor
import urllib
from twisted.web.client import Agent, FileBodyProducer, readBody, CookieAgent
from twisted.web.http_headers import Headers
from twisted.internet.ssl import ClientContextFactory
from StringIO import StringIO

NAME = 'Yukari'
PASSWORD = 'secret'
IMAGEURL = 'linktopicture.png'
TEXT = ':D'

class WebClientContextFactory(ClientContextFactory):
    def getContext(self, hostname, port):
        return ClientContextFactory.getContext(self)

def cbRequest(response):
    print "Received response"
    print response.code
    d = readBody(response)
    d.addCallback(cbBody)
    return d

def cbBody(body):
    print 'Response body:'
    print body

def displayCookies(response, cookieJar):
    print 'Received response'
    print response
    print 'Cookies:', len(cookieJar)
    for cookie in cookieJar:
        print cookie

def setProfile(response, agent):
    text = 'teto testing testo'
    img = 'http://i.imgur.com/3dnFPdW.png'
    d = agent.request(
            'POST',
            'https://ssl.cytu.be:8443/account/profile',
            Headers({'content-type': ['application/x-www-form-urlencoded']}),
            FileBodyProducer(StringIO(urllib.urlencode(dict(text=TEXT,
                                  image=IMAGEURL, action='account/profile')))))
    d.addCallback(cbRequest)

def main():
    cookieJar = CookieJar()
    contextFactory = WebClientContextFactory()
    agent = CookieAgent(Agent(reactor, contextFactory), cookieJar)
    d = agent.request(
                'POST',
                'https://ssl.cytu.be:8443/login',
                Headers({'content-type': ['application/x-www-form-urlencoded']}),
                FileBodyProducer(StringIO(urllib.urlencode(dict(name=NAME, 
                                               password=PASSWORD)))))

    d.addCallback(displayCookies, cookieJar)
    d.addCallback(setProfile, agent)
    reactor.run()
main()
