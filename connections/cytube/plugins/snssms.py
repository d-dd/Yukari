import os
import random
import re
import sqlite3
import sys
from twisted.internet import protocol, reactor
from conf import config
from tools import clog, commandThrottle
import database

syst = 'SNSSMS'
TOPIC = config['aws']['snstopicarn'].encode('utf8')

def createTable():
    """Set up neceesary table if none exists."""
    con = sqlite3.connect('data.db')
    con.execute('pragma foreign_keys=ON')
    con.execute("""
        CREATE TABLE IF NOT EXISTS Sms(
        userId INTEGER NOT NULL,
        subAttempts INTEGER NOT NULL DEFAULT 1,
        flag INTEGER NOT NULL DEFAULT 0,
        FOREIGN KEY(userId) REFERENCES CyUser(userId));""")

class SnsReminder(object):
    @commandThrottle(2)
    def _com_sms(self, cy, username, args, source):
        if source != 'pm' or not args:
            return
        num = re.sub(r'\D', '', args)
        if len(num) not in (10, 11):
            cy.doSendPm('Invalid phone number.', username)
            return
        rank = cy._getRank(username)
        if len(num) == 11:
            num = num[1:]
        number = '1-{0}-{1}-{2}'.format(num[0:3], num[3:6], num[6:10])
        self.dbQuerySubAttempt(cy, username, rank, number)
    
    def subscribeSms(self, result, cy, username, rank, number):
        path = 'connections/cytube/plugins'
        p = SmsProtocol(self, username, cy)
        args = ['aws', 'sns', 'subscribe', '--topic-arn', TOPIC,
                    '--notification-endpoint', number, '--protocol', 'sms']
        subprocess = reactor.spawnProcess(p, 'aws', args, os.environ, path)
        self.dbIncrementSubAttempt(cy, username, rank)
        cy.doSendChat('Please check for a text from 303-04.', 'pm', username)

    def dbQuerySubAttempt(self, cy, username, rank, number):
        sql = ('SELECT subAttempts FROM Sms WHERE userId= '
             '(SELECT userId FROM CyUser WHERE nameLower=? AND registered=?)')
        binds = (username.lower(), 1 if rank else 0)
        d = database.query(sql, binds)
        d.addCallback(self.dbQuerySubAttemptRes, cy, username, rank, number)

    def dbQuerySubAttemptRes(self, result, cy, username, rank, number):
        if not result: #user not in table yet
            d = self.dbWriteSubAttempt(cy, username, rank)
            d.addCallback(self.subscribeSms, cy, username, rank, number)
            return d
        else:
            if result[0][0] > 3:
                clog.warning('Too many subscribe attempts by %s.' % username,
                        syst)
                # too many attempts
                cy.doSendChat('Request denied: Too many previous attempts.',
                        'pm', username)
            else:
                self.subscribeSms(None, cy, username, rank, number)

    def dbWriteSubAttempt(self, cy, username, rank):
        sql = ('INSERT INTO Sms (userId) VALUES '
               '((SELECT userId FROM CyUser WHERE nameLower=? AND registered=?))')
        binds = (username.lower(), 1 if rank else 0)
        return database.operate(sql, binds)

    def dbIncrementSubAttempt(self, cy, username, rank):
        sql = ('UPDATE Sms SET subAttempts=subAttempts + 1 WHERE userId= '
             '(SELECT userId FROM CyUser WHERE nameLower=? AND registered=?)')
        binds = (username.lower(), 1 if rank else 0)
        return database.operate(sql, binds)

class SmsProtocol(protocol.ProcessProtocol):
    def __init__(self, sms, username, cy):
        self.sms = sms
        self.cy = cy
        self.username = username
        self.output = ''

    def connectionMade(self):
        self.pid = self.transport.pid
        clog.warning('Connected to Sms process!', syst)

    def outReceived(self, data):
        clog.info('[outRec] %s' % data.decode('utf8'), syst)
        self.output += data
    
    def errReceived(self, data):
        clog.error('[errRec] %s' % data.decode('utf8'), syst)

    def processEnded(self, reason):
        clog.warning('[processEnded] Process %s has ended' % self.pid, syst)
        
def setup():
    createTable()
    return SnsReminder()
