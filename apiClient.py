import json
from twisted.internet import reactor
from twisted.web.client import Agent, readBody

def processBody(body):
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

def requestApi(ytId):
    """ Request video information from Youtube API """
    # ytId is unicode, so needs to be changed to str/bytes
    agent = Agent(reactor)
    url = 'http://gdata.youtube.com/feeds/api/videos/%s' % str(ytId)
    url += ('?v=2&alt=json&fields=title,author,media:group%28yt:duration%29'
            ',gd:rating,yt:statistics')

    d = agent.request('GET', url)
    d.addCallback(readBody)
    d.addCallback(processBody)
    return d
