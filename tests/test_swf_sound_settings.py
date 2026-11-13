"""The game's music and sound buttons keep their choice (swf_sound_settings.py, SE_SOUND_FIX)."""

import contextlib
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from swf_abc import AbcError, disassemble
from swf_sound_settings import MUSIC_METHOD, SAVE_METHOD, fix_sound_settings, fix_sound_settings_in_abc
from test_swf_duel_bridge import abc_of

_boot_directory = tempfile.TemporaryDirectory(prefix='socialemperors-tests-')
with patch.dict(os.environ, {
    'SOCIAL_EMPIRES_DATA_DIR': _boot_directory.name,
    'SOCIAL_EMPIRES_LANGUAGE': 'pt-BR',
    'SOCIAL_EMPIRES_SAVES_DIR': str(Path(_boot_directory.name) / 'saves'),
}), contextlib.redirect_stdout(io.StringIO()):
    import server


def ops(abc, method_index):
    return [(name, str(operand)) for _, name, operand in disassemble(abc, abc.body_of(method_index)['code'])]


class SoundSettingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with patch.object(server, 'SOUND_FIX_ENABLED', False), contextlib.redirect_stdout(io.StringIO()):
            cls.original, _ = server.localized_game_movie('es')
        cls.patched = fix_sound_settings(cls.original)
        cls.before, _ = abc_of(cls.original)
        cls.abc, cls.raw = abc_of(cls.patched)

    def test_the_movie_rebuilds_byte_for_byte(self):
        self.assertEqual(self.abc.serialize(), self.raw)

    def test_the_switch_is_on_by_default_and_off_serves_the_game_without_it(self):
        self.assertIn("SOUND_FIX_ENABLED = os.environ.get('SE_SOUND_FIX', 'on')", Path(server.__file__).read_text(encoding='utf-8'))
        gui = self.before.instances[self.before.class_index('GuiManager')]
        self.assertNotIn(SAVE_METHOD, [self.before.multiname_name(t['name']) for t in gui['traits']])
        with self.assertRaises(AbcError):
            fix_sound_settings_in_abc(self.abc)  # added once

    def test_both_buttons_save_the_choice_and_the_music_button_sets_it_first(self):
        save = ops(self.abc, self.abc.method_of('GuiManager', SAVE_METHOD))
        self.assertIn(('callpropvoid', 'flush 0'), save)
        self.assertIn(('getproperty', 'settings'), save)
        for name in ('toggleMusic', 'toggleSound'):
            code = ops(self.abc, self.abc.method_of('GuiManager', name))
            self.assertEqual(code[-2:], [('callpropvoid', f'{SAVE_METHOD} 0'), ('returnvoid', '')], name)
        music = ops(self.abc, self.abc.method_of('GuiManager', 'toggleMusic'))
        self.assertEqual(music[:2], [('getlocal0', ''), ('callpropvoid', f'{MUSIC_METHOD} 0')])
        first = ops(self.abc, self.abc.method_of('GuiManager', MUSIC_METHOD))
        self.assertIn(('getproperty', 'musicOn'), first)
        self.assertIn(('setproperty', 'music'), first)
        # Each new method runs inside its own try/catch, and the handler pushes the scope back.
        for name in (SAVE_METHOD, MUSIC_METHOD):
            body = self.abc.body_of(self.abc.method_of('GuiManager', name))
            self.assertEqual(len(body['exceptions']), 1)


if __name__ == '__main__':
    unittest.main()
