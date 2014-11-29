from twisted.internet import defer
import database, vdbapi
import json
from conf import config
from tools import clog, commandThrottle, getTime

vdb = config['UserAgent']['vocadb']
syst = 'VocaDB'

class VocaDB(object):

    def __init__(self):
        self.jsName = 'vocadb'

    # this is the changeMedia Js trigger
    # it will emit the song information on changeMedia
    # _js_ must return a deferred; it will be put in a deferredList with
    # other deferreds. Js will update once by deferredList callback.
    def _cmjs_loadVocaDb(self, cy, mType, mId):
        return self._loadVocaDb(None, mType, mId)

    # this is the $vocadb chat command
    @commandThrottle(0)
    def _com_vocadb(self, cy, username, args, source):
        if not vdb:
            return
        mType = cy.nowPlayingMedia['type']
        mId = cy.nowPlayingMedia['id']
        if args is None:
            d = database.getSongId(mType, mId)
            d.addCallback(self.checkVocadbCommand, cy, mType, mId)
            d.addCallback(self.emitJs, cy)
        try:
            songId = int(args)
        except IndexError:
            clog.warning('(_com_vocadb) Index Error by %s' % username, syst)
            return
        except ValueError:
            clog.warning('(_com_vocadb) Value Error by %s' % username, syst)
            return
        userId = cy.userdict[username]['keyId']
        timeNow = getTime()
        d = vdbapi.requestSongById(mType, mId, songId, userId, timeNow, 4)
        # method 4 = manual set
        d.addCallback(self._loadVocaDb, mType, mId)
        d.addCallback(self.emitJs, cy)

    def emitJs(self, result, cy):
        """ update cy's js dict and updateJs() immediatley """
        cy.currentJs[self.jsName] = result[1] # just the string js
        cy.updateJs()

    def checkVocadbCommand(self, res, cy, mType, mId):
        # no match or connection error
        #clog.debug('checkVdbCommand: %s' % res[0][0], syst)
        if res[0][0] < 1:
            # TODO do a full request 
            return
        else:
            d = vdbapi.requestApiBySongId(None, res[0][0], getTime())
            d.addCallback(self._loadVocaDb, mType, mId)

    def _loadVocaDb(self, ignored, mType, mId):
        d = database.queryVocaDbInfo(mType, mId)
        d.addCallback(self.processVocadb, mType, mId)
        return d

    def processVocadb(self, res, mType, mId):
        if not res:
            clog.info('(processVocadb) Vocadb db query returned []')
            self.currentVocadb = 'vocapack =' + json.dumps({'res': False})
        else:
            setby = res[0][0]
            mediaId = res[0][1]
            vocadbId = res[0][2]
            method = res[0][3]
            vocadbData = res[0][4]
            if vocadbId == 0:
                self.currentVocadb = 'vocapack =' + json.dumps({'res': False})
            else:
                vocadbInfo = self.parseVocadb(vocadbData)
                vocapack = {'setby': setby, 'vocadbId': vocadbId, 'method': method,
                            'vocadbInfo': vocadbInfo, 'res': True}
                vocapackjs = json.dumps(vocapack)
                self.currentVocadb = 'vocapack =' + vocapackjs
        return defer.succeed((self.jsName, self.currentVocadb))

    def parseVocadb(self, vocadbData):
        artists = []
        data = json.loads(vocadbData)
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
