import unittest
from cyClient import CyProtocol

class TestParseAdd(unittest.TestCase):

    def setUp(self):
        self.prot = CyProtocol()

    def test(self):
        command = '-u yukarin -t Kasane Teto -n 3 -T true -n true'
        title = self.prot.parseTitle(command)
        correct = ('Kasane Teto', '-u yukarin -n 3 -T true -n true')
        self.assertEqual(title, correct)
        command = '-u yukarin -t  Kasane Teto -n 3 -T true -n true'
        title = self.prot.parseTitle(command)
        correct = (' Kasane Teto', '-u yukarin -n 3 -T true -n true')
        self.assertEqual(title, correct)
        command = '-t Kasane Teto'
        title = self.prot.parseTitle(command)
        self.assertEqual(title, ('Kasane Teto', ''))
        command = '-u yukarin -t Kasane Teto'
        title = self.prot.parseTitle(command)
        self.assertEqual(title, ('Kasane Teto', '-u yukarin '))
        command = '-n 2'
        title = self.prot.parseTitle(command)
        self.assertEqual(title, (None, '-n 2'))

if __name__ == '__main__':
    unittest.main()
