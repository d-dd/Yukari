import json
from tools import clog
from twisted.internet import reactor, defer
from twisted.web.client import Agent, readBody
from twisted.web.http_headers import Headers

def requestYtApi(ytId, content):
    """ Request video information from Youtube API """
    # ytId is unicode, so needs to be changed to str/bytes
    ytId = str(ytId)
    agent = Agent(reactor)
    url = 'http://gdata.youtube.com/feeds/api/videos/%s?v=2&alt=json' % ytId
    if content == 'info':
        url += ('&fields=title,author,media:group%28yt:duration%29,'
                'gd:rating,yt:statistics')
    elif content == 'check':
        url += '&fields=yt:accessControl'
    elif content == 'desc':
        url += '&fields=media:group(media:description)'

    clog.debug(url,'debug' )
    d = agent.request('GET', url, Headers({'Content-type':['application/json']}))
    d.addCallbacks(checkStatus, networkError, (ytId, content))
    return d

def checkStatus(response, ytId, content):
    clog.info('Response code: %s' % response.code)
    d = readBody(response)
    if response.code == 403:
        d.addCallback(badVideo, ytId)
        return d
    if response.code == 404:
        d.addCallback(noVideo, ytId)
        return d
    elif response.code == 503:
        d.addCallback(ytUnavailable, ytId)
        return d
    if content == 'info':
        d.addCallback(processYtInfo)
    elif content == 'check':
        d.addCallback(processYtCheck, ytId)
    elif content == 'desc':
        d.addCallback(processYtDesc, ytId)
    return d

def processYtInfo(body):
    res = json.loads(body)
    entry = res['entry']
    title = entry['title']['$t']
    author = entry['author'][0]['name']['$t']
    duration = entry['media$group']['yt$duration']['seconds']
    try:
        rating = entry['gd$rating']['average']
        ratingRound = round(rating, 2)
        if ratingRound == 5.0 and rating != 5.0:
            ratingRound = 4.99
    except(KeyError):
        rating = '-'
    seconds = int(duration)
    min, sec = divmod(seconds, 60)
    hour, min = divmod(min, 60)
    if hour:
        dur = '%sh %sm %ss' % (hour, min, sec)
    else:
        dur = '%sm %ss' % (min, sec)

    s = (title, dur, ratingRound, author)
    return '`[Youtube]`  Title: %s,  length: %s, rating: %s, uploader: %s' % s

def processYtCheck(body, ytId):
    try:
        res = json.loads(body)
    except(ValueError): # not valid json
        clog.error('(proccessYtCheck) Error processing JSON')
        return 'BadResponse'
    
    accesses = res['entry']['yt$accessControl']
    for access in accesses:
        if access['action'] == 'embed':
            embeddable = access['permission']
    clog.info('(processYtCheck) embed allowed: %s' % embeddable)
    if embeddable != 'allowed':
        return 'NoEmbed'
    return 'EmbedOk'

def processYtDesc(body, ytId):
    try:
        res = json.loads(body)
    except(ValueError): # not valid json
        clog.error('(proccessYtCheck) Error processing JSON')
        return
    desc = res['entry']['media$group']['media$description']['$t']
    return desc

def badVideo(res, ytId):
    clog.info('(badVideo) %s: %s' % (ytId, res))
    clog.info('This video needs to be deleted and flagged')
    return 'Status403'

def noVideo(res, ytId):
    # cQ39pN3u1yg
    clog.info('(noVideo) %s: %s' % (ytId, res))
    clog.info('This video needs to be deleted and flagged')
    return 'Status404'

def ytUnavailable(res, ytId):
    clog.err('(ytUnavailable) %s: %s' % (ytId, res))
    clog.info('This video needs to be flagged')
    return 'Status503'

def networkError(err):
    clog.error('Network Error %s' % err.value)
    return 'NetworkError'

def printres(res):
    clog.error(res)

#d = requestYtApi('Dxt3OonUmFY', 'check')
#d = requestYtApi('kMhBHBYHqus', 'check')
#d.addCallback(printres)
#from twisted.internet import reactor
#reactor.run()
