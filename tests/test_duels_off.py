"""With SE_DUELS off (the default) the server is exactly as before the duels."""

import contextlib
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from auth import AccountStore

_boot_directory = tempfile.TemporaryDirectory(prefix='socialemperors-tests-')
with patch.dict(os.environ, {
    'SOCIAL_EMPIRES_DATA_DIR': _boot_directory.name,
    'SOCIAL_EMPIRES_LANGUAGE': 'pt-BR',
    'SOCIAL_EMPIRES_SAVES_DIR': str(Path(_boot_directory.name) / 'saves'),
}), contextlib.redirect_stdout(io.StringIO()):
    os.environ.pop('SE_DUELS', None)
    import server
    import sessions


class DuelsOffTests(unittest.TestCase):
    def test_switch_defaults_to_off_and_registers_nothing(self):
        self.assertFalse(server.DUELS_ENABLED)
        self.assertNotIn('duels', server.app.extensions)
        rules = {rule.rule for rule in server.app.url_map.iter_rules()}
        self.assertFalse({rule for rule in rules if 'duel' in rule or 'tournaments/' in rule})
        self.assertNotIn('duel_command_filter', server.app.extensions)  # game commands untouched
        self.assertNotIn('duels_page', server.app.view_functions)
        source = Path(server.__file__).read_text(encoding='utf-8')
        self.assertIn('threaded=DUELS_ENABLED', source)  # one request at a time while off

    def test_pages_show_no_duel_link_script_or_notice(self):
        directory = tempfile.TemporaryDirectory(prefix='socialemperors-off-')
        self.addCleanup(directory.cleanup)
        saves = patch.object(sessions, 'SAVES_DIR', str(Path(directory.name) / 'saves'))
        saves.start()
        self.addCleanup(saves.stop)
        with contextlib.redirect_stdout(io.StringIO()):
            sessions.load_saved_villages()
        store = AccountStore(Path(directory.name) / 'accounts.sqlite3')
        extension = patch.dict(server.app.extensions, {'accounts': store})
        extension.start()
        self.addCleanup(extension.stop)
        server.app.config.update(TESTING=True)
        client = server.app.test_client()
        store.create_admin('Administrador', 'admin@example.com', 'secret-password')
        client.get('/login')
        with client.session_transaction() as session:
            token = session['_csrf_token']
        with contextlib.redirect_stdout(io.StringIO()):
            client.post('/login', data={'email': 'admin@example.com', 'password': 'secret-password', 'csrf_token': token})
            for path in ('/play.html', '/treasury', '/rivals', '/admin', '/admin/villages'):
                with self.subTest(path=path):
                    page = client.get(path).get_data(as_text=True)
                    self.assertNotIn('duel', page.lower())
            self.assertEqual(client.get('/duels').status_code, 404)
            self.assertEqual(client.get('/admin/duels').status_code, 404)
            self.assertEqual(client.get('/css/duels.css').status_code, 200)  # a static file, linked from nowhere

    def test_game_config_keeps_the_original_tournaments(self):
        self.assertEqual(server.app.view_functions['get_game_config_response'].__name__, 'get_game_config_response')
        from get_game_config import get_game_config
        self.assertEqual(get_game_config('es')['tournament_type']['1']['weekly_tournaments'], 0)

    def test_switch_values(self):
        for value, expected in (('on', True), ('ON ', True), ('1', True), ('true', True), ('off', False), ('', False), ('no', False)):
            with self.subTest(value=value):
                self.assertEqual(value.strip().lower() in ('on', '1', 'true', 'yes'), expected)


if __name__ == '__main__':
    unittest.main()
