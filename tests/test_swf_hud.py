import unittest
from pathlib import Path

from swf_abc import Abc, AbcError, disassemble
from swf_duel_bridge import DO_ABC
from swf_hud import (CALLBACKS, CASH_METHOD, EXPERIENCE_PARTS, HIDDEN, HIDE_METHOD, REGISTER_METHOD, STATE_FIELDS,
                     STATE_METHOD, TEXT_FIELDS, add_hud, add_hud_to_abc)
from swf_localization import decode_swf, iter_tags

MOVIE = Path('assets/flash/SocialEmpires0926bsec.swf')


def abc_of(data):
    body, header_length = decode_swf(data)
    return next(Abc(payload[payload.index(b'\0', 4) + 1:]) for code, payload, _ in iter_tags(body, header_length)
                if code == DO_ABC)


class Hud(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.abc = abc_of(add_hud(MOVIE.read_bytes()))

    def names(self, method):
        ops = disassemble(self.abc, self.abc.body_of(self.abc.method_of('Base', method))['code'])
        return [str(op[2]) for op in ops if len(op) > 2]

    def test_the_state_has_the_players_numbers_and_the_shown_texts(self):
        names = self.names(STATE_METHOD)
        for _, field in STATE_FIELDS + TEXT_FIELDS:
            self.assertIn(field, names)
        self.assertIn('gameMode', names)
        self.assertIn('popupLayer', names)
        ops = disassemble(self.abc, self.abc.body_of(self.abc.method_of('Base', STATE_METHOD))['code'])
        self.assertIn(str(len(STATE_FIELDS) + len(TEXT_FIELDS) + 2), [op[2] for op in ops if op[1] == 'newobject'])

    def test_the_ribbon_goes_but_the_world_globe_stays(self):
        names = self.names(HIDE_METHOD)
        for name in HIDDEN:
            self.assertIn(name, names)
        self.assertEqual(names.count('getChildAt 1'), len(EXPERIENCE_PARTS))
        self.assertNotIn(9, EXPERIENCE_PARTS)  # btnWorld, the globe

    def test_the_cash_button_gets_a_mouse_press(self):
        ops = disassemble(self.abc, self.abc.body_of(self.abc.method_of('Base', CASH_METHOD))['code'])
        self.assertIn("'mouseDown'", [str(op[2]) for op in ops if op[1] == 'pushstring'])

    def test_the_page_can_call_it_and_init_registers_it_first(self):
        for callback in CALLBACKS:
            self.assertIn(callback, self.abc.strings)
        first = disassemble(self.abc, self.abc.body_of(self.abc.method_of('Base', 'init'))['code'])[:2]
        self.assertEqual([op[1] for op in first], ['getlocal0', 'callpropvoid'])
        self.assertIn(REGISTER_METHOD, str(first[1][2]))

    def test_it_is_added_once(self):
        with self.assertRaises(AbcError):
            add_hud_to_abc(self.abc)


if __name__ == '__main__':
    unittest.main()
