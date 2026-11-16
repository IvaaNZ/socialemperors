import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import updater


class FakeProcess:
    def __init__(self, args, env):
        self.args, self.env = args, env
        self.returncode = None
        self.stopped = False

    def poll(self):
        return self.returncode

    def terminate(self):
        self.stopped = True
        self.returncode = 0

    def kill(self):
        self.terminate()

    def wait(self, timeout=None):
        return self.returncode


class Updates(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.commit = 'a' * 40
        self.tests_ok = True
        self.trial_ok = True
        self.settings = b'SE_PVP=on\n'
        self.started = []  # (kind, process): 'server' or 'trial'
        self.test_runs = 0
        self.now = 1000.0
        self.watcher = updater.Watcher({'SOCIAL_EMPIRES_DATA_DIR': folder.name, 'PORT': '5050', 'SE_PVP': 'off'},
                                       clock=self.clock, sleep=self.sleep, run=self.fake_run, popen=self.fake_popen)
        self.watcher.answers = lambda port, host='127.0.0.1': (
            self.trial_ok if port != 5050 else True)
        patch.object(updater.Watcher, 'current_settings', lambda _: self.settings).start()
        self.addCleanup(patch.stopall)
        self.log = Path(folder.name) / 'actualizaciones.log'

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds

    def fake_run(self, args, **options):
        if args[:2] == ['git', 'rev-parse']:
            return subprocess.CompletedProcess(args, 0, stdout=self.commit + '\n', stderr='')
        self.test_runs += 1
        self.assertEqual(options['env']['SE_SERVER_CHILD'], '1')
        if self.tests_ok:
            return subprocess.CompletedProcess(args, 0, stdout='', stderr='Ran 486 tests in 160s\n\nOK\n')
        return subprocess.CompletedProcess(args, 1, stdout='', stderr='FAIL: test_x (tests.test_y)\nRan 486 tests\nFAILED (failures=1)\n')

    def fake_popen(self, args, env, **options):
        process = FakeProcess(args, env)
        self.started.append(('trial' if env.get('SE_BUILD') == 'prueba' else 'server', process))
        return process

    def servers(self):
        return [process for kind, process in self.started if kind == 'server']

    def test_a_new_commit_that_passes_replaces_the_server_with_a_new_build(self):
        self.watcher.commit, self.watcher.settings = self.commit, self.settings
        self.watcher.start()
        first = self.servers()[0]
        self.assertEqual(first.env['SE_SERVER_CHILD'], '1')
        self.assertEqual(first.env['SE_PVP'], 'off')  # the console's values: the child reads server.env itself
        self.assertIsNone(self.watcher.check())  # nothing new
        self.commit = 'b' * 40
        self.now += 60
        self.assertEqual(self.watcher.check(), 'updated')
        trial = [process for kind, process in self.started if kind == 'trial'][0]
        self.assertNotEqual(trial.env['PORT'], '5050')  # the trial never touches the real port or data
        self.assertNotEqual(trial.env['SOCIAL_EMPIRES_DATA_DIR'], self.watcher.console_env['SOCIAL_EMPIRES_DATA_DIR'])
        self.assertTrue(trial.stopped and first.stopped)
        second = self.servers()[1]
        self.assertTrue(second.env['SE_BUILD'].startswith('bbbbbbbbbbbb-'))
        self.assertNotEqual(second.env['SE_BUILD'], first.env['SE_BUILD'])
        self.assertEqual(self.watcher.commit, self.commit)
        self.assertIn('actualización aprobada', self.log.read_text(encoding='utf-8'))

    def test_failing_tests_or_start_keep_the_running_server_and_are_not_retried(self):
        self.watcher.commit, self.watcher.settings = self.commit, self.settings
        self.watcher.start()
        running = self.servers()[0]
        self.commit, self.tests_ok = 'c' * 40, False
        self.assertEqual(self.watcher.check(), 'rejected')
        self.assertFalse(running.stopped)
        self.assertIsNone(self.watcher.check())  # the same commit is not tried again
        self.assertEqual(self.test_runs, 1)
        self.commit, self.tests_ok, self.trial_ok = 'd' * 40, True, False
        self.assertEqual(self.watcher.check(), 'rejected')
        self.assertFalse(running.stopped)
        self.assertEqual(len(self.servers()), 1)
        self.assertIn('FAIL: test_x', self.log.read_text(encoding='utf-8'))

    def test_a_changed_server_env_needs_only_the_trial_start(self):
        self.watcher.commit, self.watcher.settings = self.commit, self.settings
        self.watcher.start()
        self.settings = b'SE_PVP=off\n'
        self.assertEqual(self.watcher.check(), 'updated')
        self.assertEqual(self.test_runs, 0)
        self.assertEqual(len(self.servers()), 2)

    def test_a_server_that_stops_is_started_again(self):
        self.watcher.commit, self.watcher.settings = self.commit, self.settings
        self.watcher.start()
        self.servers()[0].returncode = 1
        self.assertEqual(self.watcher.check(), 'restarted')
        self.assertEqual(len(self.servers()), 2)

    def test_listening_everywhere_is_checked_locally(self):
        self.assertEqual(updater.Watcher({'HOST': '0.0.0.0'}, run=self.fake_run).host, '127.0.0.1')


class VersionPage(unittest.TestCase):
    def test_the_server_tells_its_build_and_the_game_page_watches_it(self):
        import server
        response = server.app.test_client().get('/version')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {'build': server.SERVER_BUILD})
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        script = (Path(server.TEMPLATES_DIR) / 'js' / 'game.js').read_text(encoding='utf-8')
        self.assertIn('UPDATE_SECONDS = 10', script)
        page = (Path(server.TEMPLATES_DIR) / 'play.html').read_text(encoding='utf-8')
        self.assertIn('id="update-restart"', page)


if __name__ == '__main__':
    unittest.main()
