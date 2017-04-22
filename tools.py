from datetime import datetime
import pytz
import HTMLParser, htmlentitydefs
import logging, sys, time
from functools import wraps
from twisted.words.protocols.irc import attributes as A
from twisted.python import log
from twisted.internet.error import AlreadyCalled, AlreadyCancelled
from twisted.logger import Logger

class EscapedLogger(Logger):
    """Logger with additional log methods that escape
    { and }, so it can display json.
    """
    def _unescape_curly(msg):
        msg = msg.replace('{', '{{')
        msg = msg.replace('}', '}}')
        return msg

    def debugz(self, msg):
        self.debug(_unescape_curly(msg))

    def infoz(self, msg):
        self.info(_unescape_curly(msg))

    def warnz(self, msg):
        self.warn(_unescape_curly(msg))

    def errorz(self, msg):
        self.error(_unescape_curly(msg))

    def criticalz(self, msg):
        self.critical(_unescape_curly(msg))

class LevelFileLogObserver(log.FileLogObserver):
    def __init__(self, f, level=logging.INFO):
        log.FileLogObserver.__init__(self, f)
        self.logLevel = level

    def emit(self, eventDict):
        # Reset text color
        if eventDict['isError']:
            level = logging.ERROR
            self.write("\033[91m")
            log.FileLogObserver.emit(self, eventDict)
            self.write('\033[0m')
            return
        elif 'level' in eventDict:
            level = eventDict['level']
        else:
            level = logging.INFO
        if level >= self.logLevel and level == logging.ERROR:
            self.write('\033[91m')
            log.FileLogObserver.emit(self, eventDict)
            self.write('\033[0m')
        elif level >= self.logLevel and level == logging.WARNING:
            self.write('\033[33m')
            log.FileLogObserver.emit(self, eventDict)
            self.write('\033[0m')
        elif level >= self.logLevel:
            log.FileLogObserver.emit(self, eventDict)

class CustomLog():
    """ logging shortcut """
    def debug(self, msg, sys=None):
        msg = returnStr(msg)
        log.msg(msg, level=logging.DEBUG, system=sys)
    def info(self, msg, sys=None):
        msg = returnStr(msg)
        log.msg(msg, level=logging.INFO, system=sys)
    def warning(self, msg, sys=None):
        msg = returnStr(msg)
        log.msg(msg, level=logging.WARNING, system=sys)
    def error(self, msg, sys=None):
        msg = returnStr(msg)
        log.msg(msg, level=logging.ERROR, system=sys)
    # using log.err emits the error message twice. :?
    def errorm(self, msg, sys=None):
        msg = returnStr(msg)
        log.err(msg, level=logging.ERROR, system=sys)
    def critical(self, msg, sys=None):
        msg = returnStr(msg)
        log.msg(msg, level=logging.CRITICAL, system=sys)

def unescapeMsg(htmlStr):
    """ Unescape HTML entities from a string """
    if not htmlStr:
        return ''
    return h.unescape(htmlStr)

class TagStrip(HTMLParser.HTMLParser):
    """ Strip HTML tags from a CyTube messsage and format it for IRC if 
    necessary."""

    def __init__(self):
        HTMLParser.HTMLParser.__init__(self)
        self.result = []
    def handle_data(self, d):
        self.result.append(d)
    def handle_charref(self, number):
        if number[0] in (u'x', u'X'):
            codepoint = int(number[1:], 16)
        else:
            codepoint = int(number)
        self.result.append(unichr(codepoint))
    def handle_entityref(self, name):
        #clog.warning('handle_entityref %s' % name, 'debug')
        try:
            codepoint = htmlentitydefs.name2codepoint[name]
            self.result.append(unichr(codepoint))
        except(KeyError):
            self.result.append('&'+name) # patch for the time being TODO
    def get_text(self):
        return ''.join(self.result)

class MLStripper(HTMLParser.HTMLParser):
    """ Strips tags and removes (deletes) HTML entities"""
    def __init__(self):
        self.reset()
        self.fed = []

    def handle_data(self, d):
        self.fed.append(d)

    def get_data(self):
        return ''.join(self.fed)

def strip_tags(html):
    self = mls
    self.reset()
    self.fed = []
    self.feed(html)
    return self.get_data()

def strip_tag_entity(html):
    self = chatFormat
    self.result = []
    self.reset()
    self.feed(html)
    return self.get_text()

def getTime():
    """Return timezone aware datetime object
    in UTC.
    e.g.
    >>>datetime.datetime(2017, 2, 18, 7, 19, 57, 758400, tzinfo=<UTC>)
    """
    return datetime.now(pytz.utc)

##    return int(time.time()*100)

def returnStr(text):
    if isinstance(text, unicode):
        return text.encode('utf-8')
    else:
        return text

def returnUnicode(text):
    if isinstance(text, str):
        return text.decode('utf-8')
    else:
        return text

class MotdParser(HTMLParser.HTMLParser):
    def __init__(self, searchId):
        HTMLParser.HTMLParser.__init__(self)
        self.searchId = searchId
        self.link = None

    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            d = dict(attrs)
            anchorId = d.get('id', None)
            if anchorId == self.searchId:
                self.link = d.get('href', None)

def cleanLoops(looplist):
    """ stops Twisted LoopingCalls """
    while looplist:
        loop = looplist.pop()
        if loop.running:
            loop.stop()

def cleanLaters(laterslist):
    """ cancelles all callLater's """
    while laterslist:
        try:
            laterslist.pop().cancel()
        except(AlreadyCancelled, AlreadyCalled):
            pass

def commandThrottle(cost):
    """ Decorator to Throttle commands
    # Decorator
    # Add @commandThrottle(cost) before a command method to enable throttle
    # cost: how much limit to reduce for the command
    # Use high cost for expensive to comupte commands such as $greet and
    #  $points, and API dependent commands such as $anagram
    #
    # The limit is shared between all commands that use this decorator
    # Note that failed commands (such as $choose without arguments) will still
    # cost users to use their limits.
    """
    syst = 'commandThrottle'
    def limiter(func):
        @wraps(func)
        def throttleWrap(*args, **kwargs):
            #clog.warning("Wrapping things %s, %s" % (args, kwargs), syst)
            try:
                prot = kwargs.get('prot', None)
                username = args[2]
                origin = args[4]
            except(IndexError, NameError):
                clog.error('commandThrottle: Invalid args!', syst)
                return
            if not prot:
                clog.warning('commandThrottle: Could not find protocol!', syst)
                return

            # delete the protocol reference / argument; the _com_ methods
            # do not expect it
            del kwargs['prot']

            # for cytube only
            if origin != 'chat' and origin != 'pm':
                # pass-through
                # we don't have any throttle for IRC users, because the
                # network throttles them already
                return func(*args, **kwargs)

            # Cytube
            if prot.userdict.get(username, None):
                cthrot = prot.userdict[username]['cthrot']
                # add limit back depending on how long they waited, with cap
                cthrot['net'] += (time.time() - cthrot['last'])/8
                cthrot['net'] = min(cthrot['net'], cthrot['max'])
                cthrot['last'] = time.time()
                if cthrot['net'] >= cost:
                    cthrot['net'] -= cost
                    clog.warning('command ok', syst)
                    return func(*args, **kwargs)
                else:
                    clog.warning('%s is requesting commands too quickly!' 
                                  % username, syst)
            else:
                clog.error('(throttleWrap) could not find %s in userdict!'
                            % username, syst)
        return throttleWrap
    return limiter

clog = CustomLog()

h = HTMLParser.HTMLParser()
chatFormat = TagStrip()

# instantiate once and reuse same instance
mls = MLStripper()
