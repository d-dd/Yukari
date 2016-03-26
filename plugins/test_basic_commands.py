"""
run by:
    python -m unittest discover plugins
from Yukari/
"""
import  unittest
import mock
from basic_commands import BasicPlugin
from yukari import Connections
from connections.cytube.cyClient import CyProtocol

class TestBasicCommands(unittest.TestCase):

    @mock.patch('basic_commands.random.choice', return_value='Yes')
    def test_ask_mock(self, rnd):
        username = 'Teto'
        source = 'pm'
        args = 'Hello?'
        msg = '[Ask: Hello?] Yes'
        mock_yuk_service = mock.create_autospec(Connections)
        mock_cy_service = mock.create_autospec(CyProtocol)
        mock_cy_service.userdict = {'Teto':{'cthrot':{'net':1001, 'last':0, 'max':9999}}}
        reference = BasicPlugin()
        reference._com_ask(mock_yuk_service, username, args, source, prot=mock_cy_service)
        mock_yuk_service.reply.assert_called_with(msg, source, username)
        

