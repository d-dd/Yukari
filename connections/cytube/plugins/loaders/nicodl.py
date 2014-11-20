import re
import requests
import urllib
import urllib2
from optparse import OptionParser
try:
    import xml.etree.cElementTree as ET
except ImportError:
    import xml.etree.ElementTree as ET

def login(email, pw):
    url = 'https://secure.nicovideo.jp/secure/login?site=niconico'
    session = requests.session()
    p = session.post(url, {'mail_tel': email, 'password': pw})
    print p.status_code
    if p.status_code == 200:
        return session
    else:
        print 'Error', p.response
        return

def get_video_info(smid):
    t = requests.get('http://ext.nicovideo.jp/api/getthumbinfo/%s' % smid)
    root = ET.fromstring(t.text.encode('utf8'))
    thumb = root.find('thumb')
    title = thumb.find('title').text
    desc = thumb.find('description').text
    size_high = thumb.find('size_high')
    return title, desc

def get_video_url(session, smid):
    q = session.get('http://flapi.nicovideo.jp/api/getflv?v=%s' % smid)
    if q.status_code == 200:
        u = urllib.unquote(q.text)
        urlg = re.search(r'url=(.*?)&', u)
        if urlg:
            return urlg.group(1)
    return

def download(session, url, smid):
    file_name = '%s.flv' % smid
    r = session.get(url, stream=True)
    size_dled = 0
    print 'Starting download. This may take a while.'
    with open(file_name, 'wb') as f:
        for chunk in r.iter_content(chunk_size=8388608): #8MiB
            size_dled += 8388608
            print 'downloading...: downloaded %d bytes' % size_dled
            if chunk:
                f.write(chunk)
                f.flush()
    print 'Completed download: %s.flv' % smid
    return file_name

def main(smid, user, password, dl=True):
    title, desc = get_video_info(smid)
    if not dl:
        return title, desc
    print title.encode('utf8')
    session = login(user, password)
    if session:
        url = get_video_url(session, smid)
        print url
        if 'low' in url:
            print 'This video may be low resoultion'
        if url.endswith('low'):
            print 'This video is low resolution. Aborting download.'
            import sys
            sys.exit()
        web = session.get('http://www.nicovideo.jp/watch/%s' % smid)
        print 'web: ', web.status_code
        if web.status_code == 200:
            download(session, url, smid)
    return title, desc

if __name__ == '__main__':
    parser = OptionParser()
    parser.add_option('--id', dest='smid', help='Nico video id to download')
    parser.add_option('--user', dest='user', help='NND login username/email')
    parser.add_option('--pass', dest='password', help='NND login password')
    (options, args) = parser.parse_args()

    if options.smid is None or options.user is None or options.password is None:
        exit('Please specify a NicoNicoDouga video id and login credentials.')
    else:
        main(options.smid, options.user, options.password)

