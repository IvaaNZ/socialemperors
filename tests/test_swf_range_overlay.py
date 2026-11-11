"""ABC round trip and the attack-area overlay added to the game code."""

from pathlib import Path
import unittest

from swf_abc import Abc, AbcError, disassemble, find_abc
from swf_localization import decode_swf
from swf_range_overlay import (DRAW_METHOD, NAMES, SHAPE_SLOT, add_range_overlay, add_range_overlay_to_abc,
                               assemble)

MOVIE = Path('assets/flash/SocialEmpires0926bsec.swf')


def game_abc(data=None):
    body, header = decode_swf(data or MOVIE.read_bytes())
    payload, offset = find_abc(body, header)
    return payload[offset:]


class AbcRoundTripTests(unittest.TestCase):
    def test_parse_and_serialize_is_byte_exact(self):
        source = game_abc()
        self.assertEqual(Abc(source).serialize(), source)

    def test_every_method_body_disassembles(self):
        abc = Abc(game_abc())
        for body in abc.bodies:
            disassemble(abc, body['code'])


class RangeOverlayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = game_abc()
        cls.abc = add_range_overlay_to_abc(Abc(cls.source))
        cls.output = cls.abc.serialize()

    def test_overlay_round_trips_and_keeps_existing_code(self):
        again = Abc(self.output)
        self.assertEqual(again.serialize(), self.output)
        original = Abc(self.source)
        self.assertEqual(len(again.bodies), len(original.bodies) + 1)
        update = original.method_of('Base', 'UpdateGame2')
        for before, after in zip(original.bodies, again.bodies):
            if before['method'] != update:
                self.assertEqual(before['code'], after['code'])

    def test_update_calls_the_new_method_first(self):
        update = self.abc.body_of(self.abc.method_of('Base', 'UpdateGame2'))
        first = disassemble(self.abc, update['code'])[:2]
        self.assertEqual([(name, operands) for _, name, operands in first],
                         [('getlocal0', ''), ('callpropvoid', f'{DRAW_METHOD} 0')])

    def test_draw_method_uses_only_existing_game_names(self):
        body = self.abc.body_of(self.abc.method_of('Base', DRAW_METHOD))
        used = {operands.split(' ')[0] for _, name, operands in disassemble(self.abc, body['code'])
                if name in ('getproperty', 'setproperty', 'getlex', 'callpropvoid', 'callproperty',
                            'findpropstrict', 'constructprop')}
        allowed = set(NAMES) | {'push', SHAPE_SLOT}
        self.assertTrue(used <= allowed, used - allowed)
        self.assertIn('lineStyle', used)
        self.assertIn('iconoSeleccionado', used)

    def test_overlay_is_added_once_and_the_movie_still_builds(self):
        with self.assertRaises(AbcError):
            add_range_overlay_to_abc(Abc(self.output))
        movie = add_range_overlay(MOVIE.read_bytes())
        self.assertEqual(Abc(game_abc(movie)).serialize(), game_abc(movie))

    def test_assembler_resolves_forward_and_backward_branches(self):
        code = assemble([('label:', 'top'), ('label',), ('jump', 'end'), ('jump', 'top'), ('label:', 'end'), ('returnvoid',)])
        ops = disassemble(Abc(self.source), code)
        self.assertEqual([(offset, name, operands) for offset, name, operands in ops],
                         [(0, 'label', ''), (1, 'jump', '->9'), (5, 'jump', '->0'), (9, 'returnvoid', '')])


if __name__ == '__main__':
    unittest.main()
