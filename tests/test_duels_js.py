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
        result = subprocess.run([NODE, str(TESTS / 'duels_js_check.js'), mode], capture_output=True, text=True, encoding='utf-8', timeout=60)
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
        self.assertEqual(report['onlineName'], '[BET] Beto')  # clan tag next to the name
        self.assertTrue(report['onlineRival'])  # marked as a rival of the active clan challenge
        challenge = self.notice(report, 'clan_challenge')
        self.assertEqual((challenge['hidden'], challenge['text'].split(']')[0] + ']'), (False, '[clan_challenge]'))
        self.assertIn('[ALF] Alfa', challenge['text'])
        self.assertIn('[clan_challenge_accepted]', self.notice(report, 'clan_challenge_answer')['text'])
        # on the game page the clan notices open the in-game window instead of leaving the game
        self.assertEqual(report['openedClan'], ['challenges', 'clan'])
        self.assertIsNone(report['navigatedByClan'])
        self.assertFalse(report['gameRetired'])  # the tab that opened the arena keeps its game
        self.assertEqual(report['closedClan'], 1)  # the clan window closes when the arena opens

    def test_a_second_game_tab_stands_aside(self):
        report = self.run_page('aside')
        self.assertEqual(report['errors'], [])
        self.assertEqual(report['startDuel'], [])
        self.assertIn('[game_in_other_tab]', report['afterLaunch']['detail'])
        self.assertTrue(report['gameRetired'])  # its game closes: one copy of the village at a time

    def test_portal_page_does_not_open_a_second_game(self):
        report = self.run_page('portal-game-open')
        self.assertEqual(report['errors'], [])
        self.assertIsNone(report['navigated'])  # the open game tab opens the arena
        self.assertIn('[game_in_other_tab]', report['afterStart']['detail'])
        self.assertNotIn({'type': 'taking-over', 'id': 9}, report['broadcasts'])

    def test_a_game_tab_does_not_open_a_battle_another_tab_claimed(self):
        report = self.run_page('claimed')
        self.assertEqual(report['errors'], [])
        self.assertEqual(report['startDuel'], [])
        self.assertTrue(report['gameRetired'])
        self.assertIn('[game_in_other_tab]', report['afterLaunch']['detail'])
        self.assertNotIn('se-game-page', report['store'])  # its game closed: it no longer counts as an open game

    def test_portal_page_takes_the_player_to_the_game(self):
        report = self.run_page('portal')
        self.assertEqual(report['errors'], [])
        self.assertFalse(self.notice(report, 'challenge_received')['hidden'])
        self.assertEqual(report['startDuel'], [])
        self.assertEqual(report['navigated'], '/play.html')
        self.assertEqual(report['openedClan'], [])
        self.assertEqual(report['navigatedByClan'], '/clans/1')  # no game window here: the clan page
        self.assertIn({'type': 'taking-over', 'id': 9}, report['broadcasts'])


if __name__ == '__main__':
    unittest.main()
