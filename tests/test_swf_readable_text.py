"""White game lettering gets a black outline; spent units leave the team window (swf_readable_text.py)."""

import contextlib
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from swf_abc import AbcError, disassemble, u30
from swf_readable_text import OUTLINE_METHOD, REGISTER_METHOD, make_text_readable, make_text_readable_in_abc
from test_swf_duel_bridge import abc_of

_boot_directory = tempfile.TemporaryDirectory(prefix='socialemperors-tests-')
with patch.dict(os.environ, {
    'SOCIAL_EMPIRES_DATA_DIR': _boot_directory.name,
    'SOCIAL_EMPIRES_LANGUAGE': 'pt-BR',
    'SOCIAL_EMPIRES_SAVES_DIR': str(Path(_boot_directory.name) / 'saves'),
}), contextlib.redirect_stdout(io.StringIO()):
    import server


class ReadableTextTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        clear = getattr(server.localized_game_movie, 'cache_clear', lambda: None)
        clear()
        with patch.object(server, 'READABLE_UI_ENABLED', False), contextlib.redirect_stdout(io.StringIO()):
            cls.original, _ = server.localized_game_movie('es')
        clear()
        cls.before, _ = abc_of(cls.original)
        cls.abc, cls.raw = abc_of(make_text_readable(cls.original))

    def ops(self, cls, method):
        return [(name, str(operand)) for _, name, operand in disassemble(self.abc, self.abc.body_of(self.abc.method_of(cls, method))['code'])]

    def test_the_movie_rebuilds_byte_for_byte_and_the_switch_is_on_by_default(self):
        self.assertEqual(self.abc.serialize(), self.raw)
        self.assertIn("READABLE_UI_ENABLED = os.environ.get('SE_READABLE_UI', 'on')", Path(server.__file__).read_text(encoding='utf-8'))
        base = self.before.instances[self.before.class_index('Base')]
        self.assertNotIn(OUTLINE_METHOD, [self.before.multiname_name(t['name']) for t in base['traits']])
        with self.assertRaises(AbcError):
            make_text_readable_in_abc(self.abc)

    def test_white_text_that_appears_gets_a_black_outline(self):
        self.assertEqual(self.ops('Base', 'init')[:2], [('getlocal0', ''), ('callpropvoid', f'{REGISTER_METHOD} 0')])
        register = self.ops('Base', REGISTER_METHOD)
        self.assertIn(('getproperty', 'ADDED_TO_STAGE'), register)
        self.assertIn(('pushtrue', ''), register)  # capture phase: the event does not bubble
        outline = self.ops('Base', OUTLINE_METHOD)
        for op in (('getproperty', 'textColor'), ('constructprop', 'GlowFilter 5'), ('setproperty', 'filters')):
            self.assertIn(op, outline)
        white = [int(operand) for name, operand in outline if name == 'pushint']
        self.assertEqual(len(white), 2)
        self.assertEqual({self.abc.ints[index - 1] for index in white}, {u30(0xFFFFFF)})  # pool index -> white
        for method in (OUTLINE_METHOD, REGISTER_METHOD):
            self.assertEqual(len(self.abc.body_of(self.abc.method_of('Base', method))['exceptions']), 1)

    def test_a_spent_unit_hides_and_comes_back(self):
        self.assertEqual(self.ops('ThumbUnit', 'deactivate')[:3], [('getlocal0', ''), ('pushfalse', ''), ('setproperty', 'visible')])
        self.assertEqual(self.ops('ThumbUnit', 'activate')[:3], [('getlocal0', ''), ('pushtrue', ''), ('setproperty', 'visible')])


if __name__ == '__main__':
    unittest.main()
