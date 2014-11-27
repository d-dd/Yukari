from tools import clog
syst = 'AnnounceQueue'
class AnnounceQueue(object):
    def _q_announceQueue(self, cy, fdict):
        try:
            title = fdict['args'][0]['item']['media']['title']
            queueby = fdict['args'][0]['item']['queueby']
            after = fdict['args'][0]['after']
        except(KeyError):
            clog.error('KeyError unpacking frame.', syst)
            return
        #clog.warning('AfterUID: %s; EndUID: %s' %
        #             (after, cy.playlist[-2]['uid']), syst)
        # if the 2nd to last (becuase last is the one we just added) media's
        # UID is same as after, then it means it as placed at the end
        if cy.playlist[-2]['uid'] == after:
            next = ''
        else:
            next = 'next'
        cy.sendCyWhisper('%s added %s %s!' % (queueby, next, title))

def setup():
    return AnnounceQueue()
