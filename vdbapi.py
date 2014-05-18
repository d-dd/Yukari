import json
from twisted.internet import reactor, defer
from twisted.web.client import Agent, readBody
from tools import clog
import database

syst = 'vdbapi'
def processVdbJson(body):
    clog.info('(processVdbJson) Received reply from VocaDB', syst)
    clog.debug('(processVdbJson) %s' % body, syst)
    body = body.decode('UTF-8')
    try:
        pbody = json.loads(body)
    except(ValueError):
        return defer.fail(None)
    if 'message' in pbody:
        clog.error(pbody['message'], syst)
    return defer.succeed(body)

def requestSongById(mType, mId, songId, userId, timeNow, method):
    """ Returns a deferred of Vocadb data of Song songId"""
    # check Song table to see if it's already saved
    ##if not, request data from VocaDB
    # UPDATE (or add) row in MediaSong table
    
    d = database.dbQuery(('data',), 'Song', songId=songId)
    d.addCallback(database.queryResult)
    d.addErrback(requestApiBySongId, songId, timeNow) # res is body
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
    d = agent.request('GET', url)
    d.addCallback(readBody)
    d.addCallbacks(processVdbJson, dbErr)
    d.addCallback(database.insertSong, songId, timeNow)
    return d

def apiError(err):
    clog.error('(apiError) There was a problem with VocaDB API. %s' %
               err.value, syst)
    return err

def dbErr(err):
    clog.error('(dbErr) %s' % err.value, syst)
    return err

def ignoreErr(err):
    'Consume error and return a success'
    return defer.succeed(None)
