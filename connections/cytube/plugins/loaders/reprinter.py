import nicodl
import youtube_upload
from optparse import OptionParser
from oauth2client.tools import argparser

class Options:
    pass

INFO = ('This video was reprinted from NicoNicoDouga.\n'
        u'\u3053\u306e\u52d5\u753b\u306f\u30cb\u30b3\u30cb\u30b3\u52d5\u753b'
        u'\u304b\u3089\u306e\u8ee2\u8f09\u3067\u3059\u3002'
        '\n') 

def reprint(smid, nicouser, nicopass, dl=True):
    title, desc = nicodl.main(smid, nicouser, nicopass, dl)
    print title.encode('utf8')
    options = Options()
    options.file = smid + '.flv'
    options.keywords = None
    options.title = title
    options.description = ('%s http://nicovideo.jp/watch/%s' % 
                    (INFO, smid))
    options.category = None
    options.privacyStatus = 'unlisted' # public, private, or unlisted

    youtube = youtube_upload.get_authenticated_service(options)
    youtube_upload.initialize_upload(youtube, options)

print 'import successful!'
if __name__ == '__main__':
    parser = OptionParser()
    parser.add_option('--smid', dest='smid', help='NicoNicoDouga video sm ID')
    parser.add_option('--user', dest='username', 
                      help='NicoNicoDouga login user id/email')
    parser.add_option('--pass', dest='password',
                      help='NicoNicoDouga login password')
    (options, args) = parser.parse_args()
    if options.smid is None:
        exit('Please specify a valid nico id')
    elif options.username is None or options.password is None:
        exit('Please supply your NND login credentials.')
    else:
        reprint(options.smid, options.username, options.password)

