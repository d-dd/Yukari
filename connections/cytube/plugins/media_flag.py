import database
from tools import clog, commandThrottle
from twisted.internet import defer

syst = 'MediaFlag'
class MediaFlag(object):
    """ Plugin that deals with omit and blacklist flags and commands. """

    def __init__(self):
        # remember the last flag media
        self.recent = {'type': '', 'id': '', 'flag': 0}
        self.jsName = 'yukariOmit'

    def _cmjs_checkOmit(self, cy, fdict):
        """ Check for omit flag """
        media = fdict['args'][0]
        mType = media['type']
        mId = media['id']
        d = self._checkFlag(mType, mId)
        d.addCallback(self._makeJs)
        return d
   
    def _cm_checkBlacklist(self, cy, fdict):
        """ Check for blacklist flag on changeMedia """
        # We use cm here because blacklist media should be removed immediatley.
        media = fdict['args'][0]
        mType = media['type']
        mId = media['id']
        mTitle = media['title']
        d = self._checkFlag(mType, mId)
        d.addCallback(self._cbBlacklist, cy, 'cm', mType, mId, mTitle)
        return d
        
    @commandThrottle(0)
    def _com_blacklist(self, cy, username, args, source):
        if cy._getRank(username) < 3:
            return
        self._omit(cy, username, args, 'blflag', source)

    @commandThrottle(0)
    def _com_unblacklist(self, cy, username, args, source):
        if cy._getRank(username) < 3:
            return
        self._omit(cy, username, args, 'blunflag', source)

    @commandThrottle(0)
    def _com_omit(self, cy, username, args, source):
        self._omit(cy, username, args, 'omitflag', source)

    @commandThrottle(0)
    def _com_unomit(self, cy, username, args, source):
        self._omit(cy, username, args, 'omitunflag', source)

    def _q_checkBlacklist(self, cy, fdict):
        """ Check for blacklist flag on queue """
        mType = fdict['args'][0]['item']['media']['type']
        mId = fdict['args'][0]['item']['media']['id']
        mTitle = fdict['args'][0]['item']['media']['title']
        d = self._checkFlag(mType, mId)
        d.addCallback(self._cbBlacklist, cy,'queue', mType, mId, mTitle)
        return d

    def _checkFlag(self, mType, mId):
        d = database.getMediaFlag(mType, mId)
        d.addCallback(self._cbCheckFlag)
        d.addCallback(self._gotFlag, mType, mId)
        return d

    def _cbCheckFlag(self, res):
        try:
            flag = res[0][0]
        except(IndexError): # Media not in database yet
            clog.warning('(_cbCheckFlag) New media, no flag returned', syst)
            flag = 0 # can't have been flagged yet
        return defer.succeed(flag)

    def _gotFlag(self, flag, mType, mId):
        """ Set current, and pass on the flag result """
        self.recent['type'] = mType
        self.recent['id'] = mId
        self.recent['flag'] = flag
        return defer.succeed(flag)

    def _makeJs(self, flag):
        if flag & 2: # omitted
            strjs = 'yukariOmit=true'
        else:
            strjs = 'yukariOmit=false'
        return defer.succeed((self.jsName, strjs))

    def _cbBlacklist(self, flag, cy, caller, mType, mId, mTitle):
        if flag & 4:
            if caller == 'cm':
                cy.cancelChangeMediaJs = True
            # include type/id in message so admin can unblacklist easier
            cy.sendCyWhisper('Removing blacklisted media %s (%s:%s)'
                                      % (mTitle, mType, mId))
            uid = cy.getUidFromTypeId(mType, mId)
            cy.doDeleteMedia(uid)
        return defer.succeed(True)

    def _omit(self, cy, username, args, dir, source):
        if cy._getRank(username) < 2:
            return
        clog.info('(_com_omit) %s' % args)
        mType, mId = self._omit_args(cy, args)
        if not mType: 
            cy.doSendChat('Invalid parameters.')
        else:
            # check existence and retrieve title
            d = database.getMediaByTypeId(mType, mId)
            d.addCallback(self.cbOmit, cy, mType, mId, username, dir, source)

    def cbOmit(self, res, cy, mType, mId, username, dir, source):
        prefix = 'un' if dir.endswith('unflag') else ''
        verb = 'omit' if dir.startswith('omit') else 'blacklist'
        suffix = 'ted' if verb == 'omit' else 'ed'
        # & 2 = omit, & 4 for blacklist
        bit = 2 if verb == 'omit' else 4
        if not res:
            cy.doSendChat('Cannot %s%s media not in database.'
                            % (prefix, verb), source, username, toIrc=False)

        elif not prefix and res[0][6] & bit :# already flagged
            cy.doSendChat('%s is already %s%s.' % (res[0][4], verb, suffix),
                                    source, username, toIrc=False)

        elif prefix and not res[0][6] & bit: # not flagged
            cy.doSendChat('%s is not %s%s.' % (res[0][4], verb, suffix), source,
                                            username, toIrc=False)
        else:
            np = cy.nowPlayingMedia
            title = res[0][4]
            # flag/unflag
            if not prefix:
                database.flagMedia(bit, mType, mId)
            else:
                database.unflagMedia(bit, mType, mId)
            if verb == 'omit':
                boo = 'false' if prefix else 'true'
                strjs = 'yukariOmit=' + boo
                if (mType, mId) == (np['type'], np['id']):
                    cy.currentJs[self.jsName] = strjs
                    cy.updateJs()
            elif verb == 'blacklist':
                uid = cy.getUidFromTypeId(mType, mId)
                cy.doDeleteMedia(uid)
            cy.sendCyWhisper('%s%s %s.' %((prefix+verb).title(), suffix, title),
                            source=source, username=username, toIrc=False) 

    def _omit_args(self, cy, args):
        if not args:
            i = cy.getIndexFromUid(cy.nowPlayingUid)
            if i is None:
                return None, None
            media = cy.playlist[i]['media']
            return media['type'], media['id']
        elif args:
            if ',' in args:
                argl = args.split(',')
            elif ' ' in args:
                argl = args.split()
            else:
                argl = (args, 'yt')
            try:
                mType = argl[1]
                mId = argl[0]
            except(IndexError):
                return False
        return mType, mId
def setup():
    return MediaFlag()
