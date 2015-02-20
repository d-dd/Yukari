import database
from twisted.internet import defer
import tools
from tools import clog, commandThrottle

syst = 'Points'

class Points(object):

    @commandThrottle(4)
    def _com_greet(self, cy, username, args, source):

        # $greet ings, Yukari.
        if args.startswith('ings '):
            reply = 'Greetings, %s!' % username
            cy.doSendChat(reply, source, username)
            return
        isReg = cy.checkRegistered(username)
        d = database.getUserFlag(username.lower(), isReg)
        d.addCallback(self.greet, cy, username, isReg, source)

    @commandThrottle(4)
    def _com_points(self, cy, username, args, source):
        if source != 'pm':
            return
        querier = username
        # if admin+ pm's $points user, yukari will pm back user's points
        if args and source == 'pm':
            if cy._getRank(username) >= 3:
               username = args
        reg = cy.checkRegistered(username)
        if reg is None:
            # assume registered
            reg = 1
        d1 = self.calculatePoints(username, reg)
        d2 = self.calculateStats(username, reg)
        dl = defer.DeferredList([d1, d2])
        dl.addCallback(self.returnPoints, cy, querier, username, source)

    def greet(self, res, cy, username, isReg, source):
        flag = res[0][0]
        if flag & 1: # user has greeted us before
            d = self.calculatePoints(username, isReg)
            d.addCallback(self.returnGreeting, cy, username, source)
        elif not flag & 1:
            database.flagUser(1, username.lower(), isReg)
            reply = 'Nice to meet you, %s!' % username
            cy.doSendChat(reply, source, username)

    def returnGreeting(self, points, cy, username, source):
        clog.info('(returnGreeting) %s: %d points' % (username, points), syst)
        modflair = False
        if not points or points < 0:
            reply = 'Hello %s.' % username
        elif points < 999:
            reply = 'Hi %s.' % username
        elif points < 2000:
            reply = 'Hi %s!' % username
        elif points < 10000:
            reply = 'Hi %s! <3' % username
        elif points < 50000:
            reply = 'Hi %s!! <3' % username
            modflair = 3
        else:
            reply = '>v< Hi %s!! <3' % username
            modflair = 3
        cy.doSendChat(reply, source, username, modflair)

    def returnPoints(self, stats, cy, querier, username, source):
        # e.g. [(True, 1401.87244), (True, [(True, [(19,)]), (True, [(96,)]),
        # (True, [(22,)]), (True, [(3,)]), (True, [(23,)]), (True, [(2,)])])]
        points = stats[0][1]
        adds = stats[1][1][0][1][0][0]
        queues = stats[1][1][1][1][0][0]
        likes = stats[1][1][2][1][0][0]
        dislikes = stats[1][1][3][1][0][0]
        liked = stats[1][1][4][1][0][0]
        disliked = stats[1][1][5][1][0][0]

        clog.info('(returnPoints) %s has %d points.' %(username, points), syst)
        cy.doSendChat('[%s] points:%d (a%d / q%d / l%d / d%d / L%d / D%d)' %
           (username, points, adds, queues, likes, dislikes, liked, disliked),
            source=source, username=querier)

    def calculatePoints(self, username, isRegistered):
        d1 = database.calcUserPoints(None, username.lower(), isRegistered)
        d2 = database.calcAccessTime(None, username.lower(), isRegistered)
        dl = defer.DeferredList([d1, d2])
        dl.addCallback(self.sumPoints, username, isRegistered)
        return dl

    def calculateStats(self, username, isRegistered):
        user = (username.lower(), isRegistered)
        dAdded = database.getUserAddSum(*user)
        dQueued = database.getUserQueueSum(*user)
        dLikes = database.getUserLikesReceivedSum(*user, value=1)
        dDislikes = database.getUserLikesReceivedSum(*user, value=-1)
        dLiked = database.getUserLikedSum(*user, value=1)
        dDisliked = database.getUserLikedSum(*user, value=-1)
        dl = defer.DeferredList([dAdded, dQueued, dLikes, dDislikes,
                                 dLiked, dDisliked])
        return dl

    def sumPoints(self, res, username, isRegistered):
        # sample res [(True, [(420,)]), (True, [(258.7464,)])]
        # [(True, [(0,)]), (True, [(None,)])] # no add/queue, no userinoutrow
        clog.debug('(sumPoints %s)' % res, syst)
        try:
            points = res[0][1][0][0] + res [1][1][0][0]
        except(TypeError):
            points = res[0][1][0][0]
        return points
 
def setup():
    return Points()
