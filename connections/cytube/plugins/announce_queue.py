import time
from tools import clog, commandThrottle
from twisted.internet import reactor
from twisted.internet.error import AlreadyCalled, AlreadyCancelled

syst = 'AnnounceQueue'
class AnnounceQueue(object):
    """Plugin object.
    Announces in Cytube chat when a user queues media to the
    playlist. Toggle with $announcequeue.

    To prevent too many lines, waits queueThreshold seconds to collect
    multiple queues into a single message.
    """

    def __init__(self):
        self.announce = True

        # last time cycall transmitted "queue"
        self.lastCycallQueue = time.time()
        self.queueThreshold = 1.0
        self.queueCounter = 0

        
    @commandThrottle(0)
    def _com_announcequeue(self, cy, username, args, source):
        """Toggle queue annoucement
        Source: Cytube chat or Cytube PM
        Rank: Moderator"""
        rank = cy._getRank(username)
        if rank < 2:
            return
        self.announce = not self.announce
        cy.doSendChat('Announce queue: %s' % self.announce, toIrc=False)

    def _q_announceQueue(self, cy, fdict):
        if not self.announce:
            return
        try:
            title = fdict['args'][0]['item']['media']['title']
            queueby = fdict['args'][0]['item']['queueby']
            after = fdict['args'][0]['after']
        except(KeyError):
            clog.error('KeyError unpacking frame.', syst)
            return

        # if the 2nd to last (becuase last is the one we just added) media's
        # UID is same as after, then it means it as placed at the end
        try:
            last = cy.playlist[-2]['uid']
        except(IndexError):
            # when the playlist is empty (before this queue)
            last = 0

        if last == after:
            next = ':'
        else:
            next = 'next:'

        if time.time() - self.lastCycallQueue < self.queueThreshold:
            self.queueCounter += 1
            try:
                self.later.reset(self.queueThreshold)
            except(AlreadyCalled, AlreadyCancelled,
                        NameError, TypeError, AttributeError):
                self.queueCounter = 1
                self.later = reactor.callLater(self.queueThreshold,
                                               self.sendAnnounce,
                                               cy, title, queueby, next)
        else:
            self.queueCounter = 0
            self.sendAnnounce(cy, title, queueby, next)
        self.lastCycallQueue = time.time()

    def sendAnnounce(self, cy, title, queueby, next):

        if self.queueCounter == 1:
            andmore = " and %s more video" % self.queueCounter
            
        elif self.queueCounter >1:
            andmore = " and %s more videos" % self.queueCounter
        else:
            andmore = ""

        cy.sendCyWhisper('%s added %s %s%s!' % (queueby, next, title, andmore))

def setup():
    return AnnounceQueue()
