""" Module for configuration settings. """
        
from ConfigParser import SafeConfigParser
import codecs

parser = SafeConfigParser()

with codecs.open('settings.cfg', 'r', encoding='utf-8') as f:
    parser.readfp(f)

config = dict()
for section in parser.sections():
    config[section] = dict(parser.items(section))
