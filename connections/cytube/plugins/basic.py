from tools import clog, commandThrottle
import random

class BasicCommands(object):

    @commandThrottle(2)
    def _com_who(self, cy, username, args, source):
        if source == 'chat' and args:
            msg = '[Who: %s] %s' % (args, random.choice(cy.userdict.keys()))
            cy.doSendChat(msg)

def setup():
    return BasicCommands()
