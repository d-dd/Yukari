class AnnounceQueue(object):
    def _q_announceQueue(self, cy, fdict):
        try:
            title = fdict['args'][0]['item']['media']['title']
            queueby = fdict['args'][0]['item']['queueby']
        except(KeyError):
            return
        cy.sendCyWhisper('%s added %s!' % (queueby, title))

def setup():
    return AnnounceQueue()
