"""Live duel checks against a real threaded server (run by test_duels_live.py with SE_DUELS=on).

Not collected by unittest discovery on its own: the server module must be
imported with SE_DUELS=on, and the rest of the suite imports it with duels off.
"""

import contextlib
import http.cookiejar
import io
import json
import os
from pathlib import Path
import re
import tempfile
import threading
import unittest
import urllib.parse
import urllib.request

assert os.environ.get('SE_DUELS') == 'on', 'run through test_duels_live.py'
_data = tempfile.mkdtemp(prefix='socialemperors-duels-')
os.environ.update(SOCIAL_EMPIRES_DATA_DIR=_data, SOCIAL_EMPIRES_SAVES_DIR=str(Path(_data) / 'saves'),
                  SOCIAL_EMPIRES_LANGUAGE='es')
with contextlib.redirect_stdout(io.StringIO()):
    import server
    import sessions

import simple_websocket
from werkzeug.serving import make_server

SPEARMAN = 509


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
        return self.opener.open(self.base + path).status


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

    def test_challenge_accept_and_same_result_for_both(self):
        ana, beto = self.player(troops=8), self.player(troops=3)
        ws_ana, ws_beto = ana.socket(), beto.socket()
        try:
            receive_until(ws_ana, 'hello')
            receive_until(ws_beto, 'hello')
            ws_ana.send(json.dumps({'type': 'challenge', 'to': beto.account_id}))
            received = receive_until(ws_beto, 'challenge_received')
            self.assertEqual(received['other']['id'], ana.account_id)
            ws_beto.send(json.dumps({'type': 'respond', 'id': received['id'], 'accept': True}))
            result_ana, result_beto = receive_until(ws_ana, 'duel_result'), receive_until(ws_beto, 'duel_result')
            self.assertEqual(result_ana, result_beto)
            self.assertEqual((result_ana['winner'], result_ana['ranked']), ('challenger', True))
            from duels import army_profile
            self.assertEqual(result_ana['challenger']['power'], army_profile(sessions.session(ana.village_id))['power'])
            self.assertEqual(result_ana['defender']['power'], army_profile(sessions.session(beto.village_id))['power'])
        finally:
            ws_ana.close()
            ws_beto.close()
        self.assertEqual(server.app.extensions['duels'].store.history(ana.account_id)[0]['winner'], 'challenger')
        self.assertEqual(ana.get('/duels'), 200)
        page = ana.opener.open(self.base + '/duels').read().decode()
        config = json.loads(re.search(r'<script id="duel-config" type="application/json">(.*?)</script>', page).group(1))
        self.assertEqual(config['wsPath'], '/duels/ws')  # a path; the page adds its own ws(s)://host

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

    def test_many_simultaneous_challenges_with_threads(self):
        pairs = [(self.player(troops=4), self.player(troops=2)) for _ in range(10)]
        sockets = {player.account_id: player.socket() for pair in pairs for player in pair}
        before = {player.village_id: json.dumps(sessions.session(player.village_id), sort_keys=True)
                  for pair in pairs for player in pair}
        try:
            for ws in sockets.values():
                receive_until(ws, 'hello')
            errors, results = [], []
            stop = threading.Event()

            def duel(challenger, defender):
                try:
                    sockets[challenger.account_id].send(json.dumps({'type': 'challenge', 'to': defender.account_id}))
                    received = receive_until(sockets[defender.account_id], 'challenge_received', timeout=10)
                    sockets[defender.account_id].send(json.dumps({'type': 'respond', 'id': received['id'], 'accept': True}))
                    results.append((receive_until(sockets[challenger.account_id], 'duel_result', timeout=10),
                                    receive_until(sockets[defender.account_id], 'duel_result', timeout=10)))
                except Exception as error:  # collected and reported below
                    errors.append(repr(error))

            def browse(player):
                while not stop.is_set():
                    try:
                        with contextlib.redirect_stdout(io.StringIO()):
                            for path in ('/village/events', '/duels', '/treasury'):
                                self.assertEqual(player.get(path), 200)
                    except Exception as error:
                        errors.append(repr(error))
                        return

            browsers = [threading.Thread(target=browse, args=(pair[0],)) for pair in pairs[:4]]
            for thread in browsers:
                thread.start()
            duels = [threading.Thread(target=duel, args=pair) for pair in pairs]
            for thread in duels:
                thread.start()
            for thread in duels:
                thread.join(30)
            stop.set()
            for thread in browsers:
                thread.join(30)
            self.assertEqual(errors, [])
            self.assertEqual(len(results), len(pairs))
            for mine, theirs in results:
                self.assertEqual(mine, theirs)
                self.assertEqual(mine['winner'], 'challenger')
            self.assertEqual(server.app.extensions['duels'].challenges, {})
            after = {village_id: json.dumps(sessions.session(village_id), sort_keys=True) for village_id in before}
            self.assertEqual(after, before)  # duels never change a village
        finally:
            for ws in sockets.values():
                ws.close()


if __name__ == '__main__':
    unittest.main()
