import datetime
import unittest

from seasons import AUTUMN, SPRING, SUMMER, WINTER, apply_season, season_of


def village():
    return {'privateState': {'unlockedSkins': {}}, 'maps': [{'skin': 0}, {'skin': 0}]}


class SeasonDates(unittest.TestCase):
    def test_argentinas_seasons_and_their_edges(self):
        cases = {(1, 10): (SUMMER, '2025-summer'), (3, 20): (SUMMER, '2025-summer'), (3, 21): (AUTUMN, '2026-autumn'),
                 (6, 20): (AUTUMN, '2026-autumn'), (6, 21): (WINTER, '2026-winter'), (9, 22): (WINTER, '2026-winter'),
                 (9, 23): (SPRING, '2026-spring'), (12, 20): (SPRING, '2026-spring'), (12, 21): (SUMMER, '2026-summer')}
        for (month, day), expected in cases.items():
            with self.subTest(month=month, day=day):
                self.assertEqual(season_of(datetime.date(2026, month, day)), expected)


class ApplySeason(unittest.TestCase):
    def test_a_new_season_sets_every_island_once_and_its_weather_is_free(self):
        save = village()
        self.assertEqual(apply_season(save, datetime.date(2026, 7, 1)), WINTER)
        self.assertEqual([town['skin'] for town in save['maps']], [2, 2])
        self.assertEqual(save['privateState']['unlockedSkins'], {'2': 'true'})
        save['maps'][0]['skin'] = 0  # the player picks another weather: it stays during the season
        self.assertIsNone(apply_season(save, datetime.date(2026, 8, 1)))
        self.assertEqual(save['maps'][0]['skin'], 0)

    def test_the_free_weather_goes_back_unless_it_was_bought(self):
        save = village()
        save['privateState']['unlockedSkins'] = {'1': 'true'}  # the desert was bought
        apply_season(save, datetime.date(2026, 7, 1))   # winter: snow for free
        apply_season(save, datetime.date(2026, 10, 1))  # spring: meadows, snow goes back
        self.assertEqual(save['privateState']['unlockedSkins'], {'1': 'true'})
        self.assertEqual(save['maps'][1]['skin'], 0)
        apply_season(save, datetime.date(2027, 1, 1))   # summer: the bought desert stays bought
        apply_season(save, datetime.date(2027, 4, 1))   # autumn
        self.assertEqual(save['privateState']['unlockedSkins'], {'1': 'true', '4': 'true'})
        self.assertEqual(save['maps'][0]['skin'], 4)
