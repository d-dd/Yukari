import random
from twisted.internet import reactor

class BasicPlugin(object):
    """ Basic and generic chat-bot commands """

    def _com_8ball(self, yuka, username, args):
        if not args:
            return
        choices = ('It is certain', 'It is decidedly so', 'Without a doubt',
                'Yes - definitely', 'You may rely on it', 'As I see it, yes',
                'Most likely', 'Outlook good', 'Signs point to yes', 'Yes',
                'Reply hazy, try again', 'Ask again later',
                'Better not tell you now', 'Cannot predict now',
                'Concentrate and ask again', "Don't count on it",
                'My reply is no', 'My sources say no','Outlook not so good',
                'Very doubtful')
        msg = '[8ball: %s] %s' % (args, random.choice(choices))
        yuka.sendChats(msg)

    def _com_ask(self, yuka, username, args):
         if not args:
             return
         if len(args) > 227:
             args = args[:224] + '(...)'
         msg = '[Ask: %s] %s' % (args, random.choice(('Yes', 'No')))
         yuka.sendChats(msg)

    def _com_bye(self, yuka, username, args):
         farewell = random.choice(('Goodbye', 'See you', 'Bye', 'Bye bye',
                                  'See you later', 'See you soon', 'Take care'))
         msg = '%s, %s.' % (farewell, user)
         reactor.callLater(0.2, yuka.sendChats, msg)

    def _com_coin(self, yuka, username, args):
        reactor.callLater(0.2, yuka.sendChats,
                          '[coin flip]: %s' % random.choice(['Heads', 'Tails']))

    def _com_choose(self, yuka, username, args):
        if not args:
            return
        choices = self._getChoices(args)
        if choices:
            msg = '[Choose: %s] %s' % (args, random.choice(choices))
            yuka.sendChats(msg)

    def _com_dice(self, yuka, username, args):
        if not args:
            nums = (1, 6)
        elif ',' in args:
            nums = args.split(',')
        else:
            nums = args.split()
        if len(nums) < 2:
            return
        times, sides = nums[0], nums[1]
        if not times or not sides:
            return
        try:
            times = int(times)
            sides = int(sides)
        except(ValueError):
            return
        rolls = self._rollDice(times, sides)
        if not rolls:
            return
        if len(rolls) == 1:
            rollsStr = ''
            plural = ''
        elif len(rolls) > 5:
            rollsStr = str(rolls[:5])[:-1] + ' ...]'
            plural = 's'
        else:
            rollsStr = str(rolls)
            plural = 's'
        msg = ('[Dice roll%s: %dd%d] %s %s' %
               (plural, times, sides, sum(rolls), rollsStr))
        yuka.sendChats(msg)

    def _com_flip(self, yuka, username, args):
        """ Alias of coin """
        self._com_coin(yuka, username, args)

    def _com_goodnight(self, yuka, username, args):
        reactor.callLater(0.2, yuka.sendChats, 'Goodnight, %s.' % username)

    def _com_greet(self, yuka, username, args):
        reactor.callLater(0.2, yuka.sendChats, 'Hi, %s.' % username)

    def _com_help(self, yuka, username, args):
        msg =('Commands: https://github.com/d-dd/Yukari/blob/master/commands.md'
                                        ' Repo: https://github.com/d-dd/Yukari')
        yuka.sendChats(msg)

    def _com_permute(self, yuka, username, args):
        if not args:
            return
        choices = self._getChoices(args)
        if choices:
            random.shuffle(choices)
            msg = '[Permute: %s] %s' % (args, ', '.join(choices))
            yuka.sendChats(msg)

    def _com_poke(self, yuka, username, args):
        return
        yuka.sendChats('Please be nice, %s!' % username)

    def _com_roll(self, yuka, username, args):
        """ Alias of dice """
        self._com_dice(yuka, username, args)

    def _getChoices(self, args):
        if len(args) > 230:
            return
        if ',' in args:
            choices = args.split(',')
        else:
            choices = args.split()
        if choices:
            return choices

    def _rollDice(self, times, sides):
        if times < 1 or sides < 1 or times > 999 or sides > 999:
            return
        if sides == 1:
            rolls = times * [sides]
            return rolls
        else:
            return [random.randrange(1, sides+1) for x in range(1, times+1)]

def setup():
    return BasicPlugin()
