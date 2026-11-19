"""Draw the "cristal" badges of the game's Clan, PvP and Pase buttons (SE_HUD_BADGES, hud_badges.py).

templates/img/hud_badge_<clan|pvp|pass>_<lang>.png, 60 x 72 like the old art: a dark rounded square with a ring in
the button's colour and a shield inside (the owner's design, family C of the HUD redesign), with the word under it
in the game's outlined white lettering. Drawn on a canvas in headless Chrome or Edge:

    .venv/Scripts/python tools/make_hud_badges.py
"""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from make_clan_button import BROWSER, draw  # noqa: E402

SIZE = 54  # the badge, centred above the word
SHIELD = 'M16 12H104V58C104 86 84 104 60 112C36 104 16 86 16 58Z'
SWORDS = ('<g transform="translate(22 18) scale(.76)">'
          '<path d="M18 18L28 20L72 64L64 72L20 28Z" fill="#eef1f5" stroke="#1b1f26" stroke-width="3" stroke-linejoin="round"/>'
          '<path d="M58 74L74 58L79 63L63 79Z" fill="#e8b23a" stroke="#1b1f26" stroke-width="3" stroke-linejoin="round"/>'
          '<path d="M82 18L72 20L28 64L36 72L80 28Z" fill="#eef1f5" stroke="#1b1f26" stroke-width="3" stroke-linejoin="round"/>'
          '<path d="M42 74L26 58L21 63L37 79Z" fill="#e8b23a" stroke="#1b1f26" stroke-width="3" stroke-linejoin="round"/></g>')
TOWER = ('<g transform="translate(16 6) scale(.88)"><path d="M32 84V50H36V44H42V50H46V44H54V50H58V44H64V50H68V84Z '
         'M45 84V72A5 5 0 0 1 55 72V84Z" fill="#e9edf1" fill-rule="evenodd" stroke="#1b1f26" stroke-width="2.5" '
         'stroke-linejoin="round"/></g>')
CROWN = ('<g transform="translate(16 4) scale(.88)"><path d="M28 72L24 44L38 56L50 38L62 56L76 44L72 72Z M28 76H72V82H28Z" '
         'fill="#ffd95a" stroke="#5a3214" stroke-width="2.5" stroke-linejoin="round"/></g>'
         '<circle cx="38" cy="30" r="3" fill="#ffd95a"/><circle cx="82" cy="30" r="3" fill="#ffd95a"/>'
         '<circle cx="60" cy="88" r="3" fill="#ffd95a"/>')

# kind: (ring, gradient top, gradient bottom, shield border, emblem, labels)
BADGES = {
    'clan': ('#163a7c', '#3a78d6', '#163a7c', '#e8b23a', TOWER, {'es': 'Clan', 'en': 'Clan', 'pt-BR': 'Clã'}),
    'pvp': ('#931c19', '#e2463a', '#8e1a14', '#c9d0d8', SWORDS, {'es': 'PvP', 'en': 'PvP', 'pt-BR': 'PvP'}),
    'pass': ('#4a1d6b', '#9b59b6', '#4a1d6b', '#e8b23a', CROWN, {'es': 'Pase', 'en': 'Pass', 'pt-BR': 'Passe'}),
}


def badge_svg(ring, top, bottom, border, emblem):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 120" width="{SIZE}" height="{SIZE}">'
            '<rect x="4" y="4" width="112" height="112" rx="30" fill="#10141c" fill-opacity=".82" '
            'stroke="#ffffff" stroke-opacity=".2" stroke-width="2"/>'
            f'<rect x="10" y="10" width="100" height="100" rx="26" fill="none" stroke="{ring}" stroke-width="4"/>'
            f'<defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{top}"/>'
            f'<stop offset="1" stop-color="{bottom}"/></linearGradient></defs>'
            '<g transform="translate(60 62) scale(.8) translate(-60 -62)">'
            f'<path d="{SHIELD}" fill="url(#g)" stroke="#1b1f26" stroke-width="8" stroke-linejoin="round"/>'
            f'<path d="{SHIELD}" fill="none" stroke="{border}" stroke-width="4" stroke-linejoin="round"/>'
            f'{emblem}</g></svg>')


def main():
    if not BROWSER:
        raise SystemExit('Chrome or Edge is needed to draw the badges.')
    for kind, (ring, top, bottom, border, emblem, labels) in BADGES.items():
        draw(badge_svg(ring, top, bottom, border, emblem), labels, f'hud_badge_{kind}', SIZE, SIZE)


if __name__ == '__main__':
    main()
