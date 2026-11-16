import unittest
from pathlib import Path

from swf_abc import Abc, AbcError, disassemble
from swf_duel_bridge import DO_ABC
from swf_localization import decode_swf, iter_tags
from swf_view import (CALLBACKS, FIT_METHOD, MOVE_METHOD, REGISTER_METHOD, VIEW_METHOD, ZOOM_METHOD, add_view,
                      add_view_to_abc)

MOVIE = Path('assets/flash/SocialEmpires0926bsec.swf')


def abc_of(data):
    body, header_length = decode_swf(data)
    return next(Abc(payload[payload.index(b'\0', 4) + 1:]) for code, payload, _ in iter_tags(body, header_length)
                if code == DO_ABC)


class View(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.abc = abc_of(add_view(MOVIE.read_bytes()))

    def ops(self, method):
        return disassemble(self.abc, self.abc.body_of(self.abc.method_of('Base', method))['code'])

    def names(self, method):
        return [str(op[2]) for op in self.ops(method) if len(op) > 2]

    def test_the_state_has_the_zoom_its_limits_and_the_stage_size(self):
        names = self.names(VIEW_METHOD)
        for name in ('currentZoom', 'MIN_ZOOM', 'MAX_ZOOM', 'stageWidth', 'stageHeight'):
            self.assertIn(name, names)

    def test_the_fit_uses_the_games_own_full_screen_layout_and_hides_the_slider(self):
        names = self.names(FIT_METHOD)
        self.assertIn('normalscreen 0', names)
        self.assertIn('fullscreen 0', names)
        self.assertLess(names.index('normalscreen 0'), names.index('fullscreen 0'))
        self.assertIn('zoomSlider', names)
        self.assertIn('centerBuildings 0', names)

    def test_the_zoom_keeps_the_point_under_the_pointer_and_respects_the_games_locks(self):
        names = self.names(ZOOM_METHOD)
        for name in ('tutorialMode', 'mapLocked', 'addingBuildings', 'globalToLocal 1', 'localToGlobal 1',
                     'setZoom 2', 'setZoom 1', 'moveMap 2'):
            self.assertIn(name, names)
        self.assertIn('moveMap 2', self.names(MOVE_METHOD))

    def test_the_page_can_call_it_and_init_registers_it_first(self):
        for callback, _ in CALLBACKS:
            self.assertIn(callback, self.abc.strings)
        first = self.ops('init')[:2]
        self.assertEqual([op[1] for op in first], ['getlocal0', 'callpropvoid'])
        self.assertIn(REGISTER_METHOD, str(first[1][2]))

    def test_it_is_added_once(self):
        with self.assertRaises(AbcError):
            add_view_to_abc(self.abc)


if __name__ == '__main__':
    unittest.main()
