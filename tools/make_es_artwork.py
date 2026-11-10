#!/usr/bin/env python3
"""Build the Spanish button artwork from the Portuguese versions.

The Portuguese images keep the original button shapes; only their lettering
is replaced. Old text is covered by copying a clean column of the button's own
background, which preserves its gradient, and the new text is drawn with
Arial Bold, close to the client's Arial Rounded MT Bold.

Run from the repository root: python tools/make_es_artwork.py
"Construir" and "ALIADO" are spelled the same in Spanish, so those images are
reused from Portuguese at load time.
"""

import hashlib
import json
from pathlib import Path
import zlib

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
ARTWORK = ROOT / 'config' / 'locales' / 'artwork'
FONT = Path('C:/Windows/Fonts/arialbd.ttf')

# file suffix -> text, clean background column, region to repaint (x0, y0, x1, y1),
# text color, outline color or None, and how much of the region height the text may use.
JOBS = {
    '220': ('Dinero', 37, (38, 6, 104, 27), (25, 25, 25), None, 0.62),
    '220-hd': ('Dinero', 150, (152, 24, 416, 108), (25, 25, 25), None, 0.62),
    '3967': ('Agregar vecinos', 14, (16, 17, 142, 43), (255, 255, 255), (8, 70, 130), 0.72),
}


def repaint(suffix):
    text, clean_x, (x0, y0, x1, y1), color, outline, fill_ratio = JOBS[suffix]
    image = Image.open(ARTWORK / f'pt-BR-{suffix}.png').convert('RGBA')
    pixels = image.load()
    for x in range(x0, x1 + 1):
        for y in range(y0, y1 + 1):
            pixels[x, y] = pixels[clean_x, y]
    draw = ImageDraw.Draw(image)
    width, height = x1 - x0, y1 - y0
    stroke = max(1, height // 14) if outline else 0
    size = height
    while size > 6:
        font = ImageFont.truetype(str(FONT), size)
        left, top, right, bottom = draw.textbbox((0, 0), text, font=font, stroke_width=stroke)
        if right - left <= width * 0.94 and bottom - top <= height * fill_ratio:
            break
        size -= 1
    x = x0 + (width - (right - left)) / 2 - left
    y = y0 + (height - (bottom - top)) / 2 - top
    draw.text((x, y), text, font=font, fill=color + (255,), stroke_width=stroke,
              stroke_fill=(outline + (255,)) if outline else None)
    return image


def pack(image):
    """Flash Lossless2 format 5: premultiplied ARGB, zlib-compressed."""
    rgba = image.convert('RGBA').tobytes()
    out = bytearray()
    for offset in range(0, len(rgba), 4):
        r, g, b, a = rgba[offset:offset + 4]
        out += bytes((a, r * a // 255, g * a // 255, b * a // 255))
    return zlib.compress(bytes(out), 9)


def main():
    manifest_path = ARTWORK / 'manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    manifest = [entry for entry in manifest if not entry.get('png', '').startswith('es-')]
    for suffix, (text, *_rest) in JOBS.items():
        image = repaint(suffix)
        png_path = ARTWORK / f'es-{suffix}.png'
        packed_path = ARTWORK / f'es-{suffix}.argb.zlib'
        image.save(png_path, optimize=True)
        packed = pack(image)
        packed_path.write_bytes(packed)
        character_id = int(suffix.split('-')[0])
        manifest.append({
            'id': character_id, 'width': image.width, 'height': image.height, 'text': text,
            'editor': 'tools/make_es_artwork.py (Pillow, Arial Bold over the pt-BR artwork)',
            'png': png_path.name, 'packed': packed_path.name,
            'png_sha256': hashlib.sha256(png_path.read_bytes()).hexdigest(),
            'packed_sha256': hashlib.sha256(packed).hexdigest(),
        })
        print('wrote', png_path.name, image.size)
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
