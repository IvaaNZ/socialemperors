"""The "Clan" button added to the game's icon panel (swf_clan_button.py)."""

import contextlib
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from swf_abc import AbcError, disassemble
from swf_clan_button import (ADD_METHOD, CALLBACK, CHALLENGE_CLICK_METHOD, CHALLENGE_TAB, CLICK_METHOD, GAME_MAX_HEIGHT, MAX_HEIGHT,
                             add_clan_button)
from swf_localization import decode_swf
from test_swf_duel_bridge import abc_of

_boot_directory = tempfile.TemporaryDirectory(prefix='socialemperors-tests-')
with patch.dict(os.environ, {
    'SOCIAL_EMPIRES_DATA_DIR': _boot_directory.name,
    'SOCIAL_EMPIRES_LANGUAGE': 'pt-BR',
    'SOCIAL_EMPIRES_SAVES_DIR': str(Path(_boot_directory.name) / 'saves'),
}), contextlib.redirect_stdout(io.StringIO()):
    os.environ.pop('SE_CLANS', None)
    import server

ROOT = Path(__file__).resolve().parents[1]


def ops(abc, method_index):
    return [(name, operands) for _, name, operands in disassemble(abc, abc.body_of(method_index)['code'])]


class ClanButtonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with contextlib.redirect_stdout(io.StringIO()):
            cls.original, _ = server.localized_game_movie('es')  # clans off: no button
        cls.patched = add_clan_button(cls.original, tooltip='Clan', image_url='/img/clan_button_es.png',
                                      challenge_tooltip='Retar clan', challenge_image_url='/img/clan_challenge_button_es.png')
        cls.before, _ = abc_of(cls.original)
        cls.abc, cls.raw = abc_of(cls.patched)

    def test_the_movie_rebuilds_byte_for_byte(self):
        self.assertEqual(self.abc.serialize(), self.raw)

    def test_clans_off_serves_the_movie_without_the_button(self):
        self.assertFalse(server.CLANS_ENABLED)
        with self.assertRaises(AbcError):
            self.before.method_of('GuiManager', ADD_METHOD)
        body, _ = decode_swf(self.original)
        self.assertNotIn(CALLBACK.encode(), body)

    def test_the_panel_builder_adds_the_buttons_on_every_path(self):
        original = ops(self.before, self.before.method_of('GuiManager', 'createViralButtons'))
        patched = ops(self.abc, self.abc.method_of('GuiManager', 'createViralButtons'))
        # room for three icons: the only original operand changed
        changed = [(a, b) for a, b in zip(original, patched[:len(original) - 1]) if a != b]
        self.assertEqual(changed, [(('pushshort', str(GAME_MAX_HEIGHT)), ('pushshort', str(MAX_HEIGHT)))])
        self.assertEqual(patched[len(original) - 1:], [('getlocal0', ''), ('callpropvoid', f'{ADD_METHOD} 0'), ('returnvoid', '')])
        # the branches that ended the method still land on the new call (its offset did not move)
        code = disassemble(self.abc, self.abc.body_of(self.abc.method_of('GuiManager', 'createViralButtons'))['code'])
        call_at = next(offset for offset, name, operands in code if operands == f'{ADD_METHOD} 0') - 1
        old_end = disassemble(self.before, self.before.body_of(self.before.method_of('GuiManager', 'createViralButtons'))['code'])[-1][0]
        self.assertEqual(call_at, old_end)

    def test_both_buttons_are_icons_of_the_game_panel(self):
        method = self.abc.method_of('GuiManager', ADD_METHOD)
        code = ops(self.abc, method)
        for text in ("'/img/clan_button_es.png'", "'Clan'", "'/img/clan_challenge_button_es.png'", "'Retar clan'"):
            self.assertIn(('pushstring', text), code)
        calls = [operands for name, operands in code if name in ('constructprop', 'callpropvoid')]
        self.assertEqual(calls, ['Sprite 0', 'Loader 0', 'URLRequest 1', 'load 1', 'addChild 1', 'addIcon 3'] * 2)
        handlers = [operands for name, operands in code if name == 'getproperty' and operands.startswith('__clan')]
        self.assertEqual(handlers, [CLICK_METHOD, CHALLENGE_CLICK_METHOD])
        self.assertEqual(len(self.abc.body_of(method)['exceptions']), 1)  # it can never break the interface

    def test_a_click_asks_the_page_to_open_the_clan_window(self):
        for name, extra in ((CLICK_METHOD, []), (CHALLENGE_CLICK_METHOD, [CHALLENGE_TAB])):
            method = self.abc.method_of('GuiManager', name)
            code = ops(self.abc, method)
            pushed = [operands for op, operands in code if op == 'pushstring']
            self.assertEqual(pushed, ["'rollOut'", f"'{CALLBACK}'"] + [f"'{text}'" for text in extra])
            self.assertIn(('callpropvoid', 'dispatchEvent 1'), code)  # the tooltip goes away on click
            self.assertIn(('callpropvoid', f'call {1 + len(extra)}'), code)
            self.assertIn(('getproperty', 'available'), code)
            self.assertEqual(len(self.abc.methods[method]['param_types']), 1)  # the click event
            self.assertEqual(len(self.abc.body_of(method)['exceptions']), 1)

    def test_it_is_added_once(self):
        with self.assertRaises(AbcError):
            add_clan_button(self.patched)

    def test_button_art_exists_for_every_language(self):
        for language in ('es', 'en', 'pt-BR'):
            for prefix in ('clan_button', 'clan_challenge_button'):
                art = ROOT / 'templates' / 'img' / f'{prefix}_{language}.png'
                self.assertEqual(art.read_bytes()[:8], b'\x89PNG\r\n\x1a\n', art.name)

    def test_the_page_opens_the_window_from_the_game(self):
        script = (ROOT / 'templates' / 'js' / 'clan_overlay.js').read_text(encoding='utf-8')
        self.assertIn('window.seOpenClan', script)
        game = (ROOT / 'templates' / 'js' / 'game.js').read_text(encoding='utf-8')
        self.assertIn('document.getElementById("clan-overlay-config")', game)  # allowScriptAccess with clans on


if __name__ == '__main__':
    unittest.main()
