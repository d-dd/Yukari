from datetime import timedelta
import random
import subprocess
import time

class StatusPlugin(object):
    """ A few extras """

    def __init__(self):
        input = ['git', 'rev-parse', '--short', 'HEAD']
        try:
            self.githash = subprocess.check_output(input).strip()
        except(subprocess.CalledProcessError):
            self.githash = 'Error'

    def _com_help(self, yuka, username, args):
        msg =('Commands: https://github.com/d-dd/Yukari/blob/master/commands.md'
                ' Repo: https://github.com/d-dd/Yukari')
        yuka.sendChats(msg)


    def _com_uptime(self, yuka, user, args):
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
        yuka.sendChats('[status] UPTIME Yukari: %s, Cytube: %s, IRC: %s' %
                       (uptime, cyUptime, ircUptime))

    def _com_version(self, yuka, username, args):
        yuka.sendChats('[Version] %s' % self.githash)

def setup():
    return StatusPlugin()
