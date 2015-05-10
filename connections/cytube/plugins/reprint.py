import json
import os
import sys

from twisted.internet import protocol, reactor

from conf import config
from tools import clog, commandThrottle

syst = 'REPRINT'

class Reprint(object):

    @commandThrottle(0)
    def _com_reprint(self, cy, username, args, source):
        if not args or len(args) > 11 or not args.startswith('sm'):
            clog.debug('reprint - no args or bad args', syst)
            return
        # user must be rank at least rank 3 AND be on the allowed.txt list
        rank = cy._getRank(username)
        if rank < 2:
            clog.debug('not enough rank for $reprint', syst)
            return
        with open('connections/cytube/plugins/loaders/allowed.cfg') as f:
            allowed = f.read().lower().split()
            if username.lower() not in allowed:
                clog.debug('not in allowed.txt for $reprint', syst)
                return
        try:
            if cy.reprint is False:
                clog.debug('cy.reprint is False', syst)
                return
            elif self.reprint == 'IP':
                cy.doSendChat('[reprint] Busy with another request.',
                                toIrc=False)
                return
        except(AttributeError):
            cy.reprint = True
        path = 'connections/cytube/plugins/loaders'
        try:
            d = json.load(open('%s/videos.json' % path))
        except(IOError, ValueError): #No file, #not a JSON
            clog.error('Error loading file "videos.json"', syst)
            return
        if args in d:
            cy.doSendChat('[reprint] This video has already been reprinted',
                            toIrc=False)
            return
        p = ReprintProtocol(self, cy)
        clog.warning('Spawning Reprint process!', syst)
        subprocess = reactor.spawnProcess(p, sys.executable,
            ['python', 'reprinter.py', '--smid', args, '--user', 
                config['reprinter']['nicoid'], '--pass',
                config['reprinter']['nicopass']], os.environ, path)

    def _add_done_video(self, cy, ytid):
        #send a message saying it's done
        cy.doSendChat('[reprint] Done uploading. The video will automatically '
                        'be added 5 minutes later.', toIrc=False)
        # wait 5 minutes to let Youtube finish processing
        # If we add too soon, the YT API returns 0:00 duration, and Cytube will
        # think it's a livestream and will never queue to the next video.
        # Perhaps Yukari can call the YT API herself and only add if it returns
        # a valid duration #TODO
        reactor.callLater(300, cy.sendf, {'name': 'queue', 'args': {'type': 'yt', 
                            'id': ytid, 'pos': 'end', 'temp': False}})

class ReprintProtocol(protocol.ProcessProtocol):
    def  __init__(self, reprinter, cy):
        self.reprinter = reprinter
        self.cy = cy

    def connectionMade(self):
        self.pid = self.transport.pid
        clog.warning('Connected to Reprint process!', syst)
        self.cy.doSendChat('[reprint] Connected to reprint process. This may '
                           'take up to 30 minutes.', toIrc=False)
        self.output = ''
        self.cy.reprint = 'IP'

    def outReceived(self, data):
        clog.info('[outRec] %s' % data.decode('utf8'), syst)
        self.output += data

    def errReceived(self, data):
        clog.error('[errRec] %s' % data.decode('utf8'), syst)

    def processEnded(self, reason):
        clog.warning('[processEnded] Process %s had ended' % self.pid, syst)
        index = self.output.find('DONE ')
        if index != -1:
            ytid = self.output[index+5:-1] #-1 to remove \n
            self.reprinter._add_done_video(self.cy, ytid)
            self.cy.reprint = True
        else:
            if self.output.find('This video is low resolution.') != -1:
                self.cy.doSendChat('[reprint] NND is currently in economy mode.'
                                 ' Please try again another time.', toIrc=False)
                self.cy.reprint = True
                return
            # process failed to upload, check console
            msg = ('[reprint] Failed to upload video. $reprint funcionality'
                   'has been disabled. Check the log for errors.')
            self.cy.doSendChat(msg, toIrc=False)
            self.cy.reprint = False

def setup():
    return Reprint()
