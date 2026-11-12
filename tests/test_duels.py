"""Duel challenges, arena battles, Elo, review and storage (duels.py), with a fake clock."""

import copy
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import duels
from duels import (ARENA_MAP_ID, ARMY_LIMIT, CHALLENGE_SECONDS, ELO_START, RATE_LIMIT,
                   RATE_WINDOW, RECONNECT_GRACE, DuelError, DuelHub, DuelStore, army_profile, decide, elo_update,
                   parse_percent)

SPEARMAN, SWORDSMAN, COW = 509, 510, 504
BASE = json.loads(Path('villages/initial.json').read_text(encoding='utf-8'))
MIN = duels.BATTLE_MIN_SECONDS
DEADLINE = duels.BATTLE_DEADLINE_SECONDS


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
            1: {'name': 'Ana', 'level': 30, 'power': 5000, 'troops': 3, 'units': [510, 510, 509], 'tutorial_complete': True},
            2: {'name': 'Beto', 'level': 40, 'power': 3000, 'troops': 2, 'units': [510, 509], 'tutorial_complete': True},
            3: {'name': 'Caro', 'level': 26, 'power': 3000, 'troops': 2, 'units': [509, 509], 'tutorial_complete': True},
            4: {'name': 'Dani', 'level': 10, 'power': 9000, 'troops': 4, 'units': [510] * 4, 'tutorial_complete': True},
            5: {'name': 'Eva', 'level': 50, 'power': 900, 'troops': 1, 'units': [509], 'tutorial_complete': True},
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


class BattleTests(HubTestCase):
    def accept(self, challenger, defender):
        self.hub.handle(challenger, {'type': 'challenge', 'to': defender})
        challenge_id = self.pages[defender].last('challenge_received')['id']
        self.hub.handle(defender, {'type': 'respond', 'id': challenge_id, 'accept': True})
        return self.pages[challenger].last('duel_start'), self.pages[defender].last('duel_start')

    def play(self, account_id, percent, seconds):
        self.hub.start_match(account_id)
        self.clock.now += seconds
        self.hub.report(account_id, percent)

    def results(self, *account_ids):
        return [self.pages[account_id].last('duel_result') for account_id in account_ids]

    def test_accepting_sends_both_players_into_the_arena_with_both_armies(self):
        mine, theirs = self.accept(1, 2)
        self.assertEqual((mine['side'], theirs['side']), ('challenger', 'defender'))
        self.assertEqual((mine['army'], mine['enemy_army']), ([510, 510, 509], [510, 509]))
        self.assertEqual((theirs['army'], theirs['enemy_army']), ([510, 509], [510, 510, 509]))
        self.assertEqual((mine['arena'], mine['seconds_left'], mine['other']['name']), (ARENA_MAP_ID, DEADLINE, 'Beto'))
        self.assertEqual(mine['id'], theirs['id'])
        self.assertEqual(self.store.get(mine['id'])['status'], 'playing')
        online = self.pages[3].last('presence')['online']
        self.assertTrue(all(player['busy'] for player in online if player['id'] in (1, 2)))
        self.hub.handle(3, {'type': 'challenge', 'to': 1})
        self.assertEqual(self.error(3), 'target_busy')  # in a battle: cannot be challenged
        self.hub.handle(1, {'type': 'challenge', 'to': 3})
        self.assertEqual(self.error(1), 'busy')

    def test_higher_percentage_wins_and_both_get_the_same_result(self):
        self.accept(1, 2)
        self.hub.start_match(2)
        self.play(1, '40.5', MIN + 5)
        waiting = self.pages[1].last('duel_waiting')
        self.assertEqual((waiting['other']['name'], waiting['seconds_left']), ('Beto', round(DEADLINE - MIN - 5)))
        self.assertIsNone(self.pages[1].last('duel_result'))
        self.clock.now += 10
        self.hub.report(2, 75)
        mine, theirs = self.results(1, 2)
        self.assertEqual(mine, theirs)
        self.assertEqual((mine['winner'], mine['status'], mine['rated']), ('defender', 'done', True))
        self.assertEqual((mine['challenger']['percent'], mine['defender']['percent']), (40.5, 75))
        self.assertEqual((mine['challenger']['seconds'], mine['defender']['seconds']), (MIN + 5, MIN + 15))
        self.assertEqual(mine['defender']['rating_after'], ELO_START + 16)
        self.assertEqual(self.store.rating(2), ELO_START + 16)
        self.assertEqual(self.hub.battles, {})

    def test_equal_percentage_the_faster_battle_wins(self):
        self.accept(1, 2)
        self.hub.start_match(1)
        self.hub.start_match(2)
        self.clock.now += MIN + 30
        self.hub.report(2, 100)  # defender: 100 % in MIN + 30 s
        self.clock.now += 5
        self.hub.report(1, 100)  # challenger: 100 % in MIN + 35 s
        self.assertEqual(self.results(1)[0]['winner'], 'defender')

    def test_draw_when_percentage_and_time_are_equal(self):
        self.accept(2, 3)
        self.hub.start_match(2)
        self.hub.start_match(3)
        self.clock.now += MIN + 1
        self.hub.report(2, 60)
        self.hub.report(3, 60)
        result = self.results(2)[0]
        self.assertEqual((result['winner'], result['status']), ('draw', 'done'))
        self.assertEqual(result['challenger']['rating_after'], ELO_START)

    def test_short_battles_bad_values_and_repeated_reports_are_rejected(self):
        for value in ('-1', 101, 'abc', None, float('nan'), True, '1e400', [50]):
            self.assertIsNone(parse_percent(value), value)
        self.assertEqual(parse_percent('99.5'), 99.5)
        self.accept(1, 2)
        self.play(1, 100, MIN - 1)  # too fast
        with self.assertRaises(DuelError) as raised:
            self.hub.report(1, 50)
        self.assertEqual(raised.exception.code, 'already_reported')
        with self.assertRaises(DuelError):
            self.hub.start_match(1)
        self.hub.report(2, 30)  # never started its battle
        result = self.results(1)[0]
        self.assertEqual((result['challenger']['report'], result['defender']['report']), ('too_fast', 'not_started'))
        self.assertEqual((result['status'], result['winner'], result['rated']), ('void', None, False))
        self.assertEqual(self.store.rating(1), ELO_START)

    def test_invalid_percentage_counts_as_no_report(self):
        self.accept(1, 2)
        self.play(1, '250', MIN + 1)
        self.play(2, 10, MIN + 1)
        result = self.results(1)[0]
        self.assertEqual((result['challenger']['report'], result['winner']), ('invalid', 'defender'))

    def test_one_player_does_not_report_in_time_and_loses(self):
        start, _ = self.accept(1, 2)
        self.hub.start_match(2)
        self.play(1, 5, MIN + 1)
        self.clock.now = self.store.get(start['id'])['created_at'] + DEADLINE - 1
        self.hub.sweep()
        self.assertIn(start['id'], self.hub.battles)  # still within the deadline
        self.clock.now += 1
        self.hub.sweep()
        result = self.results(2)[0]
        self.assertEqual((result['winner'], result['defender']['report'], result['status']), ('challenger', 'missing', 'done'))
        self.assertEqual(self.store.rating(1), ELO_START + 16)

    def test_nobody_reports_and_the_duel_is_void(self):
        start, _ = self.accept(1, 2)
        self.clock.now += DEADLINE
        self.hub.sweep()
        mine, theirs = self.results(1, 2)
        self.assertEqual(mine, theirs)
        self.assertEqual((mine['status'], mine['winner'], mine['review_reason']), ('void', None, 'no_reports'))
        self.assertEqual(self.store.get(start['id'])['status'], 'void')
        self.assertEqual(self.store.ranking(), [])

    def test_unlikely_result_goes_to_review_and_the_admin_validates_it(self):
        # Eva (power 900) beats Ana (5000): 900 < 5000 / 3, so it does not count yet.
        start, _ = self.accept(5, 1)
        self.play(5, 100, MIN + 1)
        self.play(1, 20, MIN + 1)
        result = self.results(5)[0]
        self.assertEqual((result['winner'], result['status'], result['rated'], result['review_reason']),
                         ('challenger', 'review', False, 'power'))
        self.assertEqual(self.store.rating(5), ELO_START)
        pending, resolved = self.store.reviews()
        self.assertEqual(([row['id'] for row in pending], resolved), ([start['id']], []))
        duel = self.store.resolve(start['id'], 'validate', 'Admin', self.clock())
        self.assertEqual((duel['status'], duel['rated'], duel['resolved_by']), ('done', 1, 'Admin'))
        self.assertEqual(self.store.rating(5), ELO_START + 16)
        with self.assertRaises(DuelError):
            self.store.resolve(start['id'], 'void', 'Admin', self.clock())  # already resolved
        self.assertEqual([row['id'] for row in self.store.reviews()[1]], [start['id']])
        self.assertEqual(self.hub.result_message(duel)['status'], 'done')

    def test_admin_can_void_a_reviewed_duel(self):
        start, _ = self.accept(5, 1)
        self.play(5, 100, MIN + 1)
        self.play(1, 20, MIN + 1)
        with self.assertRaises(DuelError):
            self.store.resolve(start['id'], 'dance', 'Admin', self.clock())
        duel = self.store.resolve(start['id'], 'void', 'Admin', self.clock())
        self.assertEqual((duel['status'], duel['rated']), ('void', 0))
        self.assertEqual(self.store.ranking(), [])

    def test_friendly_duels_below_level_25_never_change_ratings(self):
        self.accept(4, 1)  # Dani is level 10
        self.play(4, 90, MIN + 1)
        self.play(1, 10, MIN + 1)
        result = self.results(4)[0]
        self.assertEqual((result['winner'], result['ranked'], result['rated']), ('challenger', False, False))
        self.assertEqual(self.store.rating(4), ELO_START)

    def test_reloaded_page_gets_the_arena_or_the_wait_back(self):
        self.accept(1, 2)
        self.offline(1)
        page = self.online(1)
        self.assertEqual(page.last('duel_start')['army'], [510, 510, 509])
        self.play(1, 50, MIN + 1)
        page = self.online(1)
        self.assertIsNone(page.last('duel_start'))
        self.assertEqual(page.last('duel_waiting')['other']['id'], 2)

    def test_a_page_that_missed_the_result_gets_it_until_it_confirms(self):
        start, _ = self.accept(1, 2)
        self.offline(1)  # the tab was frozen and its socket closed
        self.play(2, 40, MIN + 1)
        self.clock.now += DEADLINE
        self.hub.sweep()
        page = self.online(1)
        self.assertEqual(page.last('duel_result')['id'], start['id'])
        self.hub.handle(1, {'type': 'seen', 'id': start['id']})
        self.assertIsNone(self.online(1).last('duel_result'))
        self.assertEqual(self.online(2).last('duel_result')['id'], start['id'])  # 2 has not confirmed yet

    def test_arena_commands_are_guarded_only_during_the_battle(self):
        self.accept(1, 2)
        self.assertFalse(self.hub.guards_commands(1))  # before pressing start: village commands go through
        self.hub.start_match(1)
        self.hub.start_match(2)
        self.assertTrue(self.hub.guards_commands(1))
        self.clock.now += MIN + 1
        self.hub.report(1, 50)
        self.assertFalse(self.hub.guards_commands(1))  # reported: back in the village
        self.assertTrue(self.hub.guards_commands(2))
        self.clock.now += DEADLINE
        self.hub.sweep()  # deadline: player 2 loses and is out of the arena
        self.assertFalse(self.hub.guards_commands(2))

    def test_only_unit_death_commands_are_dropped(self):
        from duels_web import is_unit_death
        self.assertTrue(is_unit_death({'cmd': 'kill', 'args': [1, 2, 509, 0, 'u']}))
        self.assertTrue(is_unit_death({'cmd': 'sell', 'args': [65, 92, 896, 0, 1, 'KILL', 1]}))
        self.assertFalse(is_unit_death({'cmd': 'sell', 'args': [37, 16, 305, 0, 1, 'CLEAN_0']}))
        self.assertFalse(is_unit_death({'cmd': 'buy', 'args': [509, 1, 1, 0, 0, 1, 1, 'u']}))
        self.assertFalse(is_unit_death({'cmd': 'sell', 'args': 'x'}))

    def test_battles_cut_by_a_restart_are_void(self):
        start, _ = self.accept(1, 2)
        DuelHub(self.store, lambda account_id: None, self.clock)  # a new server process
        duel = self.store.get(start['id'])
        self.assertEqual((duel['status'], duel['review_reason']), ('void', 'restart'))

    def test_decide_rules(self):
        def ok(percent, seconds):
            return {'status': 'ok', 'percent': percent, 'seconds': seconds}
        missing = {'status': 'missing', 'percent': None, 'seconds': None}
        even = {'challenger': 1000, 'defender': 1000}
        self.assertEqual(decide({'challenger': ok(50, 30), 'defender': ok(49.99, 20)}, even), ('challenger', 'done', None))
        self.assertEqual(decide({'challenger': missing, 'defender': ok(0, 30)}, even), ('defender', 'done', None))
        self.assertEqual(decide({'challenger': missing, 'defender': missing}, even), (None, 'void', 'no_reports'))
        weak = {'challenger': 333, 'defender': 1000}
        self.assertEqual(decide({'challenger': ok(90, 30), 'defender': ok(10, 30)}, weak), ('challenger', 'review', 'power'))
        self.assertEqual(decide({'challenger': ok(90, 30), 'defender': ok(10, 30)}, weak, ratio=0.3), ('challenger', 'done', None))
        self.assertEqual(decide({'challenger': ok(10, 30), 'defender': ok(90, 30)}, weak), ('defender', 'done', None))

    def test_elo_rewards_beating_a_stronger_rating(self):
        self.assertEqual(elo_update(1000, 1000, 1), (1016, 984))
        up, down = elo_update(1000, 1400, 1)
        self.assertGreater(up - 1000, 16)
        self.assertEqual(up + down, 2400)
        self.assertEqual(elo_update(1200, 1000, 0.5)[0] < 1200, True)


class SettingsTests(unittest.TestCase):
    def test_battle_settings_come_from_the_environment_with_safe_defaults(self):
        with patch.dict('os.environ', {'SE_DUEL_MIN_SECONDS': '45'}):
            self.assertEqual(duels._setting('SE_DUEL_MIN_SECONDS', 20), 45)
        for bad in ('', 'abc', '-5', '0', 'nan', 'inf'):
            with patch.dict('os.environ', {'SE_DUEL_MIN_SECONDS': bad}), self.subTest(value=bad):
                self.assertEqual(duels._setting('SE_DUEL_MIN_SECONDS', 20), 20)
        self.assertEqual((duels.BATTLE_MIN_SECONDS, duels.BATTLE_DEADLINE_SECONDS), (20, 600))
        self.assertAlmostEqual(duels.SUSPICIOUS_POWER_RATIO, 1 / 3)


class MigrationTests(unittest.TestCase):
    def test_phase_one_duels_are_kept_as_finished_duels(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / 'duels.sqlite3'
        connection = sqlite3.connect(path)
        connection.executescript(
            "CREATE TABLE duels (id INTEGER PRIMARY KEY AUTOINCREMENT, challenger_id INTEGER NOT NULL,"
            " defender_id INTEGER NOT NULL, challenger_power INTEGER NOT NULL, defender_power INTEGER NOT NULL,"
            " winner TEXT NOT NULL, ranked INTEGER NOT NULL, challenger_rating_before INTEGER,"
            " challenger_rating_after INTEGER, defender_rating_before INTEGER, defender_rating_after INTEGER,"
            " created_at REAL NOT NULL);"
            "CREATE INDEX duels_challenger ON duels (challenger_id, created_at);"
            "CREATE INDEX duels_defender ON duels (defender_id, created_at);"
            "INSERT INTO duels VALUES (1, 7, 8, 500, 300, 'challenger', 1, 1000, 1016, 1000, 984, 50.0);")
        connection.commit()
        connection.close()
        store = DuelStore(path)
        duel = store.get(1)
        self.assertEqual((duel['status'], duel['winner'], duel['rated'], duel['challenger_rating_after']),
                         ('done', 'challenger', 1, 1016))
        self.assertEqual(len(store.history(7)), 1)
        self.assertEqual(store.create(7, 8, 1, 1, False, 60.0), 2)
        DuelStore(path)  # opening it again changes nothing
        self.assertEqual(store.count(), 2)


class ArenaConfigTests(unittest.TestCase):
    def test_the_arena_tournament_is_served_in_weekly_mode_without_touching_the_config(self):
        from duels_web import with_duel_tournament
        from get_game_config import get_game_config
        config = get_game_config('es')
        before = json.dumps(config['tournament_type'], sort_keys=True)
        served = with_duel_tournament(config)
        arena = served['tournament_type'][str(duels.ARENA_TOURNAMENT_TYPE)]
        self.assertEqual((arena['weekly_tournaments'], arena['map_id']), (1, ARENA_MAP_ID))
        self.assertEqual(config['tournament_type']['1']['weekly_tournaments'], 0)  # the real config stays as it was
        self.assertEqual(json.dumps(config['tournament_type'], sort_keys=True), before)
        self.assertIs(served['items'], config['items'])  # a light copy: only the tournament types change
        self.assertEqual(served['tournament_type']['2'], config['tournament_type']['2'])
        self.assertEqual(with_duel_tournament({'other': 1}), {'other': 1})


class DuelTextTests(unittest.TestCase):
    def test_every_duel_text_is_translated(self):
        import re
        pattern = re.compile(r"_\('((?:[^'\\]|\\.)*)'")
        texts = []
        for name in ('duels_web.py', 'templates/duels.html', 'templates/admin_duels.html'):
            texts += pattern.findall(Path(name).read_text(encoding='utf-8'))
        texts += re.findall(r"flash\('((?:[^'\\]|\\.)*)'", Path('duels_web.py').read_text(encoding='utf-8'))
        self.assertGreater(len(texts), 60)
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
        self.assertEqual(ARMY_LIMIT, 20)  # the game's tournament arena places at most 20 per side
        self.assertEqual(profile['troops'], ARMY_LIMIT)
        self.assertEqual(profile['power'], 3 * 170 + (ARMY_LIMIT - 3) * 125)  # swordsmen first, cows never
        self.assertEqual(profile['units'], [SWORDSMAN] * 3 + [SPEARMAN] * (ARMY_LIMIT - 3))
        self.assertTrue(profile['tutorial_complete'])
        self.assertEqual(save, before)  # a duel never changes the village

    def test_sheltered_troops_count(self):
        save = self.village([])
        save['maps'][0]['items'] = [[30, 5, 5, 0, 0, 0, [SPEARMAN, SPEARMAN]]]
        self.assertEqual(army_profile(save)['troops'], 2)

    def test_units_not_allowed_in_tournaments_stay_out(self):
        save = self.village([SPEARMAN, SWORDSMAN])
        with patch('duels._not_allowed_units', return_value={SWORDSMAN}):
            self.assertEqual(army_profile(save)['units'], [SPEARMAN])
        self.assertIn(569, duels._not_allowed_units())  # read from the game config


if __name__ == '__main__':
    unittest.main()
