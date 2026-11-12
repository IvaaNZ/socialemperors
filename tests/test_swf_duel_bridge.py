"""The duel bridge added to the game movie (swf_duel_bridge.py)."""

import contextlib
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from swf_abc import Abc, AbcError, disassemble, find_abc
from swf_duel_bridge import add_duel_bridge, add_duel_bridge_to_abc, static_method
from swf_localization import decode_swf

_boot_directory = tempfile.TemporaryDirectory(prefix='socialemperors-tests-')
with patch.dict(os.environ, {
    'SOCIAL_EMPIRES_DATA_DIR': _boot_directory.name,
    'SOCIAL_EMPIRES_LANGUAGE': 'pt-BR',
    'SOCIAL_EMPIRES_SAVES_DIR': str(Path(_boot_directory.name) / 'saves'),
}), contextlib.redirect_stdout(io.StringIO()):
    os.environ.pop('SE_DUELS', None)
    import server


def abc_of(movie):
    body, header_length = decode_swf(movie)
    payload, offset = find_abc(body, header_length)
    return Abc(payload[offset:]), payload[offset:]


def ops(abc, method_index):
    return [(name, operands) for _, name, operands in disassemble(abc, abc.body_of(method_index)['code'])]


class DuelBridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with contextlib.redirect_stdout(io.StringIO()):
            cls.original, _ = server.localized_game_movie('es')  # duels off: no bridge
        cls.bridged = add_duel_bridge(cls.original)
        cls.before, _ = abc_of(cls.original)
        cls.abc, cls.raw = abc_of(cls.bridged)

    def test_the_movie_rebuilds_byte_for_byte(self):
        self.assertEqual(self.abc.serialize(), self.raw)

    def test_duels_off_serves_the_movie_without_the_bridge(self):
        self.assertFalse(server.DUELS_ENABLED)
        with self.assertRaises(AbcError):
            self.before.method_of('Base', '__startDuel')
        body, _ = decode_swf(self.original)
        self.assertNotIn(b'startDuel', body)

    def test_start_duel_fills_the_tournament_data_and_loads_the_arena(self):
        code = ops(self.abc, self.abc.method_of('Base', '__startDuel'))
        names = [operands for name, operands in code if name in ('setproperty', 'callpropvoid', 'getproperty')]
        self.assertEqual(names, ['mapaInicializado', 'gameMode', 'setTournamentData 1', 'enemyData', 'playerArmy',
                                 'enemyArmy', 'loadTournament 0'])
        self.assertEqual(self.abc.methods[self.abc.method_of('Base', '__startDuel')]['param_types'], [0] * 7)

    def test_callback_registration_is_guarded_and_original_code_follows(self):
        init = self.abc.body_of(self.abc.method_of('Base', 'init'))
        original = self.before.body_of(self.before.method_of('Base', 'init'))
        added = len(init['code']) - len(original['code'])
        self.assertEqual(init['code'][added:], original['code'])
        self.assertEqual(ops(self.abc, self.abc.method_of('Base', 'init'))[:2],
                         [('getlocal0', ''), ('callpropvoid', '__registerDuel 0')])
        self.assertEqual([exception[:3] for exception in init['exceptions']],
                         [[position + added for position in exception[:3]] for exception in original['exceptions']])
        register = self.abc.method_of('Base', '__registerDuel')
        code = ops(self.abc, register)
        self.assertEqual(code[3], ('getproperty', 'available'))
        self.assertEqual(code[5:7], [('getlex', 'ExternalInterface'), ('pushstring', "'startDuel'")])
        self.assertEqual(len(self.abc.body_of(register)['exceptions']), 1)  # errors stay inside it

    def test_score_is_the_percentage_of_the_enemy_army_destroyed(self):
        ia_end = ops(self.abc, self.abc.method_of('TournamentIA', 'end'))
        self.assertEqual(ia_end[:6], [('getlex', 'TournamentManager'), ('getlocal0', ''), ('getlocal0', ''),
                                      ('getproperty', 'arUnits'), ('callproperty', 'countArrayItems 1'),
                                      ('setproperty', '__duelAlive')])
        end = ops(self.abc, static_method(self.abc, 'TournamentManager', 'end'))
        self.assertIn(('pushbyte', '100'), end[:8])
        self.assertIn(('setproperty', 'value'), end[:20])
        for class_name, method in (('TournamentIA', 'end'), ('TournamentManager', 'end')):
            before = (self.before.method_of(class_name, method) if class_name == 'TournamentIA'
                      else static_method(self.before, class_name, method))
            after = (self.abc.method_of(class_name, method) if class_name == 'TournamentIA'
                     else static_method(self.abc, class_name, method))
            self.assertTrue(self.abc.body_of(after)['code'].endswith(self.before.body_of(before)['code']))

    def test_the_bridge_is_added_once(self):
        with self.assertRaises(AbcError):
            add_duel_bridge_to_abc(abc_of(self.bridged)[0])


if __name__ == '__main__':
    unittest.main()
