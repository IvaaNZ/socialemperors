"""Run the clan web checks with SE_CLANS=on in a child process; with clans off nothing changes."""

import contextlib
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

TESTS = Path(__file__).resolve().parent


class ClanWebSuite(unittest.TestCase):
    def test_clan_web_checks_pass_with_clans_on(self):
        env = {**os.environ, 'SE_CLANS': 'on', 'PYTHONPATH': os.pathsep.join([str(TESTS.parent), str(TESTS)])}
        env.pop('SE_DUELS', None)
        result = subprocess.run([sys.executable, '-m', 'unittest', '-v', 'clans_web_checks'], cwd=TESTS.parent,
                                env=env, capture_output=True, text=True, timeout=300)
        self.assertEqual(result.returncode, 0, result.stderr[-4000:])
        self.assertIn('OK', result.stderr)


_boot_directory = tempfile.TemporaryDirectory(prefix='socialemperors-tests-')
with patch.dict(os.environ, {
    'SOCIAL_EMPIRES_DATA_DIR': _boot_directory.name,
    'SOCIAL_EMPIRES_LANGUAGE': 'pt-BR',
    'SOCIAL_EMPIRES_SAVES_DIR': str(Path(_boot_directory.name) / 'saves'),
}), contextlib.redirect_stdout(io.StringIO()):
    os.environ.pop('SE_CLANS', None)
    import server


class ClansOffTests(unittest.TestCase):
    def test_switch_defaults_to_off_and_registers_nothing(self):
        self.assertFalse(server.CLANS_ENABLED)
        self.assertNotIn('clans', server.app.extensions)
        rules = {rule.rule for rule in server.app.url_map.iter_rules()}
        self.assertFalse({rule for rule in rules if 'clan' in rule})
        self.assertFalse(server.app.jinja_env.globals['clans_enabled'])

    def test_pages_show_no_clan_link(self):
        from auth import AccountStore
        import sessions
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
                    page = client.get(path).get_data(as_text=True).lower()
                    self.assertNotIn('/clans', page)
                    self.assertNotIn('clãs', page)
            self.assertEqual(client.get('/clans').status_code, 404)


if __name__ == '__main__':
    unittest.main()
