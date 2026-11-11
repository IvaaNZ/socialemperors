"""Duel challenges, force resolution, Elo and storage (duels.py), with a fake clock."""

import copy
import json
from pathlib import Path
import tempfile
import unittest

from duels import (ARMY_LIMIT, CHALLENGE_SECONDS, ELO_START, RATE_LIMIT, RATE_WINDOW, RECONNECT_GRACE,
                   DuelHub, DuelStore, army_profile, elo_update)

SPEARMAN, SWORDSMAN, COW = 509, 510, 504
BASE = json.loads(Path('villages/initial.json').read_text(encoding='utf-8'))


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class Page:
    """A fake browser page: records the messages the hub sends to it."""

    def __init__(self):
        self.messages = []

    def __call__(self, message):
        self.messages.append(message)

    def last(self, kind):
        return next((m for m in reversed(self.messages) if m['type'] == kind), None)


class HubTestCase(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.store = DuelStore(Path(directory.name) / 'duels.sqlite3')
        self.clock = Clock()
        self.profiles = {
            1: {'name': 'Ana', 'level': 30, 'power': 5000, 'troops': 10, 'tutorial_complete': True},
            2: {'name': 'Beto', 'level': 40, 'power': 3000, 'troops': 8, 'tutorial_complete': True},
            3: {'name': 'Caro', 'level': 26, 'power': 3000, 'troops': 8, 'tutorial_complete': True},
            4: {'name': 'Dani', 'level': 10, 'power': 9000, 'troops': 20, 'tutorial_complete': True},
        }
        self.hub = DuelHub(self.store, lambda account_id: copy.deepcopy(self.profiles.get(account_id)), self.clock)
        self.pages = {}
        self.connections = {}
        for account_id in self.profiles:
            self.online(account_id)

    def online(self, account_id):
        page = Page()
        self.pages[account_id] = page
        self.connections[account_id] = self.hub.connect(account_id, self.profiles[account_id]['name'], page)
        return page

    def offline(self, account_id):
        self.hub.disconnect(account_id, self.connections[account_id])

    def error(self, account_id):
        message = self.pages[account_id].last('error')
        return message and message['code']


class ChallengeRuleTests(HubTestCase):
    def test_challenge_reaches_the_other_player_at_once_and_can_be_declined(self):
        self.hub.handle(1, {'type': 'challenge', 'to': 2})
        received = self.pages[2].last('challenge_received')
        self.assertEqual((received['other']['name'], received['expires_in']), ('Ana', CHALLENGE_SECONDS))
        self.assertEqual(self.pages[1].last('challenge_sent')['other']['id'], 2)
        self.hub.handle(2, {'type': 'respond', 'id': received['id'], 'accept': False})
        closed = self.pages[1].last('challenge_closed')
        self.assertEqual((closed['reason'], closed['by']['name']), ('declined', 'Beto'))
        self.assertEqual(self.store.count(), 0)
        self.assertEqual(self.hub.challenges, {})

    def test_self_offline_and_one_challenge_at_a_time(self):
        self.hub.handle(1, {'type': 'challenge', 'to': 1})
        self.assertEqual(self.error(1), 'self')
        self.offline(3)
        self.hub.handle(1, {'type': 'challenge', 'to': 3})
        self.assertEqual(self.error(1), 'offline')
        self.hub.handle(1, {'type': 'challenge', 'to': 2})
        self.hub.handle(4, {'type': 'challenge', 'to': 2})
        self.assertEqual(self.error(4), 'target_busy')  # 2 cannot receive two challenges
        self.hub.handle(1, {'type': 'challenge', 'to': 4})
        self.assertEqual(self.error(1), 'busy')  # 1 already has one pending
        self.hub.handle(2, {'type': 'challenge', 'to': 4})
        self.assertEqual(self.error(2), 'busy')
        self.assertEqual(len(self.hub.challenges), 1)

    def test_challenge_expires_after_thirty_seconds(self):
        self.hub.handle(1, {'type': 'challenge', 'to': 2})
        challenge_id = self.pages[2].last('challenge_received')['id']
        self.clock.now += CHALLENGE_SECONDS - 1
        self.hub.sweep()
        self.assertIn(challenge_id, self.hub.challenges)
        self.clock.now += 1
        self.hub.sweep()
        self.assertEqual(self.pages[1].last('challenge_closed')['reason'], 'expired')
        self.assertEqual(self.pages[2].last('challenge_closed')['reason'], 'expired')
        self.hub.handle(2, {'type': 'respond', 'id': challenge_id, 'accept': True})
        self.assertEqual(self.error(2), 'gone')
        self.assertEqual(self.store.count(), 0)

    def test_disconnect_cancels_after_the_reload_grace(self):
        self.hub.handle(1, {'type': 'challenge', 'to': 2})
        self.offline(2)
        self.clock.now += RECONNECT_GRACE - 1
        self.hub.sweep()
        self.assertEqual(len(self.hub.challenges), 1)  # still within the grace
        self.clock.now += 1
        self.hub.sweep()
        closed = self.pages[1].last('challenge_closed')
        self.assertEqual((closed['reason'], closed['by']['id']), ('disconnected', 2))

    def test_reloaded_page_gets_its_pending_challenge_back(self):
        self.hub.handle(1, {'type': 'challenge', 'to': 2})
        self.offline(2)
        self.clock.now += RECONNECT_GRACE - 2
        page = self.online(2)  # the tab came back
        self.clock.now += 10
        self.hub.sweep()
        received = page.last('challenge_received')
        self.assertEqual(received['other']['id'], 1)
        self.assertEqual(received['expires_in'], CHALLENGE_SECONDS - (RECONNECT_GRACE - 2))
        self.assertEqual(len(self.hub.challenges), 1)

    def test_rate_limit_per_minute(self):
        for _ in range(RATE_LIMIT):
            self.hub.handle(1, {'type': 'challenge', 'to': 2})
            challenge_id = self.pages[1].last('challenge_sent')['id']
            self.hub.handle(1, {'type': 'cancel', 'id': challenge_id})
        self.hub.handle(1, {'type': 'challenge', 'to': 2})
        self.assertEqual(self.error(1), 'rate_limited')
        self.clock.now += RATE_WINDOW
        self.hub.handle(1, {'type': 'challenge', 'to': 2})
        self.assertIsNotNone(self.hub.challenges)
        self.assertEqual(len(self.hub.challenges), 1)

    def test_readiness_and_bad_messages(self):
        self.profiles[3]['tutorial_complete'] = False
        self.hub.handle(3, {'type': 'challenge', 'to': 1})
        self.assertEqual(self.error(3), 'tutorial')
        self.hub.handle(1, {'type': 'challenge', 'to': 3})
        self.assertEqual(self.error(1), 'target_not_ready')
        self.profiles[2]['troops'] = 0
        self.hub.handle(2, {'type': 'challenge', 'to': 1})
        self.assertEqual(self.error(2), 'no_troops')
        for message in ('text', {'type': 'dance'}, {'type': 'respond', 'id': 'x'}, None):
            self.hub.handle(1, message)
            self.assertIn(self.error(1), ('invalid', 'gone'))
        self.hub.handle(4, {'type': 'cancel', 'id': 999})
        self.assertEqual(self.error(4), 'gone')

    def test_only_the_challenged_player_can_answer(self):
        self.hub.handle(1, {'type': 'challenge', 'to': 2})
        challenge_id = self.pages[2].last('challenge_received')['id']
        self.hub.handle(1, {'type': 'respond', 'id': challenge_id, 'accept': True})
        self.assertEqual(self.error(1), 'gone')
        self.hub.handle(3, {'type': 'respond', 'id': challenge_id, 'accept': True})
        self.assertEqual(self.error(3), 'gone')
        self.assertEqual(self.store.count(), 0)


class ResolutionTests(HubTestCase):
    def accept(self, challenger, defender):
        self.hub.handle(challenger, {'type': 'challenge', 'to': defender})
        challenge_id = self.pages[defender].last('challenge_received')['id']
        self.hub.handle(defender, {'type': 'respond', 'id': challenge_id, 'accept': True})
        return self.pages[challenger].last('duel_result'), self.pages[defender].last('duel_result')

    def test_both_players_receive_the_same_result_and_ranked_elo(self):
        mine, theirs = self.accept(1, 2)
        self.assertEqual(mine, theirs)
        self.assertEqual((mine['winner'], mine['ranked']), ('challenger', True))
        self.assertEqual(mine['challenger']['rating_before'], ELO_START)
        self.assertEqual(mine['challenger']['rating_after'], ELO_START + 16)
        self.assertEqual(mine['defender']['rating_after'], ELO_START - 16)
        self.assertEqual(self.store.rating(1), ELO_START + 16)
        ranking = self.store.ranking()
        self.assertEqual([(row['account_id'], row['wins'], row['losses']) for row in ranking], [(1, 1, 0), (2, 0, 1)])
        self.assertEqual(len(self.store.history(1)), 1)
        self.assertEqual(self.hub.challenges, {})

    def test_draw_and_friendly_duels_below_level_25(self):
        mine, _ = self.accept(2, 3)  # equal power
        self.assertEqual(mine['winner'], 'draw')
        self.assertEqual(mine['challenger']['rating_after'], ELO_START)
        mine, _ = self.accept(4, 1)  # player 4 is level 10
        self.assertEqual((mine['winner'], mine['ranked']), ('challenger', False))
        self.assertIsNone(mine['challenger']['rating_after'])
        self.assertEqual(self.store.rating(4), ELO_START)
        self.assertEqual(self.store.count(), 2)

    def test_elo_rewards_beating_a_stronger_rating(self):
        self.assertEqual(elo_update(1000, 1000, 1), (1016, 984))
        up, down = elo_update(1000, 1400, 1)
        self.assertGreater(up - 1000, 16)
        self.assertEqual(up + down, 2400)
        self.assertEqual(elo_update(1200, 1000, 0.5)[0] < 1200, True)


class DuelTextTests(unittest.TestCase):
    def test_every_duel_script_text_is_translated(self):
        import re
        source = Path('duels_web.py').read_text(encoding='utf-8')
        texts = re.findall(r"_\('((?:[^'\\]|\\.)*)'", source)
        self.assertGreater(len(texts), 25)
        for language in ('es', 'en'):
            catalog = json.loads(Path(f'config/locales/{language}-portal.json').read_text(encoding='utf-8'))
            with self.subTest(language=language):
                self.assertEqual([text for text in texts if text not in catalog], [])


class ArmyProfileTests(unittest.TestCase):
    def village(self, units):
        save = copy.deepcopy(BASE)
        save['playerInfo']['completed_tutorial'] = 1
        save['maps'][0]['race'] = 'h'
        save['maps'][0]['items'] = [[unit, 10, 10, 0, 0, 0] for unit in units]
        return save

    def test_counts_only_the_strongest_troops_up_to_the_limit(self):
        save = self.village([SPEARMAN] * (ARMY_LIMIT + 5) + [SWORDSMAN] * 3 + [COW] * 4)
        before = copy.deepcopy(save)
        profile = army_profile(save)
        self.assertEqual(profile['troops'], ARMY_LIMIT)
        self.assertEqual(profile['power'], 3 * 170 + (ARMY_LIMIT - 3) * 125)  # swordsmen first, cows never
        self.assertTrue(profile['tutorial_complete'])
        self.assertEqual(save, before)  # a duel never changes the village

    def test_sheltered_troops_count(self):
        save = self.village([])
        save['maps'][0]['items'] = [[30, 5, 5, 0, 0, 0, [SPEARMAN, SPEARMAN]]]
        self.assertEqual(army_profile(save)['troops'], 2)


if __name__ == '__main__':
    unittest.main()
