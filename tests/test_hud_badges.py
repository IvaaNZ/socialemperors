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
        self.assertNotIn("/rivals", kept)  # the PvP window has it (Modos > PvP)
        self.assertIn("url_for('admin_villages')", kept)
        self.assertNotIn('treasury', kept)
        # game.js still finds every control it drives
        for control in ('game-volume', 'mute-button', 'expand-button', 'fullscreen-button', 'sharp-button', 'perf-button'):
            self.assertGreater(page.index(f'id="{control}"'), retired)
        css = (ROOT / 'templates' / 'css' / 'game.css').read_text(encoding='utf-8')
        self.assertIn('.menu-retired, .menu-retired * { display: none !important; }', css)


    def test_a_player_has_no_menu_button_until_the_village_changes(self):
        script = (ROOT / 'templates' / 'js' / 'game.js').read_text(encoding='utf-8')
        self.assertIn('controlsToggle.hidden = Boolean(config.menuHidden);', script)
        self.assertIn('controlsToggle.hidden = false;  // also when the menu is hidden', script)
        server = (ROOT / 'server.py').read_text(encoding='utf-8')
        self.assertIn("menu_hidden=SHORT_MENU_ENABLED and not (g.account and g.account['is_admin'])", server)

    def test_escape_keeps_the_game_filling_the_tab_when_its_button_is_retired(self):
        script = (ROOT / 'templates' / 'js' / 'game.js').read_text(encoding='utf-8')
        self.assertIn('} else if (expanded && !expand.closest(".menu-retired")) {', script)


class StayInGameTests(unittest.TestCase):
    """SE_STAY_IN_GAME (on by default): nothing in the Clan and PvP windows leaves the game."""

    def test_on_by_default(self):
        server = (ROOT / 'server.py').read_text(encoding='utf-8')
        self.assertIn("os.environ.get('SE_STAY_IN_GAME', 'on')", server)

    def test_the_windows_keep_the_player_in_the_game(self):
        js = ROOT / 'templates' / 'js'
        pvp = (js / 'pvp_overlay.js').read_text(encoding='utf-8')
        self.assertIn('(stayInGame ? "" : \'<p class="pvpx-portal">', pvp)  # no "Open the full page" link
        clan = (js / 'clan_overlay.js').read_text(encoding='utf-8')
        self.assertIn('data-in-game="duels"', clan)
        self.assertIn('window.seOpenPvp(inGame.dataset.inGame);', clan)  # "Go to duels" opens the Duels tab


class SmoothPageTests(unittest.TestCase):
    """SE_SMOOTH_PAGE: lighter rain and snow, the daily chest's glow without a filter animation; missions placed."""

    def test_the_weather_is_capped_and_drawn_in_one_go(self):
        script = (ROOT / 'templates' / 'js' / 'game.js').read_text(encoding='utf-8')
        self.assertIn('const WEATHER_FPS = 30;', script)
        self.assertIn('const WEATHER_SCALE = 0.5;', script)
        start = script.index('function drawWeatherSmooth(now)')
        body = script[start:script.index('function drawWeather()', start)]
        self.assertEqual(body.count('.stroke()'), 1)  # one stroke for every streak
        self.assertNotIn('getBoundingClientRect', body)  # the layer's place is read in placeWeather, not each frame

    def test_the_chest_glows_four_times_without_a_filter(self):
        css = (ROOT / 'templates' / 'css' / 'game.css').read_text(encoding='utf-8')
        rule = next(line for line in css.splitlines()
                    if line.startswith('body.smooth-page .hud-daily.is-ready .hud-daily-chest {'))
        self.assertIn('hud-daily-pulse 1.4s ease-in-out 4', rule)
        pulse = next(line for line in css.splitlines() if line.startswith('@keyframes hud-daily-pulse'))
        self.assertNotIn('filter', pulse)

    def test_the_missions_box_can_be_moved_by_the_page(self):
        from swf_hud import PLACED
        self.assertIn('missionBox', PLACED)
        script = (ROOT / 'templates' / 'js' / 'game.js').read_text(encoding='utf-8')
        self.assertIn('placePiece("missionBox", missions.x + origin - missions.ox, NaN);', script)


if __name__ == '__main__':
    unittest.main()
