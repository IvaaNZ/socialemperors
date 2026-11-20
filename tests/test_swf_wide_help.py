"""SE_WIDE_HELP: the player's units help from 10 tiles away and join an attack order on an enemy."""

import os
import unittest
from pathlib import Path
from unittest.mock import patch

from swf_abc import Abc, AbcError, disassemble
from swf_duel_bridge import DO_ABC
from swf_localization import decode_swf, iter_tags
from swf_wide_help import RECRUIT_METHOD, add_wide_help, add_wide_help_to_abc, wide_help_enabled

MOVIE = Path('assets/flash/SocialEmpires0926bsec.swf')


def abc_of(data):
    body, header_length = decode_swf(data)
    for code, payload, _ in iter_tags(body, header_length):
        if code == DO_ABC:
            return Abc(payload[payload.index(b'\0', 4) + 1:])
    raise AssertionError('no DoABC')


class WideHelp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.abc = abc_of(add_wide_help(MOVIE.read_bytes()))

    def ops(self, cls, method):
        return [op[1:] for op in disassemble(self.abc, self.abc.body_of(self.abc.method_of(cls, method))['code'])]

    def test_off_by_default(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(wide_help_enabled())
        with patch.dict(os.environ, {'SE_WIDE_HELP': 'on'}):
            self.assertTrue(wide_help_enabled())

    def test_a_hit_calls_up_to_10_tiles_away(self):
        ops = self.ops('IsoFightingElement', 'recibirAtaque')
        radius = [first for first, second in zip(ops, ops[1:]) if second == ('setslot', '5')
                  and first[0] == 'pushbyte' and first[1] in ('4', '10')]
        self.assertEqual(radius, [('pushbyte', '10')])

    def test_the_enemies_keep_their_4_tiles(self):
        ops = self.ops('IsoFightingElement', 'CallForHelp')
        self.assertEqual(ops[:7], [('getlocal0', ''), ('pushscope', ''), ('getlocal0', ''), ('getproperty', 'PlayerID'),
                                   ('getlex', 'Constants'), ('getproperty', 'PLAYER_SELF'), ops[6]])
        self.assertEqual(ops[6][0], 'ifeq')
        self.assertEqual(ops.count(('pushbyte', '4')), 4)

    def test_an_attack_order_takes_the_idle_fighters_near_the_first_unit(self):
        self.assertEqual(self.ops('Base', 'startMovements')[4], ('callproperty', f'{RECRUIT_METHOD} 3'))
        names = [op[1] for op in self.ops('Base', RECRUIT_METHOD)]
        for name in ('PLAYER_SELF', 'PLAYER_ENEMY', 'arPlayerIsoFightingElements', 'bDead', 'uiAttack',
                     'SUBCATFUNC_UNIT_PEASANT', 'bMoving', 'bMovingToDoAction', 'bAttacking', 'concat 0', 'push 1'):
            self.assertIn(name, names)
        self.assertEqual(self.ops('Base', RECRUIT_METHOD).count(('pushbyte', '10')), 4)  # |dx| and |dy| up to 10

    def test_it_is_added_once(self):
        with self.assertRaises(AbcError):
            add_wide_help_to_abc(self.abc)

    def test_the_server_applies_it_with_the_switch(self):
        server = Path('server.py').read_text(encoding='utf-8')
        self.assertIn('if WIDE_HELP_ENABLED:', server)
        self.assertIn('translated = add_wide_help(translated)', server)


if __name__ == '__main__':
    unittest.main()
