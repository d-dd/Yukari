import random
from tools import clog, commandThrottle
import database

class BasicCommands(object):

    @commandThrottle(2)
    def _com_who(self, cy, username, args, source):
        if source == 'chat' and args:
            msg = '[Who: %s] %s' % (args, random.choice(cy.userdict.keys()))
            cy.doSendChat(msg)

    @commandThrottle(1)
    def _com_read(self, cy, username, args, source):
        if source != 'pm':
            return
        # people who read the readme/this
        if cy.checkRegistered(username):
            database.flagUser(2, username.lower(), 1)

    @commandThrottle(1)
    def _com_enroll(self, cy, username, args, source):
        if source != 'pm':
            return
            # people who have read this
        if cy.checkRegistered(username):
            database.flagUser(4, username.lower(), 1)


def setup():
    return BasicCommands()
