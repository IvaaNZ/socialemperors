"""The duel page script (templates/js/duels.js) handles every server message without errors.

Runs tests/duels_js_check.js in Node with a fake DOM; skipped when Node is not installed.
"""

import json
from pathlib import Path
import shutil
import subprocess
import unittest

TESTS = Path(__file__).resolve().parent
NODE = shutil.which('node')


@unittest.skipUnless(NODE, 'Node.js is not installed')
class DuelScriptTests(unittest.TestCase):
    def run_page(self, mode):
        result = subprocess.run([NODE, str(TESTS / 'duels_js_check.js'), mode], capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout.strip().splitlines()[-1])

    def notice(self, report, kind):
        return next(n for n in reversed(report['notices']) if n['type'] == kind)

    def test_game_page_shows_every_message_and_opens_the_arena(self):
        report = self.run_page('game')
        self.assertEqual(report['errors'], [])
        received = self.notice(report, 'challenge_received')
        self.assertFalse(received['hidden'])
        self.assertIn('[received]', received['text'])
        self.assertEqual(len(report['startDuel']), 1)  # the arena opens once
        self.assertIn('[arena_help]', report['afterLaunch']['detail'])  # not "opens in your other tab"
        self.assertEqual(report['startDuel'][0][:4], [9, 1, 2, 'Beto'])
        self.assertEqual(report['startDuel'][0][4:], [[509], [510], 'Ana'])
        self.assertIn({'type': 'launched', 'id': 9}, report['broadcasts'])
        self.assertIn('[time_left]', self.notice(report, 'duel_waiting')['detail'])
        results = [n['text'] for n in report['notices'] if n['type'] == 'duel_result']
        self.assertEqual([text.split(']')[0] + ']' for text in results], ['[won]', '[review]', '[void]'])
        self.assertIn({'type': 'seen', 'id': 9}, report['sent'])
        self.assertIsNone(report['navigated'])

    def test_a_second_game_tab_stands_aside(self):
        report = self.run_page('aside')
        self.assertEqual(report['errors'], [])
        self.assertEqual(report['startDuel'], [])
        self.assertIn('[game_in_other_tab]', report['afterLaunch']['detail'])

    def test_portal_page_takes_the_player_to_the_game(self):
        report = self.run_page('portal')
        self.assertEqual(report['errors'], [])
        self.assertFalse(self.notice(report, 'challenge_received')['hidden'])
        self.assertEqual(report['startDuel'], [])
        self.assertEqual(report['navigated'], '/play.html')
        self.assertIn({'type': 'taking-over', 'id': 9}, report['broadcasts'])


if __name__ == '__main__':
    unittest.main()
