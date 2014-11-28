import database
import tools
from tools import clog, commandThrottle
import argparse

syst = 'Add'

class Add(object):
    @commandThrottle(3)
    def _com_add(self, cy, username, args, source):
        if source != 'chat':
            return
        rank = cy._getRank(username)
        if not rank:
            return
        elif rank < 2:
            maxAdd = 5
        else:
            maxAdd = 20
        if args is None:
            args = '-n 3'
        #clog.info(args, syst)
        title, arguments = self.parseTitle(args)
        args = arguments.split()

        # shortcut in case people want to $add #
        # of course this can't be combined with other args
        try:
            num = int(args[0])
            args = ['-n', str(num)]

        except(ValueError, IndexError):
            pass
        
        parser = argparse.ArgumentParser()
        parser.add_argument('-s', '--sample', default='queue', 
                            choices=('queue', 'q', 'add', 'a', 'like', 'l'))
        parser.add_argument('-u', '--user', default='Anyone')
        parser.add_argument('-g', '--guest', default=False, type=bool)
        parser.add_argument('-n', '--number', default=3, type=int)
        parser.add_argument('-a', '--artist', default='') #TODO
        parser.add_argument('-T', '--temporary', default=False, type=bool)
        parser.add_argument('-N', '--next', default=False, type=bool)
        parser.add_argument('-o', '--omit', default=False, type=bool)

        try:
            args = parser.parse_args(args)
        except(SystemExit):
            cy.doSendChat('Invalid arguments.')
            return

        args.number = min(args.number, maxAdd)
        if rank < 2:
            args.omit = False

        info = ('Quantity:%s, sample:%s, user:%s, guest:%s, temp:%s, '
                'pos:%s, title:%s, include ommited:%s'
                % (args.number, args.sample, args.user, args.guest,
                   args.temporary, args.next, title, args.omit))
        #self.doSendChat(reply)
        clog.debug('(_com_add) %s' % info, syst)
        isRegistered = not args.guest

        if args.next:
            args.next = 'next'
        else:
            args.next = 'end'
        args.user = args.user.lower()
        if args.user == 'anyone':
            args.user = None
        
        d = self.getRandMedia(args.sample, args.number, args.user, isRegistered,
                                      title)
        d.addCallback(cy.doAddMedia, args.temporary, args.next)

    def parseTitle(self, command):
        # argparse doesn't support spaces in arguments, so we search
        # and parse the -t/ --title values in msg ourselves
        tBeg = command.find('-t ')
        if tBeg == -1:
            return None, command
        tBeg += 3
        tEnd = command.find(' -', tBeg)
        if tEnd == -1:
            tEnd = len(command)
        shortMsg = command[:tBeg-3] + command[tEnd+1:]
        title = tools.returnUnicode(command[tBeg:tEnd])
        return title, shortMsg

    def getRandMedia(self, sample, quantity, username, isRegistered, title):
        """ Queues up to quantity number of media to the playlist """
        if sample == 'queue' or sample == 'q':
            d = database.addByUserQueue(username, isRegistered, title, quantity)
        elif sample == 'add' or sample == 'a':
            d = database.addByUserAdd(username, isRegistered, title, quantity)
        
        elif sample == 'like' or sample == 'l':
            d = database.addByUserLike(username, isRegistered, quantity)
        else:
            return
        return d

def setup():
    return Add()
