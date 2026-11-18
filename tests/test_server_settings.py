import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from server_settings import SETTINGS_FILE, describe, load_settings_file, parse_settings

ROOT = Path(__file__).resolve().parent.parent


class ServerSettingsFile(unittest.TestCase):
    def test_parse_keeps_key_value_lines_and_skips_comments(self):
        settings, errors = parse_settings('# a comment\n\nSE_PVP=on\n  SE_CLANS = off  \nPORT="5051"\nnot a line\n')
        self.assertEqual(settings, {'SE_PVP': 'on', 'SE_CLANS': 'off', 'PORT': '5051'})
        self.assertEqual(errors, [6])

    def test_a_comment_glued_to_a_value_is_not_part_of_it(self):
        settings, errors = parse_settings('SE_COOP=on# the next comment\nSE_PVP = off #why\nPORT="50#51"\n')
        self.assertEqual(settings, {'SE_COOP': 'on', 'SE_PVP': 'off', 'PORT': '50#51'})
        self.assertEqual(errors, [])

    def test_the_file_fills_the_environment_but_the_console_wins(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'server.env'
            path.write_text('﻿SE_DUELS=on\nSE_PVP=on\n', encoding='utf-8')
            environ = {'SE_PVP': 'off'}
            applied = load_settings_file(str(path), environ)
        self.assertEqual(environ, {'SE_DUELS': 'on', 'SE_PVP': 'off'})
        self.assertEqual(applied, {'SE_DUELS': ('on', 'file'), 'SE_PVP': ('off', 'console')})
        self.assertEqual(describe(applied), 'SE_DUELS=on, SE_PVP=off')
        self.assertEqual(load_settings_file(str(Path(directory) / 'missing.env'), {}), {})

    def test_the_shipped_file_turns_every_feature_on(self):
        settings, errors = parse_settings((ROOT / SETTINGS_FILE).read_text(encoding='utf-8'))
        self.assertEqual(errors, [])
        for switch in ('SE_DUELS', 'SE_CLANS', 'SE_ABILITIES', 'SE_PVP', 'SE_DAILY_DARTS', 'SE_EMPIRE_NAME',
                       'SE_READABLE_UI', 'SE_SOUND_FIX', 'SE_AUTO_APPROVE', 'SE_VILLAGE_COMMANDS'):
            self.assertEqual(settings.get(switch), 'on', switch)

    def test_python_server_py_reads_it_before_the_switches_and_importing_server_does_not(self):
        source = (ROOT / 'server.py').read_text(encoding='utf-8')
        load = source.index('load_settings_file()')
        self.assertLess(load, source.index("os.environ.get('SE_"))
        self.assertLess(load, source.index('from get_game_config import'))
        main = source.index("if __name__ == '__main__':")
        self.assertLess(main, source.index('# The switches in server.env'))
        self.assertLess(main, load)
        # the update watcher (SE_AUTO_UPDATE) takes over after server.env and before the game is loaded
        self.assertLess(load, source.index('updater.supervise(_console_env)'))
        self.assertLess(source.index('updater.supervise(_console_env)'), source.index('from get_game_config import'))
        # A plain import (the tests, "flask --app server ...") keeps the built-in defaults.
        script = ("import contextlib, io, os, sys; sys.path.insert(0, '.');"
                  "f = io.StringIO();\n"
                  "with contextlib.redirect_stdout(f): import server\n"
                  "print(os.environ.get('SE_PVP'), server.PVP_ENABLED)")
        environment = {key: value for key, value in os.environ.items() if not key.startswith('SE_')}
        with tempfile.TemporaryDirectory() as directory:
            environment.update(SOCIAL_EMPIRES_DATA_DIR=directory, SOCIAL_EMPIRES_SAVES_DIR=str(Path(directory) / 'saves'))
            result = subprocess.run([sys.executable, '-c', script], cwd=ROOT, env=environment,
                                    capture_output=True, text=True, timeout=300)
        self.assertEqual(result.stdout.strip().splitlines()[-1], 'None False', result.stderr[-2000:])


if __name__ == '__main__':
    unittest.main()
