import unittest
from pathlib import Path

from swf_abc import Abc, AbcError, disassemble
from swf_duel_bridge import DO_ABC
from swf_fast_hover import SLOTS, add_fast_hover, add_fast_hover_to_abc
from swf_localization import decode_swf, iter_tags

MOVIE = Path('assets/flash/SocialEmpires0926bsec.swf')


def abc_of(data):
    body, header_length = decode_swf(data)
    return next(Abc(payload[payload.index(b'\0', 4) + 1:]) for code, payload, _ in iter_tags(body, header_length)
                if code == DO_ABC)


class FastHover(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.abc = abc_of(add_fast_hover(MOVIE.read_bytes()))
        cls.ops = disassemble(cls.abc, cls.abc.body_of(cls.abc.method_of('IsoInteractiveElement', 'getPixel'))['code'])
        cls.names = [str(op[2]) for op in cls.ops if len(op) > 2]

    def test_the_kept_picture_lives_in_static_slots(self):
        statics = [self.abc.multiname_name(t['name']) for t in self.abc.classes[self.abc.class_index('IsoInteractiveElement')][1]]
        for slot in SLOTS:
            self.assertIn(slot, statics)

    def test_it_draws_only_when_the_kept_picture_does_not_fit(self):
        # one drawing, guarded by the three checks, then the pixel read from the kept picture
        self.assertEqual(self.names.count('draw 2'), 1)
        self.assertEqual(self.names.count('getPixel32 2'), 1)
        self.assertEqual([op[1] for op in self.ops].count('ifstrictne'), 2)
        self.assertLess(self.names.index('draw 2'), self.names.index('getPixel32 2'))
        self.assertIn('dispose 0', self.names)  # the previous picture is freed

    def test_units_and_icons_answer_without_drawing_as_in_the_game(self):
        for name in ('IsoUnit', 'iconCollect', 'iconsHurryUp'):
            self.assertIn(name, self.names)
        self.assertLess(self.names.index('iconsHurryUp'), self.names.index('draw 2'))

    def test_it_is_added_once(self):
        with self.assertRaises(AbcError):
            add_fast_hover_to_abc(self.abc)


if __name__ == '__main__':
    unittest.main()
