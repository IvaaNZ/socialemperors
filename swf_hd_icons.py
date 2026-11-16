"""HD icons for the whole game (SE_HD_ICONS, on by default): the client's small pictures at twice their pixels.

Asked by the owner: "Aplica todos los iconos en HD dentro de todo el juego". The pictures were enlarged once with
Real-ESRGAN (tools/make_hd_icons.py: 4x with its anime model, then reduced to 2x, sharper than enlarging to 2x
directly) and kept in config/hd_icons. When the game movie is built, this pass:

  * replaces each of those bitmaps (DefineBits, JPEG2/3, Lossless) by a DefineBitsJPEG3 bitmap with the same
    character id and HD_FACTOR times its width and height: JPEG colours multiplied by alpha (Flash's own JPEG3
    pictures are premultiplied) plus the alpha plane. Lossless pictures made the movie 3.4 times bigger;
  * divides by HD_FACTOR the scale and skew of every shape fill that uses it, so the picture covers exactly the same
    area on screen (x = a * pixel + tx: twice the pixels at half the step). Shape bounds, edges, placements and
    hit areas keep their bytes.

Only safe pictures are touched (eligible_bitmaps):
  * not exported to the game's code (SymbolClass / ExportAssets): ActionScript may read their size;
  * used by at least one shape and by no morph shape (whose fills animate between two matrices);
  * icons: at most MAX_ICON_SIDE pixels on each side (backgrounds and whole windows stay as they are: twice their
    pixels would cost memory for little gain), and not the ones that already have their own HD (swf_hd_art).

Pictures translated for a language (swf_bitmap_art) are enlarged from their translation: config/hd_icons/<language>/
<id>.png; the rest use config/hd_icons/<id>.png. A picture without its HD file stays as it is.
"""

import os
import struct
from functools import lru_cache
from pathlib import Path

from bundle import CONFIG_DIR

HD_DIR = Path(CONFIG_DIR) / 'hd_icons'
HD_FACTOR = 2
MAX_ICON_SIDE = 256
BITMAP_TAGS = (6, 20, 21, 35, 36, 90)
SHAPE_TAGS = (2, 22, 32, 83)
MORPH_TAGS = (46, 84)
LOSSLESS2 = 36
JPEG3 = 35
JPEG_QUALITY = 92  # the HD pictures are stored like most of the game's own: JPEG colours plus an alpha plane


def hd_icons_enabled():
    return os.environ.get('SE_HD_ICONS', 'on').strip().lower() in ('on', '1', 'true', 'yes')


class _Bits:
    def __init__(self, data, offset):
        self.data, self.bit = data, offset * 8

    def read(self, count):
        value = 0
        for _ in range(count):
            value = (value << 1) | ((self.data[self.bit >> 3] >> (7 - (self.bit & 7))) & 1)
            self.bit += 1
        return value

    def aligned(self):
        return (self.bit + 7) >> 3


def _style_arrays(payload, offset, code, fills):
    """Read a FILLSTYLEARRAY and a LINESTYLEARRAY from `offset`; bitmap fills go to `fills`. Returns the offset
    after them."""
    from swf_hd_art import _fill_end
    rgba = code in (32, 83)

    def count_at(position):
        count = payload[position]
        position += 1
        if count == 255:
            count = struct.unpack_from('<H', payload, position)[0]
            position += 2
        return count, position

    def fill_style(position):
        end, kind, bitmap_id, matrix_start, matrix = _fill_end(payload, position, rgba)
        if bitmap_id is not None:
            fills.append((position, bitmap_id, matrix_start, end, matrix))
        return end

    count, offset = count_at(offset)
    for _ in range(count):
        offset = fill_style(offset)
    count, offset = count_at(offset)
    for _ in range(count):
        if code == 83:  # LINESTYLE2: width, two flag bytes, maybe a miter limit, then a fill style or a colour
            flags = struct.unpack_from('>H', payload, offset + 2)[0]
            offset += 4
            if (flags >> 12) & 3 == 2:  # miter join
                offset += 2
            offset = fill_style(offset) if flags & (1 << 11) else offset + 4
        else:
            offset += 2 + (4 if rgba else 3)
    return offset


def _shape_fill_offsets(payload, code):
    """[(fill start, bitmap id, matrix start, matrix end, matrix)] of every bitmap fill of a DefineShape: the
    style arrays at its start and the new ones its shape records may declare (StyleChangeRecord NewStyles, which
    DefineShape2 to 4 allow), in byte order."""
    from swf_static_text import _rect_end
    offset = _rect_end(payload, 2)
    if code == 83:  # DefineShape4: edge bounds and flags
        offset = _rect_end(payload, offset) + 1
    fills = []
    offset = _style_arrays(payload, offset, code, fills)
    bits = _Bits(payload, offset)
    fill_bits, line_bits = bits.read(4), bits.read(4)
    while True:
        if bits.read(1):  # edge record
            straight, size = bits.read(1), bits.read(4) + 2
            if straight:
                bits.read(size * 2 if bits.read(1) else size + 1)
            else:
                bits.read(size * 4)
            continue
        new_styles, line, fill1, fill0, move = (bits.read(1) for _ in range(5))
        if not (new_styles or line or fill1 or fill0 or move):
            break  # end of the shape
        if move:
            bits.read(bits.read(5) * 2)
        bits.read((fill_bits if fill0 else 0) + (fill_bits if fill1 else 0) + (line_bits if line else 0))
        if new_styles and code != 2:
            position = _style_arrays(payload, bits.aligned(), code, fills)
            bits = _Bits(payload, position)
            fill_bits, line_bits = bits.read(4), bits.read(4)
    return fills


def _morph_bitmaps(payload, code):
    """Bitmap ids used by a morph shape's fills (they are left alone)."""
    from swf_hd_art import read_matrix
    from swf_static_text import _rect_end
    offset = _rect_end(payload, 2)
    offset = _rect_end(payload, offset)
    if code == 84:  # DefineMorphShape2: edge bounds twice and flags
        offset = _rect_end(payload, offset)
        offset = _rect_end(payload, offset) + 1
    offset += 4  # offset to the end edges
    count = payload[offset]
    offset += 1
    if count == 255:
        count = struct.unpack_from('<H', payload, offset)[0]
        offset += 2
    found = set()
    for _ in range(count):
        kind = payload[offset]
        offset += 1
        if kind == 0:
            offset += 8
        elif kind in (0x10, 0x12, 0x13):
            _, offset = read_matrix(payload, offset)
            _, offset = read_matrix(payload, offset)
            records = payload[offset] & 15
            offset += 1 + records * 10 + (4 if kind == 0x13 else 0)
        elif kind in (0x40, 0x41, 0x42, 0x43):
            found.add(struct.unpack_from('<H', payload, offset)[0])
            _, offset = read_matrix(payload, offset + 2)
            _, offset = read_matrix(payload, offset)
        else:
            break
    return found


def _bitmap_size(code, payload):
    if code in (20, 36):
        return struct.unpack_from('<HH', payload, 3)
    return None  # JPEG: known from the decoded picture (the tool) or the HD file (the pass)


def eligible_bitmaps(tags, own_hd=None):
    """Ids of the pictures that can be enlarged, from [(code, payload)] of the movie's top-level tags.
    `own_hd`: ids left out because they already have their own HD (the client movie's, by default)."""
    from swf_hd_art import HD_BITMAP_IDS
    if own_hd is None:
        own_hd = HD_BITMAP_IDS
    bitmaps, exported, used, morphed = set(), set(), set(), set()
    for code, payload in tags:
        if code in BITMAP_TAGS:
            bitmaps.add(struct.unpack_from('<H', payload)[0])
        elif code in (56, 76):  # ExportAssets / SymbolClass
            count, position = struct.unpack_from('<H', payload)[0], 2
            for _ in range(count):
                exported.add(struct.unpack_from('<H', payload, position)[0])
                position = payload.index(b'\0', position + 2) + 1
        elif code in SHAPE_TAGS:
            used.update(fill[1] for fill in _shape_fill_offsets(payload, code))
        elif code in MORPH_TAGS:
            morphed |= _morph_bitmaps(payload, code)
    return {b for b in bitmaps if b in used and b not in exported and b not in morphed and b not in own_hd}


def translated_ids(language):
    """Pictures a language replaces with its own art (their HD comes from that art)."""
    from localization import normalize_locale
    from swf_bitmap_art import BITMAP_DIMENSIONS, LANGUAGE_BITMAP_DIMENSIONS
    locale = normalize_locale(language)
    if locale == 'en':
        return set()
    return set(BITMAP_DIMENSIONS) | set(LANGUAGE_BITMAP_DIMENSIONS.get(locale, {}))


def hd_path(character_id, language):
    from localization import normalize_locale
    if character_id in translated_ids(language):
        locale = normalize_locale(language)
        for folder in (locale, 'pt-BR'):
            path = HD_DIR / folder / f'{character_id}.png'
            if path.exists():
                return path
        return None
    path = HD_DIR / f'{character_id}.png'
    return path if path.exists() else None


@lru_cache(maxsize=1024)
def _packed(path):
    """(width, height, JPEG3 body) of an HD picture file."""
    from PIL import Image
    return pack_picture(Image.open(path))


def pack_picture(image):
    """(width, height, JPEG3 body after the character id) of a picture: a JPEG of its colours multiplied by
    alpha (as the game's own JPEG3 pictures, measured: Flash premultiplies them) and the zlib alpha plane."""
    import io
    import zlib
    from PIL import Image, ImageChops
    image = image.convert('RGBA')
    red, green, blue, alpha = image.split()
    colours = Image.merge('RGB', [ImageChops.multiply(channel, alpha) for channel in (red, green, blue)])
    stream = io.BytesIO()
    colours.save(stream, 'JPEG', quality=JPEG_QUALITY, subsampling=0)
    jpeg = stream.getvalue()
    return image.width, image.height, struct.pack('<I', len(jpeg)) + jpeg + zlib.compress(alpha.tobytes(), 9)


def _scaled_matrix(matrix):
    """The fill matrix for a picture HD_FACTOR times bigger: same placement, smaller step per pixel."""
    from swf_hd_art import encode_matrix
    a, d, b, c, tx, ty = matrix
    return encode_matrix((round(a / HD_FACTOR), round(d / HD_FACTOR), round(b / HD_FACTOR), round(c / HD_FACTOR), tx, ty))


def apply_hd_icons(data, language='es'):
    """Return the movie with its icons in HD (only the pictures that have an HD file and are safe to swap)."""
    import zlib
    from swf_localization import decode_swf, encode_tag, iter_tags
    body, header_length = decode_swf(data)
    tags = list(iter_tags(body, header_length))
    candidates = eligible_bitmaps([(code, payload) for code, payload, _ in tags])
    skip = {int(value) for value in os.environ.get('SE_HD_ICONS_SKIP', '').replace(',', ' ').split() if value.isdigit()}
    candidates -= skip  # SE_HD_ICONS_SKIP: pictures left as they are (to find one that misbehaves)
    replaced = {}  # id -> (width, height, packed)
    for code, payload, _ in tags:
        if code not in BITMAP_TAGS:
            continue
        character_id = struct.unpack_from('<H', payload)[0]
        if character_id not in candidates:
            continue
        path = hd_path(character_id, language)
        if path is None:
            continue
        width, height, packed = _packed(path)
        size = _bitmap_size(code, payload)
        if size is not None and (size[0] * HD_FACTOR, size[1] * HD_FACTOR) != (width, height):
            continue  # the HD file does not match this picture: keep the original
        if max(width, height) > MAX_ICON_SIDE * HD_FACTOR:
            continue
        replaced[character_id] = (width, height, packed)
    return _rebuild(data, body, header_length, tags, replaced)


def replace_pictures(data, pictures):
    """Return a movie (a building or unit sprite) with pictures swapped: {character id: HD picture HD_FACTOR times
    the original size}. Only safe pictures (eligible_bitmaps) are swapped."""
    from swf_localization import decode_swf, iter_tags
    body, header_length = decode_swf(data)
    tags = list(iter_tags(body, header_length))
    candidates = eligible_bitmaps([(code, payload) for code, payload, _ in tags], own_hd=set())
    replaced = {character_id: pack_picture(picture) for character_id, picture in pictures.items()
                if character_id in candidates}
    return _rebuild(data, body, header_length, tags, replaced)


def _rebuild(data, body, header_length, tags, replaced):
    """The movie with the `replaced` pictures ({id: (width, height, JPEG3 body)}) and their fills rescaled."""
    import zlib
    from swf_localization import encode_tag
    out = []
    for code, payload, long_length in tags:
        if code in BITMAP_TAGS:
            character_id = struct.unpack_from('<H', payload)[0]
            if character_id in replaced:
                width, height, packed = replaced[character_id]
                code, payload, long_length = JPEG3, struct.pack('<H', character_id) + packed, True
        elif code in SHAPE_TAGS:
            fills = [fill for fill in _shape_fill_offsets(payload, code) if fill[1] in replaced]
            for _, _, start, end, matrix in reversed(fills):  # from the end: earlier offsets stay valid
                payload = payload[:start] + _scaled_matrix(matrix) + payload[end:]
        out.append(encode_tag(code, payload, long_length))
    patched = body[:header_length] + b''.join(out)
    header = data[:4] + struct.pack('<I', len(patched) + 8)
    return header + (zlib.compress(patched) if data[:3] == b'CWS' else patched)


def resource_sprite_names(items):
    """img_names of the map's resources (SE_HD_SPRITES=recursos): the game's own "Resources" category (mills, crops,
    ranches, gold and stone mines, trees: subcategory 12) and anything else that gives wood or stone when collected
    (the trees and rocks of the map), but not the Wonders (they produce resources too, but they are buildings)."""
    return {item['img_name'] for item in items if item.get('type') == 'b' and item.get('subcategory_id') != '51'
            and (item.get('subcategory_id') == '12' or item.get('collect_type') in ('w', 's'))}
