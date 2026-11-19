"""SE_HUD_BADGES: the Clan, PvP and Pase buttons use the new "cristal" badges; off, the old shields."""

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from hud_badges import button_art, hud_badges_enabled

ROOT = Path(__file__).resolve().parent.parent
IMG = ROOT / 'templates' / 'img'


class HudBadgeTests(unittest.TestCase):
    def test_off_by_default(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(hud_badges_enabled())
        with patch.dict(os.environ, {'SE_HUD_BADGES': 'on'}):
            self.assertTrue(hud_badges_enabled())

    def test_every_badge_exists_with_the_old_size(self):
        from PIL import Image
        for kind in ('clan', 'pvp', 'pass'):
            for lang in ('es', 'en', 'pt-BR'):
                with Image.open(IMG / f'hud_badge_{kind}_{lang}.png') as image:
                    self.assertEqual(image.size, (60, 72))

    def test_on_picks_the_new_art_and_off_the_old(self):
        self.assertEqual(button_art('clan', 'pt-BR', IMG, enabled=True), '/img/hud_badge_clan_pt-BR.png')
        self.assertEqual(button_art('pass', 'en', IMG, enabled=True), '/img/hud_badge_pass_en.png')
        self.assertEqual(button_art('pvp', 'es', IMG, enabled=False), '/img/pvp_button_es.png')
        self.assertEqual(button_art('pass', 'pt-BR', IMG, enabled=False), '/img/season_pass_button_pt-BR.png')

    def test_missing_files_fall_back_to_spanish_then_to_the_old_art(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / 'clan_button_es.png').write_bytes(b'x')
            self.assertEqual(button_art('clan', 'en', folder, enabled=True), '/img/clan_button_es.png')
            (folder / 'hud_badge_clan_es.png').write_bytes(b'x')
            self.assertEqual(button_art('clan', 'en', folder, enabled=True), '/img/hud_badge_clan_es.png')


if __name__ == '__main__':
    unittest.main()
