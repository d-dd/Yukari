from tools import clog
import random
from connections.cytube.cyClient import commandThrottle

class BasicCommands(object):

    @commandThrottle(1)
    def _com_who(self, cy, username, args, source):
        if source == 'chat' and args:
            msg = '[Who: %s] %s' % (args, random.choice(cy.userdict.keys()))
            cy.doSendChat(msg)

    @commandThrottle(10)
    def _com_poke(self, cy, username, args, source):
        if source == 'chat':
            msg = 'Please be nice, %s!' % username
            cy.doSendChat(msg)
def setup():
    return BasicCommands()
