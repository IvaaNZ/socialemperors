"""Test names and real two-player raid transfers through authenticated HTTP."""

import contextlib
import copy
from html.parser import HTMLParser
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from auth import AccountStore
from pvp import RaidService

_boot_directory = tempfile.TemporaryDirectory(prefix='socialemperors-community-boot-')
with patch.dict(os.environ, {
    'SOCIAL_EMPIRES_DATA_DIR': _boot_directory.name,
    'SOCIAL_EMPIRES_LANGUAGE': 'pt-BR',  # These tests cover the Portuguese texts.
    'SOCIAL_EMPIRES_SAVES_DIR': str(Path(_boot_directory.name) / 'saves'),
}), contextlib.redirect_stdout(io.StringIO()):
    import server
    import sessions


class Forms(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.forms = {}
        self.current = None
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'form':
            self.current = self.forms.setdefault(attrs.get('action'), {})
        elif tag == 'input' and self.current is not None and 'name' in attrs:
            self.current[attrs['name']] = attrs.get('value', '')

    def handle_endtag(self, tag):
        if tag == 'form':
            self.current = None


class CommunityTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix='socialemperors-community-')
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name)
        self.saves_path = self.path / 'saves'
        patcher = patch.object(sessions, 'SAVES_DIR', str(self.saves_path))
        patcher.start()
        self.addCleanup(patcher.stop)
        with contextlib.redirect_stdout(io.StringIO()):
            sessions.load_saved_villages()
        self.accounts = AccountStore(self.path / 'accounts.sqlite3')
        self.raids = RaidService(self.path / 'raids.sqlite3')
        patcher = patch.dict(server.app.extensions, {'accounts': self.accounts, 'raids': self.raids})
        patcher.start()
        self.addCleanup(patcher.stop)
        server.app.config.update(TESTING=True)
        self.alice, self.alice_id = self.player('alice')
        self.bob, self.bob_id = self.player('bob', units=1)

    @staticmethod
    def csrf(client):
        with client.session_transaction() as browser_session:
            return browser_session['_csrf_token']

    def player(self, name, units=5):
        self.accounts.create_account(name.title(), name + '@example.test', 'test-password', status='approved')
        client = server.app.test_client()
        client.get('/login')
        with contextlib.redirect_stdout(io.StringIO()):
            response = client.post('/login', data={
                'email': name + '@example.test', 'password': 'test-password', 'csrf_token': self.csrf(client),
            })
        self.assertEqual(response.status_code, 302)
        with client.session_transaction() as browser_session:
            userid = browser_session['USERID']
        save = sessions.session(userid)
        save['playerInfo']['map_names'][0] = 'Vila ' + name.title()
        save['playerInfo']['completed_tutorial'] = 1
        save['maps'][0].update({
            'coins': 1000, 'wood': 500, 'food': 200, 'stone': 9,
            'items': [[512, index, 0, 0, 0, 0] for index in range(units)],
        })
        with contextlib.redirect_stdout(io.StringIO()):
            sessions.save_session(userid)
        return client, userid

    def attack_form(self, client=None, defender=None):
        client = client or self.alice
        path = f'/rivals/{defender or self.bob_id}/raid'
        response = client.get('/rivals')
        self.assertEqual(response.status_code, 200)
        return path, Forms(response.text).forms[path]

    def test_community_routes_require_an_approved_owned_session(self):
        anonymous = server.app.test_client()
        for route in ('/village', '/village/events', '/rivals'):
            self.assertEqual(anonymous.get(route).status_code, 302)
        route, form = self.attack_form()
        self.assertEqual(anonymous.post(route, data=form).status_code, 302)
        account = next(row for row in self.accounts.list_accounts() if row['village_id'] == self.alice_id)
        self.accounts.set_status(account['id'], 'pending')
        self.assertEqual(self.alice.get('/village/events').status_code, 302)
        self.assertEqual(sessions.session(self.bob_id)['maps'][0]['coins'], 1000)

    def test_name_form_changes_only_owned_village_and_rejects_unsafe_names(self):
        original_player_name = sessions.session(self.alice_id)['playerInfo']['name']
        response = self.alice.post('/village', data={
            'csrf_token': self.csrf(self.alice), 'village_name': ' São João & Lua ', 'USERID': self.bob_id,
        }, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn('Nome da vila atualizado.', response.text)
        self.assertIn('São João &amp; Lua', response.text)
        alice = sessions.session(self.alice_id)
        self.assertEqual(alice['playerInfo']['map_names'][0], 'São João & Lua')
        self.assertEqual(alice['playerInfo']['name'], original_player_name)
        self.assertEqual(sessions.session(self.bob_id)['playerInfo']['map_names'][0], 'Vila Bob')
        self.assertEqual(json.loads((self.saves_path / (self.alice_id + '.save.json')).read_text()), alice)
        self.assertIn('São João &amp; Lua', self.alice.get('/play.html').text)
        for value in ('', 'A', 'X' * 33, '<script>alert(1)</script>', 'Vila\nNova'):
            response = self.alice.post('/village', data={'csrf_token': self.csrf(self.alice), 'village_name': value})
            self.assertEqual(response.status_code, 400)
            self.assertEqual(alice['playerInfo']['map_names'][0], 'São João & Lua')
        self.assertEqual(self.alice.post('/village', data={'village_name': 'Outra vila'}).status_code, 400)

    def test_old_default_is_translated_without_changing_custom_village_names(self):
        village = sessions.session(self.alice_id)
        village['playerInfo']['map_names'][0] = 'My Empire'
        self.assertEqual(self.alice.get('/play.html').status_code, 200)
        self.assertEqual(village['playerInfo']['map_names'][0], 'Meu Império')
        village['playerInfo']['map_names'][0] = 'My Empire dos Dragões'
        self.alice.get('/play.html')
        self.assertEqual(village['playerInfo']['map_names'][0], 'My Empire dos Dragões')

    def test_attack_transfers_twenty_percent_once_and_is_visible_to_both_players(self):
        path, form = self.attack_form()
        self.assertEqual(self.bob.get('/village/events').json, {'revision': ''})
        with contextlib.redirect_stdout(io.StringIO()):
            response = self.alice.post(path, data={**form, 'loot': '99999999', 'win': 'true'}, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn('Vitória contra Vila Bob!', response.text)
        expected_loot = {'coins': 200, 'wood': 100, 'food': 40, 'stone': 1}
        for resource, loot in expected_loot.items():
            original = {'coins': 1000, 'wood': 500, 'food': 200, 'stone': 9}[resource]
            self.assertEqual(sessions.session(self.alice_id)['maps'][0][resource], original + loot)
            self.assertEqual(sessions.session(self.bob_id)['maps'][0][resource], original - loot)
        balances = {key: copy.deepcopy(sessions.session(key)) for key in (self.alice_id, self.bob_id)}
        response = self.alice.post(path, data=form, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual({key: sessions.session(key) for key in balances}, balances)
        revision = self.bob.get('/village/events').json['revision']
        self.assertTrue(revision)
        carol, _ = self.player('carol')
        self.assertEqual(carol.get('/village/events?USERID=' + self.bob_id).json, {'revision': ''})
        self.assertNotIn('Sua vila foi saqueada', carol.get('/rivals?battle=' + revision).text)
        self.assertIn(revision, self.bob.get('/play.html').text)
        defender_page = self.bob.get('/rivals?battle=' + revision)
        self.assertIn('Sua vila foi saqueada por Vila Alice.', defender_page.text)
        self.assertNotIn('Vitória contra Vila Bob!', defender_page.text)
        for userid in balances:
            self.assertEqual(json.loads((self.saves_path / (userid + '.save.json')).read_text()), balances[userid])

    def test_raid_tokens_bind_owner_and_target_and_require_csrf(self):
        path, form = self.attack_form()
        before = copy.deepcopy(sessions.session(self.bob_id))
        self.assertEqual(self.alice.post(path, data={'raid_token': form['raid_token']}).status_code, 400)
        self.assertEqual(self.alice.post(path, data={**form, 'raid_token': 'forged'}).status_code, 400)
        self.assertEqual(self.bob.post(path, data={**form, 'csrf_token': self.csrf(self.bob)}).status_code, 403)
        self.assertEqual(self.alice.post(f'/rivals/{self.alice_id}/raid', data=form).status_code, 403)
        self.assertEqual(sessions.session(self.bob_id), before)

    def test_revalidates_approval_and_tutorial_even_with_a_previously_valid_form(self):
        path, form = self.attack_form()
        bob_account = next(row for row in self.accounts.list_accounts() if row['village_id'] == self.bob_id)
        self.accounts.set_status(bob_account['id'], 'pending')
        self.assertNotIn(path, Forms(self.alice.get('/rivals').text).forms)
        response = self.alice.post(path, data=form, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn('contas aprovadas', response.text)
        self.accounts.set_status(bob_account['id'], 'approved')
        sessions.session(self.bob_id)['playerInfo']['completed_tutorial'] = 0
        response = self.alice.post(path, data=form, follow_redirects=True)
        self.assertIn('protegida durante o tutorial', response.text)
        self.assertEqual(sessions.session(self.bob_id)['maps'][0]['coins'], 1000)

    def test_recovery_failure_blocks_game_commands_info_and_rename(self):
        before = copy.deepcopy(sessions.session(self.alice_id))
        game_data = {'USERID': self.alice_id, 'user_key': self.csrf(self.alice), 'language': 'en', 'client_id': 'test'}
        packet = {'ts': 1, 'first_number': 1, 'accessToken': '', 'tries': 1,
                  'publishActions': [], 'commands': [{'cmd': 'game_status', 'args': ['test']}]}
        game_data['data'] = '0' * 64 + ';' + json.dumps(packet)
        with patch.object(self.raids, 'recover_pending', side_effect=OSError('disk unavailable')), \
                patch.object(server, 'command') as command, patch.object(server.app.logger, 'exception'):
            self.assertEqual(self.alice.post(server.DYNAMIC_GAME_PREFIX + 'command.php', data=game_data).status_code, 503)
            command.assert_not_called()
            self.assertEqual(self.alice.post(server.DYNAMIC_GAME_PREFIX + 'get_player_info.php', data=game_data).status_code, 503)
            self.assertEqual(self.alice.post('/village', data={'csrf_token': self.csrf(self.alice), 'village_name': 'Não salvar'}).status_code, 503)
        self.assertEqual(sessions.session(self.alice_id), before)


if __name__ == '__main__':
    unittest.main()
