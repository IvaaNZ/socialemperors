"""The game's own pictures for the World Editor (needs Pillow).

Every building and unit is drawn by the game from assets/buildingsprites/<img_name>.swf: a symbol exported with
the item's img_name whose first frame places bitmap-filled shapes (DefineBitsJPEG3 / DefineBitsLossless2, with
alpha), sometimes inside nested sprites (a unit's animations). This module composes that first frame into one
picture, without Flash:

  * every PlaceObject of the first frame is followed down to its shapes, multiplying the placement matrices;
  * a shape draws its bitmap fill through the fill's matrix (bitmap pixels -> twips, 20 per pixel);
  * the result is cropped to what was drawn and keeps where the symbol's origin (0, 0) falls: the game puts that
    point on the item's map position, so the editor anchors the picture there.

Pictures are cached as PNG in WorldEditor/imagenes (with their origin in index.json), made the first time an
item is drawn. The shop thumbnails (assets/buildingthumbs/<id>_<img_name>.jpg) are read as they are.
"""

import io
import json
import struct
import zlib
from pathlib import Path

from PIL import Image

TWIPS = 20.0
UNIT_FRAME = 4


class _Bits:
    def __init__(self, data, offset=0):
        self.data, self.pos = data, offset * 8

    def read(self, count):
        value = 0
        for _ in range(count):
            byte = self.data[self.pos >> 3]
            value = (value << 1) | ((byte >> (7 - (self.pos & 7))) & 1)
            self.pos += 1
        return value

    def signed(self, count):
        value = self.read(count)
        return value - (1 << count) if count and value & (1 << (count - 1)) else value

    def align(self):
        self.pos = (self.pos + 7) & ~7
        return self.pos >> 3


def _rect(data, offset):
    bits = _Bits(data, offset)
    size = bits.read(5)
    for _ in range(4):
        bits.read(size)
    return bits.align()


def _matrix(data, offset):
    """(a, b, c, d, tx, ty) of a MATRIX record and the offset after it: x' = a*x + c*y + tx, y' = b*x + d*y + ty."""
    bits = _Bits(data, offset)
    a = d = 1.0
    b = c = 0.0
    if bits.read(1):
        size = bits.read(5)
        a, d = bits.signed(size) / 65536.0, bits.signed(size) / 65536.0
    if bits.read(1):
        size = bits.read(5)
        b, c = bits.signed(size) / 65536.0, bits.signed(size) / 65536.0
    size = bits.read(5)
    tx, ty = bits.signed(size), bits.signed(size)
    return (a, b, c, d, float(tx), float(ty)), bits.align()


def _multiply(outer, inner):
    a1, b1, c1, d1, x1, y1 = outer
    a2, b2, c2, d2, x2, y2 = inner
    return (a1 * a2 + c1 * b2, b1 * a2 + d1 * b2, a1 * c2 + c1 * d2, b1 * c2 + d1 * d2,
            a1 * x2 + c1 * y2 + x1, b1 * x2 + d1 * y2 + y1)


IDENTITY = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def _tags(data, offset, end):
    while offset < end:
        header = struct.unpack_from('<H', data, offset)[0]
        code, length = header >> 6, header & 0x3F
        offset += 2
        if length == 0x3F:
            length = struct.unpack_from('<I', data, offset)[0]
            offset += 4
        yield code, offset, length
        offset += length


def _decode_swf(raw):
    if raw[:3] == b'CWS':
        body = raw[:8] + zlib.decompress(raw[8:])
    elif raw[:3] == b'FWS':
        body = raw
    else:
        raise ValueError('not a supported SWF')
    first = _rect(body, 8) + 4  # frame size, frame rate and count
    return body, first


def _jpeg(data):
    if data[:4] == b'\xff\xd9\xff\xd8':  # the old "erroneous header" of Flash JPEGs
        data = data[4:]
    return Image.open(io.BytesIO(data)).convert('RGBA')


def _unpremultiply(image):
    """Flash keeps colours multiplied by their alpha (Lossless2, and JPEG3 too): back to plain RGBA, or the edges
    of a picture come out dark when it is drawn or enlarged."""
    return Image.merge('RGBa', image.split()).convert('RGBA')


def _bitmap(code, data, offset, length):
    payload = data[offset:offset + length]
    if code == 35 or code == 90:  # DefineBitsJPEG3 / 4: JPEG plus a zlib alpha plane
        alpha_at = struct.unpack_from('<I', payload, 2)[0]
        start = 6 if code == 35 else 8
        image = _jpeg(payload[start:start + alpha_at])
        rest = payload[start + alpha_at:]
        if rest:
            try:
                alpha = zlib.decompress(rest)
                if len(alpha) == image.width * image.height:
                    image.putalpha(Image.frombytes('L', image.size, alpha))
                    image = _unpremultiply(image)  # JPEG3 colours come multiplied by their alpha
            except zlib.error:
                pass
        return image
    if code == 21:  # DefineBitsJPEG2
        return _jpeg(payload[2:])
    if code in (20, 36):  # DefineBitsLossless / 2
        form, width, height = payload[2], *struct.unpack_from('<HH', payload, 3)
        if form == 3:
            colours = payload[7] + 1
            pixels = zlib.decompress(payload[8:])
            entry = 4 if code == 36 else 3
            table, indexes = pixels[:colours * entry], pixels[colours * entry:]
            row = (width + 3) & ~3
            image = Image.new('RGBA', (width, height))
            out = []
            for y in range(height):
                for x in range(width):
                    i = indexes[y * row + x] * entry
                    if entry == 4:
                        out.append((table[i], table[i + 1], table[i + 2], table[i + 3]))
                    else:
                        out.append((table[i], table[i + 1], table[i + 2], 255))
            image.putdata(out)
            return image
        pixels = zlib.decompress(payload[7:])
        if code == 36:  # premultiplied ARGB
            image = Image.frombytes('RGBA', (width, height), pixels, 'raw', 'ARGB')
            return _unpremultiply(image)
        image = Image.frombytes('RGBX', (width, height), pixels, 'raw', 'XRGB')
        return image.convert('RGBA')
    return None


def _shape_fill(code, data, offset):
    """(bitmap id, fill matrix) of a shape's first bitmap fill, or None."""
    position = _rect(data, offset + 2)
    if code == 83:
        position = _rect(data, position) + 1
    count = data[position]
    position += 1
    if count == 0xFF and code != 2:
        count = struct.unpack_from('<H', data, position)[0]
        position += 2
    rgba = code in (32, 83)
    for _ in range(count):
        kind = data[position]
        position += 1
        if kind == 0x00:
            position += 4 if rgba else 3
        elif kind in (0x10, 0x12, 0x13):
            _, position = _matrix(data, position)
            records = data[position] & 0x0F
            position += 1 + records * (1 + (4 if rgba else 3))
            if kind == 0x13:
                position += 2
        elif 0x40 <= kind <= 0x43:
            bitmap_id = struct.unpack_from('<H', data, position)[0]
            matrix, position = _matrix(data, position + 2)
            if bitmap_id != 0xFFFF:
                return bitmap_id, matrix
        else:
            return None
    return None


def _first_frame(data, offset, end, frame=1):
    """[(character id, matrix)] on a frame of a timeline (the display list builds up frame after frame)."""
    placed = {}
    shown = 0
    for code, start, length in _tags(data, offset, end):
        if code == 1:  # ShowFrame
            shown += 1
            if shown >= frame:
                break
            continue
        if code in (26, 70):  # PlaceObject2 / 3
            flags = data[start]
            position = start + (2 if code == 70 else 1)
            depth = struct.unpack_from('<H', data, position)[0]
            position += 2
            if code == 70 and (data[start + 1] & 0x08 or (data[start + 1] & 0x10 and flags & 0x02)):
                position = data.index(b'\0', position) + 1  # class name
            character = placed.get(depth, (None, IDENTITY))[0]
            matrix = placed.get(depth, (None, IDENTITY))[1]
            if flags & 0x02:
                character = struct.unpack_from('<H', data, position)[0]
                position += 2
            if flags & 0x04:
                matrix, position = _matrix(data, position)
            if character is not None:
                placed[depth] = (character, matrix)
        elif code == 28:  # RemoveObject2
            placed.pop(struct.unpack_from('<H', data, start)[0], None)
    return [placed[depth] for depth in sorted(placed)]


def compose(raw, symbol, frame=1):
    """(RGBA picture, (origin x, origin y)) of a frame of a symbol (its first frame by default), or None."""
    data, first = _decode_swf(raw)
    bitmaps, shapes, sprites, symbols = {}, {}, {}, {}
    root_end = len(data)
    for code, start, length in _tags(data, first, root_end):
        if code in (20, 21, 35, 36, 90):
            bitmaps[struct.unpack_from('<H', data, start)[0]] = (code, start, length)
        elif code in (2, 22, 32, 83):
            fill = _shape_fill(code, data, start)
            if fill:
                shapes[struct.unpack_from('<H', data, start)[0]] = fill
        elif code == 39:
            sprite_id = struct.unpack_from('<H', data, start)[0]
            sprites[sprite_id] = (start + 4, start + length)
        elif code == 76:
            count, position = struct.unpack_from('<H', data, start)[0], start + 2
            for _ in range(count):
                character = struct.unpack_from('<H', data, position)[0]
                name_end = data.index(b'\0', position + 2)
                symbols[data[position + 2:name_end].decode('utf-8', 'replace')] = character
                position = name_end + 1
    if symbol not in symbols or symbols[symbol] not in sprites:
        return None

    pieces = []

    def walk(character, matrix, depth=0):
        if depth > 12:
            return
        if character in shapes:
            bitmap_id, fill = shapes[character]
            if bitmap_id in bitmaps:
                pieces.append((bitmap_id, _multiply(matrix, fill)))
        elif character in sprites:
            for child, child_matrix in _first_frame(data, *sprites[character]):
                walk(child, _multiply(matrix, child_matrix), depth + 1)

    for child, child_matrix in _first_frame(data, *sprites[symbols[symbol]], frame=frame):
        walk(child, child_matrix)
    if not pieces:
        return None
    decoded = {}
    corners = []
    for bitmap_id, matrix in pieces:
        if bitmap_id not in decoded:
            decoded[bitmap_id] = _bitmap(*bitmaps[bitmap_id], ) if False else _bitmap(bitmaps[bitmap_id][0], data,
                                                                                         bitmaps[bitmap_id][1],
                                                                                         bitmaps[bitmap_id][2])
        image = decoded[bitmap_id]
        if image is None:
            continue
        a, b, c, d, tx, ty = matrix
        for x, y in ((0, 0), (image.width, 0), (0, image.height), (image.width, image.height)):
            corners.append(((a * x + c * y + tx) / TWIPS, (b * x + d * y + ty) / TWIPS))
    if not corners:
        return None
    left = int(min(x for x, _ in corners)) - 1
    top = int(min(y for _, y in corners)) - 1
    width = int(max(x for x, _ in corners)) - left + 2
    height = int(max(y for _, y in corners)) - top + 2
    if width <= 0 or height <= 0 or width * height > 4096 * 4096:
        return None
    canvas = Image.new('RGBA', (width, height), (0, 0, 0, 0))
    for bitmap_id, matrix in pieces:
        image = decoded.get(bitmap_id)
        if image is None:
            continue
        a, b, c, d, tx, ty = matrix
        # canvas pixel (u, v) -> twips ((u + left) * 20, (v + top) * 20) -> bitmap pixel through the inverse matrix
        det = a * d - b * c
        if abs(det) < 1e-9:
            continue
        ia, ib, ic, id_ = d / det, -b / det, -c / det, a / det
        X0, Y0 = left * TWIPS - tx, top * TWIPS - ty
        coefficients = (ia * TWIPS, ic * TWIPS, ia * X0 + ic * Y0,
                        ib * TWIPS, id_ * TWIPS, ib * X0 + id_ * Y0)
        layer = image.transform((width, height), Image.AFFINE, coefficients, resample=Image.BILINEAR)
        canvas.alpha_composite(layer)
    box = canvas.getbbox()
    if not box:
        return None
    canvas = canvas.crop(box)
    return canvas, (-left - box[0], -top - box[1])


class Library:
    """The pictures of the items, made once and kept in a cache folder."""

    def __init__(self, project, cache):
        self.sprites = Path(project) / 'assets' / 'buildingsprites'
        self.thumbs = Path(project) / 'assets' / 'buildingthumbs'
        self.cache = Path(cache)
        self.cache.mkdir(parents=True, exist_ok=True)
        self.index_file = self.cache / 'index.json'
        try:
            self.index = json.loads(self.index_file.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            self.index = {}
        self.pending = False

    def picture(self, img_name, unit=False):
        """(PIL picture, origin) of an item as the world shows it, or None. A unit stands still facing the
        viewer (frame 4 of its QUIETO animation: frames 1 to 5 turn from the back to the front)."""
        if not img_name:
            return None
        known = self.index.get(img_name)
        if known is False:
            return None
        png = self.cache / f'{img_name}.png'
        if known and png.exists():
            try:
                return Image.open(png).convert('RGBA'), tuple(known)
            except OSError:
                pass
        source = self.sprites / f'{img_name}.swf'
        result = None
        if source.exists():
            try:
                raw = source.read_bytes()
                result = (compose(raw, img_name, UNIT_FRAME) if unit else None) or compose(raw, img_name)
            except Exception:  # a sprite this reader does not understand: the editor draws a block
                result = None
        if result is None:
            self.index[img_name] = False
        else:
            result[0].save(png)
            self.index[img_name] = list(result[1])
        self.pending = True
        return result

    def thumbnail(self, item_id, img_name):
        """The shop picture of an item, or None."""
        for name in (f'{item_id}_{img_name}.jpg', f'{item_id}_{img_name}.png', f'{img_name}.jpg', f'{img_name}.png'):
            path = self.thumbs / name
            if path.exists():
                try:
                    return Image.open(path).convert('RGBA')
                except OSError:
                    return None
        return None

    def save_index(self):
        if self.pending:
            self.index_file.write_text(json.dumps(self.index), encoding='utf-8')
            self.pending = False
