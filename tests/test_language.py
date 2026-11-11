"""Per-account language: chosen on the login page, saved, and used by portal and game."""

import contextlib
import io
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

from auth import AccountError, AccountStore

_boot_directory = tempfile.TemporaryDirectory(prefix='socialemperors-tests-')
with patch.dict(os.environ, {
    'SOCIAL_EMPIRES_DATA_DIR': _boot_directory.name,
    'SOCIAL_EMPIRES_LANGUAGE': 'pt-BR',  # Server default in these tests.
    'SOCIAL_EMPIRES_SAVES_DIR': str(Path(_boot_directory.name) / 'saves'),
}), contextlib.redirect_stdout(io.StringIO()):
    import server
    import sessions


class LanguageTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='socialemperors-language-')
        self.addCleanup(self.directory.cleanup)
        saves = patch.object(sessions, 'SAVES_DIR', str(Path(self.directory.name) / 'saves'))
        saves.start()
        self.addCleanup(saves.stop)
        with contextlib.redirect_stdout(io.StringIO()):
            sessions.load_saved_villages()
        self.store = AccountStore(Path(self.directory.name) / 'accounts.sqlite3')
        extension = patch.dict(server.app.extensions, {'accounts': self.store})
        extension.start()
        self.addCleanup(extension.stop)
        language = patch.object(server, 'GAME_LANGUAGE', 'pt-BR')
        language.start()
        self.addCleanup(language.stop)
        server.app.config.update(TESTING=True)
        self.client = server.app.test_client()
        self.stdout = contextlib.redirect_stdout(io.StringIO())
        self.stdout.__enter__()
        self.addCleanup(self.stdout.__exit__, None, None, None)

    def token(self):
        self.client.get('/login')
        with self.client.session_transaction() as session:
            return session['_csrf_token']

    def choose(self, language, next_path='/login'):
        return self.client.post('/language', data={'language': language, 'next': next_path, 'csrf_token': self.token()})

    def login(self, email='player@example.com'):
        return self.client.post('/login', data={'email': email, 'password': 'secret-password', 'csrf_token': self.token()})

    def game_config(self):
        with self.client.session_transaction() as session:
            data = {'USERID': session['USERID'], 'user_key': session['_csrf_token'], 'language': 'en', 'client_id': 'test'}
        response = self.client.post(server.DYNAMIC_GAME_PREFIX + 'get_game_config.php', data=data)
        self.assertEqual(response.status_code, 200)
        return response.get_json()

    def test_login_page_uses_the_server_default_until_a_language_is_chosen(self):
        page = self.client.get('/login').get_data(as_text=True)
        self.assertIn('<html lang="pt-BR" translate="no">', page)
        self.assertIn('Entre na sua vila', page)
        self.assertIn('name="language"', page)
        response = self.choose('es')
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers['Location'].endswith('/login'))
        page = self.client.get('/login').get_data(as_text=True)
        self.assertIn('<html lang="es" translate="no">', page)
        self.assertIn('Entra a tu aldea', page)

    def test_choice_on_the_login_page_is_saved_and_drives_the_game(self):
        player = self.store.create_account('Jogador', 'player@example.com', 'secret-password', status='approved')
        self.assertIsNone(player['language'])
        self.choose('es')
        self.assertEqual(self.login().status_code, 302)
        self.assertEqual(self.store.get(player['id'])['language'], 'es')
        self.assertEqual(self.game_config()['items'][0]['name'], 'Casa I')
        self.assertIn('<html lang="es" translate="no">', self.client.get('/play.html').get_data(as_text=True))

        # A new browser session starts from the saved account language.
        self.client = server.app.test_client()
        self.login()
        self.assertIn('Mi aldea', self.client.get('/treasury').get_data(as_text=True))

        # Switching while logged in updates the account at once.
        self.choose('pt-BR', '/treasury')
        self.assertEqual(self.store.get(player['id'])['language'], 'pt-BR')
        self.assertIn('Minha vila', self.client.get('/treasury').get_data(as_text=True))

    def test_each_language_gets_its_own_game_movie(self):
        player = self.store.create_account('Jogador', 'player@example.com', 'secret-password', status='approved')
        self.login()
        movie_url = server.STATIC_GAME_PREFIX + 'flash/' + server.GAME_VERSION
        portuguese = self.client.get(movie_url)
        self.assertEqual(portuguese.headers['Cache-Control'], 'private, no-cache')
        self.store.set_language(player['id'], 'es')
        spanish = self.client.get(movie_url, headers={'If-None-Match': portuguese.headers['ETag']})
        self.assertEqual(spanish.status_code, 200)
        self.assertNotEqual(spanish.headers['ETag'], portuguese.headers['ETag'])
        self.assertEqual(spanish.data, server.localized_game_movie('es')[0])

    def test_english_portal_and_original_english_game(self):
        self.choose('en')
        page = self.client.get('/login').get_data(as_text=True)
        self.assertIn('<html lang="en" translate="no">', page)
        self.assertIn('Enter your village', page)
        self.assertIn('flags/us.svg', page)
        player = self.store.create_account('Jogador', 'player@example.com', 'secret-password', status='approved')
        self.login()
        self.assertEqual(self.store.get(player['id'])['language'], 'en')
        self.assertEqual(self.game_config()['items'][0]['name'], 'House I')
        self.assertIn('My village', self.client.get('/treasury').get_data(as_text=True))

    def test_selector_offers_each_language_with_its_flag(self):
        page = self.client.get('/login').get_data(as_text=True)
        for code, name, flag in (('es', 'Español', 'es.svg'), ('pt-BR', 'Português', 'br.svg'), ('en', 'English', 'us.svg')):
            with self.subTest(code=code):
                self.assertIn(f'value="{code}"', page)
                self.assertIn(f'<span>{name}</span>', page)
                self.assertIn(f'flags/{flag}', page)
                self.assertEqual(self.client.get(f'/img/flags/{flag}').mimetype, 'image/svg+xml')
        self.assertIn('aria-pressed="true"', page)
        self.assertEqual(page.count('class="language-toggle"'), 1)
        self.assertIn('<span>Idioma</span>', page)

    def test_unknown_pages_show_a_translated_message(self):
        self.choose('es')
        response = self.client.get('/no-existe')
        self.assertEqual(response.status_code, 404)
        page = response.get_data(as_text=True)
        self.assertIn('Esta página no existe.', page)
        self.assertNotIn('The requested URL was not found', page)

    def test_admin_addresses_lead_to_the_accounts_page(self):
        self.assertEqual(self.client.get('/admin/').status_code, 403)
        self.store.create_admin('Administrador', 'admin@example.com', 'secret-password')
        self.login('admin@example.com')
        for path in ('/admin/', '/admin/accounts', '/admin/accounts/1'):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 302)
                self.assertTrue(response.headers['Location'].endswith('/admin'))
        self.assertEqual(self.client.get('/admin').status_code, 200)

    def test_registration_keeps_the_chosen_language(self):
        self.choose('es')
        self.client.post('/register', data={
            'name': 'Maria', 'email': 'maria@example.com', 'password': 'secret-password',
            'password_confirm': 'secret-password', 'csrf_token': self.token(),
        })
        account = next(a for a in self.store.list_accounts() if a['email'] == 'maria@example.com')
        self.assertEqual(account['language'], 'es')

    def test_invalid_language_and_unsafe_redirects_are_rejected(self):
        self.assertEqual(self.choose('fr').status_code, 400)
        for target in ('https://example.com/', '//example.com/', '/\\example.com'):
            with self.subTest(target=target):
                location = self.choose('es', target).headers['Location']
                self.assertNotIn('example.com', location)
                self.assertIn(urlsplit(location).netloc, ('', 'localhost'))
        self.assertEqual(self.client.post('/language', data={'language': 'es'}).status_code, 400)
        with self.assertRaises(AccountError):
            self.store.create_account('Maria', 'm@example.com', 'secret-password', language='fr')

    def test_existing_database_gains_the_language_column(self):
        path = Path(self.directory.name) / 'old.sqlite3'
        connection = sqlite3.connect(path)
        with connection:
            connection.execute('''CREATE TABLE accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
                is_admin INTEGER NOT NULL DEFAULT 0, village_id TEXT UNIQUE, created_at TEXT NOT NULL)''')
            connection.execute("INSERT INTO accounts (name, email, password_hash, status, created_at) "
                               "VALUES ('Old', 'old@example.com', 'x', 'approved', '2026-01-01T00:00:00+00:00')")
        connection.close()
        store = AccountStore(path)
        account = store.list_accounts()[0]
        self.assertIsNone(account['language'])
        self.assertEqual(store.set_language(account['id'], 'es')['language'], 'es')


if __name__ == '__main__':
    unittest.main()
