"""SE_KEEP_FIGHTING: the player's units attack the nearest enemy when theirs dies."""

import os
import unittest
from pathlib import Path
from unittest.mock import patch

from swf_abc import Abc, AbcError, disassemble
from swf_duel_bridge import DO_ABC
from swf_keep_fighting import NEXT_METHOD, add_keep_fighting, add_keep_fighting_to_abc, keep_fighting_enabled
from swf_localization import decode_swf, iter_tags

MOVIE = Path('assets/flash/SocialEmpires0926bsec.swf')


def abc_of(data):
    body, header_length = decode_swf(data)
    for code, payload, _ in iter_tags(body, header_length):
        if code == DO_ABC:
            return Abc(payload[payload.index(b'\0', 4) + 1:])
    raise AssertionError('no DoABC')


class KeepFighting(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.abc = abc_of(add_keep_fighting(MOVIE.read_bytes()))

    def ops(self, method):
        return [op[1:] for op in disassemble(self.abc, self.abc.body_of(self.abc.method_of('IA', method))['code'])]

    def test_off_by_default(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(keep_fighting_enabled())
        with patch.dict(os.environ, {'SE_KEEP_FIGHTING': 'on'}):
            self.assertTrue(keep_fighting_enabled())

    def test_target_dead_asks_for_the_next_enemy_first(self):
        ops = self.ops('TargetDead')
        self.assertEqual(ops[4], ('callproperty', f'{NEXT_METHOD} 3'))
        self.assertEqual([ops[5][0], ops[6]], ['iffalse', ('returnvoid', '')])

    def test_only_the_players_units_look_for_the_nearest_enemy_and_attack_it(self):
        ops = self.ops(NEXT_METHOD)
        names = [op[1] for op in ops]
        for name in ('PLAYER_SELF', 'ciaCollectiveIA', 'STATE_FORCE_MOVE', 'iAggroRange', 'acquireNewTarget 3',
                     'IA_Attack 1'):
            self.assertIn(name, names)
        self.assertLess(names.index('PLAYER_SELF'), names.index('acquireNewTarget 3'))
        self.assertIn(('pushbyte', '10'), ops)  # at least 10 tiles around the dead enemy

    def test_it_is_added_once(self):
        with self.assertRaises(AbcError):
            add_keep_fighting_to_abc(self.abc)

    def test_the_server_applies_it_with_the_switch(self):
        server = Path('server.py').read_text(encoding='utf-8')
        self.assertIn('if KEEP_FIGHTING_ENABLED:', server)


if __name__ == '__main__':
    unittest.main()
