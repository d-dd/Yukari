import database
from twisted.internet import defer
import tools
from tools import clog, commandThrottle

import time

syst = 'Hug'


class Hug(object):

    @commandThrottle(0)
    def _com_hug(self, cy, username, args, source):
        # yukari will not hug guests or IRC
        # no args allowed
        if args or source == 'irc' or not cy.checkRegistered(username):
            self._sendhug(cy, username)
            return
        
        # isRegistered=True
        d = database.getUserFlag(username.lower(), True)
        d.addCallback(self.hug, cy, username, True, source)

    def hug(self, res, cy, username, isReg, source):
        flag = res[0][0]
        if flag & 1: # user has greeted Yukari before
            reply = 'hug hug'
            #self._sendhug(cy, username, reply)
            d = self.calculateTiers(username)
            d.addCallback(self.returnHug, cy, username)
        else:
            self._sendhug(cy, username)

    def returnHug(self, res, cy, username):
        self._sendhug(cy, username, res)


    def _sendhug(self, cy, username, reply=''):
        """ Send the hug message back to chat """
        source = 'chat'
        if not reply:
            reply = '{}...'.format(username)
        cy.doSendChat(reply, source)

    def calculateTiers(self, username, isReg=True):
        d1 = database.calcUserPoints(None, username.lower(), isReg)
        d2 = database.calcAccessTime(None, username.lower(), isReg)
        dl = defer.DeferredList([d1, d2])
        dl.addCallback(self.getHugPicture)
        return dl

    def getHugPicture(self, res):
        clog.debug('(getHugPicture) %s' % res, syst)
        addTier = int(min(res[0][1][0][0]/5000, 5))
        try:
            timeTier = int(min(res[1][1][0][0]/5000, 5))
        except(TypeError):
            timeTier = 0
        hugimg = '0{}-0{}-'
        random.randint(1, addTier)
        return addTier, timeTier


def setup():
    return Hug()
