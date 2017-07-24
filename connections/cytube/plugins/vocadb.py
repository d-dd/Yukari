from collections import deque
from twisted.internet import defer
from twisted.internet.task import LoopingCall
import database, vdbapi3
import json
from conf import config
from tools import clog, commandThrottle, getTime

vdb = config['UserAgent']['vocadb']
syst = 'VocaDB'

class VocaDB(object):

    def __init__(self):
        self.jsName = 'vocadb'
        self.mediaToCheck = deque()

    # this is the changeMedia Js trigger
    # it will emit the song information on changeMedia
    # _js_ must return a deferred; it will be put in a deferredList with
    # other deferreds. Js will update once by deferredList callback.
    def _scjs_loadVocaDb(self, cy, fdict):#mType, mId):
        media = fdict['args'][0]
        mType = media['type']
        mId = media['id']
        yukname = cy.name
        return self._loadVocaDb(None, mType, mId, yukname.lower())

    # this is the $vocadb chat command
    @commandThrottle(0)
    def _com_vocadb(self, cy, username, args, source):
        """
        Vocadb command
        $vocadb (no commands) - rerun full search
        $vocadb 0 - set as 'no match found'
        $vocadb {vocadb song id} - manually set vocadb to specific song
        """
        if not vdb or not cy.nowPlayingMedia:
            clog.warning('no nowPlayingMedia', syst)
            return
        mType = cy.nowPlayingMedia['type']
        mId = cy.nowPlayingMedia['id']
        if not args:
            d = self.processVocadb(None, mType, mId, cy.name.lower(), 
                                                                True, True)
            d.addCallback(self.emitJs, cy)
            return
        try:
            songId = int(args)
        except IndexError:
            clog.warning('(_com_vocadb) Index Error by %s' % username, syst)
            return
        except ValueError:
            clog.warning('(_com_vocadb) Value Error by %s' % username, syst)
            return
        userId = cy.userdict[username]['keyId']
        isReg = cy.checkRegistered(username)
        nameLower = username.lower()
        timeNow = getTime()
        d = vdbapi3.setVocadbBySongId(mType, mId, songId, nameLower, isReg)
        # method 4 = manual set
        #d.addCallback(self._loadVocaDb, mType, mId, username)
        d.addCallback(self.emitJs, cy)

    def emitJs(self, result, cy):
        """ update cy's js dict and updateJs() immediatley 
            result is json of vocadb data"""
        if not result:
            return
        vocadbInfo = self.parseVocadb(result)
        vocadbId = result.get('id')
        vocapack = {
                'vocadbId': vocadbId,
                'vocadbInfo': vocadbInfo,
                'res': True,
                }
        # just the string js
        cy.currentJs[self.jsName] = 'vocapack=' + json.dumps(vocapack)
        cy.updateJs()

    def _loadVocaDb(self, ignored, mType, mId, nameLower, isReg=True, isCommand=False):
        d = vdbapi3.lookupSongInDb(mType, mId)
        d.addCallback(self.processVocadb, mType, mId, nameLower, isReg, isCommand)
        return d

    def processVocadb(self, res, mType, mId, nameLower, isReg, isCommand):
        if not res:
            d = vdbapi3.obtainSong(mType, mId, nameLower, isReg)
            if isCommand:
                clog.info('(processVocadb) we got $vocadb command', syst)
            else:
                clog.info('(processVocadb) Vocadb db query returned [] ', syst)
                d.addCallback(self.displayResults, mType, mId, nameLower, isReg)
            return d
        else:
            return self.displayResults(res, mType, mId, nameLower, isReg)

    def packageVocadb(self, vdbjson):
        if not vdbjson:
            vdbjson = {}
        vocadbId = vdbjson.get('id')
        if not vocadbId:
            vocapack = {'res': False}
            clog.info('Pacakge Vocadb - None', syst)
        else:
            vocadbInfo = self.parseVocadb(vdbjson)
            vocapack = {
                    'vocadbId': vocadbId,
                    'vocadbInfo': vocadbInfo,
                    'res': True,
                    }
        return vocapack

    def displayResults(self, res, mType, mId, nameLower, isReg):
        vocapack = self.packageVocadb(res)
        vocapackjs = json.dumps(vocapack)
        currentVocadb = 'vocapack =' + vocapackjs
        return defer.succeed((self.jsName, currentVocadb))

    def parseVocadb(self, vocadbData):
        artists = []
        data = vocadbData
        for artist in data['artists']:
            artistd = {}
            artistd['name'] = artist['name']
            try:
                artistd['id'] = artist['artist']['id']
            except(KeyError): # Some Artists do not have entries and thus no id
                artistd['id'] = None
            artistd['isSup'] = artist['isSupport']
            artistd['role'] = artist['effectiveRoles']
            if artistd['role'] == 'Default':
                artistd['role'] = artist['categories']
            artists.append(artistd)
        titles = []
        for title in data['names']:
            if title['language'] in ('Japanese', 'Romaji', 'English'):
                titles.append(title['value'])

        songType = data['songType']
        return {'titles': titles, 'artists': artists, 'songType': songType}

def setup():
    return VocaDB()
