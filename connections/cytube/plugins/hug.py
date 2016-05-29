import json
import random
from twisted.internet import defer
import database
import tools
from tools import clog, commandThrottle

import time
from operator import mul

syst = 'Hug'

class Hug(object):
    def __init__(self, huglinks):
        self.hostpath = huglinks['hostpath']
        self.hugimglinks = huglinks['hugimgs']
        self.maxlevel = max([int(i) for i in self.hugimglinks])

    @commandThrottle(0)
    def _com_hug(self, cy, username, args, source):
        # yukari will not hug guests or IRC
        # no args are allowed
        if (args or source == 'irc' 
                 or not cy.checkRegistered(username)):
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
            reply = '...'
        if reply == 'hug!':
            reply = (u'/me hugs {}. '
                    u'\uff77\uff9e\uff6d\uff73\uff70!').format(username)
        else:
            reply = '{}: {}'.format(username, reply)
        cy.doSendChat(reply, source)

    def calculateTiers(self, username, isReg=True):
        d1 = database.calcUserPoints(None, username.lower(), isReg)
        d2 = database.calcAccessTime(None, username.lower(), isReg)
        dl = defer.DeferredList([d1, d2])
        dl.addCallback(self.getHugPicture)
        return dl

    def getHugPicture(self, res):
        clog.debug('(getHugPicture) %s' % res, syst)
        # get add and time tiers
        addTier = max(min(res[0][1][0][0]/25.0, 3.0), 1.0)
        try:
            timeTier = max(min(res[1][1][0][0]/25.0, 3.0),1.0)
        except(TypeError):
            timeTier = 0.0
        multiplier = [addTier, timeTier]
        clog.debug('addTier, timerTier: %s' % str(multiplier), syst)
        randomTier = max(random.gauss(0.4, 1.7), 0.0)
        clog.debug('randomTier roll: %s' % randomTier, syst)
        if randomTier >= 4:
            return 'hug!'
        elif randomTier == 0:
            return
        multiplier[random.randint(0,1)] = min(randomTier, 3.0)
        # product of the list
        hugTier = reduce(mul, multiplier, 1.0)
        hugTier = min(hugTier, self.maxlevel)
        clog.debug('hugtier: %s' % hugTier, syst)
        hugTier = str(int(hugTier)).zfill(3)
        picture = random.choice(self.hugimglinks[hugTier])
        return '%s-%s' % (hugTier, picture)

def setup():
    try:
        with open('connections/cytube/plugins/_huglinks.json') as huglink_file:
            huglinks = json.load(huglink_file)
    except(IOError):
        clog.error('_huglinks.json file not found! This module '
                   'will not be loaded.', syst)
        return
    except(ValueError):
        clog.error('_huglinks.json is invalid! This module '
                   'will not be loaded.', syst)
        return
    return Hug(huglinks)
