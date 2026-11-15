import unittest
from pathlib import Path

from swf_abc import Abc, AbcError, disassemble
from swf_daylight import CALLBACK, SET_METHOD, add_daylight, add_daylight_to_abc
from swf_duel_bridge import DO_ABC
from swf_localization import decode_swf, iter_tags

MOVIE = Path('assets/flash/SocialEmpires0926bsec.swf')


def abc_of(data):
    body, header_length = decode_swf(data)
    return next(Abc(payload[payload.index(b'\0', 4) + 1:]) for code, payload, _ in iter_tags(body, header_length)
                if code == DO_ABC)


class DayLight(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.abc = abc_of(add_daylight(MOVIE.read_bytes()))

    def test_the_map_layer_gets_a_colour_transform(self):
        ops = disassemble(self.abc, self.abc.body_of(self.abc.method_of('Base', SET_METHOD))['code'])
        names = [str(op[2]) for op in ops if len(op) > 2]
        self.assertIn('buildingLayer', names)
        self.assertIn('ColorTransform 4', names)
        self.assertIn('colorTransform', names)

    def test_the_page_can_call_it_and_init_registers_it_first(self):
        self.assertIn(CALLBACK, self.abc.strings)
        first = disassemble(self.abc, self.abc.body_of(self.abc.method_of('Base', 'init'))['code'])[:2]
        self.assertEqual([op[1] for op in first], ['getlocal0', 'callpropvoid'])

    def test_it_is_added_once(self):
        with self.assertRaises(AbcError):
            add_daylight_to_abc(self.abc)
