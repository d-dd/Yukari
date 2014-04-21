import HTMLParser
import htmlentitydefs
from twisted.words.protocols.irc import attributes as A

def unescapeMsg(htmlStr):
    """ Unescape HTML entities from a string """
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
        codepoint = htmlentitydefs.name2codepoint[name]
        self.result.append(unichr(codepoint))
    def get_text(self):
        return ''.join(self.result)

h = HTMLParser.HTMLParser()
chatFormat = TagStrip()
