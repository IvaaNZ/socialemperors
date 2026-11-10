#!/usr/bin/env python3
"""Build the Spanish button artwork shown by the game.

Two kinds of jobs:
  * PT_JOBS start from the Portuguese images (config/locales/artwork/pt-BR-*.png)
    and cover their lettering by copying a clean column of the button background.
  * SWF_JOBS start from the original English bitmaps inside the client SWF. The old
    lettering is erased (text fill plus outline pixels), the hole is filled from the
    surrounding pixels, and the Spanish text is drawn in a similar style.

New text is drawn with Arial Bold, close to the client's rounded sans fonts.
Run from the repository root: python tools/make_es_artwork.py
"Construir" and "ALIADO" are the same words in Spanish, so those images are
reused from Portuguese at load time.
"""

import hashlib
import io
import json
from pathlib import Path
import struct
import sys
import zlib

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from bundle import ASSETS_DIR  # noqa: E402
from swf_localization import decode_swf, iter_tags  # noqa: E402

ARTWORK = ROOT / 'config' / 'locales' / 'artwork'
FONT = Path('C:/Windows/Fonts/arialbd.ttf')
GAME_MOVIE = Path(ASSETS_DIR) / 'flash' / 'SocialEmpires0926bsec.swf'

# file suffix -> text, clean background column, region to repaint (x0, y0, x1, y1),
# text color, outline color or None, and how much of the region height the text may use.
PT_JOBS = {
    '220': ('Dinero', 37, (38, 6, 104, 27), (25, 25, 25), None, 0.62),
    '220-hd': ('Dinero', 150, (152, 24, 416, 108), (25, 25, 25), None, 0.62),
    '3967': ('Agregar vecinos', 14, (16, 17, 142, 43), (255, 255, 255), (8, 70, 130), 0.72),
}

WHITE = (255, 255, 255)
# character id -> text (\n for two lines), text box (x0, y0, x1, y1), which old pixels
# are lettering ('light' = light letters with a dark outline, 'dark' = dark letters,
# 'yellow' = yellow letters with a dark outline, 'white-flat' = white letters only),
# fill color, outline color or None, and optionally how much of the box height the
# text may use (default 0.9; 1.0 helps cover wide old lettering).
SWF_JOBS = {
    147: ('MI ALDEA', (1, 0, 81, 14), 'light', WHITE, (95, 55, 20), 1.0),
    149: ('MENÚ DE\nBATALLA', (28, 24, 90, 62), 'light', WHITE, (75, 40, 15)),
    233: ('ATACANDO', (9, 3, 116, 24), 'light', WHITE, (75, 45, 10)),
    234: ('BOTÍN DE BATALLA', (36, 1, 214, 24), 'light', WHITE, (20, 60, 15)),
    1028: ('¡VAMOS!', (1, 9, 62, 37), 'light', WHITE, (110, 35, 15), 1.0),
    1034: ('RESULTADOS\nDE BATALLA', (37, 11, 101, 40), 'dark', (55, 25, 40), None),
    1038: ('OPCIONES', (3, 2, 81, 22), 'dark', (55, 25, 40), None),
    1042: ('EXPLORADOR\nDEL MUNDO', (1, 26, 110, 77), 'light', WHITE, (25, 55, 110), 1.0),
    798: ('LANZAR\nHECHIZO', (5, 11, 48, 49), 'yellow', (250, 215, 40), (70, 35, 10)),
    1529: ('ATAQUES ENVIADOS', (12, 5, 146, 25), 'light', WHITE, (75, 45, 10)),
    1534: ('ATAQUES RECIBIDOS', (8, 5, 151, 25), 'light', WHITE, (75, 45, 10)),
    2421: ('HECHIZOS', (24, 17, 159, 43), 'light', WHITE, (80, 50, 20)),
    3431: ('GUARDAR', (1, 17, 49, 33), 'light', WHITE, (95, 55, 20)),
    3545: ('ENTRENAR', (1, 18, 54, 37), 'light', WHITE, (95, 55, 20)),
    3582: ('Más dinero', (17, 19, 141, 38), 'white-flat', WHITE, None),
    792: ('Más dinero', (17, 19, 141, 38), 'white-flat', WHITE, None),
}


def swf_bitmaps():
    """Original client bitmaps as RGBA images, keyed by character id."""
    body, header = decode_swf(GAME_MOVIE.read_bytes())
    images = {}
    for code, payload, _ in iter_tags(body[header:]):
        if code not in (35, 36) or len(payload) < 2:
            continue
        character_id = struct.unpack_from('<H', payload)[0]
        if character_id not in SWF_JOBS:
            continue
        if code == 36:
            _, _, width, height = struct.unpack_from('<HBHH', payload)
            data = zlib.decompress(payload[7:])
            rgba = bytearray()
            for offset in range(0, width * height * 4, 4):
                a, r, g, b = data[offset:offset + 4]
                if a:
                    r, g, b = (min(255, value * 255 // a) for value in (r, g, b))
                rgba += bytes((r, g, b, a))
            images[character_id] = Image.frombytes('RGBA', (width, height), bytes(rgba))
        else:
            size = struct.unpack_from('<I', payload, 2)[0]
            image = Image.open(io.BytesIO(payload[6:6 + size])).convert('RGBA')
            image.putalpha(Image.frombytes('L', image.size, zlib.decompress(payload[6 + size:])))
            images[character_id] = image
    return images


def lum(pixel):
    r, g, b = pixel[:3]
    return (r * 299 + g * 587 + b * 114) // 1000


def lettering_mask(image, box, kind):
    """Pixels inside box that belong to the old lettering, grown by one pixel."""
    x0, y0, x1, y1 = box
    px = image.load()

    def is_fill(x, y):
        r, g, b, a = px[x, y]
        if a < 40:
            return False
        if kind in ('light', 'white-flat'):
            return lum((r, g, b)) > 205 and max(r, g, b) - min(r, g, b) < 60
        if kind == 'dark':
            return lum((r, g, b)) < 110
        return r > 190 and g > 150 and b < 140  # yellow

    inside = [(x, y) for x in range(x0, x1 + 1) for y in range(y0, y1 + 1)
              if 0 <= x < image.width and 0 <= y < image.height]
    fill = {point for point in inside if is_fill(*point)}
    mask = set(fill)
    if kind in ('light', 'yellow'):
        reach = 3
        for x, y in fill:
            for dx in range(-reach, reach + 1):
                for dy in range(-reach, reach + 1):
                    nx, ny = x + dx, y + dy
                    if x0 - 1 <= nx <= x1 + 1 and y0 - 1 <= ny <= y1 + 1 and 0 <= nx < image.width and 0 <= ny < image.height:
                        if lum(px[nx, ny]) < 120 and px[nx, ny][3] > 40:
                            mask.add((nx, ny))
    grown = set(mask)
    for x, y in mask:
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if 0 <= nx < image.width and 0 <= ny < image.height:
                grown.add((nx, ny))
    return grown


def fill_from_surroundings(image, mask):
    """Fill masked pixels layer by layer with the average of known neighbors."""
    px = image.load()
    unknown = set(mask)
    while unknown:
        filled = {}
        for x, y in unknown:
            known = [px[nx, ny] for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1),
                                                (x + 1, y + 1), (x - 1, y - 1), (x + 1, y - 1), (x - 1, y + 1))
                     if 0 <= nx < image.width and 0 <= ny < image.height and (nx, ny) not in unknown]
            if known:
                filled[(x, y)] = tuple(sum(channel) // len(known) for channel in zip(*known))
        if not filled:
            break
        for point, value in filled.items():
            px[point] = value
        unknown -= set(filled)


def draw_text(image, text, box, color, outline, fill_ratio=0.9, width_ratio=0.96):
    draw = ImageDraw.Draw(image)
    x0, y0, x1, y1 = box
    width, height = x1 - x0, y1 - y0
    size = height
    while size > 5:
        font = ImageFont.truetype(str(FONT), size)
        stroke = max(1, round(size / 5)) if outline else 0
        spacing = max(0, size // 8)
        left, top, right, bottom = draw.multiline_textbbox((0, 0), text, font=font, stroke_width=stroke,
                                                            spacing=spacing, align='center')
        if right - left <= width * width_ratio and bottom - top <= height * fill_ratio:
            break
        size -= 1
    x = x0 + (width - (right - left)) / 2 - left
    y = y0 + (height - (bottom - top)) / 2 - top
    draw.multiline_text((x, y), text, font=font, fill=color + (255,), stroke_width=stroke,
                        stroke_fill=(outline + (255,)) if outline else None, spacing=spacing, align='center')
    return image


def repaint_pt(suffix):
    text, clean_x, (x0, y0, x1, y1), color, outline, fill_ratio = PT_JOBS[suffix]
    image = Image.open(ARTWORK / f'pt-BR-{suffix}.png').convert('RGBA')
    pixels = image.load()
    for x in range(x0, x1 + 1):
        for y in range(y0, y1 + 1):
            pixels[x, y] = pixels[clean_x, y]
    return draw_text(image, text, (x0, y0, x1, y1), color, outline, fill_ratio, 0.94)


def repaint_swf(image, character_id):
    text, box, kind, color, outline, *options = SWF_JOBS[character_id]
    image = image.copy()
    fill_from_surroundings(image, lettering_mask(image, box, kind))
    fill_ratio = options[0] if options else 0.9
    return draw_text(image, text, box, color, outline, fill_ratio, 1.0 if fill_ratio >= 1 else 0.96)


def pack(image):
    """Flash Lossless2 format 5: premultiplied ARGB, zlib-compressed."""
    rgba = image.convert('RGBA').tobytes()
    out = bytearray()
    for offset in range(0, len(rgba), 4):
        r, g, b, a = rgba[offset:offset + 4]
        out += bytes((a, r * a // 255, g * a // 255, b * a // 255))
    return zlib.compress(bytes(out), 9)


def save(manifest, image, name, character_id, text, editor):
    png_path = ARTWORK / f'es-{name}.png'
    packed_path = ARTWORK / f'es-{name}.argb.zlib'
    image.save(png_path, optimize=True)
    packed = pack(image)
    packed_path.write_bytes(packed)
    manifest.append({
        'id': character_id, 'width': image.width, 'height': image.height, 'text': text.replace('\n', ' '),
        'editor': editor, 'png': png_path.name, 'packed': packed_path.name,
        'png_sha256': hashlib.sha256(png_path.read_bytes()).hexdigest(),
        'packed_sha256': hashlib.sha256(packed).hexdigest(),
    })
    print('wrote', png_path.name, image.size)


def main():
    manifest_path = ARTWORK / 'manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    manifest = [entry for entry in manifest if not entry.get('png', '').startswith('es-')]
    for suffix, job in PT_JOBS.items():
        save(manifest, repaint_pt(suffix), suffix, int(suffix.split('-')[0]), job[0],
             'tools/make_es_artwork.py (Pillow, Arial Bold over the pt-BR artwork)')
    originals = swf_bitmaps()
    missing = sorted(set(SWF_JOBS) - set(originals))
    if missing:
        raise SystemExit(f'Bitmaps not found in the client SWF: {missing}')
    for character_id in sorted(SWF_JOBS):
        save(manifest, repaint_swf(originals[character_id], character_id), str(character_id), character_id,
             SWF_JOBS[character_id][0], 'tools/make_es_artwork.py (Pillow, Arial Bold over the original bitmap)')
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
