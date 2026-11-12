"""Live duel checks against a real threaded server (run by test_duels_live.py with SE_DUELS=on).

Not collected by unittest discovery on its own: the server module must be
imported with SE_DUELS=on, and the rest of the suite imports it with duels off.
test_duels_live.py also sets SE_DUEL_MIN_SECONDS to half a second so the
battles here do not last 20 seconds; the arena game is played by HTTP calls to
the same tournament services the game uses.
"""

import contextlib
import hashlib
import hmac
import http.cookiejar
import io
import json
import os
from pathlib import Path
import re
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request

assert os.environ.get('SE_DUELS') == 'on', 'run through test_duels_live.py'
_data = tempfile.mkdtemp(prefix='socialemperors-duels-')
os.environ.update(SOCIAL_EMPIRES_DATA_DIR=_data, SOCIAL_EMPIRES_SAVES_DIR=str(Path(_data) / 'saves'),
                  SOCIAL_EMPIRES_LANGUAGE='es')
with contextlib.redirect_stdout(io.StringIO()):
    import server
    import sessions

import duels
import simple_websocket
from werkzeug.serving import make_server

SPEARMAN = 509
GAME = '/dynamic.flash1.dev.socialpoint.es/appsfb/socialempiresdev/srvempires/'
KEY = b'3m0d3pwiupoetn7ysa02'


class Player:
    def __init__(self, base, email):
        self.base = base
        self.cookies = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cookies))
        page = self.opener.open(base + '/login').read().decode()
        token = re.search(r'name="csrf_token" value="([^"]+)"', page).group(1)
        data = urllib.parse.urlencode({'email': email, 'password': 'secret-password', 'csrf_token': token}).encode()
        with contextlib.redirect_stdout(io.StringIO()):
            self.opener.open(base + '/login', data)

    def cookie_header(self):
        return '; '.join(f'{c.name}={c.value}' for c in self.cookies)

    def socket(self, origin=None):
        ws_url = self.base.replace('http://', 'ws://') + '/duels/ws'
        # simple_websocket sends "Host: 127.0.0.1" without the port (browsers include
        # it), so the page origin it represents is the bare host.
        same_site = 'http://' + urllib.parse.urlsplit(self.base).hostname
        return simple_websocket.Client.connect(ws_url, headers={'Cookie': self.cookie_header(), 'Origin': origin or same_site})

    def get(self, path):
        with contextlib.redirect_stdout(io.StringIO()):
            return self.opener.open(self.base + path).status

    def text(self, path, data=None):
        body = urllib.parse.urlencode(data).encode() if data is not None else None
        with contextlib.redirect_stdout(io.StringIO()):
            return self.opener.open(self.base + path, body).read().decode()

    def game_key(self):
        page = self.text('/play.html')
        return json.loads(re.search(r'<script id="game-config" type="application/json">(.*?)</script>', page, re.S).group(1))['userKey']

    def service(self, name, params):
        """Call a tournament service like the game's ServiceManager; returns its data."""
        payload = json.dumps(params)
        signed = hmac.new(KEY, payload.encode(), hashlib.sha256).hexdigest() + ';' + payload
        answer = self.text(GAME + 'tournaments/' + name, {'data': signed})
        signature, _, body = answer.partition(';')
        assert hmac.compare_digest(signature, hmac.new(KEY, body.encode(), hashlib.sha256).hexdigest()), answer
        return json.loads(body)['data']

    def play(self, start, percent, during=None):
        """The game in the arena: press start, fight for the minimum time, report."""
        params = {'user_id': self.village_id, 'victim_id': start['other']['id'], 'tournament_id': start['id']}
        assert self.service('start_tournament_match.php', params) == {'result': 'OK'}
        if during:
            during()
        time.sleep(duels.BATTLE_MIN_SECONDS + 0.1)
        finish = {**params, 'attacker_won': percent >= 100, 'attacker_points': f'{percent:.2f}', 'victim_points': 0}
        assert self.service('finish_tournament_match.php', finish) == {'result': 'OK'}

    def commands(self, key, *commands):
        data = {'ts': 1, 'first_number': 1, 'accessToken': '', 'tries': 0, 'publishActions': 0, 'commands': list(commands)}
        self.text(GAME + 'command.php', {'USERID': self.village_id, 'user_key': key, 'language': 'es', 'client_id': 't',
                                         'data': '0' * 64 + ';' + json.dumps(data)})


def receive_until(ws, kind, timeout=5):
    while True:
        raw = ws.receive(timeout=timeout)
        if raw is None:
            raise AssertionError(f'no {kind} message within {timeout}s')
        message = json.loads(raw)
        if message['type'] == kind:
            return message


class LiveDuelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        server.app.config.update(TESTING=False)
        cls.http = make_server('127.0.0.1', 0, server.app, threaded=True)
        cls.base = f'http://127.0.0.1:{cls.http.server_port}'
        threading.Thread(target=cls.http.serve_forever, daemon=True).start()
        cls.store = server.app.extensions['accounts']
        cls.hub = server.app.extensions['duels']
        cls.count = 0

    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown()

    def player(self, level=30, troops=5):
        type(self).count += 1
        email = f'player{self.count}@example.com'
        account = self.store.create_account(f'Jugador {self.count}', email, 'secret-password', status='approved')
        player = Player(self.base, email)
        village_id = self.store.get(account['id'])['village_id']
        with server.village_lock:
            save = sessions.session(village_id)
            save['playerInfo']['completed_tutorial'] = 1
            town = save['maps'][0]
            town['race'] = 'h'
            town['level'] = level
            town['items'] += [[SPEARMAN, 20 + i, 20, 0, 0, 0] for i in range(troops)]
        player.account_id = account['id']
        player.village_id = village_id
        return player

    def start_duel(self, challenger, defender, ws_challenger, ws_defender, timeout=5):
        ws_challenger.send(json.dumps({'type': 'challenge', 'to': defender.account_id}))
        received = receive_until(ws_defender, 'challenge_received', timeout)
        ws_defender.send(json.dumps({'type': 'respond', 'id': received['id'], 'accept': True}))
        return receive_until(ws_challenger, 'duel_start', timeout), receive_until(ws_defender, 'duel_start', timeout)

    def snapshot(self, *players):
        with server.village_lock:
            return {p.village_id: json.dumps(sessions.session(p.village_id), sort_keys=True) for p in players}

    def test_battle_in_the_arena_and_same_result_for_both(self):
        ana, beto = self.player(troops=8), self.player(troops=3)
        before = self.snapshot(ana, beto)
        ws_ana, ws_beto = ana.socket(), beto.socket()
        try:
            receive_until(ws_ana, 'hello')
            receive_until(ws_beto, 'hello')
            start_ana, start_beto = self.start_duel(ana, beto, ws_ana, ws_beto)
            self.assertEqual(start_ana['army'], duels.army_profile(sessions.session(ana.village_id))['units'])
            self.assertEqual(start_ana['enemy_army'], start_beto['army'])
            self.assertEqual((start_ana['arena'], start_beto['side']), (duels.ARENA_MAP_ID, 'defender'))

            # The game loads the arena like an adventure map.
            key = ana.game_key()
            arena = json.loads(ana.text(GAME + 'get_player_info.php?' + urllib.parse.urlencode(
                {'USERID': ana.village_id, 'user_key': key, 'user': duels.ARENA_MAP_ID, 'language': 'es', 'client_id': 't'})))
            self.assertEqual((arena['playerInfo']['pid'], arena['map']['items']), (str(duels.ARENA_MAP_ID), []))
            # ... with the tournament type in weekly mode, so the rival AI advances and attacks.
            config = json.loads(ana.text(GAME + 'get_game_config.php?' + urllib.parse.urlencode(
                {'USERID': ana.village_id, 'user_key': key, 'language': 'es'})))
            self.assertEqual(config['tournament_type'][str(duels.ARENA_TOURNAMENT_TYPE)]['weekly_tournaments'], 1)

            # Units killed in the arena would mean "kill"/"sell KILL" for the player's town
            # (the game never queues them outside its NORMAL mode); a forged one is dropped.
            kill = {'cmd': 'kill', 'args': [20, 20, SPEARMAN, 0, 'u']}
            death = {'cmd': 'sell', 'args': [21, 20, SPEARMAN, 0, 1, 'KILL', 1]}
            ana.play(start_ana, 80, during=lambda: ana.commands(key, kill, death))
            waiting = receive_until(ws_ana, 'duel_waiting')
            self.assertEqual(waiting['other']['id'], beto.account_id)
            self.assertGreater(waiting['seconds_left'], duels.BATTLE_DEADLINE_SECONDS - 30)

            beto.play(start_beto, 50)
            result_ana, result_beto = receive_until(ws_ana, 'duel_result'), receive_until(ws_beto, 'duel_result')
            self.assertEqual(result_ana, result_beto)
            self.assertEqual((result_ana['winner'], result_ana['status'], result_ana['rated']), ('challenger', 'done', True))
            self.assertEqual((result_ana['challenger']['percent'], result_ana['defender']['percent']), (80, 50))
            self.assertEqual(result_ana['challenger']['report'], 'ok')
        finally:
            ws_ana.close()
            ws_beto.close()
        self.assertEqual(self.snapshot(ana, beto), before)  # the arena never changes a village
        # Back in the village after the report, its commands count again.
        ana.commands(key, {'cmd': 'kill', 'args': [20, 20, SPEARMAN, 0, 'u']})
        with server.village_lock:
            items = sessions.session(ana.village_id)['maps'][0]['items']
            self.assertFalse(any(item[:3] == [SPEARMAN, 20, 20] for item in items))
        self.assertEqual(self.hub.store.history(ana.account_id)[0]['winner'], 'challenger')
        page = ana.text('/duels')
        config = json.loads(re.search(r'<script id="duel-config" type="application/json">(.*?)</script>', page).group(1))
        self.assertEqual(config['wsPath'], '/duels/ws')  # a path; the page adds its own ws(s)://host
        self.assertIn('80', page)

    def test_services_without_a_battle_and_fake_results(self):
        ana, beto = self.player(troops=1), self.player(troops=9)
        self.assertEqual(ana.service('start_tournament_match.php', {}), {'result': 'NOK'})  # no battle
        ws_ana, ws_beto = ana.socket(), beto.socket()
        try:
            receive_until(ws_ana, 'hello')
            receive_until(ws_beto, 'hello')
            start_ana, start_beto = self.start_duel(ana, beto, ws_ana, ws_beto)
            # A forged report before pressing start does not count ...
            ana.service('finish_tournament_match.php', {'attacker_points': '100.00'})
            receive_until(ws_ana, 'duel_waiting')
            self.assertEqual(ana.service('start_tournament_match.php', {}), {'result': 'NOK'})  # ... nor can it start now
            beto.play(start_beto, 10)
            result = receive_until(ws_ana, 'duel_result')
            self.assertEqual((result['challenger']['report'], result['winner']), ('not_started', 'defender'))
        finally:
            ws_ana.close()
            ws_beto.close()

    def test_unlikely_result_is_reviewed_by_an_admin(self):
        weak, strong = self.player(troops=1), self.player(troops=12)
        admin_account = self.store.create_admin('Admin Duelos', 'duel-admin@example.com', 'secret-password')
        admin = Player(self.base, 'duel-admin@example.com')
        ws_weak, ws_strong = weak.socket(), strong.socket()
        try:
            receive_until(ws_weak, 'hello')
            receive_until(ws_strong, 'hello')
            start_weak, start_strong = self.start_duel(weak, strong, ws_weak, ws_strong)
            weak.play(start_weak, 100)
            strong.play(start_strong, 0)
            result = receive_until(ws_weak, 'duel_result')
            self.assertEqual((result['winner'], result['status'], result['rated']), ('challenger', 'review', False))
            self.assertEqual(self.hub.store.rating(weak.account_id), duels.ELO_START)

            page = admin.text('/admin/duels')
            self.assertIn(f'#{result["id"]}', page)
            self.assertIn('Jugador', page)
            token = re.search(r'name="csrf_token" value="([^"]+)"', page).group(1)
            self.assertEqual(weak.get('/duels'), 200)
            with self.assertRaises(urllib.error.HTTPError):
                weak.text('/admin/duels')  # administrators only
            admin.text(f'/admin/duels/{result["id"]}', {'action': 'validate', 'csrf_token': token})
            update = receive_until(ws_weak, 'duel_result')  # both players hear the decision
            self.assertEqual((update['status'], update['rated']), ('done', True))
            self.assertEqual(self.hub.store.get(result['id'])['resolved_by'], admin_account['name'])
            self.assertGreater(self.hub.store.rating(weak.account_id), duels.ELO_START)
        finally:
            ws_weak.close()
            ws_strong.close()

    def test_socket_requires_session_and_same_origin(self):
        ana = self.player()
        with self.assertRaises(Exception):
            ana.socket(origin='http://evil.example')
        stranger = Player(self.base, 'nobody@example.com')  # failed login: no session
        with self.assertRaises(Exception):
            stranger.socket()
        ws = ana.socket()
        try:
            self.assertEqual(receive_until(ws, 'hello')['you'], ana.account_id)
        finally:
            ws.close()

    def test_many_simultaneous_battles_with_threads(self):
        pairs = [(self.player(troops=4), self.player(troops=2)) for _ in range(10)]
        sockets = {player.account_id: player.socket() for pair in pairs for player in pair}
        before = self.snapshot(*[player for pair in pairs for player in pair])
        try:
            for ws in sockets.values():
                receive_until(ws, 'hello')
            errors, results = [], []
            stop = threading.Event()

            def duel(challenger, defender):
                try:
                    start_c, start_d = self.start_duel(challenger, defender, sockets[challenger.account_id],
                                                       sockets[defender.account_id], timeout=10)
                    fighters = [threading.Thread(target=challenger.play, args=(start_c, 70)),
                                threading.Thread(target=defender.play, args=(start_d, 30))]
                    for thread in fighters:
                        thread.start()
                    for thread in fighters:
                        thread.join(20)
                    results.append((receive_until(sockets[challenger.account_id], 'duel_result', timeout=10),
                                    receive_until(sockets[defender.account_id], 'duel_result', timeout=10)))
                except Exception as error:  # collected and reported below
                    errors.append(repr(error))

            def browse(player):
                while not stop.is_set():
                    try:
                        for path in ('/village/events', '/duels', '/treasury'):
                            self.assertEqual(player.get(path), 200)
                    except Exception as error:
                        errors.append(repr(error))
                        return

            browsers = [threading.Thread(target=browse, args=(pair[0],)) for pair in pairs[:4]]
            for thread in browsers:
                thread.start()
            battles = [threading.Thread(target=duel, args=pair) for pair in pairs]
            for thread in battles:
                thread.start()
            for thread in battles:
                thread.join(60)
            stop.set()
            for thread in browsers:
                thread.join(30)
            self.assertEqual(errors, [])
            self.assertEqual(len(results), len(pairs))
            for mine, theirs in results:
                self.assertEqual(mine, theirs)
                self.assertEqual((mine['winner'], mine['status']), ('challenger', 'done'))
            self.assertEqual((self.hub.challenges, self.hub.battles), ({}, {}))
            self.assertEqual(self.snapshot(*[player for pair in pairs for player in pair]), before)
        finally:
            for ws in sockets.values():
                ws.close()


if __name__ == '__main__':
    unittest.main()
