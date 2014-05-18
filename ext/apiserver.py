import database
from twisted.web.resource import Resource
from twisted.web.server import NOT_DONE_YET
import json

class GetMedia(Resource):
    isLeaf = True
    def _delayedRender(self, result, request):
        out = {'title': result[0][0].encode('UTF-8'), 'duration':result[0][1]}
        j = json.dumps(out)
        request.write(j)
        request.finish()
    def render_GET(self, request):
        request.setHeader('Content-Type', 'application/json; charset=UTF-8')
        #d = database.query('SELECT * FROM Media', ())
        d = database.query('SELECT title, dur FROM Media where mediaId=?', (1,))
        d.addCallback(self._delayedRender, request)
        return NOT_DONE_YET
