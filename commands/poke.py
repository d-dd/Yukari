import random
from tools import clog
from twisted.internet import reactor

def _com_greet(self, user, args):
    msg = 'Hi, %s.' % user
    reactor.callLater(0.2, self.sendChats, msg)

def _com_bye(self, user, args):
    farewell = random.choice(('Goodbye', 'See you', 'Bye', 'Bye bye',
                              'See you later', 'See you soon', 'Take care',
                              ))
    msg = '%s, %s.' % (farewell, user)
    reactor.callLater(0.2, self.sendChats, msg)

def _com_goodnight(self, user, args):
    reactor.callLater(0.2, self.sendChats, 'Goodnight, %s.' % user)

def _com_ask(self, user, args):
    if not args:
        return
    if len(args) > 227:
        args = args[:224] + '(...)'
    msg = '[Ask: %s] %s' % (args, random.choice(('Yes', 'No')))
    self.sendChats(msg)

def _com_choose(self, user, args):
    if not args:
        return
    choices = self.getChoices(args)
    if choices:
        msg = '[Choose: %s] %s' % (args, random.choice(choices))
        self.sendChats(msg)

def _com_permute(self, user, args):
    if not args:
        return
    choices = self.getChoices(args)
    if choices:
        random.shuffle(choices)
        msg = '[Permute: %s] %s' % (args, ', '.join(choices))
        self.sendChats(msg)

def getChoices(self, args):
    if len(args) > 230:
        return
    if ',' in args:
        choices = args.split(',')
    else:
        choices = args.split()
    if len(choices) < 1:
        return
    return choices

def _com_8ball(self, user, args):
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
    self.sendChats(msg)

def _com_dice(self, user, args):
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
    rolls = self.rollDice(times, sides)
    if not rolls:
        return
    if len(rolls) == 1:
        rollsStr = ''
    elif len(rolls) > 5:
        rollsStr = str(rolls[:5])[:-1] + ' ...]' 
    else:
        rollsStr = str(rolls)
    msg = ('[Dice: %dd%d] %s %s' % 
                (times, sides, sum(rolls), rollsStr))
    self.sendChats(msg)

def rollDice(self, times, sides):
    if times < 1 or sides < 1 or times > 999 or sides > 999:
        return
    if sides == 1:
        rolls = times * [sides]
        return rolls
    else:
            return [random.randrange(1, sides+1) for x in range(1, times+1)]

def _com_poke(self, user, args):
    return
    self.sendChats('%s please be nice!' % user)
    clog.error('asdf')
    
def __add_method(bClass, names, reference):
    for name in names:
        if name not in ('reactor', 'random', 'clog') and not name.startswith('__'):
            clog.warning('ADDING METHOD %s!' % name, 'IMPORT')
            obj = getattr(reference, name, None)
            setattr(bClass, name, obj)
