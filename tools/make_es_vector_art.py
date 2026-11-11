#!/usr/bin/env python3
"""Build the Spanish images for the vector-drawn Monday chest button.

"MON DAY REWARD" is drawn with vector shapes, so there is no English bitmap to
repaint. This tool rasterizes the original shapes (tools/swf_raster.py):
  * REWARD: the ribbon is redrawn without its letter fills and PREMIO is
    written on it with the same white fill and dark outline.
  * MON / DAY on the two chest faces: the word's slanted quadrilateral is
    measured from the original letters, and LU / NES is drawn flat and then
    warped into it (white letters and their brown shadow separately).
Images use swf_vector_art.VECTOR_ART_SCALE pixels per screen pixel.
Run from the repository root: python tools/make_es_vector_art.py
"""

import hashlib
import json
from pathlib import Path
import struct
import sys

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tools'))
from bundle import ASSETS_DIR  # noqa: E402
from make_es_artwork import pack  # noqa: E402
from swf_localization import decode_swf, iter_tags  # noqa: E402
from swf_raster import Canvas, read_rect, render_shape, shape_regions  # noqa: E402
from swf_vector_art import VECTOR_ART, VECTOR_ART_SCALE, bitmap_size  # noqa: E402

ARTWORK = ROOT / 'config' / 'locales' / 'artwork'
FONT = Path('C:/Windows/Fonts/ariblk.ttf')  # Arial Black: close to the chunky original letters
GAME_MOVIE = Path(ASSETS_DIR) / 'flash' / 'SocialEmpires0926bsec.swf'
RIBBON = 678
RIBBON_STYLES = {1, 2}  # gradient band and its dark border; 3-8 are the letters
RIBBON_TEXT, RIBBON_FILL, RIBBON_OUTLINE = 'PREMIO', (255, 255, 255), (2, 30, 42)
# shape id -> word, color (None = white letters, otherwise shadow color)
FACE_WORDS = {
    854: ('LU', None), 694: ('LU', None), 850: ('LU', 'shadow'), 690: ('LU', 'shadow'),
    852: ('NES', None), 692: ('NES', None), 848: ('NES', 'shadow'), 688: ('NES', 'shadow'),
}
WHITE_FOR_SHADOW = {850: 854, 690: 694, 848: 852, 688: 692}


def shapes():
    body, header = decode_swf(GAME_MOVIE.read_bytes())
    found = {}
    for code, payload, _ in iter_tags(body[header:]):
        if code in (2, 22, 32, 83):
            shape_id = struct.unpack_from('<H', payload)[0]
            if shape_id in VECTOR_ART['es']:
                found[shape_id] = (code, payload)
    missing = sorted(set(VECTOR_ART['es']) - set(found))
    if missing:
        raise SystemExit(f'Shapes not found in the client SWF: {missing}')
    return found


def canvas_for(shape_id):
    bounds = VECTOR_ART['es'][shape_id][1]
    width, height = bitmap_size(bounds)
    return Canvas(width, height, bounds[0], bounds[2], VECTOR_ART_SCALE)


def rendered(shape_id, code, payload, keep=None):
    canvas = canvas_for(shape_id)
    render_shape(canvas, payload, code, keep=keep)
    return canvas.result()


def fit_font(draw, text, width, height, stroke_ratio=0.0):
    size = max(6, int(height * 1.4))
    while size > 5:
        font = ImageFont.truetype(str(FONT), size)
        stroke = round(size * stroke_ratio)
        left, top, right, bottom = draw.textbbox((0, 0), text, font=font, stroke_width=stroke)
        if right - left <= width and bottom - top <= height:
            return font, stroke, (left, top, right, bottom)
        size -= 1
    raise ValueError(f'No font size fits {text!r}')


def ribbon_image(code, payload):
    image = rendered(RIBBON, code, payload, keep=RIBBON_STYLES)
    letters = rendered(RIBBON, code, payload, keep=set(range(3, 9)))
    x0, y0, x1, y1 = letters.getbbox()
    layer = Image.new('RGBA', image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    font, stroke, (left, top, right, bottom) = fit_font(draw, RIBBON_TEXT, (x1 - x0) * 0.98, (y1 - y0) * 1.0, 0.16)
    x = x0 + ((x1 - x0) - (right - left)) / 2 - left
    y = y0 + ((y1 - y0) - (bottom - top)) / 2 - top
    draw.text((x, y), RIBBON_TEXT, font=font, fill=RIBBON_FILL + (255,), stroke_width=stroke,
              stroke_fill=RIBBON_OUTLINE + (255,))
    # A slight italic like the original lettering, sheared around the text's centre line.
    shear = 0.12
    centre = (y0 + y1) / 2
    layer = layer.transform(layer.size, Image.AFFINE, (1, shear, -shear * centre, 0, 1, 0), Image.BICUBIC)
    image.alpha_composite(layer)
    return image


def _fit_line(points):
    """Least-squares line v = a*u + b through (u, v) points."""
    n = len(points)
    mean_u = sum(u for u, _ in points) / n
    mean_v = sum(v for _, v in points) / n
    spread = sum((u - mean_u) ** 2 for u, _ in points)
    slope = 0.0 if spread == 0 else sum((u - mean_u) * (v - mean_v) for u, v in points) / spread
    return slope, mean_v - slope * mean_u


def word_quad(mask):
    """Corners (TL, TR, BR, BL) of the slanted box around a word's letters."""
    pixels = mask.load()
    width, height = mask.size
    columns = [x for x in range(width) if any(pixels[x, y] > 127 for y in range(height))]
    rows = [y for y in range(height) if any(pixels[x, y] > 127 for x in range(width))]
    tops = [(x, min(y for y in range(height) if pixels[x, y] > 127)) for x in columns]
    bottoms = [(x, max(y for y in range(height) if pixels[x, y] > 127)) for x in columns]
    first, last = columns[0], columns[-1]
    edge = (last - first) * 0.2
    # Only rows whose outermost pixel belongs to the first (or last) letter.
    lefts = [(y, x) for y in rows for x in [min(x for x in range(width) if pixels[x, y] > 127)] if x <= first + edge]
    rights = [(y, x) for y in rows for x in [max(x for x in range(width) if pixels[x, y] > 127)] if x >= last - edge]
    top_line, bottom_line = _fit_line(tops), _fit_line(bottoms)
    # Keep the outer envelope: shift each fitted line out to its extreme point.
    top_line = (top_line[0], min(v - top_line[0] * u for u, v in tops))
    bottom_line = (bottom_line[0], max(v - bottom_line[0] * u for u, v in bottoms))
    slant, _ = _fit_line(lefts)
    slant = max(-0.6, min(0.6, slant))  # letters lean, they never lie down
    left_offset = min(x - slant * y for y, x in lefts)
    right_offset = max(x - slant * y for y, x in rights)

    def corner(line, offset):
        a, b = line  # y = a x + b ; x = slant y + offset
        y = (a * offset + b) / (1 - a * slant)
        return offset + slant * y, y

    return (corner(top_line, left_offset), corner(top_line, right_offset),
            corner(bottom_line, right_offset), corner(bottom_line, left_offset))


def perspective_coefficients(source_size, quad):
    """Coefficients mapping output pixels inside `quad` back to the flat source image."""
    width, height = source_size
    targets = [(0, 0), (width, 0), (width, height), (0, height)]
    rows, values = [], []
    for (x, y), (u, v) in zip(quad, targets):
        rows.append([x, y, 1, 0, 0, 0, -u * x, -u * y])
        values.append(u)
        rows.append([0, 0, 0, x, y, 1, -v * x, -v * y])
        values.append(v)
    # Gaussian elimination (8x8).
    matrix = [row + [value] for row, value in zip(rows, values)]
    for column in range(8):
        pivot = max(range(column, 8), key=lambda r: abs(matrix[r][column]))
        matrix[column], matrix[pivot] = matrix[pivot], matrix[column]
        for r in range(8):
            if r != column:
                factor = matrix[r][column] / matrix[column][column]
                matrix[r] = [a - factor * b for a, b in zip(matrix[r], matrix[column])]
    return [matrix[r][8] / matrix[r][r] for r in range(8)]


def face_image(shape_id, code, payload, all_shapes):
    word, role = FACE_WORDS[shape_id]
    original = rendered(shape_id, code, payload)
    quad = word_quad(original.getchannel('A'))
    color = original.convert('RGB').getpixel(tuple(int(v) for v in _darkest_point(original)))
    flat_w = max(2, round(((quad[1][0] - quad[0][0]) ** 2 + (quad[1][1] - quad[0][1]) ** 2) ** 0.5)) * 4
    flat_h = max(2, round(((quad[3][0] - quad[0][0]) ** 2 + (quad[3][1] - quad[0][1]) ** 2) ** 0.5)) * 4
    flat = Image.new('L', (flat_w, flat_h), 0)
    draw = ImageDraw.Draw(flat)
    stroke_ratio = 0.0
    if role == 'shadow':
        white_code, white_payload = all_shapes[WHITE_FOR_SHADOW[shape_id]]
        white_quad = word_quad(rendered(WHITE_FOR_SHADOW[shape_id], white_code, white_payload).getchannel('A'))
        white_h = ((white_quad[3][0] - white_quad[0][0]) ** 2 + (white_quad[3][1] - white_quad[0][1]) ** 2) ** 0.5
        stroke_ratio = max(0.0, (flat_h / 4 - white_h) / 2) / max(white_h, 1) * 0.9
    font, stroke, (left, top, right, bottom) = fit_font(draw, word, flat_w * 0.92, flat_h * 0.92, stroke_ratio)
    x = (flat_w - (right - left)) / 2 - left
    y = (flat_h - (bottom - top)) / 2 - top
    draw.text((x, y), word, font=font, fill=255, stroke_width=stroke, stroke_fill=255)
    coefficients = perspective_coefficients(flat.size, quad)
    alpha = flat.transform(original.size, Image.PERSPECTIVE, coefficients, Image.BICUBIC)
    image = Image.new('RGBA', original.size, color + (0,))
    image.putalpha(alpha)
    return image


def _darkest_point(image):
    """A fully opaque pixel of the original letters, to read their fill colour."""
    alpha = image.getchannel('A').load()
    width, height = image.size
    for y in range(height):
        for x in range(width):
            if alpha[x, y] == 255:
                return x, y
    raise ValueError('Shape has no opaque pixel')


def save(manifest, image, shape_id, text):
    png_path = ARTWORK / f'es-vec-{shape_id}.png'
    packed_path = ARTWORK / f'es-vec-{shape_id}.argb.zlib'
    image.save(png_path, optimize=True)
    packed = pack(image)
    packed_path.write_bytes(packed)
    manifest.append({
        'id': shape_id, 'width': image.width, 'height': image.height, 'text': text,
        'editor': 'tools/make_es_vector_art.py (rasterized original shapes, Arial Black)',
        'png': png_path.name, 'packed': packed_path.name,
        'png_sha256': hashlib.sha256(png_path.read_bytes()).hexdigest(),
        'packed_sha256': hashlib.sha256(packed).hexdigest(),
    })
    print('wrote', png_path.name, image.size)


def main():
    manifest_path = ARTWORK / 'manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    manifest = [entry for entry in manifest if not entry.get('png', '').startswith('es-vec-')]
    found = shapes()
    code, payload = found[RIBBON]
    save(manifest, ribbon_image(code, payload), RIBBON, RIBBON_TEXT)
    for shape_id in sorted(FACE_WORDS):
        code, payload = found[shape_id]
        save(manifest, face_image(shape_id, code, payload, found), shape_id, FACE_WORDS[shape_id][0])
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
