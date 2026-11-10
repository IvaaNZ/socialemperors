"""Exercise naming through the real atomic writer with isolated save files."""

import contextlib
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import sessions
from village_names import (
    DEFAULT_VILLAGE_NAME,
    MAX_VILLAGE_NAME_LENGTH,
    VillageNameError,
    normalize_legacy_village_name,
    rename_village,
    set_village_name,
    validate_village_name,
)


class VillageNameTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='socialemperors-names-')
        self.addCleanup(self.directory.cleanup)
        self.village = {
            'playerInfo': {
                'pid': 'own-village', 'name': 'Jogador original',
                'default_map': 0, 'map_names': ['My Empire', 'Ilha distante'],
            },
            'maps': [
                {'id': 0, 'coins': 250, 'xp': 4, 'level': 1},
                {'id': 1, 'coins': 120, 'xp': 100, 'level': 3},
            ],
            'privateState': {'attacksSent': []},
        }
        self.other_village = copy.deepcopy(self.village)
        self.other_village['playerInfo']['pid'] = 'other-village'
        for patcher in (
            patch.object(sessions, 'SAVES_DIR', self.directory.name),
            patch.object(sessions, '__saves', {
                'own-village': self.village,
                'other-village': self.other_village,
            }),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        with contextlib.redirect_stdout(io.StringIO()):
            sessions.save_session('own-village')
        self.path = Path(self.directory.name) / 'own-village.save.json'

    def test_rename_persists_only_the_requested_map_and_keeps_player_identity(self):
        before = copy.deepcopy(self.village)
        with contextlib.redirect_stdout(io.StringIO()):
            result = rename_village('own-village', '  São Bento & Lua  ')
        self.assertEqual(result, 'São Bento & Lua')
        expected = copy.deepcopy(before)
        expected['playerInfo']['map_names'][0] = result
        self.assertEqual(self.village, expected)
        self.assertEqual(json.loads(self.path.read_text(encoding='utf-8')), expected)
        self.assertEqual(self.other_village, {
            **before, 'playerInfo': {**before['playerInfo'], 'pid': 'other-village'},
        })
        self.assertEqual(list(Path(self.directory.name).glob('*.tmp')), [])

    def test_legacy_default_migration_is_exact_and_persists_once(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertTrue(normalize_legacy_village_name('own-village'))
        self.assertEqual(self.village['playerInfo']['map_names'], [DEFAULT_VILLAGE_NAME, 'Ilha distante'])
        self.assertEqual(json.loads(self.path.read_text(encoding='utf-8')), self.village)
        with patch.object(sessions, 'save_session') as writer:
            self.assertFalse(normalize_legacy_village_name('own-village'))
            writer.assert_not_called()
        self.village['playerInfo']['map_names'][0] = 'My Empire dos Dragões'
        self.assertFalse(normalize_legacy_village_name('own-village'))
        self.assertEqual(self.village['playerInfo']['map_names'][0], 'My Empire dos Dragões')
        self.assertEqual(self.village['playerInfo']['name'], 'Jogador original')

    def test_default_name_saved_in_another_language_follows_the_server_language(self):
        import portal_i18n
        self.addCleanup(portal_i18n.set_portal_language, portal_i18n.portal_language())
        portal_i18n.set_portal_language('es')
        self.village['playerInfo']['map_names'][0] = 'Meu Império'
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertTrue(normalize_legacy_village_name('own-village'))
        self.assertEqual(self.village['playerInfo']['map_names'], ['Mi Imperio', 'Ilha distante'])
        with patch.object(sessions, 'save_session') as writer:
            self.assertFalse(normalize_legacy_village_name('own-village'))
            writer.assert_not_called()
        portal_i18n.set_portal_language('pt-BR')
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertTrue(normalize_legacy_village_name('own-village'))
        self.assertEqual(self.village['playerInfo']['map_names'][0], 'Meu Império')
        self.village['playerInfo']['map_names'][0] = 'Mi Imperio del Sur'
        self.assertFalse(normalize_legacy_village_name('own-village'))

    def test_default_player_name_follows_the_server_language_but_custom_names_stay(self):
        import portal_i18n
        self.addCleanup(portal_i18n.set_portal_language, portal_i18n.portal_language())
        portal_i18n.set_portal_language('es')
        self.village['playerInfo']['map_names'][0] = 'Ciudad del Sol'
        self.village['playerInfo']['name'] = 'Imperador'
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertTrue(normalize_legacy_village_name('own-village'))
        self.assertEqual(self.village['playerInfo']['name'], 'Emperador')
        self.assertEqual(json.loads(self.path.read_text(encoding='utf-8'))['playerInfo']['name'], 'Emperador')
        self.assertEqual(self.village['playerInfo']['map_names'][0], 'Ciudad del Sol')
        self.village['playerInfo']['name'] = 'Jogador original'
        self.assertFalse(normalize_legacy_village_name('own-village'))
        self.assertEqual(self.village['playerInfo']['name'], 'Jogador original')

    def test_unicode_validation_rejects_markup_controls_and_excess_length(self):
        self.assertEqual(validate_village_name(' Sa\u0303o Joa\u0303o '), 'São João')
        self.assertEqual(validate_village_name('Á' * MAX_VILLAGE_NAME_LENGTH), 'Á' * MAX_VILLAGE_NAME_LENGTH)
        for invalid in (None, '', '  ', 'A', 'B' * (MAX_VILLAGE_NAME_LENGTH + 1),
                        'Nova\nVila', 'Nova\tVila', 'Nova\x00Vila', 'Nova\u202eVila',
                        'Nova\u200bVila', 'Nova\u2028Vila', 'Nova\u2029Vila', '<b>Nova Vila</b>'):
            with self.subTest(invalid=repr(invalid)), self.assertRaises(VillageNameError):
                validate_village_name(invalid)

    def test_invalid_map_selection_or_name_cannot_mutate_village(self):
        before = copy.deepcopy(self.village)
        for map_index in (-1, 2, True, 0.5, '0.5', 'nope'):
            with self.subTest(map_index=map_index), self.assertRaises(VillageNameError):
                set_village_name(self.village, 'Vila nova', map_index)
        with self.assertRaises(VillageNameError):
            rename_village('missing-village', 'Vila nova')
        self.assertEqual(self.village, before)
        self.assertEqual(json.loads(self.path.read_text(encoding='utf-8')), before)

    def test_failed_atomic_replace_rolls_back_memory_and_preserves_old_file(self):
        before = self.path.read_bytes()
        with patch.object(sessions.os, 'replace', side_effect=OSError('disco indisponível')):
            with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(OSError):
                rename_village('own-village', 'Vila nova')
        self.assertEqual(self.village['playerInfo']['map_names'][0], 'My Empire')
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(list(Path(self.directory.name).glob('*.tmp')), [])

    def test_string_default_map_and_game_command_helper_keep_islands_separate(self):
        self.village['playerInfo']['default_map'] = '1'
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(rename_village('own-village', 'Ilha do Sol'), 'Ilha do Sol')
        self.assertEqual(self.village['playerInfo']['map_names'], ['My Empire', 'Ilha do Sol'])
        self.assertEqual(sessions.save_info('own-village'), {
            'userid': 'own-village', 'name': 'Ilha do Sol', 'xp': 100, 'level': 3,
        })
        self.assertFalse(normalize_legacy_village_name('own-village'))
        self.assertEqual(set_village_name(self.village, 'Vale Verde', '0'), 'Vale Verde')
        self.assertEqual(self.village['playerInfo']['map_names'], ['Vale Verde', 'Ilha do Sol'])

    def test_native_game_rename_uses_the_same_validation(self):
        from command import do_command
        from constants import Constant

        with contextlib.redirect_stdout(io.StringIO()):
            do_command('own-village', Constant.CMD_NAME_MAP, ['0', '  Vila São José '])
        self.assertEqual(self.village['playerInfo']['map_names'][0], 'Vila São José')
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(VillageNameError):
            do_command('own-village', Constant.CMD_NAME_MAP, [0, '<b>Vila</b>'])
        self.assertEqual(self.village['playerInfo']['map_names'][0], 'Vila São José')


if __name__ == '__main__':
    unittest.main()
