import argparse
import re
import database
import tools
from tools import clog, commandThrottle

syst = 'Plugin-Add'
QFLAG = 0b1000 # 8

class Add(object):
    """A plugin object.
    Handles $add and $manage. These commands queue media searched
    from the database file to Cytube."""

    def __init__(self):
        self.managing = False
        self.automedia = {}

    @commandThrottle(3)
    def _com_add(self, cy, username, args, source):
        """Parse $add command arguments and pass to callback.
        Called by $add. Requirements:
            Source: Cytube chat
            Rank: non-guest
        """
        if source != 'chat':
            return
        rank = cy._getRank(username)
        if not rank:
            return
        elif rank < 2:
            maxAdd = 5
        else:
            maxAdd = 20
        if args is None:
            args = '-n 3'
        #clog.info(args, syst)
        title, arguments = self.parseTitle(args)
        args = arguments.split()

        # shortcut in case people want to $add #
        # of course this can't be combined with other args
        try:
            num = int(args[0])
            args = ['-n', str(num)]

        except(ValueError, IndexError):
            pass
        
        parser = argparse.ArgumentParser()
        parser.add_argument('-s', '--sample', default='queue', 
                            choices=('queue', 'q', 'add', 'a', 'like', 'l'))
        parser.add_argument('-u', '--user', default='Anyone')
        parser.add_argument('-g', '--guest', default=False, type=bool)
        parser.add_argument('-n', '--number', default=3, type=int)
        parser.add_argument('-a', '--artist', default='') #TODO
        parser.add_argument('-T', '--temporary', default=False, type=bool)
        parser.add_argument('-N', '--next', default=False, type=bool)
        parser.add_argument('-o', '--omit', default=False, type=bool)
        # Yukari removes last 100 rows of queue from the media sample
        # set recent to True to disable this behavior
        parser.add_argument('-r', '--recent', default=False, type=bool)

        try:
            args = parser.parse_args(args)
        except(SystemExit):
            cy.doSendChat('Invalid arguments.')
            return

        args.number = min(args.number, maxAdd)
        if rank < 2:
            args.omit = False

        info = ('Quantity:%s, sample:%s, user:%s, guest:%s, temp:%s, '
                'pos:%s, title:%s, include ommited:%s, recent:%s'
                % (args.number, args.sample, args.user, args.guest,
                   args.temporary, args.next, title, args.omit, args.recent))
        #self.doSendChat(reply)
        clog.debug('(_com_add) %s' % info, syst)
        isRegistered = not args.guest

        if args.next:
            args.next = 'next'
        else:
            args.next = 'end'
        args.user = args.user.lower()
        if args.user == 'anyone':
            args.user = None
        
        d = self.getRandMedia(args.sample, args.number, args.user, isRegistered,
                                      title, args.recent)
        d.addCallback(cy.doAddMedia, args.temporary, args.next)

    @commandThrottle(0)
    def _com_manage(self, cy, username, args, source):
        """Toggle management mode.
        Called by $manage. Requirements:
            Source: Cytube chat
            Rank: 2 or higher
        """
        if source != 'chat':
            return
        if cy._getRank(username) < 2:
            return
        if not self.managing:
            self.managementOn(cy)
        elif self.managing:
            self.managementOff(cy)

    def _del_updateAutomedia(self, cy, fdict):
        """Remove deleted media from self.automedia. Called by CyCall
        delete."""
        if self.automedia:
            uid = fdict['args'][0]['uid']
            i = cy.getIndexFromUid(uid)
            mType = cy.playlist[i]['media']['type']
            mId = cy.playlist[i]['media']['id']
            if (mType, mId) in self.automedia:
                del self.automedia[(mType, mId)]
                self._checkSupply(cy)

    def _pl_autoadd(self, cy, pl):
        """Empty self.automedia if playlist has been cleared. Called by
        CyCall playlist."""
        if self.automedia:
            if not pl: # playlist was cleared (and not merely re-sent by server)
                self.managementOff(cy, 'Playlist cleared.')
                self.automedia = {}

    def _temp_updateAutomedia(self, cy, fdict):
        """Delete temp-ed media from self.automedia. Called by 
        CyCall temporary."""
        if self.automedia:
            uid = fdict['args'][0]['uid']
            # temp = True means media was made temporary
            #        False menas it was made permanent
            temp = fdict['args'][0]['temp']
            i = cy.getIndexFromUid(uid)
            mType = cy.playlist[i]['media']['type']
            mId = cy.playlist[i]['media']['id']
            if temp is False and (mType, mId) in self.automedia:
                del self.automedia[(mType, mId)]
                self._checkSupply(cy)

    def _q_updateAutomedia(self, cy, fdict):
        """Update self.automedia if Cytube callback `queue` is auto
        media that Yukari has queued. Return QFLAG, which is
        the bit flag value for auto-media queue to be written to the
        Queue table."""
        if self.automedia:
            media = fdict['args'][0]['item']['media']
            mType = media['type']
            mId = media['id']
            if (mType, mId) in self.automedia:
                self.automedia[(mType, mId)] = True
                return QFLAG

    def _qfail_updateAutomedia(self, cy, fdict):
        """Update self.automedia if Cytube callback `queueFail` is auto
        media that Yukari has queued."""
        if self.automedia:
            args = fdict['args'][0]
            badlink = args.get('link', '')
            if 'http://youtu' in badlink:
                mType = 'yt'
                mId = cy.ytUrl.search(badlink).group(6)
                if (mType, mId) in self.automedia:
                    del self.automedia[(mType, mId)]
                    self._checkSupply(cy)

    def _ul_checkcount(self, cy, fdict):
        """Turn manage off if Cytube named usercount falls below 2."""
        if len(cy.userdict) < 2 and self.managing:
            self.managementOff(cy, 'No named users.')

    def managementOn(self, cy, msg=''):
        """Turn manage on with msg."""
        self.managing = True
        cy.doSendChat('%s Playlist management enabled.' % msg, toIrc=False)
        self._queueMore(cy, 6 - len(self.automedia))

    def managementOff(self, cy, msg=''):
        """Turn manage off with msg."""
        self.managing = False
        cy.doSendChat('%s Playlist management has been disabled.' % msg,
                       toIrc=False)
        
    def _queueMore(self, cy, count):
        """Create a database deferred that queries random media."""
        if not self.managing:
            return
        d = self.getRandMedia('q', count, None, None, None, None)
        d.addCallback(self._manageQueue, cy)

    def _checkSupply(self, cy):
        """Check automedia length and add more media if running low."""
        remaining = len(self.automedia)
        clog.warning(str(self.automedia), syst)
        if remaining < 4:
            self._queueMore(cy, 6 - remaining)

    def _manageQueue(self, results, cy):
        """Queue media to Cytube playlist. Called by deferred from
        _queueMore."""
        for mType, mId in results:
            self.automedia[(mType, mId)] = False
        cy.doAddMedia(results, temp=True, pos='end')

    def parseTitle(self, command):
        """Return parsed title and the rest of the arguments from $add."""
        # argparse doesn't support spaces in arguments, so we search
        # and parse the -t/ --title values in msg ourselves
        tBeg = command.find('-t ')
        if tBeg == -1:
            return None, command
        tBeg += 3
        tEnd = command.find(' -', tBeg)
        if tEnd == -1:
            tEnd = len(command)
        shortMsg = command[:tBeg-3] + command[tEnd+1:]
        title = tools.returnUnicode(command[tBeg:tEnd])
        return title, shortMsg

    def getRandMedia(self, sample, quantity, username, isRegistered, title,
                     includeRecent):
        """Return a database deferred. Searches quantity number of media
        constrained by other arguments."""
        samples = {'queue': 'q', 'q': 'q', 'add': 'a', 'a': 'a', 'like': 'l',
                   'l': 'l'}
        sample = samples[sample]
        return database.addMedia(sample, username, isRegistered, title,
                                 quantity, includeRecent)

def setup():
    return Add()
