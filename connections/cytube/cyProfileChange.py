"""Log into Cytube and change the profile image and text.
Cytube uses crfs tokens to prevent session hijack.

To log in:
    GET https://cytu.be/login
    Save the cookie and csrf token
    POST https://cytu.be/login with name, password, _csrf

To change the profile info:
    GET https://cytu.be/accounts/profile
    Save the cookie and csrf token
    POST https://cytu.be/accounts/profile with text, image, _csrf
"""

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
DOMAIN = config['Cytube']['domain']
NAME = config['Cytube']['username']
PASSWORD = config['Cytube']['password']

class WebClientContextFactory(ClientContextFactory):
    def getContext(self, hostname, port):
        return ClientContextFactory.getContext(self)

def errorHandler(failure):
    clog.error(failure, syst)
    return failure

def cbGetPage(response, callback):
    if response.code == 200:
        clog.debug('Received OK response: %s' % response.code, syst)
        d = readBody(response)
        d.addCallback(callback)
        return d
    else:
        clog.error('Received bad response: %s' % response.code, syst)
        return defer.fail(response)

def cbFindCsrf(body):
    csrf = body[body.find('_csrf', 1500)+14:body.find('_csrf', 1500)+50]
    clog.debug('csrf is %s' % csrf, syst)
    return csrf

def getPage(ignored, server, endpoint, agent):
    d = agent.request(
            'GET',
            'https://{0}/{1}'.format(server, endpoint))
    return d

def postLoginPage(csrf, server, agent):
    d = agent.request(
            'POST',
            'https://{0}/login'.format(server),
            Headers({'content-type': ['application/x-www-form-urlencoded']}),
            FileBodyProducer(StringIO(urllib.urlencode(dict(
                _csrf=csrf,
                name=NAME,
                password=PASSWORD)))))

    return d

def postProfileInfo(csrf, server, agent, profileText, profileImgUrl):
    d = agent.request(
            'POST',
            'https://{0}/account/profile'.format(server),
            Headers({'content-type': ['application/x-www-form-urlencoded']}),
            FileBodyProducer(StringIO(urllib.urlencode(dict(
                _csrf=csrf,
                text=profileText,
                image=profileImgUrl)))))
    return d

def changeProfileInfo(profileText, profileImgUrl):
    cookieJar = CookieJar()
    contextFactory = WebClientContextFactory()
    agent = CookieAgent(Agent(reactor, contextFactory), cookieJar)
    d = getPage(None, DOMAIN, 'login', agent)
    d.addCallback(cbGetPage, cbFindCsrf)
    d.addErrback(errorHandler)
    d.addCallback(postLoginPage, DOMAIN, agent)
    d.addErrback(errorHandler)
    d.addCallback(getPage, DOMAIN, 'account/profile', agent)
    d.addErrback(errorHandler)
    d.addCallback(cbGetPage, cbFindCsrf)
    d.addErrback(errorHandler)
    d.addCallback(postProfileInfo, DOMAIN, agent, profileText.encode('utf8'), profileImgUrl)
    d.addErrback(errorHandler)
    d.addCallback(cbGetPage, cbFindCsrf)
    return d
