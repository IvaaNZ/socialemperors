import unittest
from pathlib import Path

from swf_abc import Abc, AbcError, disassemble
from swf_duel_bridge import DO_ABC
from swf_localization import decode_swf, iter_tags
from swf_perf_mode import CALLBACK, PERF_METHOD, REGISTER_METHOD, add_perf_mode, add_perf_mode_to_abc

MOVIE = Path('assets/flash/SocialEmpires0926bsec.swf')


def abc_of(data):
    body, header_length = decode_swf(data)
    return next(Abc(payload[payload.index(b'\0', 4) + 1:]) for code, payload, _ in iter_tags(body, header_length)
                if code == DO_ABC)


class PerfMode(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.abc = abc_of(add_perf_mode(MOVIE.read_bytes()))
        cls.ops = disassemble(cls.abc, cls.abc.body_of(cls.abc.method_of('Base', PERF_METHOD))['code'])
        cls.names = [str(op[2]) for op in cls.ops if len(op) > 2]

    def test_only_the_buildings_are_walked_and_units_are_left_alone(self):
        self.assertIn('buildingLayer', self.names)
        self.assertLess(self.names.index('IsoBuilding'), self.names.index('IsoUnit'))
        self.assertEqual(self.names.count('IsoBuilding'), 1)

    def test_clips_with_more_than_one_frame_stop(self):
        self.assertIn('totalFrames', self.names)
        self.assertEqual(self.names.count('stop 0'), 1)
        self.assertNotIn('play 0', self.names)

    def test_the_page_can_call_it_and_init_registers_it_first(self):
        self.assertIn(CALLBACK, self.abc.strings)
        first = disassemble(self.abc, self.abc.body_of(self.abc.method_of('Base', 'init'))['code'])[:2]
        self.assertEqual([op[1] for op in first], ['getlocal0', 'callpropvoid'])
        self.assertIn(REGISTER_METHOD, str(first[1][2]))

    def test_it_is_added_once(self):
        with self.assertRaises(AbcError):
            add_perf_mode_to_abc(self.abc)


if __name__ == '__main__':
    unittest.main()
