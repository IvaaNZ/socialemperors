import contextlib
import datetime
import io
import json
import os
import shutil
import subprocess
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from flask import Flask, g, session

import season_pass as sp
from season_pass_web import install_season_pass
from swf_abc import AbcError
from swf_season_pass import CALLBACK, add_season_pass_button, add_season_pass_button_to_abc
from swf_abc import Abc, disassemble, find_abc
from swf_localization import decode_swf


def abc_of(movie):
    body, header_length = decode_swf(movie)
    payload, offset = find_abc(body, header_length)
    return Abc(payload[offset:]), payload[offset:]

ROOT = Path(__file__).resolve().parent.parent


def village():
    return {'playerInfo': {'cash': 0}, 'maps': [{'coins': 0, 'wood': 0, 'food': 0, 'stone': 0}],
            'privateState': {'gifts': []}}


class SeasonPassApi(unittest.TestCase):
    def setUp(self):
        self.saves = {'v1': village()}
        self.saved = []
        self.accounts = {1: {'id': 1, 'village_id': 'v1'}, 2: {'id': 2, 'village_id': 'v2'}}
        self.saves['v2'] = village()
        app = Flask(__name__, template_folder=str(ROOT / 'templates'))
        app.secret_key = 'test'

        @app.before_request
        def sign_in():
            g.account = {'id': 1, 'status': 'approved', 'village_id': 'v1'}
            session['USERID'] = 'v1'
            session['_csrf_token'] = 'tok'

        @app.get('/play.html', endpoint='play')
        def play():
            return ''
        self.record_for = install_season_pass(app, threading.RLock(), self.saves.get, self.saved.append,
                                              lambda item: f'Unidad {item}', lambda: self.accounts)
        self.app = app
        self.client = app.test_client()
        patch.dict(os.environ, {'SE_SEASON_PASS': 'on'}).start()
        self.addCleanup(patch.stopall)

    def test_the_window_state_and_claiming_reached_levels(self):
        state = self.client.get('/season-pass/api/state').get_json()
        self.assertEqual((state['level'], state['levels'], len(state['rewards'])), (0, sp.LEVELS, sp.LEVELS))
        self.assertEqual(state['rewards'][9]['reward']['name'], f"Unidad {state['rewards'][9]['reward']['unit']}")
        self.assertEqual(self.saved, ['v1'])  # the new season was set up and kept
        self.saves['v1']['privateState']['seasonPass']['points'] = 2 * sp.POINTS_PER_LEVEL
        refused = self.client.post('/season-pass/api/claim', data={'level': 'all', 'csrf_token': 'otro'})
        self.assertEqual(refused.status_code, 400)
        answer = self.client.post('/season-pass/api/claim', data={'level': 'all', 'csrf_token': 'tok'}).get_json()
        self.assertEqual([row['level'] for row in answer['given']], [1, 2])
        self.assertEqual(answer['state']['rewards'][0]['claimed'], True)
        self.assertGreater(self.saves['v1']['maps'][0]['coins'], 0)
        self.assertEqual(sp.revision(self.saves['v1']), 'sp1')  # the page will ask to reload the village
        again = self.client.post('/season-pass/api/claim', data={'level': '1', 'csrf_token': 'tok'}).get_json()
        self.assertEqual(again['given'], [])

    def test_raids_and_duels_count_once_for_both_players(self):
        self.record_for('v1', 'raid_win', once='raid-1')
        self.record_for('v1', 'raid_win', once='raid-1')
        self.assertEqual(self.saves['v1']['privateState']['seasonPass']['seen'], ['raid_win:raid-1'])
        on_duel = self.app.extensions['season_pass']['on_duel']
        duel = {'id': 7, 'challenger_id': 1, 'defender_id': 2, 'winner': 'defender', 'status': 'done'}
        on_duel(duel)
        on_duel(duel)
        self.assertEqual(self.saves['v1']['privateState']['seasonPass']['seen'][-1], 'duel_play:7')
        self.assertIn('duel_win:7', self.saves['v2']['privateState']['seasonPass']['seen'])
        self.assertNotIn('duel_win:7', self.saves['v1']['privateState']['seasonPass']['seen'])
        self.assertEqual(self.saves['v2']['privateState']['seasonPass']['seen'].count('duel_play:7'), 1)


class SeasonPassMovie(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with patch.dict(os.environ, {'SOCIAL_EMPIRES_LANGUAGE': 'pt-BR'}), contextlib.redirect_stdout(io.StringIO()):
            import server
        clear = getattr(server.localized_game_movie, 'cache_clear', lambda: None)
        clear()
        with patch.object(server, 'SEASON_PASS_ENABLED', False), contextlib.redirect_stdout(io.StringIO()):
            cls.original, _ = server.localized_game_movie('es')
        clear()
        cls.abc, cls.raw = abc_of(add_season_pass_button(cls.original))

    def test_the_pase_button_is_in_the_games_icon_panel(self):
        names = [self.abc.multiname_name(t['name']) for t in self.abc.instances[self.abc.class_index('GuiManager')]['traits']]
        self.assertIn('__addSeasonPassButton', names)
        click = [(name, str(op)) for _, name, op in disassemble(self.abc, self.abc.body_of(self.abc.method_of('GuiManager', '__seasonPassClick'))['code'])]
        self.assertIn(('pushstring', repr(CALLBACK)), click)
        create = [(name, str(op)) for _, name, op in disassemble(self.abc, self.abc.body_of(self.abc.method_of('GuiManager', 'createViralButtons'))['code'])]
        self.assertEqual(create[-2:], [('callpropvoid', '__addSeasonPassButton 0'), ('returnvoid', '')])
        self.assertEqual(self.abc.serialize(), self.raw)
        with self.assertRaises(AbcError):
            add_season_pass_button_to_abc(self.abc)
        for lang in ('es', 'en', 'pt-BR'):
            self.assertTrue((ROOT / 'templates' / 'img' / f'season_pass_button_{lang}.png').exists())


@unittest.skipUnless(shutil.which('node'), 'node is needed for the window script')
class SeasonPassWindowView(unittest.TestCase):
    def test_unit_names_are_escaped_and_only_reached_levels_can_be_claimed(self):
        script = r"""
const View = require('./templates/js/season_pass_overlay.js');
const T = new Proxy({resources: {coins: '{amount} oro'}, challenges: {collect: 'Recolectar {target}'}},
  { get: (target, key) => key in target ? target[key] : String(key) + ' {count} {name} {amount} {days} {hours} {minutes} {points} {total} {time} {level} {levels} {cap}' });
const rewards = [
  {level: 1, reward: {resource: 'coins', amount: 1250}, claimed: true, reached: true},
  {level: 2, reward: {unit: 5, name: '<img src=x>'}, claimed: false, reached: true},
  {level: 3, reward: {cash: 5}, claimed: false, reached: false}];
const html = View.rewards(T, {rewards}, 'es');
const challenges = View.challenges(T, {play_today: 10, play_cap: 300, daily_in: 3600, weekly_in: 90000,
  daily: [{id: 'c', event: 'collect', target: 15, points: 150, progress: 5, done: false}], weekly: []}, 'es');
console.log(JSON.stringify({escaped: !html.includes('<img'), claimButtons: (html.match(/data-action="claim"/g) || []).length,
  all: html.includes('data-level="all"'), coins: html.includes('1.250 oro'), challenge: challenges.includes('Recolectar 15')}));
"""
        result = subprocess.run(['node', '-e', script], cwd=ROOT, capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {'escaped': True, 'claimButtons': 2, 'all': True, 'coins': True,
                                                     'challenge': True})


if __name__ == '__main__':
    unittest.main()
