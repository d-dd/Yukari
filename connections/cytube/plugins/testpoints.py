from points import Points

from calendar import timegm
from time import strptime
import unittest

class TestGreeting(unittest.TestCase):

    def setUp(self):
        self.g = Points()

    def test_part_of_day_0offset_local_time0(self):
        test_time = timegm(strptime('2015-04-01 00:00', '%Y-%m-%d %H:%M'))
        user_tz_offset = 0
        part_of_day = self.g.get_part_of_day(user_tz_offset, test_time)
        self.assertEqual('midnight', part_of_day)

    def test_part_of_day_0offset_local_time13(self):
        test_time = timegm(strptime('2015-04-01 13:05', '%Y-%m-%d %H:%M'))
        user_tz_offset = 0
        part_of_day = self.g.get_part_of_day(user_tz_offset, test_time)
        self.assertEqual('afternoon', part_of_day)

    def test_part_of_day_minus9offset_local_time5(self):
        test_time = timegm(strptime('2012-02-29 14:20', '%Y-%m-%d %H:%M'))
        user_tz_offset = -9
        part_of_day = self.g.get_part_of_day(user_tz_offset, test_time)
        self.assertEqual('dawn', part_of_day)

    def test_part_of_day_minus4offset_local_time22(self):
        test_time = timegm(strptime('2030-03-09 02:00', '%Y-%m-%d %H:%M'))
        user_tz_offset = -4
        part_of_day = self.g.get_part_of_day(user_tz_offset, test_time)
        self.assertEqual('night', part_of_day)

    def test_part_of_day_11offset_local_time5(self):
        # 2015-04-25 05:00:00 (+11)
        test_time = timegm(strptime('2015-04-24 18:00', '%Y-%m-%d %H:%M'))
        user_tz_offset = 11
        part_of_day = self.g.get_part_of_day(user_tz_offset, test_time)
        self.assertEqual('dawn', part_of_day)

    def test_choose_greeting_testuser_0_dawn(self):
        reply = 'Good early morning, TestUser.'
        self.assertEqual(reply, self.g.choose_greeting('TestUser', 0, 'dawn'))

    def test_choose_greeting_testuser_0_midnight(self):
        reply = 'Hi, TestUser.'
        self.assertEqual(reply, self.g.choose_greeting('TestUser', 0, 'midnight'))

    def test_choose_greeting_testuser_0_evening(self):
        reply = 'Good evening, TestUser123.'
        self.assertEqual(reply,
                self.g.choose_greeting('TestUser123', 0, 'evening'))

    def test_choose_greeting_testuser_1_afternoon(self):
        reply = 'Good afternoon, Level1User!'
        self.assertEqual(reply, 
                self.g.choose_greeting('Level1User', 1, 'afternoon'))

    def test_choose_greeting_testuser_2_dusk(self):
        reply = 'Good afternoon Level2User!!'
        self.assertEqual(reply,
                self.g.choose_greeting('Level2User', 2, 'dusk'))

    def test_choose_greeting_testuser_2_morning(self):
        reply = 'Good morning Level2User!!'
        self.assertEqual(reply,
                self.g.choose_greeting('Level2User', 2, 'morning'))

    def test_choose_greeting_testuser_0_noon(self):
        reply = 'Hi, TestUser.'
        self.assertEqual(reply, self.g.choose_greeting('TestUser', 0, 'noon'))

    def test_choose_greeting_testuser_1_noon(self):
        reply = 'Hi, TestUser!'
        self.assertEqual(reply, self.g.choose_greeting('TestUser', 1, 'noon'))

    def test_choose_greeting_testuser_2_noon(self):
        reply = 'Hi Level2User!!' # no comma
        self.assertEqual(reply, 
                self.g.choose_greeting('Level2User', 2, 'noon'))

if __name__ == '__main__':
    unittest.main()
