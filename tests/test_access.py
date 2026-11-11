"""Exercise account approval and village isolation through real Flask requests."""

import contextlib
import io
import json
import os
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

from auth import AccountStore

# Importing the legacy game loads saves; keep even that first load isolated.
_boot_directory = tempfile.TemporaryDirectory(prefix='socialemperors-tests-')
with patch.dict(os.environ, {
    'SOCIAL_EMPIRES_DATA_DIR': _boot_directory.name,
    'SOCIAL_EMPIRES_LANGUAGE': 'pt-BR',  # These tests cover the Portuguese texts.
    'SOCIAL_EMPIRES_SAVES_DIR': str(Path(_boot_directory.name) / 'saves'),
}):
    with contextlib.redirect_stdout(io.StringIO()):
        import server
        import sessions


class AccessTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='socialemperors-access-')
        self.addCleanup(self.directory.cleanup)
        self.save_path = Path(self.directory.name) / 'saves'
        self.saved_directory = patch.object(sessions, 'SAVES_DIR', str(self.save_path))
        self.saved_directory.start()
        self.addCleanup(self.saved_directory.stop)
        with contextlib.redirect_stdout(io.StringIO()):
            sessions.load_saved_villages()
        self.store = AccountStore(Path(self.directory.name) / 'accounts.sqlite3')
        self.extension = patch.dict(server.app.extensions, {'accounts': self.store})
        self.extension.start()
        self.addCleanup(self.extension.stop)
        server.app.config.update(TESTING=True)
        self.client = server.app.test_client()

    def token(self, client=None):
        client = client or self.client
        client.get('/login')
        with client.session_transaction() as session:
            return session['_csrf_token']

    def login(self, email='player@example.com', client=None):
        client = client or self.client
        return client.post('/login', data={
            'email': email, 'password': 'secret-password', 'csrf_token': self.token(client),
        })

    def create_player(self, email='player@example.com', status='pending'):
        return self.store.create_account('Jogador', email, 'secret-password', status=status)

    def create_admin(self):
        return self.store.create_admin('Administrador', 'admin@example.com', 'secret-password')

    def game_data(self, client=None):
        with (client or self.client).session_transaction() as session:
            return {
                'USERID': session['USERID'], 'user_key': session['_csrf_token'],
                'language': 'en', 'client_id': 'test',
            }

    def test_registration_waits_for_explicit_admin_approval(self):
        response = self.client.post('/register', data={
            'name': 'Maria', 'email': 'MARIA@example.com', 'password': 'secret-password',
            'password_confirm': 'secret-password', 'csrf_token': self.token(),
        }, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn('Cadastro recebido', response.text)
        account = self.store.list_accounts()[0]
        self.assertEqual(account['status'], 'pending')
        self.assertFalse(account['is_admin'])
        self.assertIsNone(account['village_id'])
        self.assertEqual(list(self.save_path.iterdir()), [])
        self.assertIn('aguardando aprovação', self.login('maria@example.com').text)
        self.assertEqual(self.client.get('/play.html').status_code, 302)
        self.assertEqual(self.client.post(server.DYNAMIC_GAME_PREFIX + 'command.php').status_code, 401)
        self.assertEqual(self.client.get('/admin').status_code, 403)

    def test_approval_login_and_return_open_same_exclusive_village(self):
        player = self.create_player()
        self.create_admin()
        admin_client = server.app.test_client()
        self.assertEqual(self.login('admin@example.com', admin_client).status_code, 302)
        admin_token = self.token(admin_client)
        response = admin_client.post(f"/admin/accounts/{player['id']}", data={
            'action': 'approve', 'csrf_token': admin_token,
        })
        self.assertEqual(response.status_code, 302)
        approved = self.store.get(player['id'])
        self.assertEqual(approved['status'], 'approved')
        self.assertIn(approved['village_id'], sessions.all_saves_userid())
        self.assertEqual(self.login().location, '/play.html')
        own_id = self.game_data()['USERID']
        self.assertEqual(own_id, approved['village_id'])
        self.assertNotEqual(own_id, self.store.get(2)['village_id'])
        page = self.client.get('/play.html')
        self.assertEqual(page.status_code, 200)
        self.assertIn('/js/game.js', page.text)
        with self.client.get('/js/game.js') as script:
            self.assertEqual(script.status_code, 200)
        with self.client.get('/vendor/ruffle/ruffle.js') as runtime:
            self.assertEqual(runtime.status_code, 200)
            self.assertIn('javascript', runtime.content_type)
        self.assertNotIn('application/x-shockwave-flash', page.text)
        self.assertNotIn('127.0.0.1:5050', page.text)
        self.assertEqual(self.client.get('/').location, '/play.html')
        self.assertEqual(self.client.get('/new.html').location, '/play.html')
        self.assertEqual(self.game_data()['USERID'], own_id)
        response = self.client.post('/logout', data={'csrf_token': self.game_data()['user_key']})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.login().status_code, 302)
        self.assertEqual(self.game_data()['USERID'], own_id)

    def test_village_identity_and_game_csrf_cannot_be_forged(self):
        self.create_player(status='approved')
        self.login()
        payload = self.game_data()
        url = server.DYNAMIC_GAME_PREFIX + 'get_player_info.php'
        response = self.client.post(url, data=payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['playerInfo']['pid'], payload['USERID'])
        self.assertEqual(self.client.post(url, data={**payload, 'USERID': '1111'}).status_code, 403)
        self.assertEqual(self.client.post(url, data={**payload, 'user_key': 'forged'}).status_code, 403)
        self.assertEqual(self.client.post(url, data={**payload, 'user_key': 'inválido'}).status_code, 403)
        self.assertEqual(self.client.post(url, data=payload, headers={'Origin': 'https://attacker.example'}).status_code, 403)
        self.assertEqual(self.client.post(url, data=payload, headers={'Sec-Fetch-Site': 'cross-site'}).status_code, 403)
        self.assertEqual(self.client.get('/admin').status_code, 403)

    def test_game_paths_remain_relative_behind_an_https_proxy(self):
        self.create_player(status='approved')
        self.login()
        for prefix in ('', '/empire'):
            with self.subTest(prefix=prefix):
                page = self.client.get('/play.html', headers={
                    'X-Forwarded-Proto': 'https',
                    'X-Forwarded-Host': 'empire.example.test:8443',
                }, environ_overrides={'SCRIPT_NAME': prefix})
                self.assertEqual(page.status_code, 200)
                configuration = json.loads(re.search(
                    r'<script id="game-config" type="application/json">(.*?)</script>',
                    page.text, re.S,
                ).group(1))
                self.assertEqual(configuration['baseUrl'], prefix + '/')
                self.assertEqual(configuration['eventsUrl'], prefix + '/village/events')
                self.assertIn(f'src="{prefix}/js/game.js"', page.text)
                self.assertNotIn('http://', configuration['baseUrl'])

    def test_language_defaults_to_spanish_and_rejects_unknown_values(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop('SOCIAL_EMPIRES_LANGUAGE', None)
            self.assertEqual(server.language_setting('SOCIAL_EMPIRES_LANGUAGE', 'es'), 'es')
            os.environ['SOCIAL_EMPIRES_LANGUAGE'] = 'pt-BR'
            self.assertEqual(server.language_setting('SOCIAL_EMPIRES_LANGUAGE', 'es'), 'pt-BR')
            os.environ['SOCIAL_EMPIRES_LANGUAGE'] = 'fr'
            with self.assertRaises(RuntimeError):
                server.language_setting('SOCIAL_EMPIRES_LANGUAGE', 'es')
        source = Path(server.__file__).read_text(encoding='utf-8')
        self.assertIn("GAME_LANGUAGE = language_setting('SOCIAL_EMPIRES_LANGUAGE', 'es')", source)

    def test_game_configuration_is_portuguese_with_bundled_font_language(self):
        self.create_player(status='approved')
        self.login()
        response = self.client.post(server.DYNAMIC_GAME_PREFIX + 'get_game_config.php', data=self.game_data())
        self.assertEqual(response.status_code, 200)
        configuration = response.json
        introduction = next(entry for entry in configuration['localization_strings'] if isinstance(entry, dict) and entry['name'] == 'TUTORIAL_INTRO_TITULO')
        self.assertEqual(introduction['text'], 'Boas-vindas ao seu império!')
        self.assertEqual(configuration['items'][0]['name'], 'Casa I')
        self.assertEqual(server.get_game_config()['items'][0]['name'], 'House I')
        self.assertEqual(sessions.save_info(self.game_data()['USERID'])['name'], 'Meu Império')

    def test_translated_movie_requires_login_and_supports_browser_range_requests(self):
        movie_url = server.STATIC_GAME_PREFIX + 'flash/' + server.GAME_VERSION
        self.assertEqual(self.client.get(movie_url).status_code, 401)
        self.create_player(status='approved')
        self.login()
        with self.client.get(movie_url) as response:
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.mimetype, 'application/x-shockwave-flash')
            movie = response.data
            checksum = response.headers['ETag']
        original = (Path(server.ASSETS_DIR) / 'flash' / server.GAME_VERSION).read_bytes()
        self.assertNotEqual(movie, original)
        with self.client.get(movie_url, headers={'Range': 'bytes=0-7'}) as partial:
            self.assertEqual(partial.status_code, 206)
            self.assertEqual(partial.data, movie[:8])
        with self.client.get(movie_url, headers={'If-None-Match': checksum}) as cached:
            self.assertEqual(cached.status_code, 304)

    def test_suspension_blocks_an_already_logged_in_player(self):
        player = self.create_player(status='approved')
        self.login()
        payload = self.game_data()
        self.store.set_status(player['id'], 'pending')
        self.assertEqual(self.client.post(server.DYNAMIC_GAME_PREFIX + 'get_player_info.php', data=payload).status_code, 403)
        self.assertEqual(self.client.get(server.STATIC_GAME_PREFIX + 'flash/SELoader.swf').status_code, 403)
        self.assertEqual(self.client.get('/play.html').status_code, 302)
        with self.client.session_transaction() as session:
            self.assertNotIn('account_id', session)

    def test_csrf_is_required_for_registration_login_logout_and_approval(self):
        self.assertEqual(self.client.post('/register', data={'name': 'Maria'}).status_code, 400)
        self.assertEqual(self.client.post('/login', data={'USERID': '1111', 'GAMEVERSION': server.GAME_VERSION}).status_code, 400)
        self.assertEqual(self.client.get('/logout').status_code, 405)
        self.create_admin()
        self.login('admin@example.com')
        player = self.create_player()
        self.assertEqual(self.client.post(f"/admin/accounts/{player['id']}", data={'action': 'approve'}).status_code, 400)
        self.assertEqual(self.store.get(player['id'])['status'], 'pending')
        self.assertEqual(self.client.post('/logout').status_code, 400)

    def test_admin_rejection_and_self_protection(self):
        admin = self.create_admin()
        player = self.create_player()
        self.login('admin@example.com')
        token = self.token()
        response = self.client.post(f"/admin/accounts/{player['id']}", data={
            'action': 'reject', 'csrf_token': token,
        }, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.store.get(player['id'])['status'], 'rejected')
        self.client.post(f"/admin/accounts/{admin['id']}", data={'action': 'suspend', 'csrf_token': token})
        self.assertEqual(self.store.get(admin['id'])['status'], 'approved')
        self.assertEqual(self.client.get('/admin?status=unknown').status_code, 400)
        rejected_client = server.app.test_client()
        self.assertIn('não foi liberado', self.login(client=rejected_client).text)

    def test_game_commands_still_persist_to_authenticated_save(self):
        self.create_player(status='approved')
        self.login()
        payload = self.game_data()
        packet = {
            'ts': 1, 'first_number': 1, 'accessToken': '', 'tries': 1,
            'publishActions': [], 'commands': [{'cmd': 'game_status', 'args': ['test']}],
        }
        payload['data'] = '0' * 64 + ';' + json.dumps(packet)
        response = self.client.post(server.DYNAMIC_GAME_PREFIX + 'command.php', data=payload)
        self.assertEqual(response.status_code, 200)
        saved = json.loads((self.save_path / (payload['USERID'] + '.save.json')).read_text())
        self.assertEqual(saved['playerInfo']['pid'], payload['USERID'])
        self.assertFalse(list(self.save_path.glob('*.tmp')))
        for malformed in ('', 'short', '0' * 64 + ';invalid', '0' * 64 + ';[]'):
            payload['data'] = malformed
            self.assertEqual(self.client.post(server.DYNAMIC_GAME_PREFIX + 'command.php', data=payload).status_code, 400)

    def test_missing_save_does_not_silently_reset_progress(self):
        player = self.create_player(status='approved')
        self.store.bind_village(player['id'], 'missing-save')
        response = self.login()
        self.assertEqual(response.status_code, 503)
        self.assertIn('restaurar o save', response.text)
        self.assertEqual(list(self.save_path.iterdir()), [])

    def test_admin_cli_has_no_default_and_existing_village_can_be_linked(self):
        with contextlib.redirect_stdout(io.StringIO()):
            village_id = sessions.new_village()
        result = server.app.test_cli_runner().invoke(args=[
            'create-admin', '--name', 'Admin', '--email', 'admin@example.com',
            '--password', 'secret-password', '--village-id', village_id,
        ])
        self.assertEqual(result.exit_code, 0, result.output)
        admin = self.store.authenticate('admin@example.com', 'secret-password')
        self.assertTrue(admin['is_admin'])
        self.assertEqual(admin['village_id'], village_id)
        result = server.app.test_cli_runner().invoke(args=[
            'create-admin', '--name', 'Outro', '--email', 'other@example.com',
            '--password', 'secret-password', '--village-id', village_id,
        ])
        self.assertNotEqual(result.exit_code, 0)
        self.assertEqual(len(self.store.list_accounts()), 1)

    def test_session_signing_key_survives_restart_and_rejects_corruption(self):
        with patch.object(server, 'data_dir', Path(self.directory.name)), patch.dict(os.environ, {'SECRET_KEY': ''}):
            key = server._secret_key()
            self.assertGreaterEqual(len(key), 32)
            self.assertEqual(server._secret_key(), key)
            (Path(self.directory.name) / 'secret_key').write_text('')
            with self.assertRaisesRegex(RuntimeError, 'inválida'):
                server._secret_key()


if __name__ == '__main__':
    unittest.main()
