"""SE_HUD_BADGES: the Clan, PvP and Pase buttons use the new "cristal" badges; off, the old shields."""

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from hud_badges import button_art, group_buttons, hud_badges_enabled, hud_group_enabled

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


class HudGroupTests(unittest.TestCase):
    """SE_HUD_GROUP: one "Modos" button on the page shows and hides the game's Clan, PvP and Pase column."""

    def test_off_by_default(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(hud_group_enabled())
        with patch.dict(os.environ, {'SE_HUD_GROUP': 'on'}):
            self.assertTrue(hud_group_enabled())

    def test_the_page_has_the_button_only_with_the_switch(self):
        page = (ROOT / 'templates' / 'play.html').read_text(encoding='utf-8')
        start = page.index('{% if hud_group %}')
        self.assertLess(start, page.index('id="hud-group"'), 'the button is inside the switch')
        self.assertLess(page.index('id="hud-group"'), page.index('{% endif %}', start))
        self.assertLess(page.index('id="hud-more"'), page.index('id="hud-group"'), '"Modos" goes below "More"')
        script = (ROOT / 'templates' / 'js' / 'game.js').read_text(encoding='utf-8')
        self.assertIn('player.seHudShow("clanPanel", false, NaN, NaN)', script)  # the game's column stays hidden

    def test_the_row_has_the_features_that_are_on_with_their_badges(self):
        row = group_buttons('en', IMG, {'clan', 'pass'})
        self.assertEqual([b['kind'] for b in row], ['clan', 'pass'])
        self.assertEqual([b['callback'] for b in row], ['seOpenClan', 'seOpenSeasonPass'])
        self.assertEqual(row[1]['label'], 'Pass')
        with patch.dict(os.environ, {'SE_HUD_BADGES': 'on'}):
            self.assertEqual(group_buttons('es', IMG, {'pvp'})[0]['url'], '/img/hud_badge_pvp_es.png')

    def test_the_game_can_hide_and_show_the_clan_column(self):
        import swf_hud
        source = Path(swf_hud.__file__).read_text(encoding='utf-8')
        self.assertIn("for number, name in enumerate(SIDE_BUTTONS + ('clanPanel',)):", source)


class ShortMenuTests(unittest.TestCase):
    """SE_SHORT_MENU: the page's menu shows only "Rivales y saqueos" and, for an admin, "Administrar aldeas"."""

    def test_the_menu_keeps_two_links_and_hides_the_rest(self):
        page = (ROOT / 'templates' / 'play.html').read_text(encoding='utf-8')
        start = page.index('{% if short_menu %}')
        retired = page.index('<div class="menu-retired" hidden>', start)
        kept = page[start:retired]
        self.assertIn("href=\"/rivals\"", kept)
        self.assertIn("url_for('admin_villages')", kept)
        self.assertNotIn('treasury', kept)
        # game.js still finds every control it drives
        for control in ('game-volume', 'mute-button', 'expand-button', 'fullscreen-button', 'sharp-button', 'perf-button'):
            self.assertGreater(page.index(f'id="{control}"'), retired)
        css = (ROOT / 'templates' / 'css' / 'game.css').read_text(encoding='utf-8')
        self.assertIn('.menu-retired, .menu-retired * { display: none !important; }', css)


if __name__ == '__main__':
    unittest.main()
