import re, urlparse
from tools import clog
import tools
from twisted.internet import reactor
__EXCLUDED = ('re', 'urlparse', 'clog', 'tools', 'reactor')

def _cyCall_setMotd(self, fdict):
    # setMotd comes after the chat buffer when joining a channel
    self.receivedChatBuffer = True
    clog.debug('(_cyCall_setMotd) MOTD set')
    self.motd = fdict['args'][0]['motd']

def _com_thread(self, username, args, source):
    rank = self._getRank(username)
    if rank < 2:
        return
    p = tools.MotdParser('threadref')
    p.feed(self.motd)
    link = p.link
    if not args:
        self.doSendChat('[thread] %s ' % link)
    elif args:
        # Cytube will make the url a link, so we remove tags
        args = tools.returnUnicode(args)
        strip = tools.TagStrip()
        strip.feed(args)
        url = strip.get_text()
        strip = None
        parts = urlparse.urlsplit(url)
        clog.debug(parts, args)
        if not parts.scheme or not parts.netloc:
            self.doSendChat('[thread] Invalid url')
        elif link is None:
            clog.warning('(_com_thread) Could not match anchor/id in MOTD')
            self.doSendChat("[thread] Error: Check MOTD for anchor with id"
                            " 'threadref' and a non-empty href after it.")
        else:
            # Cytube automatically evens out the spaces, 
            # and removes empty quotes from the MOTD
            pattern = r"""(threadref['"] href\s?=\s?)(".+?"|'.+?')"""
            newMotd = re.sub(pattern, r'\1'+url, self.motd)
            clog.debug('(_com_thread) Setting new MOTD with thread url %s'
                        % url)
            self.sendf({'name': 'setMotd', 'args': {'motd': newMotd}})

def __init(self):
    self.motd = ''

def __add_method(bClass,  names, reference):
    for name in names:
        if name not in __EXCLUDED and not name.startswith('__'):
            clog.warning('ADDING METHOD %s!' % name, 'CYIMPORT')
            obj = getattr(reference, name, None)
            setattr(bClass, name, obj)
        li = getattr(bClass,'start_init', None)
        li.append(__init)
