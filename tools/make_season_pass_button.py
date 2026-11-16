"""Draw the in-game "Pase" button (templates/img/season_pass_button_<lang>.png), below the "PvP" one.

The same shield and lettering as tools/make_clan_button.py, in blue with a gold star (own art). Drawn on a
canvas in headless Chrome or Edge:

    .venv/Scripts/python tools/make_season_pass_button.py
"""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from make_clan_button import BROWSER, draw  # noqa: E402

LABELS = {'es': 'Pase', 'en': 'Pass', 'pt-BR': 'Passe'}
STAR = ('<path d="M20 9.5l3.2 6.6 7.2 1-5.2 5 1.3 7.2L20 25.9l-6.5 3.4 1.3-7.2-5.2-5 7.2-1z" '
        'fill="#f4d77a" stroke="#3b2410" stroke-width="1.4" stroke-linejoin="round"/>')
SHIELD = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 46" width="48" height="55">'
          '<path d="M20 2L37 8v14c0 11-8 19-17 22C11 41 3 33 3 22V8z" fill="#2457a6" stroke="#3b2410" stroke-width="2"/>'
          '<path d="M20 5l14 5v12c0 9-6 16-14 19C12 38 6 31 6 22V10z" fill="none" stroke="#f4d77a" stroke-width="1.2" opacity=".85"/>'
          + STAR + '<path d="M11 33.5h18" stroke="#f4d77a" stroke-width="2" stroke-linecap="round" opacity=".9"/></svg>')


def main():
    if not BROWSER:
        raise SystemExit('Chrome or Edge is needed to draw the button.')
    draw(SHIELD, LABELS, 'season_pass_button')


if __name__ == '__main__':
    main()
