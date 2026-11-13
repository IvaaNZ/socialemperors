"""SE_PVP=on: raids and duels fight with the team chosen in the game; the PvP button and team bridge in the movie."""

import contextlib
import copy
import io
import json
import os
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

import command
import duels
import pvp
from pvp import TEAM_LIMIT, RaidError, parse_team, pick_army
from swf_abc import AbcError, disassemble
from swf_pvp import (ACCEPTED_METHOD, CLOSED_METHOD, OPEN_CALLBACK, REGISTER_METHOD, SELECT_CALLBACK, SELECT_METHOD,
                     SELECTED_CALL, add_pvp, add_pvp_to_abc)
import test_duels
import test_pvp
from test_swf_duel_bridge import abc_of

ROOT = Path(__file__).resolve().parent.parent
PVP_ON = {'SE_PVP': 'on'}
PVP_OFF = {'SE_PVP': 'off'}


class PickArmyTests(unittest.TestCase):
    def test_no_team_takes_the_strongest_and_a_team_only_what_the_village_has(self):
        strength = {1: 10, 2: 30, 3: 20}.get
        self.assertEqual(pick_army([1, 2, 3, 3], None, strength, limit=3), [2, 3, 3])
        self.assertEqual(pick_army([1, 2, 3, 3], [3, 3, 3, 1, 9], strength), [3, 3, 1])  # two 3s, no 9
        self.assertEqual(pick_army([1] * 30, [1] * 30, strength), [1] * TEAM_LIMIT)
        self.assertEqual(pick_army([1, 2], [], strength), [])

    def test_a_team_from_a_page_is_a_short_list_of_ids(self):
        self.assertIsNone(parse_team(None))
        self.assertEqual(parse_team([5, 0, 7, 0]), [5, 7])  # empty slots of the game window dropped
        for wrong in ('5', [True], [-1], [1.5], [1] * (TEAM_LIMIT + 1), {'a': 1}):
            with self.assertRaises(ValueError):
                parse_team(wrong)

    def test_the_game_remembers_the_team_only_with_pvp_on(self):
        self.assertEqual(command.attack_team(['tournament', '[2016,0,847]']), [2016, 0, 847])
        for wrong in (['quest', '[1]'], ['tournament', 'x'], ['tournament', '[true]'], ['tournament', json.dumps([1] * 21)]):
            self.assertIsNone(command.attack_team(wrong))
        with patch.dict(os.environ, PVP_OFF):
            self.assertFalse(command.pvp_teams_enabled())
        with patch.dict(os.environ, PVP_ON):
            self.assertTrue(command.pvp_teams_enabled())


class RaidTeamTests(test_pvp.RaidServiceTests):
    """The raid rules of test_pvp, with the attack made of the chosen team."""

    def test_with_pvp_off_the_team_is_ignored(self):
        with patch.dict(os.environ, PVP_OFF):
            result = self.service.raid('alice', 'bob', self.eligible, 'b' * 32, self.now, team=[512])
        self.assertTrue(result['won'])  # the whole army of five attacked
        self.assertNotIn('attacker_troops', result)

    def test_with_pvp_on_only_the_chosen_troops_attack(self):
        with patch.dict(os.environ, PVP_ON):
            result = self.service.raid('alice', 'bob', self.eligible, 'c' * 32, self.now, team=[512])
        self.assertFalse(result['won'])  # one against one: the defense wins a tie
        self.assertEqual((result['attacker_troops'], result['attacker_power']), (1, result['defender_power']))

    def test_with_pvp_on_and_no_team_the_strongest_troops_attack(self):
        self.saves['alice']['maps'][0]['items'] = [[512, index, 0, 0, 0, 0] for index in range(TEAM_LIMIT + 5)]
        with patch.dict(os.environ, PVP_ON):
            overview = self.overview()
            result = self.service.raid('alice', 'bob', self.eligible, 'd' * 32, self.now)
        self.assertEqual(overview['own']['troop_count'], TEAM_LIMIT)
        self.assertEqual(result['attacker_troops'], TEAM_LIMIT)

    def test_a_team_the_village_does_not_have_cannot_attack(self):
        with patch.dict(os.environ, PVP_ON), self.assertRaises(RaidError):
            self.service.raid('alice', 'bob', self.eligible, 'e' * 32, self.now, team=[999])


class DuelTeamTests(test_duels.HubTestCase):
    def setUp(self):
        super().setUp()
        self.asked = []

        def profile(account_id, team=None):
            self.asked.append((account_id, team))
            chosen = copy.deepcopy(self.profiles.get(account_id))
            if chosen and team is not None:
                chosen.update(units=list(team), troops=len(team), power=100 * len(team))
            return chosen
        self.hub.profile = profile

    def test_both_armies_are_the_teams_chosen_in_the_game(self):
        with patch.dict(os.environ, PVP_ON):
            self.hub.handle(1, {'type': 'challenge', 'to': 2, 'army': [510, 0, 509]})
            received = self.pages[2].last('challenge_received')
            self.assertEqual(received['expires_in'], duels.CHALLENGE_SECONDS_WITH_TEAM)  # time to choose a team
            self.hub.handle(2, {'type': 'respond', 'id': received['id'], 'accept': True, 'army': [509]})
        battle = next(iter(self.hub.battles.values()))
        self.assertEqual(battle['profiles']['challenger']['units'], [510, 509])
        self.assertEqual(battle['profiles']['defender']['units'], [509])
        row = self.store.get(battle['id'])
        self.assertEqual((row['challenger_power'], row['defender_power']), (200, 100))

    def test_with_pvp_off_a_team_is_ignored(self):
        with patch.dict(os.environ, PVP_OFF):
            self.hub.handle(1, {'type': 'challenge', 'to': 2, 'army': [510]})
            received = self.pages[2].last('challenge_received')
            self.assertEqual(received['expires_in'], duels.CHALLENGE_SECONDS)
            self.hub.handle(2, {'type': 'respond', 'id': received['id'], 'accept': True, 'army': [509]})
        battle = next(iter(self.hub.battles.values()))
        self.assertEqual(battle['profiles']['challenger']['units'], [510, 510, 509])
        self.assertTrue(all(team is None for _, team in self.asked))

    def test_a_bad_or_empty_team_is_refused(self):
        with patch.dict(os.environ, PVP_ON):
            self.hub.handle(1, {'type': 'challenge', 'to': 2, 'army': 'all'})
            self.assertEqual(self.error(1), 'invalid')
            self.hub.handle(1, {'type': 'challenge', 'to': 2, 'army': [0, 0]})
            self.assertEqual(self.error(1), 'no_troops')
            self.hub.handle(1, {'type': 'challenge', 'to': 2, 'army': [510]})
            received = self.pages[2].last('challenge_received')
            self.hub.handle(2, {'type': 'respond', 'id': received['id'], 'accept': True, 'army': []})
            self.assertEqual(self.error(2), 'no_troops')
        self.assertIn(received['id'], self.hub.challenges)  # still open: the player can choose again


class PvpMovieTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with patch.dict(os.environ, {'SOCIAL_EMPIRES_LANGUAGE': 'pt-BR'}), contextlib.redirect_stdout(io.StringIO()):
            import server
        clear = getattr(server.localized_game_movie, 'cache_clear', lambda: None)
        clear()
        with patch.object(server, 'PVP_ENABLED', False), contextlib.redirect_stdout(io.StringIO()):
            cls.original, _ = server.localized_game_movie('es')
        clear()
        cls.patched = add_pvp(cls.original)
        cls.before, _ = abc_of(cls.original)
        cls.abc, cls.raw = abc_of(cls.patched)

    def names(self, abc, cls):
        return [abc.multiname_name(t['name']) for t in abc.instances[abc.class_index(cls)]['traits']]

    def ops(self, cls, method):
        return [(name, str(operand)) for _, name, operand in disassemble(self.abc, self.abc.body_of(self.abc.method_of(cls, method))['code'])]

    def test_the_movie_rebuilds_byte_for_byte_and_off_has_nothing(self):
        self.assertEqual(self.abc.serialize(), self.raw)
        self.assertNotIn(SELECT_METHOD, self.names(self.before, 'Base'))
        with self.assertRaises(AbcError):
            add_pvp_to_abc(self.abc)

    def test_the_pvp_button_goes_below_the_clan_one(self):
        self.assertIn('__addPvpButton', self.names(self.abc, 'GuiManager'))
        self.assertIn(('pushstring', repr(OPEN_CALLBACK)), self.ops('GuiManager', '__pvpClick'))
        create = self.ops('GuiManager', 'createViralButtons')
        self.assertEqual(create[-2:], [('callpropvoid', '__addPvpButton 0'), ('returnvoid', '')])
        self.assertTrue((ROOT / 'templates' / 'img' / 'pvp_button_es.png').exists())

    def test_the_page_opens_the_games_team_window_and_hears_the_choice(self):
        register = self.ops('Base', REGISTER_METHOD)
        self.assertIn(('pushstring', repr(SELECT_CALLBACK)), register)
        self.assertIn(('callpropvoid', 'addCallback 2'), register)
        self.assertEqual(self.ops('Base', 'init')[:2], [('getlocal0', ''), ('callpropvoid', f'{REGISTER_METHOD} 0')])
        select = self.ops('Base', SELECT_METHOD)
        self.assertIn(('constructprop', 'SelectionTeamWindow 0'), select)
        self.assertIn(('getproperty', 'SELECTION_MODE_TOURNAMENT'), select)  # the window lists units only in its modes
        self.assertIn(('setproperty', 'visible'), select)  # its close button, hidden in that mode
        for method in (ACCEPTED_METHOD, CLOSED_METHOD):
            self.assertIn(('pushstring', repr(SELECTED_CALL)), self.ops('Base', method))
        self.assertIn(('getproperty', 'selectedArmy'), self.ops('Base', ACCEPTED_METHOD))
        for method in (SELECT_METHOD, ACCEPTED_METHOD, CLOSED_METHOD, REGISTER_METHOD):
            self.assertEqual(len(self.abc.body_of(self.abc.method_of('Base', method))['exceptions']), 1, method)


class PvpWindowViewTests(unittest.TestCase):
    def test_player_names_are_escaped_and_attack_buttons_only_where_allowed(self):
        script = r"""
const View = require('./templates/js/pvp_overlay.js');
const T = new Proxy({}, { get: (target, key) => String(key) + ' {name} {power} {troops} {count} {level} {amount} {mine} {theirs} {rating} {time}' });
const state = { own: { attack: 1234, troops: 3, attack_available_at: 0 }, me: 1,
  rivals: [{ id: 'a', name: '<b>x</b>', level: 9, defense: 10, loot: 5, can_attack: true, reason: '', token: 't"1' },
           { id: 'b', name: 'Bob', level: 9, defense: 10, loot: 5, can_attack: false, reason: '<i>no</i>', token: 't2' }],
  history: [{ role: 'attacker', name: '<s>y</s>', won: true, loot: 3, mine: 1, theirs: 2 }],
  duels: { rating: 1000, history: [{ other: '<u>z</u>', outcome: 'won', mine: 50, theirs: 10 }] } };
const html = View.rivals(T, state, 'es', 0, 20) + View.raids(T, state, 'es') +
  View.duels(T, state, [{ id: 1, name: 'me' }, { id: 2, name: '<em>w</em>', busy: false }], 1, 'es');
process.stdout.write(JSON.stringify({ html, raids: (html.match(/data-action="raid"/g) || []).length,
  challenges: (html.match(/data-action="challenge"/g) || []).length }));
"""
        out = json.loads(subprocess.run(['node', '-e', script], cwd=ROOT, capture_output=True, text=True,
                                        encoding='utf-8', check=True).stdout)
        for raw in ('<b>x</b>', '<i>no</i>', '<s>y</s>', '<u>z</u>', '<em>w</em>', 't"1'):
            self.assertNotIn(raw, out['html'])
        self.assertIn('&lt;b&gt;x&lt;/b&gt;', out['html'])
        self.assertEqual((out['raids'], out['challenges']), (1, 1))  # only the open rival; not myself


if __name__ == '__main__':
    unittest.main()
