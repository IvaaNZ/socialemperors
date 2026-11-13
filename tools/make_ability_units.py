"""List the units whose abilities cast by themselves (config/duels/ability_units.json).

With SE_ABILITIES=on a special unit casts its abilities with unlimited uses
by itself in combat, so it counts stronger in a duel (duels.ABILITY_POWER_BONUS).
Which units those are is only written in the game movie: this reads it
(swf_unit_abilities.automatic_ability_units) and saves the ids, so the server
does not parse the movie to compute a duel army.

Usage: python tools/make_ability_units.py [output path]
"""
import contextlib
import io
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
OUTPUT = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / 'config' / 'duels' / 'ability_units.json'


def build():
    with contextlib.redirect_stdout(io.StringIO()):
        import server
    from swf_abc import Abc, find_abc
    from swf_localization import decode_swf
    from swf_unit_abilities import automatic_ability_units

    body, header_length = decode_swf((Path(server.ASSETS_DIR) / 'flash' / server.GAME_VERSION).read_bytes())
    payload, offset = find_abc(body, header_length)
    return {'movie': server.GAME_VERSION, 'units': automatic_ability_units(Abc(payload[offset:]))}


if __name__ == '__main__':
    data = build()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(data, separators=(',', ':')) + '\n', encoding='utf-8')
    print(f'{len(data["units"])} units -> {OUTPUT}')
