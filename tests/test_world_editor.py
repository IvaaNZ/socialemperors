import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'WorldEditor'))
import world_editor_core as core  # noqa: E402

CATALOG = {1: {'type': 'b', 'width': '2', 'height': '2', 'label': 'Casa I'},
           2: {'type': 'b', 'width': '3', 'height': '1', 'label': 'Muro'},
           9: {'type': 'u', 'width': '1', 'height': '1', 'label': 'Troll'}}


class WorldEditor(unittest.TestCase):
    def setUp(self):
        self.folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.folder)
        quests = self.folder / 'quests'
        quests.mkdir()
        shutil.copy(core.QUESTS_DIR / f'{core.TEMPLATE_ISLAND}.json', quests)
        saves = self.folder / 'saves'
        saves.mkdir()
        village = {'playerInfo': {'map_names': ['Reino', 'Isla 2']}, 'privateState': {},
                   'maps': [{'level': 12, 'items': [[1, 10, 10, 0, 0]]}, {'level': 1, 'items': []}]}
        (saves / 'abc.save.json').write_text(json.dumps(village), encoding='utf-8')
        self.saves = saves
        for p in (patch.object(core, 'QUESTS_DIR', quests), patch.object(core, 'SAVES_DIR', saves)):
            p.start()
            self.addCleanup(p.stop)

    def test_every_island_is_listed_and_a_missing_one_starts_empty_with_its_id(self):
        islands = {quest_id: has_map for quest_id, _, has_map in core.quest_islands()}
        self.assertEqual(len(islands), len(core.QUEST_ISLANDS))
        self.assertTrue(islands[core.TEMPLATE_ISLAND])
        self.assertFalse(islands['100000048'])
        doc = core.Document.open_island('100000048')
        self.assertEqual((doc.items, doc.data['playerInfo']['pid'], doc.dirty), ([], '100000048', True))
        doc.add(9, 50, 50, now=1)
        path = doc.save()
        self.assertEqual(json.loads(path.read_text(encoding='utf-8'))['map']['items'], [[9, 50, 50, 0, 1]])
        self.assertEqual(list(path.parent.glob('*.bak-*')), [])  # nothing to back up for a new file
        with self.assertRaises(core.EditorError):
            core.Document.open_island('123')

    def test_editing_keeps_a_backup_and_undo_goes_back(self):
        doc = core.Document.open_island(core.TEMPLATE_ISLAND)
        before = json.loads(json.dumps(doc.items))
        doc.add(1, 200, -5, now=1)  # out of the map: kept on its edge
        self.assertEqual(doc.items[-1][:3], [1, 99, 0])
        doc.move(0, 5, 6)
        doc.rotate(0)
        doc.delete(1)
        for _ in range(4):
            self.assertTrue(doc.undo())
        self.assertFalse(doc.undo())
        self.assertEqual(doc.items, before)
        doc.add(2, 1, 1)
        doc.save()
        doc.add(2, 4, 4)
        doc.save()
        self.assertEqual(len(list(core.QUESTS_DIR.glob('*.bak-*'))), 1)  # one backup: the file as first opened
        backup = next(core.QUESTS_DIR.glob('*.bak-*'))
        self.assertEqual(json.loads(backup.read_text(encoding='utf-8'))['map']['items'], before)

    def test_a_village_is_only_saved_with_the_server_stopped(self):
        [(path, name, level)] = core.player_villages()
        self.assertEqual((name, level), ('Reino', 12))
        doc = core.Document.open_village(path, map_index=1)
        self.assertEqual(doc.title, 'Reino')
        doc.add(1, 3, 3, now=1)
        doc.set_name('Nuevo Reino')
        with self.assertRaises(core.EditorError):
            doc.save(server_up=True)
        doc.save(server_up=False)
        saved = json.loads(path.read_text(encoding='utf-8'))
        self.assertEqual(saved['maps'][1]['items'], [[1, 3, 3, 0, 1]])
        self.assertEqual(saved['maps'][0]['items'], [[1, 10, 10, 0, 0]])
        self.assertEqual(saved['playerInfo']['map_names'][0], 'Nuevo Reino')
        with self.assertRaises(core.EditorError):
            doc.select_map(5)
        with self.assertRaises(core.EditorError):
            doc.set_name('  ')

    def test_saving_keeps_each_files_layout(self):
        island = core.Document.open_island(core.TEMPLATE_ISLAND)
        island.add(1, 1, 1)
        self.assertEqual(len(island.save().read_text(encoding='utf-8').splitlines()), 1)  # islands: one line
        [(path, _, _)] = core.player_villages()
        path.write_text(json.dumps(json.loads(path.read_text(encoding='utf-8')), indent=4), encoding='utf-8')
        village = core.Document.open_village(path)
        village.add(1, 1, 1)
        village.save(server_up=False)
        self.assertTrue(path.read_text(encoding='utf-8').splitlines()[1].startswith('    "'))
        self.assertEqual(core.layout_of('{\n "a": 1\n}'), 1)

    def test_footprints_overlaps_and_picking(self):
        house, wall, troll = [1, 10, 10, 0, 0], [2, 11, 11, 1, 0], [9, 10, 10, 0, 0]
        self.assertEqual(core.footprint(wall, CATALOG), (1, 3))  # turned: width and height swap
        self.assertEqual(core.overlapping([house, wall, troll], CATALOG), {0, 1})  # units stand anywhere
        self.assertEqual(core.overlapping([house, [2, 12, 10, 0, 0]], CATALOG), set())
        self.assertEqual(core.item_at([house, troll], CATALOG, 10, 10), 1)  # the topmost
        self.assertEqual(core.item_at([house, troll], CATALOG, 11, 11), 0)
        self.assertIsNone(core.item_at([house], CATALOG, 12, 12))

    def test_the_real_catalog_has_sizes_and_spanish_names(self):
        catalog = core.load_catalog()
        self.assertEqual(catalog[1]['label'], 'Casa I')
        self.assertEqual(core.footprint([1, 0, 0, 0, 0], catalog), (2, 2))


if __name__ == '__main__':
    unittest.main()
