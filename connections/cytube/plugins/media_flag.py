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

    def _cmjs_checkOmit(self, cy, mType, mId):
        """ Check for omit flag """
        d = self._checkFlag(mType, mId)
        d.addCallback(self._makeJs)
        return d
   
    def _cm_checkBlacklist(self, cy, mType, mId, mTitle):
        """ Check for blacklist flag on changeMedia """
        # We use cm here because blacklist media should be removed immediatley.
        d = self._checkFlag(mType, mId)
        d.addCallback(self._cbcmBlacklist, cy, mType, mId, mTitle)
        return d
        
    @commandThrottle(0)
    def _com_blacklist(self, cy, username, args, source):
        rank = cy._getRank(username)
        if rank < 3:
            return
        parsed = self._omit_args(cy, args)
        if not parsed:
            cy.doSendChat('Invalid parameters.')
        elif parsed:
            mType, mId = parsed
            database.flagMedia(4, mType, mId)
            cy.doDeleteMedia(mType, mId)
            cy.sendCyWhisper('Added to blacklist (%s %s).' % (mType, mId) )

    @commandThrottle(0)
    def _com_omit(self, cy, username, args, source):
        self._omit(cy, username, args, 'flag', source)

    @commandThrottle(0)
    def _com_unomit(self, cy, username, args, source):
        self._omit(cy, username, args, 'unflag', source)

    def _q_checkBlacklist(self, cy, fdict):
        """ Check for blacklist flag on queue """
        mType = fdict['args'][0]['item']['media']['type']
        mId = fdict['args'][0]['item']['media']['id']
        mTitle = fdict['args'][0]['item']['media']['title']
        d = self._checkFlag(mType, mId)
        d.addCallback(self._cbqBlacklist, cy, mType, mId, mTitle)
        return d

    def _checkFlag(self, mType, mId):
        if (mType == self.recent['type'] and mId == self.recent['id']):
            return defer.succeed(self.recent['flag'])
        else:
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

    def _cbcmBlacklist(self, flag, cy, mType, mId, mTitle):
        # this will rarley run; blacklist media are deleted upon queue
        if flag & 4:
            cy.cancelChangeMediaJs = True
            cy.sendCyWhisper('Removing %s (blacklisted)' % mTitle)
            cy.doDeleteMedia(mType, mId)
            return defer.succeed(False)
        else:
            return defer.succeed(True)

    def _cbqBlacklist(self, flag, cy, mType, mId, mTitle):
        if flag & 4:
            cy.sendCyWhisper('Removing %s (blacklisted)' % mTitle)
            cy.doDeleteMedia(mType, mId)

    def _omit(self, cy, username, args, dir, source):
        rank = cy._getRank(username)
        clog.info('(_com_omit) %s' % args)
        if rank < 2 or not cy.nowPlayingMedia:
            return
        parsed = self._omit_args(cy, args)
        if not parsed:
            cy.doSendChat('Invalid parameters.')
        elif parsed:
            mType, mId = parsed
            # check existence and retrieve title
            d = database.getMediaByTypeId(mType, mId)
            d.addCallback(self.cbOmit, cy, mType, mId, username, dir, source)

    def cbOmit(self, res, cy, mType, mId, username, dir, source):
        if not res:
            st = '' if dir == 'flag' else 'un'
            cy.doSendChat('Cannot %somit media not in database'
                            % st, source, username, toIrc=False)

        elif dir == 'flag' and res[0][6] & 2: # already omitted
            cy.doSendChat('%s is already omitted' % res[0][4], 
                            source, username, toIrc=False)

        elif dir == 'unflag' and not res[0][6] & 2: # not omitted
            cy.doSendChat('%s is not omitted' % res[0][4], source,
                            username, toIrc=False)
        else:
            np = cy.nowPlayingMedia
            title = res[0][4]
            if dir == 'flag':
                strjs = 'yukariOmit=true'
                database.flagMedia(2, mType, mId)
                if (mType, mId) == (np['type'], np['id']):
                    cy.currentJs[self.jsName] = strjs
                    cy.updateJs()
                cy.sendCyWhisper('Omitted %s' % title, source=source,
                                 username=username, toIrc=False) 

            elif dir == 'unflag':
                strjs = 'yukariOmit=false'
                database.unflagMedia(2, mType, mId)
                if (mType, mId) == (np['type'], np['id']):
                    cy.currentJs[self.jsName] = strjs
                    cy.updateJs()
                cy.sendCyWhisper('Unomitted %s' % title, source=source,
                                 username=username, toIrc=False) 

    def _omit_args(self, cy, args):
        if not args:
            if cy.nowPlayingMedia:
                return cy.nowPlayingMedia['type'], cy.nowPlayingMedia['id']
            else:
                return False
        elif args:
            if ',' in args:
                argl = args.split(',')
            elif ' ' in args:
                argl = args.split()
            else:
                return 'yt', args
            try:
                return argl[1], argl[0]
            except(IndexError):
                return False
def setup():
    return MediaFlag()
