from conf import config
from tools import commandThrottle

class LinksPlugin(object):
    """ Return url to recent links page """

    def __init__(self):
        try:
            self.links_url = str(config['misc']['links_url'])
        except(KeyError):
            self.links_url = None

    @commandThrottle(2)
    def _com_links(self, yuka, username, args, source):
        self.give_links(yuka, username, args, source)

    @commandThrottle(2)
    def _com_link(self, yuka, username, args, source):
        self.give_links(yuka, username, args, source)

    def give_links(self, yuka, username, args, source):
        if self.links_url:
            msg =('Links: {}'.format(self.links_url))
            yuka.reply(msg, source, username)

def setup():
    return LinksPlugin()
