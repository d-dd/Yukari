# test user and chat logging functionality
import time
import cyClient
from twisted.internet import reactor

teto = {}
teto['args'] = [{}]
teto['args'][0]['name'] = 'teto'
teto['args'][0]['rank'] = 3
print teto
def makeChat(i):
    chat = {}
    chat['args'] = [{}]
    chat['args'][0]['username'] = 'teto'
    chat['args'][0]['msg'] = 'Hi! [%s]' % i
    chat['args'][0]['time'] = time.time() * 1000
    chat['args'][0]['meta'] = {}
    return chat

def spam(x):
    for i in range(x):
        c._cyCall_chatMsg(makeChat(i))

c = cyClient.CyProtocol()
c.receivedChatBuffer = True
c.userdict = {}
# join and immedialty say Hi three times
def recCyMsg(username, msg, needProcessing):
    pass
class Empty:
    pass
f = recCyMsg
c.factory = Empty()
c.factory.handle = Empty()
c.factory.handle.recCyMsg = f
c._cyCall_addUser(teto)
c._cyCall_chatMsg(makeChat(1))
c._cyCall_chatMsg(makeChat(2))
c._cyCall_chatMsg(makeChat(3))

# chat more after a few seconds
reactor.callLater(3, c._cyCall_chatMsg, makeChat(4))
reactor.callLater(3, c._cyCall_chatMsg, makeChat(5))
reactor.callLater(4, c._cyCall_chatMsg, makeChat(6))
reactor.callLater(6, c._cyCall_chatMsg, makeChat(7))
# spam 10000 lines
reactor.callLater(11, spam, 10000)
reactor.run()
