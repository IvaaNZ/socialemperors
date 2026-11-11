"""Unit and mission statistics shown in the administration pages."""

import contextlib
import copy
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from auth import AccountStore
from village_stats import mission_stats, summary, unit_stats, village_stats

SPEARMAN, SMALL_TROLL, VILLAGER, COW, HOUSE = 509, 525, 1, 504, 1
BASE = json.loads(Path('villages/initial.json').read_text(encoding='utf-8'))


def village(items=(), second_map=(), gifts=(), completed=(), rewarded=()):
    save = copy.deepcopy(BASE)
    save['maps'][0]['items'] = [list(item) for item in items]
    if second_map:
        extra = copy.deepcopy(save['maps'][0])
        extra['items'] = [list(item) for item in second_map]
        save['maps'].append(extra)
    save['privateState']['gifts'] = list(gifts)
    save['privateState']['completedMissions'] = list(completed)
    save['privateState']['rewardedMissions'] = list(rewarded)
    return save


class VillageStatsTests(unittest.TestCase):
    def test_units_are_counted_on_every_map_in_shelters_and_in_storage(self):
        gifts = [0] * 600
        gifts[SPEARMAN] = 2
        gifts[HOUSE] = 4  # A stored building is not a unit.
        save = village(
            items=[[SPEARMAN, 10, 10, 0, 0, 0], [SPEARMAN, 12, 10, 0, 0, 0], [COW, 5, 5, 0, 0, 0],
                   [30, 20, 20, 0, 0, 0, [SMALL_TROLL, SMALL_TROLL, 'bad']]],
            second_map=[[SPEARMAN, 3, 3, 0, 0, 0]], gifts=gifts)
        stats = unit_stats(save, 'es')
        rows = {row['id']: row for row in stats['units']}
        self.assertEqual((rows[SPEARMAN]['on_map'], rows[SPEARMAN]['stored'], rows[SPEARMAN]['total']), (3, 2, 5))
        self.assertEqual(rows[SMALL_TROLL]['sheltered'], 2)
        self.assertEqual(rows[COW]['kind'], 'animal')
        self.assertEqual(rows[SPEARMAN]['name'], 'Lancero')
        self.assertNotIn(HOUSE, rows)
        self.assertEqual(stats['totals'], {'units': 8, 'combat': 7, 'worker': 0, 'healer': 0, 'animal': 1, 'stored': 2})
        self.assertEqual(stats['units'][0]['id'], SPEARMAN)

    def test_missions_track_completed_rewarded_and_pending(self):
        stats = mission_stats(village(completed=[2, 3, 3, 'x', 4], rewarded=[2, 3]), 'en')
        self.assertEqual((stats['completed'], stats['rewarded']), (3, 2))
        self.assertGreater(stats['total'], 100)
        self.assertEqual([mission['id'] for mission in stats['pending_rewards']], [4])
        self.assertEqual([mission['id'] for mission in stats['recent']], [4, 3, 2])
        self.assertEqual(stats['recent'][-1]['name'], 'Train villager')

    def test_summary_ranks_only_combat_troops(self):
        first = village_stats(village(items=[[SPEARMAN, 1, 1, 0, 0, 0], [COW, 2, 2, 0, 0, 0]] * 3, completed=[2]), 'en')
        second = village_stats(village(items=[[SMALL_TROLL, 1, 1, 0, 0, 0]], completed=[2, 3, 4]), 'en')
        overview = summary([first, second])
        self.assertEqual(overview['villages'], 2)
        self.assertEqual((overview['combat'], overview['animal']), (4, 3))
        self.assertEqual([unit['id'] for unit in overview['top_units']], [SPEARMAN, SMALL_TROLL])
        self.assertEqual((overview['missions_average'], overview['missions_best']), (2.0, 3))
        self.assertEqual(summary([])['missions_average'], 0)

    def test_statistics_never_change_the_save(self):
        save = village(items=[[SPEARMAN, 1, 1, 0, 0, 0]], completed=[2])
        before = copy.deepcopy(save)
        village_stats(save, 'es')
        self.assertEqual(save, before)


_boot_directory = tempfile.TemporaryDirectory(prefix='socialemperors-tests-')
with patch.dict(os.environ, {
    'SOCIAL_EMPIRES_DATA_DIR': _boot_directory.name,
    'SOCIAL_EMPIRES_LANGUAGE': 'pt-BR',
    'SOCIAL_EMPIRES_SAVES_DIR': str(Path(_boot_directory.name) / 'saves'),
}), contextlib.redirect_stdout(io.StringIO()):
    import server
    import sessions


class AdminStatsPageTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix='socialemperors-stats-')
        self.addCleanup(directory.cleanup)
        saves = patch.object(sessions, 'SAVES_DIR', str(Path(directory.name) / 'saves'))
        saves.start()
        self.addCleanup(saves.stop)
        with contextlib.redirect_stdout(io.StringIO()):
            sessions.load_saved_villages()
        self.store = AccountStore(Path(directory.name) / 'accounts.sqlite3')
        extension = patch.dict(server.app.extensions, {'accounts': self.store})
        extension.start()
        self.addCleanup(extension.stop)
        language = patch.object(server, 'GAME_LANGUAGE', 'pt-BR')
        language.start()
        self.addCleanup(language.stop)
        server.app.config.update(TESTING=True)
        self.client = server.app.test_client()
        quiet = contextlib.redirect_stdout(io.StringIO())
        quiet.__enter__()
        self.addCleanup(quiet.__exit__, None, None, None)

    def test_admin_pages_show_army_and_missions(self):
        admin = self.store.create_admin('Administrador', 'admin@example.com', 'secret-password')
        self.client.get('/login')
        with self.client.session_transaction() as session:
            token = session['_csrf_token']
        self.client.post('/login', data={'email': 'admin@example.com', 'password': 'secret-password', 'csrf_token': token})
        userid = self.store.get(admin['id'])['village_id']
        save = sessions.session(userid)
        save['maps'][0]['items'].append([SPEARMAN, 40, 40, 0, 0, 0])
        save['privateState']['completedMissions'] = [2, 3]
        save['privateState']['rewardedMissions'] = [2]

        overview = self.client.get('/admin/villages').get_data(as_text=True)
        self.assertIn('Resumo das vilas', overview)
        self.assertIn('Tropas mais comuns', overview)
        self.assertIn('Lanceiro', overview)
        self.assertIn('1 recompensas pendentes', overview)

        detail = self.client.get(f"/admin/villages/{admin['id']}").get_data(as_text=True)
        self.assertIn('Exército', detail)
        self.assertIn('Lanceiro', detail)
        self.assertIn('Recompensas pendentes', detail)
        self.assertIn('Missões', detail)


if __name__ == '__main__':
    unittest.main()
