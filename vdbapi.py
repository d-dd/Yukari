import json, re, time, random
from twisted.internet import reactor, defer
from twisted.web.client import Agent, readBody
from twisted.web.http_headers import Headers
from conf import config
from tools import clog, getTime
import database
import connections.apiClient as apiClient
from functools import partial

syst = 'vdbapi'
UserAgentVdb = config['UserAgent']['vocadb'].encode('UTF-8')
nicoMatch = re.compile(r'sm[0-9]{6,9}|nm[0-9]{6,9}')

def processVdbJsonForSongId(body):
    clog.info('(processVdbJsonForSongId) Received reply from VocaDB', syst)
   # clog.debug('(processVdbJsonForSongId) %s' % body, syst)
    body = body.decode('UTF-8')
    try:
        pbody = json.loads(body)
    except(ValueError):
        return defer.fail(None)
    try:
        if 'message' in pbody:
            clog.error(pbody['message'], syst)
    except(TypeError): # body is null (pbody is None)
        clog.warning('(processVdbJsonForSongId) null from Vocadb', syst)
        return defer.succeed(0)
    
    songId = pbody.get('id')
    
    # Couldn't find songId, this might be a list of songs...so pick the first ;)
    if not songId:
        items = pbody.get('items')
        if items and items[0]:
            songId = items[0]['id']

    return defer.succeed((body, songId))

def processVdbJson(body):
    clog.info('(processVdbJson) Received reply from VocaDB', syst)
   # clog.debug('(processVdbJson) %s' % body, syst)
    body = body.decode('UTF-8')
    try:
        pbody = json.loads(body)
    except(ValueError):
        return defer.fail(None)
    try:
        if 'message' in pbody:
            clog.error(pbody['message'], syst)
    except(TypeError): # body is null (pbody is None)
        clog.warning('(processVdbJson) null from Vocadb', syst)
        return defer.succeed(0)

    return defer.succeed((pbody))

def requestSongById(mType, mId, songId, userId, timeNow, method):
    """ Returns a deferred of Vocadb data of Song songId"""
    # check Song table to see if it's already saved
    ##if not, request data from VocaDB
    # UPDATE (or add) row in MediaSong table

    d = database.dbQuery(('data',), 'Song', songId=songId)
    d.addCallback(database.queryResult)
    d.addErrback(requestApiBySongId, songId, timeNow) # res is (body, songId)
    d.addCallbacks(database.insertMediaSong, apiError,
                   (mType, mId, songId, userId, timeNow, method))
    d.addErrback(ignoreErr)
    return d

def requestApiBySongId(res, songId, timeNow):
    """ Request video information from VocaDb API v2
    and save to the Song table """
    agent = Agent(reactor)
    url = 'http://vocadb.net/api/songs/%s?' % songId
    url += '&fields=artists,names&lang=romaji'
    clog.warning('(requestApiBySongId) %s' % url, syst)
    d = agent.request('GET', url, Headers({'User-Agent':[UserAgentVdb]}))
    d.addCallback(readBody)
    d.addCallbacks(processVdbJsonForSongId, apiError)
    d.addCallback(database.insertSong, timeNow)
    return d

def requestPVByTagOffset(cbInfo, tag, offset):
    def localCb(res):
        try:
            pbody = json.loads(res[0])
        except(ValueError):
            return defer.fail(Exception('No video found'))
        
        if pbody.get('items') and pbody['items'][0] and pbody['items'][0]['pVs']:
            for pv in pbody['items'][0]['pVs']:
                # TODO: soundcloud, too
                if pv[u'service'] == "Youtube":
                    return [['yt', pv['pvId']]]

    agent = Agent(reactor)
    url = 'http://vocadb.net/api/songs?query=&onlyWithPvs=true&pvServices=Youtube&getTotalCount=false&start=%i&maxResults=1&fields=PVs&tagName=%s' % (offset, tag)
    url = url.encode('utf8')
    clog.warning('(requestSongByTagOffset) %s' % url, syst)
    d = agent.request('GET', url, Headers({'User-Agent':[UserAgentVdb]}))
    d.addCallback(readBody)
    d.addCallbacks(processVdbJsonForSongId, apiError)
    d.addCallback(localCb)
    return d

def requestSongByTagCountCallback(cbInfo, quantity, tag, body):
    print(body)
    total = body.get('totalCount')

    if total:
        quantity = min(total, quantity)
        indexes = random.sample(xrange(total), quantity)
        for i in indexes:
            d = requestPVByTagOffset(cbInfo, tag, i)
            d.addCallback(cbInfo[0], cbInfo[1], cbInfo[2])
    else:
        #uh, error.
        return defer.fail(Exception('Bad response'))

def requestSongsByTag(cbInfo, quantity, tag):
    agent = Agent(reactor)
    url = 'http://vocadb.net/api/songs?query=&onlyWithPvs=true&pvServices=Youtube&getTotalCount=true&maxResults=0&tagName=%s' % tag
    url = url.encode('utf8')
    clog.warning('(requestSongsByTag) %s' % url, syst)
    d = agent.request('GET', url, Headers({'User-Agent':[UserAgentVdb]}))
    d.addCallback(readBody)
    d.addCallbacks(processVdbJson, apiError)
    d.addCallbacks(partial(requestSongByTagCountCallback, cbInfo, quantity, tag))
    return d

def requestSongByPv(res, mType, mId, userId, timeNow, method):
    """ Returns a deferred of Vocadb data of Song songId"""
    # check mediaSong first
    # request data from VocaDB
    # UPDATE (or add) row in MediaSong table
    d = database.queryMediaSongRow(mType, mId)
    d.addCallback(mediaSongResult, mType, mId, userId, timeNow)
    d.addErrback(ignoreErr)
    return d

def mediaSongResult(res, mType, mId, userId, timeNow):
    clog.info('(mediaSongResult) %s' % res, syst)
    if res:
        return defer.succeed(res[0])
    else:
        dd = requestApiByPv(mType, mId, timeNow)
        dd.addErrback(apiError)
        dd.addCallback(youtubeDesc, mType, mId, timeNow)
        dd.addCallback(database.insertMediaSongPv, mType, mId, userId, timeNow)
        return dd

def requestApiByPv(mType, mId, timeNow):
    """ Request song information by Youtube or NicoNico Id,
    and save data to Song table """
    agent = Agent(reactor)
    if mType == 'yt':
        service = 'Youtube'
    else:
        service = 'NicoNicoDouga'
    url = 'http://vocadb.net/api/songs?pvId=%s&pvService=%s' % (mId, service)
    url += '&fields=artists,names&lang=romaji'
    clog.warning('(requestApiByPv) %s' % url, syst)
    dd = agent.request('GET', str(url), Headers({'User-Agent':[UserAgentVdb]}))
    dd.addCallback(readBody)
    dd.addCallbacks(processVdbJsonForSongId, apiError)
    dd.addCallback(database.insertSong, timeNow)
    return dd

def youtubeDesc(res, mType, mId, timeNow):
    """Return a deferred of a Youtube API query"""
    if res[0] == 0: # no match
        clog.debug(('(youtubeDesc) No Youtube id match. Will attemp to retrieve'
                   'and parse description %s') % res, syst)
        d = apiClient.requestYtApi(mId, 'desc')
        d.addCallback(searchYtDesc, mType, mId, timeNow)
        d.addErrback(errNoIdInDesc)
        return d
    else:
        # pass-through the with method 0, results
        return defer.succeed((0, res[0]))

def errNoIdInDesc(res):
    clog.warning('errNoIdInDesc %s' % res, syst)
    return defer.succeed((1, 0))

def nicoAcquire(res):
    clog.debug('nicoAcquire %s' % res, syst)
    if res[0] == 0: # no match
        clog.debug('(youtubeDesc) No Nico id match.', syst)
    return defer.succeed((1, res[0]))

def searchYtDesc(jsonResponse, mType, mId, timeNow):
    items = jsonResponse['items']
    if not items:
        clog.error('searchYtDesc: no video found', syst)
        return defer.fail(Exception('No video found'))
    desc = items[0]['snippet']['description']
    m = nicoMatch.search(desc)
    if m:
        nicoId = m.group(0)
        clog.debug(nicoId, 'searchYtDesc')
        d = requestApiByPv('NicoNico', nicoId, timeNow)
        d.addCallback(nicoAcquire)
        d.addCallback(database.insertMediaSongPv, mType, mId, 1, timeNow)
        return d
    else:
        database.insertMediaSongPv(0, mType, mId, 1, timeNow)
        return defer.fail(Exception('No NicoId in Description found'))

def apiError(err):
    clog.error('(apiError) There was a problem with VocaDB API. %s' %
               err.value, syst)
    err.printDetailedTraceback()
    return err

def dbErr(err):
    clog.error('(dbErr) %s' % err.value, syst)
    return err

def ignoreErr(err):
    'Consume error and return a success'
    clog.error('(ignoreErr) %s' % err.value, syst)
    return defer.succeed(None)
