"""Exercise administrator edits, stale clients and free rewards over HTTP."""

import contextlib
import copy
import io
import json
import os
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

from admin_villages import AdminVillageService
from auth import AccountStore
from economy import EconomyService
from pvp import RaidService

_boot_directory = tempfile.TemporaryDirectory(prefix='socialemperors-management-boot-')
with patch.dict(os.environ, {
    'SOCIAL_EMPIRES_DATA_DIR': _boot_directory.name,
    'SOCIAL_EMPIRES_LANGUAGE': 'pt-BR',  # These tests cover the Portuguese texts.
    'SOCIAL_EMPIRES_SAVES_DIR': str(Path(_boot_directory.name) / 'saves'),
}), contextlib.redirect_stdout(io.StringIO()):
    import server
    import sessions


class ManagementTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix='socialemperors-management-tests-')
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
        self.administration = AdminVillageService(self.path / 'administration.sqlite3')
        self.economy = EconomyService(self.path / 'treasury.sqlite3')
        patcher = patch.dict(server.app.extensions, {
            'accounts': self.accounts, 'raids': self.raids,
            'village_admin': self.administration, 'economy': self.economy,
        })
        patcher.start()
        self.addCleanup(patcher.stop)
        server.app.config.update(TESTING=True)
        self.admin_account = self.accounts.create_admin('Administrador', 'admin@example.test', 'test-password')
        self.player_account = self.accounts.create_account('Amigo', 'player@example.test', 'test-password', status='approved')
        self.admin, self.admin_id = self.login('admin@example.test')
        self.player, self.player_id = self.login('player@example.test')
        self.edit_path = f"/admin/villages/{self.player_account['id']}"

    @staticmethod
    def csrf(client):
        with client.session_transaction() as browser_session:
            return browser_session['_csrf_token']

    def login(self, email):
        client = server.app.test_client()
        client.get('/login')
        with contextlib.redirect_stdout(io.StringIO()):
            response = client.post('/login', data={
                'email': email, 'password': 'test-password', 'csrf_token': self.csrf(client),
            })
        self.assertEqual(response.status_code, 302)
        with client.session_transaction() as browser_session:
            return client, browser_session['USERID']

    def form(self, **changes):
        response = self.admin.get(self.edit_path)
        self.assertEqual(response.status_code, 200)
        revision = re.search(r'name="expected_revision" value="([^"]+)"', response.text).group(1)
        village = self.administration.get(self.player_id)
        return {
            'csrf_token': self.csrf(self.admin), 'expected_revision': revision,
            'name': village['name'], **village['resources'], 'cash': village['cash'],
            'level': village['level'], 'tutorial_complete': str(int(village['tutorial_complete'])),
            'reason': 'Ajuste para jogar com os amigos', **changes,
        }

    def game_config(self):
        page = self.player.get('/play.html')
        self.assertEqual(page.status_code, 200)
        return json.loads(re.search(r'<script id="game-config" type="application/json">(.*?)</script>', page.text, re.S).group(1))

    def post_command(self, config, commands):
        packet = {'ts': 1, 'first_number': 1, 'accessToken': '', 'tries': 1,
                  'publishActions': [], 'commands': commands}
        return self.player.post(server.DYNAMIC_GAME_PREFIX + 'command.php', data={
            'USERID': self.player_id, 'user_key': config['userKey'], 'language': 'en', 'client_id': 'test',
            'data': '0' * 64 + ';' + json.dumps(packet),
        })

    def test_only_admin_can_read_and_modify_villages_and_csrf_is_required(self):
        form = self.form(cash=500)
        anonymous = server.app.test_client()
        for client in (anonymous, self.player):
            self.assertEqual(client.get('/admin/villages').status_code, 403)
            self.assertEqual(client.get(self.edit_path).status_code, 403)
            self.assertEqual(client.post(self.edit_path, data=form).status_code, 403)
        form.pop('csrf_token')
        self.assertEqual(self.admin.post(self.edit_path, data=form).status_code, 400)
        self.assertEqual(sessions.session(self.player_id)['playerInfo']['cash'], 0)
        pending = self.accounts.create_account('Pendente', 'pending@example.test', 'test-password')
        self.assertEqual(self.admin.get(f"/admin/villages/{pending['id']}").status_code, 404)

    def test_admin_edit_persists_audits_and_notifies_only_the_target(self):
        admin_before = copy.deepcopy(sessions.session(self.admin_id))
        response = self.admin.post(self.edit_path, data=self.form(
            name='Vila São Bento', cash=700, coins=12345, wood=400, food=600, stone=800,
            level=4, tutorial_complete='1', USERID=self.admin_id, reason='Preparar encontro dos amigos',
        ), follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn('Preparar encontro dos amigos', response.text)
        self.assertIn('Administrador', response.text)
        self.assertIn('12.345', response.text)
        actual = self.administration.get(self.player_id)
        self.assertEqual((actual['name'], actual['cash'], actual['level'], actual['tutorial_complete']), ('Vila São Bento', 700, 4, True))
        self.assertEqual(actual['xp'], server.get_game_config()['levels'][3]['exp_required'])
        self.assertEqual(sessions.session(self.admin_id), admin_before)
        self.assertTrue(self.player.get('/village/events').json['revision'])
        self.assertEqual(self.admin.get('/village/events').json['revision'], '')
        saved = json.loads((self.saves_path / (self.player_id + '.save.json')).read_text())
        self.assertEqual(saved, sessions.session(self.player_id))
        self.assertEqual(len(self.administration.history(self.player_id)), 1)

    def test_admin_validation_and_stale_form_preserve_current_state_and_draft(self):
        form = self.form(coins=-5, reason='Inválido')
        before = copy.deepcopy(sessions.session(self.player_id))
        response = self.admin.post(self.edit_path, data=form)
        self.assertEqual(response.status_code, 400)
        self.assertIn('value="-5"', response.text)
        self.assertEqual(sessions.session(self.player_id), before)
        form = self.form(cash=123)
        sessions.session(self.player_id)['maps'][0]['coins'] += 50
        response = self.admin.post(self.edit_path, data=form)
        self.assertEqual(response.status_code, 409)
        self.assertIn('Recarregar dados da vila', response.text)
        self.assertIn('value="123"', response.text)
        self.assertIn(f'value="{form["expected_revision"]}"', response.text)
        self.assertRegex(response.text, r'type="submit"\s+disabled')
        self.assertEqual(sessions.session(self.player_id)['playerInfo']['cash'], 0)
        self.assertEqual(self.administration.history(self.player_id), [])

    def test_old_game_key_cannot_undo_admin_progress_and_reload_restores_game_access(self):
        old_config = self.game_config()
        form_csrf = self.csrf(self.player)
        response = self.admin.post(self.edit_path, data=self.form(level=8, cash=500))
        self.assertEqual(response.status_code, 303)
        after = copy.deepcopy(sessions.session(self.player_id))
        with patch.object(server, 'command') as command:
            response = self.post_command(old_config, [{'cmd': 'rt_publish_score', 'args': [4]}])
            self.assertEqual(response.status_code, 403)
            command.assert_not_called()
        self.assertEqual(sessions.session(self.player_id), after)
        new_config = self.game_config()
        self.assertNotEqual(new_config['userKey'], old_config['userKey'])
        self.assertEqual(self.csrf(self.player), form_csrf)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self.post_command(new_config, [{'cmd': 'game_status', 'args': ['fresh client']}]).status_code, 200)
        self.assertEqual(self.administration.get(self.player_id)['level'], 8)

    def test_game_uses_saved_last_login_instead_of_a_historical_flashvar(self):
        config = self.game_config()
        self.assertEqual(config['lastLoggedIn'], config['serverTime'])
        sessions.session(self.player_id)['playerInfo']['last_logged_in'] = 1_700_000_000
        self.assertEqual(self.game_config()['lastLoggedIn'], 1_700_000_000)

    def test_pending_admin_recovery_revalidates_game_key_inside_command_lock(self):
        old_config = self.game_config()
        form = self.form(level=9)
        with patch.object(sessions, 'save_session', side_effect=OSError('disk unavailable')), patch.object(server.app.logger, 'exception'):
            self.assertEqual(self.admin.post(self.edit_path, data=form).status_code, 503)
        # The before_request key check still sees the previous applied revision;
        # recovery inside the command lock must invalidate the old client too.
        with patch.object(server, 'command') as command:
            self.assertEqual(self.post_command(old_config, [{'cmd': 'rt_publish_score', 'args': [4]}]).status_code, 403)
            command.assert_not_called()
        self.assertEqual(self.administration.get(self.player_id)['level'], 9)
        self.assertEqual(len(self.administration.history(self.player_id)), 1)

    def test_free_claims_are_owned_once_only_and_use_server_amount_and_clock(self):
        self.assertIn('Bônus inicial', self.player.get('/treasury').text)
        self.assertEqual(sessions.session(self.player_id)['playerInfo']['cash'], 0)
        with patch('economy.time') as clock, contextlib.redirect_stdout(io.StringIO()):
            clock.time.return_value = 1_000_000
            for action in ('initial', 'daily'):
                response = self.player.post('/treasury/claim', data={
                    'csrf_token': self.csrf(self.player), 'action': action,
                    'USERID': self.admin_id, 'amount': '999999', 'claimed_at': '0',
                }, follow_redirects=True)
                self.assertEqual(response.status_code, 200)
            self.assertEqual(sessions.session(self.player_id)['playerInfo']['cash'], 600)
            self.assertEqual(sessions.session(self.admin_id)['playerInfo']['cash'], 0)
            for action in ('initial', 'daily'):
                self.player.post('/treasury/claim', data={'csrf_token': self.csrf(self.player), 'action': action})
            self.assertEqual(sessions.session(self.player_id)['playerInfo']['cash'], 600)
        with patch('economy.time') as clock, contextlib.redirect_stdout(io.StringIO()):
            clock.time.return_value = 1_000_000 + 86400
            self.player.post('/treasury/claim', data={'csrf_token': self.csrf(self.player), 'action': 'daily'})
        self.assertEqual(sessions.session(self.player_id)['playerInfo']['cash'], 700)
        self.assertEqual(len(self.economy.overview(self.player_id)['history']), 3)

    def test_claim_permissions_csrf_and_admin_cash_do_not_reset_eligibility(self):
        anonymous = server.app.test_client()
        self.assertEqual(anonymous.get('/treasury').status_code, 302)
        self.assertEqual(anonymous.post('/treasury/claim', data={'action': 'initial'}).status_code, 302)
        self.assertEqual(self.player.post('/treasury/claim', data={'action': 'initial'}).status_code, 400)
        self.player.post('/treasury/claim', data={'csrf_token': self.csrf(self.player), 'action': 'initial'})
        self.admin.post(self.edit_path, data=self.form(cash=0))
        response = self.player.post('/treasury/claim', data={'csrf_token': self.csrf(self.player), 'action': 'initial'}, follow_redirects=True)
        self.assertIn('já resgatou', response.text)
        self.assertEqual(sessions.session(self.player_id)['playerInfo']['cash'], 0)
        account = self.accounts.get(self.player_account['id'])
        self.accounts.set_status(account['id'], 'pending')
        self.assertEqual(self.player.post('/treasury/claim', data={'action': 'daily', 'csrf_token': self.csrf(self.player)}).status_code, 302)

    def test_all_service_recovery_failures_block_other_mutations(self):
        config = self.game_config()
        before = copy.deepcopy(sessions.session(self.player_id))
        for service in (self.administration, self.economy):
            with self.subTest(service=type(service).__name__), \
                    patch.object(service, 'recover_pending', side_effect=ValueError('invalid journal')), \
                    patch.object(server.app.logger, 'exception'), patch.object(server, 'command') as command:
                self.assertEqual(self.post_command(config, [{'cmd': 'game_status', 'args': ['blocked']}]).status_code, 503)
                command.assert_not_called()
                self.assertEqual(self.player.post('/village', data={'csrf_token': self.csrf(self.player), 'village_name': 'Não alterar'}).status_code, 503)
                self.assertEqual(self.player.post('/treasury/claim', data={'csrf_token': self.csrf(self.player), 'action': 'daily'}).status_code, 503)
        self.assertEqual(sessions.session(self.player_id), before)

    def test_tutorial_load_recovers_a_consumed_target_without_replaying_rewards(self):
        save = sessions.session(self.player_id)
        save['privateState'].pop('startingTutorialStep', None)
        save['maps'][0]['items'] = [item for item in save['maps'][0]['items']
                                  if item[:3] != [19, 50, 58]]
        save['maps'][0]['items'].append([500, 53, 53, 0, 0, 0, [], {}])
        save['maps'][0].update(xp=151, level=4)
        before = copy.deepcopy(save)
        config = self.game_config()
        for _ in range(2):
            response = self.player.post(server.DYNAMIC_GAME_PREFIX + 'get_player_info.php', data={
                'USERID': self.player_id, 'user_key': config['userKey'],
                'language': 'en', 'client_id': 'tutorial-regression',
            })
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json['privateState']['startingTutorialStep'], 8)
            self.assertEqual(response.json['playerInfo']['completed_tutorial'], 0)
            self.assertEqual(save['maps'], before['maps'])
            self.assertEqual(save['playerInfo']['cash'], before['playerInfo']['cash'])
        persisted = json.loads((self.saves_path / (self.player_id + '.save.json')).read_text())
        self.assertEqual(persisted['privateState']['startingTutorialStep'], 8)
        self.assertEqual(persisted['maps'], before['maps'])

    def test_native_tutorial_finish_persists_and_admin_can_reopen_it(self):
        config = self.game_config()
        before = copy.deepcopy(sessions.session(self.player_id)['maps'])
        response = self.post_command(config, [{'cmd': 'complete_tutorial', 'args': [15]}])
        self.assertEqual(response.status_code, 200)
        save = sessions.session(self.player_id)
        self.assertEqual(save['playerInfo']['completed_tutorial'], 0)
        self.assertEqual(save['privateState']['startingTutorialStep'], 15)
        response = self.post_command(config, [{'cmd': 'complete_tutorial', 'args': [31]}])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(save['playerInfo']['completed_tutorial'], 1)
        self.assertEqual(save['privateState']['startingTutorialStep'], 31)
        self.assertEqual(save['maps'], before)
        response = self.post_command(config, [{'cmd': 'complete_tutorial', 'args': [3]}])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(save['privateState']['startingTutorialStep'], 31)
        response = self.admin.post(self.edit_path, data=self.form(tutorial_complete='0'))
        self.assertEqual(response.status_code, 303)
        self.assertEqual(save['playerInfo']['completed_tutorial'], 0)
        self.assertNotIn('startingTutorialStep', save['privateState'])


if __name__ == '__main__':
    unittest.main()
