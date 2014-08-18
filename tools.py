import HTMLParser, htmlentitydefs
import sys, time
import logging
from twisted.words.protocols.irc import attributes as A
from twisted.python import log

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
        if level > self.logLevel and level == logging.ERROR:
            self.write('\033[91m')
            log.FileLogObserver.emit(self, eventDict)
            self.write('\033[0m')
        elif level == logging.WARNING:
            self.write('\033[33m')
            log.FileLogObserver.emit(self, eventDict)
            self.write('\033[0m')
        else:
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
    return int(time.time()*100)

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

clog = CustomLog()
# only debug will show Twisted-produced messages
logger = LevelFileLogObserver(sys.stdout, level=logging.DEBUG)
log.addObserver(logger.emit)

h = HTMLParser.HTMLParser()
chatFormat = TagStrip()

# instantiate once and reuse same instance
mls = MLStripper()
