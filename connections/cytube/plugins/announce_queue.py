from tools import clog, commandThrottle
syst = 'AnnounceQueue'
class AnnounceQueue(object):
    """Plugin object.
    Announces in Cytube chat when a user queues media to the
    playlist. Toggle with $announcequeue.
    """

    def __init__(self):
        self.announce = True
        
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
            cy.sendCyWhisper('%s added: %s!!!' % (queueby, title))
            return

        if last == after:
            next = ':'
        else:
            next = 'next:'
        cy.sendCyWhisper('%s added %s %s!' % (queueby, next, title))

def setup():
    return AnnounceQueue()
