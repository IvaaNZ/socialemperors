"""The in-game clan window views (templates/js/clan_overlay.js), rendered in Node.

Skipped when Node.js is not installed.
"""

import json
from pathlib import Path
import re
import shutil
import subprocess
import unittest

TESTS = Path(__file__).resolve().parent
NODE = shutil.which('node')


@unittest.skipUnless(NODE, 'Node.js is not installed')
class ClanOverlayViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        result = subprocess.run([NODE, str(TESTS / 'clan_overlay_check.js')], capture_output=True, text=True, encoding='utf-8', timeout=60)
        if result.returncode:
            raise AssertionError(result.stderr)
        cls.out = json.loads(result.stdout)

    def every_html(self):
        def walk(value):
            if isinstance(value, str):
                yield value
            elif isinstance(value, dict):
                for item in value.values():
                    yield from walk(item)
            elif isinstance(value, list):
                for item in value:
                    yield from walk(item)
        return [html for html in walk({k: v for k, v in self.out.items() if k != 'keys'})]

    def test_player_text_is_always_escaped(self):
        for html in self.every_html():
            self.assertNotIn('<img src=x', html)
        self.assertIn('&lt;img src=x onerror=alert(1)&gt;', self.out['master']['clan'])
        self.assertIn('segunda línea', self.out['master']['clan'])
        self.assertIn('<br>', self.out['master']['clan'])  # announcement line breaks

    def test_no_missing_text_or_value(self):
        for html in self.every_html():
            self.assertNotIn('undefined', html)
            self.assertNotIn('NaN', html)
            self.assertNotIn('[object', html)

    def test_buttons_follow_the_role(self):
        master, assist, member = self.out['master'], self.out['assist'], self.out['member']
        self.assertIn('data-action="edit"', master['clan'])
        self.assertIn('data-action="dissolve"', master['clan'])
        self.assertNotIn('data-action="leave"', master['clan'])  # the Guild Master hands over the lead first
        for other in (assist, member):
            self.assertNotIn('data-action="edit"', other['clan'])
            self.assertIn('data-action="leave"', other['clan'])
        self.assertIn('data-form="settings"', master['edit'])
        self.assertNotIn('data-form="settings"', assist['edit'])
        self.assertIn('data-action="make_assist"', master['members'])
        self.assertIn('data-action="transfer"', master['members'])
        self.assertIn('data-action="accept_request"', assist['members'])
        self.assertNotIn('data-action="transfer"', assist['members'])
        self.assertEqual(len(re.findall('data-action="kick"', assist['members'])), 1)  # only the plain member
        self.assertNotIn('data-action="kick"', member['members'])
        self.assertNotIn('data-action="accept_request"', member['members'])
        self.assertIn('data-action="surrender"', master['challenges'])
        self.assertNotIn('data-action="surrender"', assist['challenges'])

    def test_challenge_views(self):
        active = self.out['master']['challenges']
        self.assertIn('[ALF] 2 – 1 [BET]', active)
        self.assertIn('href="/duels"', active)
        self.assertIn('is-won', active)
        self.assertIn('[by_majority]', active)
        self.assertIn('[expired]', active)
        self.assertIn('data-action="accept_challenge"', self.out['pendingIncoming'])
        self.assertIn('data-action="cancel_challenge"', self.out['pendingOutgoing'])
        self.assertNotIn('data-action="accept_challenge"', self.out['pendingOutgoing'])

    def test_views_without_a_clan_and_other_clans(self):
        no_clan = self.out['noClan']
        self.assertIn('data-tab="create"', no_clan['tabs'])
        self.assertNotIn('data-tab="members"', no_clan['tabs'])
        self.assertIn('data-form="create"', no_clan['create'])
        self.assertEqual(no_clan['create'].count('name="emblem"'), 12)
        self.assertIn('data-action="open_clan"', no_clan['find'])
        self.assertIn('[loading]', no_clan['findLoading'])
        self.assertIn('data-action="join"', no_clan['card'])  # an open clan: join at once
        self.assertIn('[join]', no_clan['card'])
        self.assertIn('[no_ranking]', no_clan['ranking'])
        self.assertIn('data-form="challenge"', self.out['cardForMaster'])
        self.assertNotIn('data-action="join"', self.out['cardForMaster'])  # already in a clan

    def test_chat_and_alliance_views(self):
        out = self.out
        self.assertIn('data-tab="chat"', out['master']['tabs'])
        self.assertIn('data-channel="alliance"', out['chatClan'])  # an active alliance adds the shared channel
        self.assertNotIn('data-channel="alliance"', out['chatEmpty'])
        self.assertIn('data-form="chat"', out['chatClan'])
        self.assertEqual(out['chatClan'].count('data-action="delete_message"'), 1)  # only where allowed
        self.assertIn('[no_messages]', out['chatEmpty'])
        self.assertIn('[loading]', out['chatLoading'])
        self.assertIn('is-mine', out['chatClan'])
        self.assertRegex(out['chatClan'], r'<small>\d\d:\d\d</small>')
        self.assertIn('data-action="end_alliance"', out['alliedClan'])
        self.assertIn('[ally]', out['alliedClan'])
        self.assertIn('data-action="accept_alliance"', out['allianceIncoming'])
        self.assertIn('data-action="cancel_alliance"', out['allianceOutgoing'])
        self.assertNotIn('data-action="end_alliance"', out['allianceMemberView'])
        self.assertIn('data-action="propose_alliance"', out['cardAlly'])
        self.assertIn('[allied_label]', out['cardAllied'])
        self.assertNotIn('data-form="challenge"', out['cardAllied'])  # allies do not challenge each other

    def test_twelve_distinct_emblems(self):
        self.assertEqual(len(set(self.out['emblems'])), 12)
        for svg in self.out['emblems']:
            self.assertTrue(svg.startswith('<svg class="clanx-emblem"'))

    def test_power_uses_the_viewer_separator(self):
        self.assertIn('123.456', self.out['master']['clan'])


if __name__ == '__main__':
    unittest.main()
