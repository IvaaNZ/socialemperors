"""Flash parameters the game page passes to the SWF (templates/js/game.js)."""

from pathlib import Path
import re
import unittest

GAME_JS = (Path(__file__).resolve().parents[1] / 'templates' / 'js' / 'game.js').read_text(encoding='utf-8')


class FlashvarsTests(unittest.TestCase):
    def test_achievement_permission_counts_as_granted(self):
        # Without it, from level 10 the game shows the Facebook-only "More achievements" hand.
        self.assertRegex(GAME_JS, r'publishActions:\s*"1"')

    def test_achievement_post_command_is_handled(self):
        source = (Path(__file__).resolve().parents[1] / 'command.py').read_text(encoding='utf-8')
        self.assertTrue(re.search(r'elif cmd == Constant\.CMD_RT_PUBLISH_ACHIEVEMENT_UNIT:', source))


if __name__ == '__main__':
    unittest.main()
