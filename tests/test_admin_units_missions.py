"""Units given or removed and missions completed or reset by an administrator (Tareas.txt point 19)."""

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import admin_villages
from admin_villages import AdminVillageError, AdminVillageService
from get_game_config import get_game_config
import sessions
import test_management as pages
from test_admin_villages import village


class AdminUnitAndMissionTests(unittest.TestCase):
    UNIT = 500      # Aldeano I: sold in the game
    MISSION = 2

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='socialemperors-admin-units-')
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name)
        save = village('alice')
        save['privateState']['gifts'] = [0] * self.UNIT + [2]          # two in the warehouse
        save['maps'][1]['items'] = [[19, 7, 8], [self.UNIT, 1, 1], [self.UNIT, 2, 2], [19, 3, 3, 0, 0, 0, [self.UNIT]]]
        save['privateState']['completedMissions'] = [3, 4]
        save['privateState']['rewardedMissions'] = [3]
        self.saves = {'alice': save}
        self.service = AdminVillageService(self.path / 'administration.sqlite3')
        for patcher in (patch.object(sessions, 'SAVES_DIR', self.directory.name), patch.object(sessions, '__saves', self.saves)):
            patcher.start()
            self.addCleanup(patcher.stop)
        output = redirect_stdout(io.StringIO())
        output.__enter__()
        self.addCleanup(output.__exit__, None, None, None)
        sessions.save_session('alice')

    def disk(self):
        return json.loads((self.path / 'alice.save.json').read_text(encoding='utf-8'))

    def test_the_count_covers_warehouse_map_and_buildings(self):
        self.assertEqual(admin_villages.unit_count(self.saves['alice'], self.UNIT), 5)

    def test_given_units_go_to_the_warehouse_and_are_audited(self):
        self.service.change_units('alice', self.UNIT, 3, 'give', 17, 'Premio do torneio')
        self.assertEqual(self.disk()['privateState']['gifts'][self.UNIT], 5)
        self.assertEqual(admin_villages.unit_count(self.disk(), self.UNIT), 8)
        entry = self.service.history('alice')[0]
        self.assertEqual((entry['changed_fields'], entry['before'], entry['after'], entry['reason']),
                         (['units'], {'unit': self.UNIT, 'total': 5}, {'unit': self.UNIT, 'total': 8}, 'Premio do torneio'))
        self.assertTrue(self.service.change_revision('alice'))  # the player is told to reload

    def test_a_new_unit_extends_the_warehouse_list(self):
        self.saves['alice']['privateState']['gifts'] = []
        self.service.change_units('alice', 501, 1, 'give', 17, 'Teste de entrega')
        gifts = self.disk()['privateState']['gifts']
        self.assertEqual((len(gifts), gifts[501]), (502, 1))

    def test_removal_takes_the_warehouse_then_the_map_then_buildings(self):
        self.service.change_units('alice', self.UNIT, 3, 'remove', 17, 'Correcao de erro')
        save = self.disk()
        self.assertEqual(save['privateState']['gifts'], [])  # trailing zeros trimmed, as the game does
        self.assertEqual([placed[0] for placed in save['maps'][1]['items']], [19, self.UNIT, 19])
        self.assertEqual(save['maps'][1]['items'][2][6], [self.UNIT])
        self.service.change_units('alice', self.UNIT, 2, 'remove', 17, 'Correcao de erro')
        save = self.disk()
        self.assertEqual(save['maps'][1]['items'], [[19, 7, 8], [19, 3, 3, 0, 0, 0, []]])
        self.assertEqual(admin_villages.unit_count(save, self.UNIT), 0)

    def test_invalid_unit_changes_write_nothing(self):
        before = self.disk()
        not_sold = next(int(item['id']) for item in get_game_config()['items']
                        if item.get('type') == 'u' and not admin_villages.giveable_unit(item))
        cases = ((self.UNIT, 6, 'remove', 'Demais'), (self.UNIT, 0, 'give', 'Zero'), (self.UNIT, 101, 'give', 'Muito'),
                 (19, 1, 'give', 'Edificio'), (not_sold, 1, 'give', 'Nao vendida'), (self.UNIT, 1, 'steal', 'Acao'),
                 (self.UNIT, 1, 'give', ''), ('abc', 1, 'give', 'Texto'))
        for unit_id, count, action, reason in cases:
            with self.assertRaises(AdminVillageError, msg=(unit_id, count, action)):
                self.service.change_units('alice', unit_id, count, action, 17, reason)
        self.assertEqual(self.disk(), before)
        self.assertEqual(self.service.history('alice'), [])

    def test_missions_complete_leaving_the_reward_and_reset_erasing_it(self):
        self.service.change_mission('alice', self.MISSION, 'complete', 17, 'Missao travada')
        private = self.disk()['privateState']
        self.assertEqual((private['completedMissions'], private['rewardedMissions']), ([3, 4, self.MISSION], [3]))
        self.service.change_mission('alice', 3, 'reset', 17, 'Repetir a missao')
        private = self.disk()['privateState']
        self.assertEqual((private['completedMissions'], private['rewardedMissions']), ([4, self.MISSION], []))
        states = [(entry['before']['state'], entry['after']['state']) for entry in self.service.history('alice')]
        self.assertEqual(states, [('rewarded', 'open'), ('open', 'completed')])

    def test_invalid_mission_changes_write_nothing(self):
        before = self.disk()
        for mission_id, action in ((4, 'complete'), (self.MISSION, 'reset'), (999999, 'complete'), (self.MISSION, 'skip')):
            with self.assertRaises(AdminVillageError, msg=(mission_id, action)):
                self.service.change_mission('alice', mission_id, action, 17, 'Motivo valido')
        self.assertEqual(self.disk(), before)


class AdminUnitsAndMissionsPageTests(unittest.TestCase):
    """The village page gives and removes units and changes missions."""

    setUp = pages.ManagementTests.setUp
    csrf = staticmethod(pages.ManagementTests.csrf)
    login = pages.ManagementTests.login

    def test_admin_gives_units_and_completes_a_mission_from_the_page(self):
        page = self.admin.get(self.edit_path)
        self.assertIn('name="unit_id"', page.text)
        self.assertIn('name="mission_id"', page.text)
        response = self.admin.post(f'{self.edit_path}/units', data={
            'csrf_token': self.csrf(self.admin), 'unit_id': '500', 'count': '2', 'action': 'give',
            'reason': 'Premio do evento', 'anchor': '#army-title'})
        self.assertEqual(response.status_code, 303)
        self.assertTrue(response.headers['Location'].endswith('#army-title'))
        self.assertEqual(pages.sessions.session(self.player_id)['privateState']['gifts'][500], 2)
        response = self.admin.post(f'{self.edit_path}/missions', data={
            'csrf_token': self.csrf(self.admin), 'mission_id': '2', 'action': 'complete', 'reason': 'Missao travada'},
            follow_redirects=True)
        self.assertIn(2, pages.sessions.session(self.player_id)['privateState']['completedMissions'])
        self.assertIn('Premio do evento', response.text)
        self.assertIn('Missão: ', response.text)
        self.assertIn('Unidades: ', response.text)
        self.assertTrue(self.player.get('/village/events').json['revision'])

    def test_errors_are_shown_and_only_admins_with_csrf_can_change(self):
        data = {'unit_id': '500', 'count': '1', 'action': 'remove', 'reason': 'Retirar uma'}
        for client in (pages.server.app.test_client(), self.player):
            self.assertEqual(client.post(f'{self.edit_path}/units', data=data).status_code, 403)
            self.assertEqual(client.post(f'{self.edit_path}/missions',
                                         data={'mission_id': '2', 'action': 'complete', 'reason': 'Concluir'}).status_code, 403)
        self.assertEqual(self.admin.post(f'{self.edit_path}/units', data=data).status_code, 400)  # no CSRF token
        response = self.admin.post(f'{self.edit_path}/units', data={**data, 'csrf_token': self.csrf(self.admin)},
                                   follow_redirects=True)
        self.assertIn('A vila não tem tantas unidades desse tipo para retirar.', response.text)
        self.assertEqual(self.administration.history(self.player_id), [])


if __name__ == '__main__':
    unittest.main()
