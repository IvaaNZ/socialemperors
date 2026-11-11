"""Replace vector-drawn English lettering with translated images.

Most drawn English words in the client are bitmaps (see swf_bitmap_art). The
Monday chest button ("MON DAY REWARD") draws its words as vector shapes
instead. For those allowlisted shapes the derived movie defines a new lossless
bitmap and redefines the shape, with the same character id and bounds, as a
rectangle filled with that bitmap. Placements, animation and the sprite tree
keep their original bytes. The images are made by tools/make_es_vector_art.py
at VECTOR_ART_SCALE pixels per screen pixel.
"""

import math
from pathlib import Path
import struct

from bundle import CONFIG_DIR
from localization import normalize_locale
from swf_bitmap_art import _validated
from swf_hd_art import encode_matrix

ARTWORK_DIR = Path(CONFIG_DIR) / 'locales' / 'artwork'
VECTOR_ART_SCALE = 2
LOSSLESS2 = 36
DEFINE_SHAPE3 = 32
SHAPE_TAGS = (2, 22, 32, 83)
# shape id -> (new bitmap id, original bounds in twips: xmin, xmax, ymin, ymax)
VECTOR_ART = {
    'es': {
        678: (64001, (-1092, 1568, 0, 2000)),  # REWARD ribbon
        848: (64002, (0, 496, 0, 487)),        # DAY shadow
        850: (64003, (2, 572, 0, 466)),        # MON shadow
        852: (64004, (0, 446, 0, 437)),        # DAY
        854: (64005, (1, 523, 0, 416)),        # MON
        688: (64006, (-1, 496, 0, 487)),       # DAY shadow (second state)
        690: (64007, (1, 572, 0, 466)),        # MON shadow (second state)
        692: (64008, (0, 447, 0, 438)),        # DAY (second state)
        694: (64009, (2, 522, 0, 416)),        # MON (second state)
    },
}


class _BitWriter:
    def __init__(self):
        self.bytes = bytearray()
        self.pending = self.count = 0

    def write(self, value, width):
        self.pending = self.pending << width | (value & ((1 << width) - 1))
        self.count += width
        while self.count >= 8:
            self.count -= 8
            self.bytes.append((self.pending >> self.count) & 255)
            self.pending &= (1 << self.count) - 1

    def finish(self):
        if self.count:
            self.bytes.append(self.pending << (8 - self.count))
            self.pending = self.count = 0
        return bytes(self.bytes)


def _signed_width(*values):
    return max((value if value >= 0 else ~value).bit_length() + 1 for value in values)


def read_bounds(payload):
    """Return the shape's RECT (xmin, xmax, ymin, ymax) in twips."""
    data = payload[2:]
    width = data[0] >> 3
    bit = 5
    values = []
    for _ in range(4):
        value = 0
        for _ in range(width):
            value = (value << 1) | ((data[bit // 8] >> (7 - bit % 8)) & 1)
            bit += 1
        values.append(value - (1 << width) if width and value >> (width - 1) else value)
    return tuple(values)


def encode_rect(xmin, xmax, ymin, ymax):
    writer = _BitWriter()
    width = _signed_width(xmin, xmax, ymin, ymax)
    writer.write(width, 5)
    for value in (xmin, xmax, ymin, ymax):
        writer.write(value, width)
    return writer.finish()


def bitmap_size(bounds):
    xmin, xmax, ymin, ymax = bounds
    pixel = 20 // VECTOR_ART_SCALE
    return math.ceil((xmax - xmin) / pixel), math.ceil((ymax - ymin) / pixel)


def bitmap_rect_shape(shape_id, bitmap_id, bounds):
    """DefineShape3 payload: the bounds rectangle filled with the bitmap."""
    xmin, xmax, ymin, ymax = bounds
    scale = (20 // VECTOR_ART_SCALE) * 65536
    fills = bytes([1, 0x41]) + struct.pack('<H', bitmap_id) + encode_matrix((scale, scale, 0, 0, xmin, ymin))
    writer = _BitWriter()
    writer.write(1, 4)  # fill index bits
    writer.write(0, 4)  # line index bits
    move = _signed_width(xmin, ymin)
    writer.write(0, 1)
    writer.write(0b00101, 5)  # StyleChange: FillStyle1 + MoveTo
    writer.write(move, 5)
    writer.write(xmin, move)
    writer.write(ymin, move)
    writer.write(1, 1)  # FillStyle1 = 1
    for dx, dy in ((xmax - xmin, 0), (0, ymax - ymin), (xmin - xmax, 0), (0, ymin - ymax)):
        width = max(_signed_width(dx, dy), 2)
        writer.write(1, 1)  # edge
        writer.write(1, 1)  # straight
        writer.write(width - 2, 4)
        if dx and dy:
            writer.write(1, 1)
            writer.write(dx, width)
            writer.write(dy, width)
        else:
            writer.write(0, 1)
            writer.write(1 if dx == 0 else 0, 1)  # vertical line flag
            writer.write(dy if dx == 0 else dx, width)
    writer.write(0, 6)  # EndShapeRecord
    return struct.pack('<H', shape_id) + encode_rect(*bounds) + fills + bytes([0]) + writer.finish()


def load_vector_art(shape_id, language):
    bitmap_id, bounds = VECTOR_ART[normalize_locale(language)][shape_id]
    width, height = bitmap_size(bounds)
    path = ARTWORK_DIR / f'{normalize_locale(language)}-vec-{shape_id}.argb.zlib'
    return _validated(path.read_bytes(), shape_id, width, height)


def localize_vector_art(code, payload, language):
    """Return [(tag code, payload), ...] replacing one allowlisted shape tag."""
    shape_id = struct.unpack_from('<H', payload)[0]
    entry = VECTOR_ART.get(normalize_locale(language), {}).get(shape_id)
    if entry is None or code not in SHAPE_TAGS:
        return [(code, payload)]
    bitmap_id, bounds = entry
    if read_bounds(payload) != bounds:
        raise ValueError(f'Unexpected original bounds for SWF shape {shape_id}')
    width, height = bitmap_size(bounds)
    bitmap = struct.pack('<HBHH', bitmap_id, 5, width, height) + load_vector_art(shape_id, language)
    return [(LOSSLESS2, bitmap), (DEFINE_SHAPE3, bitmap_rect_shape(shape_id, bitmap_id, bounds))]
