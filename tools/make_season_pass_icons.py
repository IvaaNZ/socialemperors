"""Draw the reward icons of the season pass window (templates/img/season_pass/*.png).

  * gold, wood, food and stone: the game's own pictures in the client SWF (its icoGoldMC... HUD symbols are only
    grey placeholders filled at run time, so the bitmaps themselves are taken: RESOURCE_BITMAPS); cash: its bills
    (CashMC, vector shapes rasterized with tools/swf_raster.py);
  * the units of every season (season_pass.SEASON_UNITS): their picture on the map, facing the viewer, taken from
    assets/buildingsprites with the World Editor's reader (WorldEditor/sprites.py); a unit drawn with vector shapes
    only (the black yeti) is rasterized the same way.

Run from the repository root:  .venv/Scripts/python tools/make_season_pass_icons.py
"""

from pathlib import Path
import struct
import sys

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / 'WorldEditor'))

import sprites  # noqa: E402
from season_pass import SEASON_UNITS  # noqa: E402
from swf_raster import Canvas, read_rect, render_shape  # noqa: E402

GAME = ROOT / 'assets' / 'flash' / 'SocialEmpires0926bsec.swf'
OUT = ROOT / 'templates' / 'img' / 'season_pass'
SIZE = 64  # pixels of every icon (square, transparent)
RESOURCE_BITMAPS = {'coins': 156, 'wood': 329, 'food': 782, 'stone': 783}  # bitmap ids in the client SWF
CASH_SYMBOL = 'CashMC'
SHAPES = (2, 22, 32, 83)


def library(data, first):
    shapes, sprites_, symbols = {}, {}, {}
    for code, start, length in sprites._tags(data, first, len(data)):
        if code in SHAPES:
            shapes[struct.unpack_from('<H', data, start)[0]] = (code, data[start:start + length])
        elif code == 39:
            sprites_[struct.unpack_from('<H', data, start)[0]] = (start + 4, start + length)
        elif code == 76:
            count, position = struct.unpack_from('<H', data, start)[0], start + 2
            for _ in range(count):
                character = struct.unpack_from('<H', data, position)[0]
                end = data.index(b'\0', position + 2)
                symbols[data[position + 2:end].decode('utf-8', 'replace')] = character
                position = end + 1
    return shapes, sprites_, symbols


def placed_shapes(data, shapes, sprites_, character, matrix=sprites.IDENTITY, depth=0, frame=1):
    """[(code, payload, matrix)] of a frame of a symbol (nested sprites at their first frame)."""
    if depth > 10:
        return []
    if character in shapes:
        return [(shapes[character][0], shapes[character][1], matrix)]
    if character not in sprites_:
        return []
    out = []
    for child, child_matrix in sprites._first_frame(data, *sprites_[character], frame=frame):
        out += placed_shapes(data, shapes, sprites_, child, sprites._multiply(matrix, child_matrix), depth + 1)
    return out


def rasterized(data, first, symbol, frame=1):
    """A symbol drawn from its vector shapes, or None."""
    shapes, sprites_, symbols = library(data, first)
    if symbol not in symbols:
        return None
    pieces = placed_shapes(data, shapes, sprites_, symbols[symbol], frame=frame)
    if not pieces:
        return None
    xmin, xmax, ymin, ymax = bounds_of(pieces)
    scale = 4  # pixels per screen pixel, then reduced: smooth edges
    width, height = int((xmax - xmin) / 20 * scale) + 2, int((ymax - ymin) / 20 * scale) + 2
    canvas = Canvas(width, height, xmin, ymin, scale)
    for code, payload, matrix in pieces:
        render_shape(canvas, payload, code, matrix)
    return canvas.result()


def bounds_of(pieces):
    xs, ys = [], []
    for code, payload, (a, b, c, d, tx, ty) in pieces:
        xmin, xmax, ymin, ymax = read_rect(payload, 2)[0]
        for x, y in ((xmin, ymin), (xmax, ymin), (xmin, ymax), (xmax, ymax)):
            xs.append(a * x + c * y + tx)
            ys.append(b * x + d * y + ty)
    return min(xs), max(xs), min(ys), max(ys)


def square(image):
    """The picture cropped to what it draws, centred in a transparent SIZE x SIZE square."""
    box = image.getbbox()
    if box:
        image = image.crop(box)
    image.thumbnail((SIZE - 4, SIZE - 4), Image.LANCZOS)
    out = Image.new('RGBA', (SIZE, SIZE), (0, 0, 0, 0))
    out.alpha_composite(image, ((SIZE - image.width) // 2, (SIZE - image.height) // 2))
    return out


def resource_icons(raw):
    data, first = sprites._decode_swf(raw)
    bitmaps = {}
    for code, start, length in sprites._tags(data, first, len(data)):
        if code in (20, 21, 35, 36, 90):
            bitmaps[struct.unpack_from('<H', data, start)[0]] = (code, start, length)
    for name, bitmap in RESOURCE_BITMAPS.items():
        image = sprites._bitmap(bitmaps[bitmap][0], data, bitmaps[bitmap][1], bitmaps[bitmap][2])
        target = OUT / f'{name}.png'
        square(image).save(target)
        print('wrote', target.relative_to(ROOT))
    cash = rasterized(data, first, CASH_SYMBOL)
    if cash is None:
        raise SystemExit('cash: nothing drawn')
    square(cash).save(OUT / 'cash.png')
    print('wrote', (OUT / 'cash.png').relative_to(ROOT))


def unit_icons():
    from get_game_config import get_game_config
    items = {int(item['id']): item for item in get_game_config()['items']}
    for season, units in SEASON_UNITS.items():
        for unit in units:
            name = items[unit]['img_name']
            raw = (ROOT / 'assets' / 'buildingsprites' / f'{name}.swf').read_bytes()
            found = sprites.compose(raw, name, sprites.UNIT_FRAME) or sprites.compose(raw, name)
            if found:
                picture = found[0]
            else:  # drawn with vector shapes only
                data, first = sprites._decode_swf(raw)
                picture = rasterized(data, first, name, sprites.UNIT_FRAME) or rasterized(data, first, name)
            if picture is None:
                raise SystemExit(f'unit {unit} ({name}): no picture')
            target = OUT / f'unit_{unit}.png'
            square(picture).save(target)
            print('wrote', target.relative_to(ROOT), season)


def main():
    import contextlib
    import io
    import os
    os.chdir(ROOT)
    OUT.mkdir(parents=True, exist_ok=True)
    resource_icons(GAME.read_bytes())
    with contextlib.redirect_stdout(io.StringIO()):
        from get_game_config import get_game_config  # noqa: F401  (prints its patch list once)
    unit_icons()


if __name__ == '__main__':
    main()
