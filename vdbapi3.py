import json
import re
import urllib

import treq

from twisted.internet import reactor, task, defer
from twisted.web.http_headers import Headers
from tools import clog, getTime
from conf import config
from connections import apiClient

import database
syst = 'vdbapi'
u_agent_str = config['UserAgent']['vocadb'].encode('utf-8')
HEADERS = Headers({'User-Agent': [u_agent_str]})

def getRes(res):
    try:
        return res[0][0]
    except(TypeError, IndexError):
        return

def setVocadbBySongId(mType, mId, songId, nameLower, isReg, refresh=False):
    """
    Used for $vocadb {vocadb_songID} command
    Search song in database,
    if not in database, request data from vocadb, and save it to local db.
    
    If refresh=True, skip database lookup and get info from vocadb.
    This is used when the db cache is out of date.

    Returns deferred of vocadb data, or None
    """
    if not refresh:
        d = database.getVocadbBySongId(songId)
        d.addCallback(getRes)
        d.addCallback(conditionSetVocadbSongId, songId)
    elif refresh:
        d = conditionSetVocadbSongId(None, songId)

    # 4 is manual entry
    d.addCallback(saveSongResults, mType, mId, nameLower, isReg, 4)
    return d

def conditionSetVocadbSongId(result, songId):
    if result is not None:
        return result
    elif result is None:
        return getVdbBySongId(songId)

def lookupSongInDb(mType, mId):
    """
    Return deferred of results of DB lookup (dict),
    Return None if there is no record on the local db.
    """

    d = database.getVocadbData(mType, mId)
    d.addCallback(getRes)
    return d

def obtainSong(mType, mId, nameLower, isReg):
    """
    Return deferred of result of vocadb (including 
    yt desc lookup)
    Deferred results in None when no match is found.

    Results are saved to the database.
    """
    d = getVdbByPvId(mType, mId)
    d.addCallback(conditionVocadbYtPvResult, mType, mId, nameLower, isReg)
    d.addErrback(err)
    return d

def conditionVocadbYtPvResult(result, mType, mId, nameLower, isReg):
    """If result is None, 
    search YT description for a nico ID"""
    if not result and mType == 'yt':
        d = apiClient.requestYtApi(mId, 'desc')
        d.addCallback(_cbYtDesc, mType, mId, nameLower, isReg)
        return d
    else:
        saveSongResults(result, mType, mId, nameLower, isReg, 0)
        return result

def _cbYtDesc(result, mType, mId, nameLower, isReg):
    items = result['items']
    if not items:
        clog.error('no youtube description', syst)
        saveSongResults(None, mType, mId, nameLower, isReg, 1)
        return
    desc = items[0]['snippet']['description']
    rx = r'sm[0-9]{6,9}|nm[0-9]{6,9}'
    m = re.search(rx, desc)
    clog.info('looking for smid in yt desc', syst)
    if m:
        nicoId = m.group(0)
        clog.info('found nicoid: %s' % nicoId, syst)
        d = getVdbByPvId('nico', nicoId)
        d.addCallback(saveSongResults, mType, mId, nameLower, isReg, 1)
        return d

def saveSongResults(results, mType, mId, nameLower, isReg, method):
    """
    Save song to DB, update mediasong and pass through results.
    """
    if not results:
        print "save with 0"
        songId = 0
        d = database.upsertMediaSong(songId, mType, mId, nameLower, isReg,
                                     getTime(), 1)
        d.addErrback(err)
    elif results.get('message') or not results.get('id'):
        print "bad request"
        songId = -1
        d = database.upsertMediaSong(songId, mType, mId, nameLower, isReg,
                                     getTime(), 1)
        d.addErrback(err)
    else:
        # save song data to song table, then update/insert MediaSong
        songId = results.get('id')
        data = json.dumps(results)
        d = database.upsertSong(songId, data, getTime())
        d.addErrback(err)
        d.addCallback(database.upsertMediaSong, mType, mId, nameLower, isReg,
                getTime(), method)
        d.addErrback(err)
    return defer.succeed(results)

def getVdbByPvId(mType, mId):
    """Return a deferred of the json response of vocadb song result"""

    if mType == 'yt':
        service = 'Youtube'
    else:
        service = 'NicoNicoDouga'

    args = {'pvId': mId,
            'pvService': service,
            'fields': 'Artists,Names',
            'lang': 'romaji',
            }
    url = 'https://vocadb.net/api/songs/?{}'.format(urllib.urlencode(args))
    clog.info('requesting vocadb API by pv search: {}'.format(url), syst)
    d = treq.get(url, headers=HEADERS)
    d.addCallback(cbResponse)
    return d

def getVdbBySongId(songId):
    """Return a deferred of the json response of vocadb song result"""
    args = {
            'fields': 'Artists,Names',
            'lang': 'romaji',
            }
    url = 'https://vocadb.net/api/songs/{}?{}'.format(songId, 
                                                urllib.urlencode(args))
    clog.info('requesting vocadb API by song id : {}'.format(url), syst)
    d = treq.get(url, headers=HEADERS)
    d.addCallback(cbResponse)
    return d

def cbResponse(response):
    if response.code == 200:
        return treq.json_content(response)
    else:
        clog.error(response.code, syst)
        return treq.json_content(response)

def err(err):
    print dir(err)
    err.printDetailedTraceback()
    print err.getTraceback()

if __name__ == '__main__':
    from twisted.internet import reactor

    #d= lookupSongInDb('yt', 'TAYZgVEk_hA')
    #d.addCallback(pprint)
    a = obtainSong('yt', 'TAYZgVEk_hA', 'yukari', True)
    a.addErrback(err)
    a.addCallback(pprint)
    a.addErrback(err)
    a.addCallback(lambda x: reactor.stop)
    a.addErrback(err)
    reactor.run()
