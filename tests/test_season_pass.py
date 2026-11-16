import datetime
import os
import unittest
from unittest.mock import patch

import season_pass as sp

AR = sp.ARGENTINA


def moment(year, month, day, hour=12):
    return datetime.datetime(year, month, day, hour, tzinfo=AR)


def village():
    return {'playerInfo': {'cash': 10}, 'maps': [{'coins': 100, 'wood': 0, 'food': 0, 'stone': 0}],
            'privateState': {'gifts': []}}


class SeasonPassTests(unittest.TestCase):
    def test_a_season_is_one_of_argentinas_and_its_bounds_are_known(self):
        season, key, first, last = sp.season_bounds(datetime.date(2026, 7, 10))
        self.assertEqual((season, key, first, last), ('winter', '2026-winter', datetime.date(2026, 6, 21),
                                                      datetime.date(2026, 9, 22)))
        self.assertEqual(sp.season_bounds(datetime.date(2027, 2, 1))[1:], (
            '2026-summer', datetime.date(2026, 12, 21), datetime.date(2027, 3, 20)))

    def test_playing_gives_points_up_to_the_daily_cap_and_challenges_on_top(self):
        save = village()
        now = moment(2026, 7, 10)
        pas = sp.SeasonPass(save, now)
        quest = next((c for c in pas.daily if c['event'] == 'quest_win'), None)
        won = pas.record('quest_win', stars=3)  # 25 + 2 * 10
        expected = 45 + (quest['points'] if quest and quest['target'] == 1 else 0)
        self.assertEqual(won, expected)
        for _ in range(500):
            pas.record('collect')
        self.assertEqual(save['privateState']['seasonPass']['play_today'], sp.PLAY_POINTS_PER_DAY)  # capped
        self.assertEqual(sp.SeasonPass(save, now).record('nada'), 0)
        # the next day the cap starts again and the daily challenges change for everybody alike
        tomorrow = sp.SeasonPass(save, moment(2026, 7, 11))
        self.assertEqual(save['privateState']['seasonPass']['play_today'], 0)
        self.assertEqual([c['id'] for c in tomorrow.daily],
                         [c['id'] for c in sp.challenges_of('daily', '2026-07-11', '2026-winter')])
        self.assertEqual(len(tomorrow.daily), sp.DAILY_COUNT)
        self.assertEqual(len(tomorrow.weekly), sp.WEEKLY_COUNT)

    def test_a_challenge_is_paid_once(self):
        save = village()
        pas = sp.SeasonPass(save, moment(2026, 7, 10))
        challenge = pas.daily[0]
        before = pas.points
        for _ in range(challenge['target'] * 3):
            pas.record(challenge['event'])
        self.assertIn(challenge['id'], save['privateState']['seasonPass']['daily_done'])
        view = pas.view()
        done = next(c for c in view['daily'] if c['id'] == challenge['id'])
        self.assertEqual((done['progress'], done['done']), (challenge['target'], True))
        self.assertGreaterEqual(pas.points - before, challenge['points'])

    def test_rewards_resources_cash_and_the_seasons_units(self):
        self.assertEqual(sp.reward_of('winter', 1), {'resource': 'coins', 'amount': 1250})
        self.assertEqual(sp.reward_of('winter', 2)['resource'], 'wood')
        self.assertEqual(sp.reward_of('winter', 5), {'cash': 5})
        self.assertEqual(sp.reward_of('winter', 35), {'cash': 10})
        self.assertEqual(sp.reward_of('winter', 10), {'unit': 666})
        self.assertEqual(sp.reward_of('summer', 40), {'unit': 2178})
        with self.assertRaises(ValueError):
            sp.reward_of('winter', 41)

    def test_reached_levels_are_claimed_once_and_change_the_revision(self):
        save = village()
        now = moment(2026, 7, 10)
        pas = sp.SeasonPass(save, now)
        save['privateState']['seasonPass']['points'] = 10 * sp.POINTS_PER_LEVEL + 50
        self.assertEqual(sp.SeasonPass(save, now).level, 10)
        self.assertEqual(sp.revision(save), '')
        given = sp.SeasonPass(save, now).claim([1, 5, 11])  # 11 is not reached
        self.assertEqual([level for level, _ in given], [1, 5])
        self.assertEqual(save['maps'][0]['coins'], 100 + 1250)
        self.assertEqual(save['playerInfo']['cash'], 15)
        self.assertEqual(sp.revision(save), 'sp1')
        rest = sp.SeasonPass(save, now).claim()
        self.assertEqual(len(rest), 8)
        self.assertEqual(save['privateState']['gifts'][666], 1)  # the level 10 unit, to the gifts
        self.assertEqual(sp.SeasonPass(save, now).claim(), [])  # nothing twice
        self.assertEqual(sp.revision(save), 'sp2')
        view = sp.SeasonPass(save, now).view()
        self.assertTrue(all(r['claimed'] for r in view['rewards'][:10]))
        self.assertEqual((view['level'], view['level_points'], view['name']), (10, 50, 'Inverno'))

    def test_a_new_season_starts_from_zero(self):
        save = village()
        save_pass = sp.SeasonPass(save, moment(2026, 9, 22))
        save['privateState']['seasonPass']['points'] = 5000
        save_pass.claim()
        spring = sp.SeasonPass(save, moment(2026, 9, 23))
        self.assertEqual((spring.key, spring.points, spring.data['claimed']), ('2026-spring', 0, []))
        self.assertEqual(sp.revision(save), 'sp1')  # the revision keeps counting: the page still sees changes

    def test_a_raid_or_duel_reported_twice_counts_once(self):
        save = village()
        pas = sp.SeasonPass(save, moment(2026, 7, 10))
        self.assertGreater(pas.record('raid_win', once='r1'), 0)
        self.assertEqual(pas.record('raid_win', once='r1'), 0)
        self.assertGreater(pas.record('duel_play', once='r1'), 0)  # another kind of event

    def test_the_hook_does_nothing_with_the_pass_off(self):
        save = village()
        with patch.dict(os.environ, {'SE_SEASON_PASS': 'off'}):
            self.assertEqual(sp.record_event(save, 'collect'), 0)
            self.assertNotIn('seasonPass', save['privateState'])
        with patch.dict(os.environ, {'SE_SEASON_PASS': 'on'}):
            self.assertGreater(sp.record_event(save, 'collect', now=moment(2026, 7, 10)), 0)


if __name__ == '__main__':
    unittest.main()
