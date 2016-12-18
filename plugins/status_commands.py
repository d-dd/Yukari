from datetime import timedelta
import random
import subprocess
import time
from tools import commandThrottle

class StatusPlugin(object):
    """ A few extras """

    def __init__(self):
        input = ['git', 'rev-parse', '--short', 'HEAD']
        try:
            self.githash = subprocess.check_output(input).strip()
        except(subprocess.CalledProcessError):
            self.githash = 'Error'

    @commandThrottle(2)
    def _com_help(self, yuka, username, args, source):
        msg =('Commands: https://github.com/d-dd/Yukari/blob/master/commands.md'
                ' Repo: https://github.com/d-dd/Yukari')
        yuka.reply(msg, source, username)

    @commandThrottle(2)
    def _com_uptime(self, yuka, username, args, source):
        uptime = time.time() - yuka.startTime
        uptime = str(timedelta(seconds=round(uptime)))
        if yuka.cy:
            cyUptime = time.time() - yuka.cyLastConnect
            cyUptime = str(timedelta(seconds=round(cyUptime)))
        else:
            cyUptime = 'n/a'
        if yuka.irc:
            ircUptime = time.time() - yuka.ircFactory.prot.ircConnect
            ircUptime = str(timedelta(seconds=round(ircUptime)))
        else:
            ircUptime = 'n/a'
        yuka.reply('[status] UPTIME Yukari: %s, Cytube: %s, IRC: %s' %
                       (uptime, cyUptime, ircUptime), source, username)

    @commandThrottle(2)
    def _com_version(self, yuka, username, args, source):
        yuka.reply('[Version] %s' % self.githash, source, username)

def setup():
    return StatusPlugin()
