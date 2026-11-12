"""Run the live duel checks (real threaded server, WebSockets) with SE_DUELS=on in a child process."""

import os
from pathlib import Path
import subprocess
import sys
import unittest

TESTS = Path(__file__).resolve().parent


class LiveDuelSuite(unittest.TestCase):
    def test_live_duel_checks_pass_with_duels_on(self):
        env = {**os.environ, 'SE_DUELS': 'on', 'SE_DUEL_MIN_SECONDS': '0.5', 'PYTHONPATH': os.pathsep.join([str(TESTS.parent), str(TESTS)])}
        result = subprocess.run([sys.executable, '-m', 'unittest', '-v', 'duels_live_checks'], cwd=TESTS.parent,
                                env=env, capture_output=True, text=True, timeout=300)
        self.assertEqual(result.returncode, 0, result.stderr[-4000:])
        self.assertIn('OK', result.stderr)


if __name__ == '__main__':
    unittest.main()
