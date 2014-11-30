import random, time
from twisted.internet import defer
from tools import clog, commandThrottle
syst = 'Replay'

class Replay(object):

    def __init__(self):
        self.replay = -1
        # we skip the cmjs for the new media, and the media being replayed
        self.skipJs = False
        self.poll = False

    def _cm_replay(self, cy, fdict):
        if self.poll:
            cy.doClosePoll()

        if self.skipJs:
            cy.cancelSetCurrentJs = True
            self.skipJs = False
            return defer.succeed(0)
        if self.replay != -1:
            if cy.mediaRemainingTime > 6.0:
                cy.sendCyWhisper('Cancelling replay - user activity detected.')
            else:
                cy.cancelSetCurrentJs = True 
                index = cy.getIndexFromUid(self.replay)
                replayTitle = cy.playlist[index]['media']['title']
                cy.sendCyWhisper('Replaying %s!' % replayTitle)
                cy.jumpToMedia(self.replay)
                self.skipJs = True # we don't need to update because replay
            self.replay = -1
        return defer.succeed(0)

    @commandThrottle(0)
    def _com_replay(self, cy, username, args, source):
        self.doReplay(cy, username, args, source)

    @commandThrottle(0)
    def _com_repeat(self, cy, username, args, source):
        self.doReplay(cy, username, args, source)

    @commandThrottle(0)
    def _vote_replay(self, cy, username, args, source):
        self.voteReplay(cy, username, args, source)

    @commandThrottle(0)
    def _vote_repeat(self, cy, username, args, source):
        self.voteReplay(cy, username, args, source)

    def doReplay(self, cy, username, args, source):
        if source != 'chat':
            return
        rank = cy._getRank(username)
        if rank < 2:
            return
        if self.replay != -1:
            self.replay = -1
            cy.sendCyWhisper('Cancelled replay.')
        else:
            index = cy.getIndexFromUid(cy.nowPlayingUid)
            mTitle = cy.playlist[index]['media']['title']
            self.replay = cy.nowPlayingUid
            cy.sendCyWhisper('%s has been set to replay once.' % mTitle)

    def voteReplay(self, cy, username, args, source):
        if source != 'chat':
            return
        rank = cy._getRank(username)
        if rank < 2:
            return
        if cy.activePoll:
            cy.doSendChat('There is an active poll. Please end it first.',
                            toIrc=False)
            return
        if self.replay != -1:
            cy.doSendChat('This is already set to replay.', toIrc=False)
            return
        elif cy.mediaRemainingTime > 30:
            self.makePoll(cy)
        elif cy.mediaRemainingTime <= 30:
            cy.doSendChat('There is no time left for a poll.', toIrc=False)

    def makePoll(self, cy):
        """ Make a poll asking users if they would like the current video
        to be replayed """
        self.poll = True
        boo = random.randint(0, 1)
        pollTime = min(int(cy.mediaRemainingTime - 12), 100)
        choices = ('Yes!', 'No!') if boo else ('No!', 'Yes!')
        target = '3:1' if boo else '1:3'
        title = ('Replay %s? (%s to replay, vote time: %s seconds)' % 
                 (cy.nowPlayingMedia['title'], target, pollTime))
        opts = {'boo': boo, 'uid': cy.nowPlayingUid}
        cy.doMakePoll(self, self.gotPollResults, opts, 'Replay poll', title,
                                                     choices, pollTime)

    # called by cy
    def gotPollResults(self, cy, opts, pollState):
        # cancelled
        if pollState is False: 
            self.poll = False
            return
        order = opts['boo']
        counts = pollState.get('counts', None)
        if not counts:
            return
        if order == 0:
            yes = counts[1]
            no = counts[0]
        elif order == 1:
            yes = counts[0]
            no = counts[1]
        if not no and not yes:
            # no votes at all, can happen when user rejoins, losing their vote
            return
        elif not no and yes:
            self.replay = opts['uid']
            title = cy.playlist[cy.getIndexFromUid(opts['uid'])]['media']['title']
            cy.sendCyWhisper('%s has been set to replay!' % title)

def setup():
    return Replay()
