"""Draw the in-game "PvP" button (templates/img/pvp_button_<lang>.png), below the "Clan" one.

The same shield and lettering as tools/make_clan_button.py, in red with two
crossed swords (own art). Drawn on a canvas in headless Chrome or Edge:

    .venv/Scripts/python tools/make_pvp_button.py
"""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from make_clan_button import BROWSER, draw  # noqa: E402

LABELS = {'es': 'PvP', 'en': 'PvP', 'pt-BR': 'PvP'}
# One sword, hilt at the bottom left and tip at the top right; the other is its mirror image.
SWORD = ('<line x1="12" y1="34" x2="30" y2="11" stroke="#3b2410" stroke-width="4.6"/>'
         '<line x1="12" y1="34" x2="30" y2="11" stroke="#fff6d8" stroke-width="2.6"/>'
         '<line x1="11.6" y1="26.6" x2="19.2" y2="32.8" stroke="#3b2410" stroke-width="3.6"/>'
         '<line x1="11.6" y1="26.6" x2="19.2" y2="32.8" stroke="#f4d77a" stroke-width="1.8"/>'
         '<circle cx="11" cy="35.2" r="1.9" fill="#f4d77a" stroke="#3b2410" stroke-width=".8"/>')
SHIELD = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 46" width="48" height="55">'
          '<path d="M20 2L37 8v14c0 11-8 19-17 22C11 41 3 33 3 22V8z" fill="#b3261e" stroke="#3b2410" stroke-width="2"/>'
          '<path d="M20 5l14 5v12c0 9-6 16-14 19C12 38 6 31 6 22V10z" fill="none" stroke="#f4d77a" stroke-width="1.2" opacity=".85"/>'
          '<g stroke-linecap="round">' + SWORD + '<g transform="matrix(-1 0 0 1 40 0)">' + SWORD + '</g></g></svg>')


def main():
    if not BROWSER:
        raise SystemExit('Chrome or Edge is needed to draw the button.')
    draw(SHIELD, LABELS, 'pvp_button')


if __name__ == '__main__':
    main()
