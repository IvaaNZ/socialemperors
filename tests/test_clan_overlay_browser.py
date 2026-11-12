"""The in-game clan window in a real browser (headless Chrome or Edge): typed text survives redraws.

Opens tests/clan_overlay_browser.html, which runs templates/js/clan_overlay.js with a fake
server. Skipped when neither Chrome nor Edge is installed.
"""

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

TESTS = Path(__file__).resolve().parent
CANDIDATES = [shutil.which('chrome'), shutil.which('google-chrome'), shutil.which('chromium'), shutil.which('msedge'),
              r'C:\Program Files\Google\Chrome\Application\chrome.exe',
              r'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe',
              r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe']
BROWSER = next((path for path in CANDIDATES if path and os.path.exists(path)), None)


@unittest.skipUnless(BROWSER, 'Chrome or Edge is not installed')
class ClanOverlayBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        profile = tempfile.TemporaryDirectory(prefix='clan-overlay-browser-')
        cls.addClassCleanup(profile.cleanup)
        page = (TESTS / 'clan_overlay_browser.html').as_uri()
        result = subprocess.run([BROWSER, '--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
                                 f'--user-data-dir={profile.name}', '--allow-file-access-from-files',
                                 '--virtual-time-budget=15000', '--dump-dom', page],
                                capture_output=True, text=True, encoding='utf-8', timeout=120)
        match = re.search(r'<pre id="result">(.*?)</pre>', result.stdout, re.S)
        if not match:
            raise AssertionError('no result from the browser: ' + result.stderr[-2000:])
        text = match.group(1).replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>').replace('&quot;', '"')
        if text == 'pending':
            raise AssertionError('the page did not finish')
        cls.report = json.loads(text)

    def test_no_error(self):
        self.assertNotIn('error', self.report, self.report.get('error'))

    def test_create_form_keeps_what_was_typed(self):
        self.assertTrue(self.report['stateReloaded'])  # the redraws really happened
        self.assertEqual((self.report['name'], self.report['tag'], self.report['emblem']), ('Los Ñandúes', 'NA', '7'))
        self.assertTrue(self.report['focusKept'])

    def test_creating_still_works(self):
        self.assertTrue(self.report['created'])
        self.assertTrue(self.report['onClanTab'])
        self.assertTrue(self.report['editOpen'])

    def test_chat_keeps_the_draft_and_has_no_delete(self):
        self.assertTrue(self.report['chatHasMessage'])
        self.assertTrue(self.report['chatDraftKept'])
        self.assertTrue(self.report['noDelete'])


if __name__ == '__main__':
    unittest.main()
