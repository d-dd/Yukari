import time
from twisted.internet.error import AlreadyCalled, AlreadyCancelled
from tools import clog, commandThrottle
from conf import config

syst = 'Poke'
class Poke(object):

    def __init__(self):
        self.lastPoke = time.time()
        self.waitingPokeUser= ''
        self.waitingPokeReply = 0
        self.pokeTimer = None
        self.pokeReply = ' ' + str(config['poke']['pokereply'])
        self.pokeTime = int(config['poke']['poketime'])
        self.pokeInterval = int(config['poke']['pokeinterval'])
        self.pokeRespondBy = int(config['poke']['pokerespondby'])

    @commandThrottle(10)
    def _com_poke(self, cy, username, args, source):
        if source != 'chat':
            return
        if username == self.waitingPokeUser:
            self.waitingPokeUser = ''
            # User must $poke within 90 seconds
            if time.time() - self.waitingPokeReply < self.pokeRespondBy:
                cy.doSendChat(self.pokeReply, modflair=True, toIrc=False)
            else:
                cy.doSendChat('Please be nice, %s...' % username)
        else:
            msg = 'Please be nice, %s!' % username
            cy.doSendChat(msg)

    def _uj_startTimer(self, cy, fdict):
        self.startPokeTimer(cy)

    def _ul_startTimer(self, cy, fdict):
        self.startPokeTimer(cy)

    def startPokeTimer(self, cy):
        """ Starts poke timer if only one user left (besides Yukari) in the
        channel and timer hasn't been run for past 24h. It will be cancelled on:
        -user join
        -user leave
        """
        self.stopTimer(cy)
        if time.time() - self.lastPoke < self.pokeInterval:
            return
        if not len(cy.userdict) == 2: # if not only Yukari and user
            return
        for name in cy.userdict.iterkeys():
            if name != cy.name:
                username = name
            else:
                username = None
        if not username:
            clog.error('Error at startTimer. 2 users but no non-Yukari name',
                    syst)
            return
        from twisted.internet import reactor
        self.pokeTimer = reactor.callLater(self.pokeTime,
            self.yukariPoke, cy, username)
        cy.laters.append(self.pokeTimer)
        clog.warning('Started poke timer for %s!' % username, syst)
        self.lastChatAtTimer = cy.factory.handle.lastIrcChat

    def yukariPoke(self, cy, username):
        # check if IRC messages were sent during wait time
        if not self.lastChatAtTimer == cy.factory.handle.lastIrcChat:
            clog.warning('(yukariPoke) Cancelling poke because there was irc'
                         ' chat activity', syst)
            return
        cy.sendCyWhisper('Yukari pokes %s...!' % username, modflair=True, 
                         toIrc=False)
        self.lastPoke = time.time()
        self.waitingPokeUser = username
        self.waitingPokeReply = time.time()
        self.stopTimer(cy)

    def stopTimer(self, cy):
        # stop timer;
        try:
            self.pokeTimer.cancel()
        except(AttributeError, AlreadyCalled, AlreadyCancelled):
            pass
        # remove timer from cy.laters:
        while self.pokeTimer in cy.laters:
            cy.laters.remove(self.pokeTimer)
        self.pokeTimer = None
    
def setup():
    return Poke()
