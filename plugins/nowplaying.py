"""
Plugin to show currently playing media.
Use: $np x
Where x is the distance from the currently playing media.
"""

from tools import clog, commandThrottle
syst = 'NowPlaying'
class NowPlayingPlugin(object):
    """Plugin of NowPlaying command"""

    @commandThrottle(0)
    def _com_np(self, yuka, username, args, source):
        offset = parse_arg_for_offset(args)
        try:
            cy = yuka.wsFactory.prot
        except(AttributeError):
            clog.warning('No cytube instance.', syst) 
            return
        i = cy.getIndexFromUid(cy.nowPlayingUid)
        clog.debug('np+0 index is {}'.format(i), syst)
        if i is None:
            return
        else:
            i = i + offset
        
        if not cy.playlist[i:i+1]: # out of bounds
            clog.warning('Request out of bounds.', syst)
            return
        media = cy.playlist[i]['media']
        title = media['title'].encode('utf8')
        url = make_media_url(media['type'], media['id'])

        if offset > 0:
            plus_minus = '+{}'.format(offset)
        elif offset < 0:
            # str(negative_int) already includes '-' sign
            plus_minus = '{}'.format(offset)
        else:
            plus_minus = ''

        msg = '[np{}]: {} {}'.format(plus_minus, title, url)
        yuka.reply(msg, source, username)
        
def parse_arg_for_offset(args):
    """args : args from $np
    returns: integer"""
    if not args:
        offset = 0
    else:
        try:
            offset = int(args)
        except(ValueError):
            offset = 0
    return offset

def make_media_url(mType, mId):
    """Make media url from mType, mId
    """
    if mType == 'yt':
        url = 'https://youtu.be/{}'.format(mId)
    elif mType == 'sc':
        url = mId
        if mId.startswith('http://'):
            url = 'https{}'.format(mId[4:])
    else:
        url = mId
    return url

def setup():
    return NowPlayingPlugin()
