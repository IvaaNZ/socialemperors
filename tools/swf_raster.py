"""Small rasterizer for SWF vector shapes, used only by the artwork tools.

It draws DefineShape 1-4 fills (solid, linear and radial gradients; bitmap
fills as flat grey) with even-odd scanlines and supersampling. Line styles are
ignored: the button lettering it is used for is made of filled outlines only.
Sprites render their first frame. The game never runs this code.
"""

import math
import struct

from PIL import Image


class Bits:
    def __init__(self, data, offset):
        self.data, self.bit = data, offset * 8

    def ub(self, count):
        value = 0
        for _ in range(count):
            value = (value << 1) | ((self.data[self.bit // 8] >> (7 - self.bit % 8)) & 1)
            self.bit += 1
        return value

    def sb(self, count):
        value = self.ub(count)
        return value - (1 << count) if count and value >> (count - 1) else value

    def align(self):
        self.bit = (self.bit + 7) // 8 * 8

    def offset(self):
        return (self.bit + 7) // 8


IDENTITY = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)  # a, b, c, d, tx, ty (Flash order)


def read_rect(data, offset):
    bits = Bits(data, offset)
    count = bits.ub(5)
    return [bits.sb(count) for _ in range(4)], bits.offset()  # xmin, xmax, ymin, ymax


def read_matrix(data, offset):
    bits = Bits(data, offset)
    a = d = 1.0
    b = c = 0.0
    if bits.ub(1):
        count = bits.ub(5)
        a, d = bits.sb(count) / 65536, bits.sb(count) / 65536
    if bits.ub(1):
        count = bits.ub(5)
        b, c = bits.sb(count) / 65536, bits.sb(count) / 65536
    count = bits.ub(5)
    tx, ty = bits.sb(count), bits.sb(count)
    return (a, b, c, d, tx, ty), bits.offset()


def concat(inner, outer):
    """Matrix applying inner first, then outer."""
    a1, b1, c1, d1, x1, y1 = inner
    a2, b2, c2, d2, x2, y2 = outer
    return (a1 * a2 + b1 * c2, a1 * b2 + b1 * d2, c1 * a2 + d1 * c2, c1 * b2 + d1 * d2,
            x1 * a2 + y1 * c2 + x2, x1 * b2 + y1 * d2 + y2)


def apply(matrix, x, y):
    a, b, c, d, tx, ty = matrix
    return a * x + c * y + tx, b * x + d * y + ty


def invert(matrix):
    a, b, c, d, tx, ty = matrix
    det = a * d - b * c
    ia, ib, ic, id_ = d / det, -b / det, -c / det, a / det
    return (ia, ib, ic, id_, -(ia * tx + ic * ty), -(ib * tx + id_ * ty))


def _color(data, offset, rgba):
    size = 4 if rgba else 3
    color = tuple(data[offset:offset + size]) + (() if rgba else (255,))
    return color, offset + size


def read_fill_styles(data, offset, code):
    count = data[offset]
    offset += 1
    if count == 0xFF:
        count = struct.unpack_from('<H', data, offset)[0]
        offset += 2
    styles = []
    for _ in range(count):
        kind = data[offset]
        offset += 1
        if kind == 0x00:
            color, offset = _color(data, offset, code >= 32)
            styles.append(('solid', color))
        elif kind in (0x10, 0x12, 0x13):
            matrix, offset = read_matrix(data, offset)
            stops_count = data[offset] & 0x0F
            offset += 1
            stops = []
            for _ in range(stops_count):
                ratio = data[offset]
                color, offset = _color(data, offset + 1, code >= 32)
                stops.append((ratio, color))
            if kind == 0x13:
                offset += 2
            styles.append(('linear' if kind == 0x10 else 'radial', matrix, stops))
        elif kind in (0x40, 0x41, 0x42, 0x43):
            offset += 2
            _, offset = read_matrix(data, offset)
            styles.append(('solid', (128, 128, 128, 255)))
        else:
            raise ValueError(f'Unsupported fill style {kind:#x}')
    return styles, offset


def read_line_styles(data, offset, code):
    count = data[offset]
    offset += 1
    if count == 0xFF:
        count = struct.unpack_from('<H', data, offset)[0]
        offset += 2
    for _ in range(count):
        if code == 83:
            flags = data[offset + 2]
            offset += 4
            if flags & 0x30 == 0x20:  # miter join factor
                offset += 2
            if flags & 0x08:
                raise ValueError('Filled line styles are not supported')
            offset += 4
        else:
            offset += 2 + (4 if code >= 32 else 3)
    return offset


def shape_regions(payload, code):
    """[(style_number, style, [polyline, ...])] in shape twips, numbered from 1."""
    _, offset = read_rect(payload, 2)
    if code == 83:
        _, offset = read_rect(payload, offset)
        offset += 1
    styles, offset = read_fill_styles(payload, offset, code)
    offset = read_line_styles(payload, offset, code)
    bits = Bits(payload, offset)
    fill_bits, line_bits = bits.ub(4), bits.ub(4)
    x = y = 0
    fill0 = fill1 = 0
    base = 0
    edges = {}
    while True:
        if bits.ub(1) == 0:
            flags = bits.ub(5)
            if not flags:
                break
            if flags & 1:
                count = bits.ub(5)
                x, y = bits.sb(count), bits.sb(count)
            if flags & 2:
                fill0 = bits.ub(fill_bits)
            if flags & 4:
                fill1 = bits.ub(fill_bits)
            if flags & 8:
                bits.ub(line_bits)
            if flags & 16:
                bits.align()
                new_styles, offset = read_fill_styles(payload, bits.offset(), code)
                offset = read_line_styles(payload, offset, code)
                base = len(styles)
                styles += new_styles
                bits = Bits(payload, offset)
                fill_bits, line_bits = bits.ub(4), bits.ub(4)
            continue
        if bits.ub(1):  # straight edge
            count = bits.ub(4) + 2
            if bits.ub(1):
                dx, dy = bits.sb(count), bits.sb(count)
            elif bits.ub(1):
                dx, dy = 0, bits.sb(count)
            else:
                dx, dy = bits.sb(count), 0
            segment = [(x, y), (x + dx, y + dy)]
            x, y = x + dx, y + dy
        else:  # quadratic curve
            count = bits.ub(4) + 2
            cx, cy = x + bits.sb(count), y + bits.sb(count)
            ax, ay = cx + bits.sb(count), cy + bits.sb(count)
            segment = [((1 - t) ** 2 * x + 2 * (1 - t) * t * cx + t * t * ax,
                        (1 - t) ** 2 * y + 2 * (1 - t) * t * cy + t * t * ay)
                       for t in (step / 12 for step in range(13))]
            x, y = ax, ay
        for fill in (fill0, fill1):
            if fill:
                edges.setdefault(base + fill, []).append(segment)
    return [(number, styles[number - 1], segments) for number, segments in sorted(edges.items())]


def _style_color(style, inverse, sx, sy):
    if style[0] == 'solid':
        return style[1]
    _, matrix, stops = style
    gx, gy = apply(invert(matrix), *apply(inverse, sx, sy))
    if style[0] == 'linear':
        ratio = (gx + 16384) / 32768 * 255
    else:
        ratio = math.hypot(gx, gy) / 16384 * 255
    ratio = min(max(ratio, stops[0][0]), stops[-1][0])
    for (r0, c0), (r1, c1) in zip(stops, stops[1:]):
        if r0 <= ratio <= r1:
            t = 0 if r1 == r0 else (ratio - r0) / (r1 - r0)
            return tuple(round(a + (b - a) * t) for a, b in zip(c0, c1))
    return stops[-1][1]


class Canvas:
    """RGBA canvas whose pixel (0, 0) is at origin (twips), at `scale` pixels per pixel unit."""

    def __init__(self, width, height, origin_x, origin_y, scale, supersample=4):
        self.ss = supersample
        self.image = Image.new('RGBA', (width * supersample, height * supersample), (0, 0, 0, 0))
        self.size = (width, height)
        # twips -> canvas pixels
        factor = scale * supersample / 20
        self.view = (factor, 0.0, 0.0, factor, -origin_x * factor, -origin_y * factor)

    def fill(self, style, segments, matrix):
        to_canvas = concat(matrix, self.view)
        lines = []
        for segment in segments:
            points = [apply(to_canvas, px, py) for px, py in segment]
            lines += list(zip(points, points[1:]))
        if not lines:
            return
        inverse = invert(to_canvas)
        width, height = self.image.size
        pixels = self.image.load()
        top = max(0, int(min(min(p[1], q[1]) for p, q in lines)))
        bottom = min(height - 1, int(max(max(p[1], q[1]) for p, q in lines)) + 1)
        for row in range(top, bottom + 1):
            sy = row + 0.5
            xs = sorted(x0 + (sy - y0) * (x1 - x0) / (y1 - y0)
                        for (x0, y0), (x1, y1) in lines if (y0 <= sy < y1) or (y1 <= sy < y0))
            for start, end in zip(xs[0::2], xs[1::2]):
                for column in range(max(0, int(start + 0.5)), min(width, int(end + 0.5))):
                    color = _style_color(style, inverse, column + 0.5, sy)
                    if color[3] == 0:
                        continue
                    if color[3] == 255:
                        pixels[column, row] = color
                    else:
                        under = pixels[column, row]
                        alpha = color[3] / 255
                        out_alpha = alpha + under[3] / 255 * (1 - alpha)
                        mixed = tuple(round((c * alpha + u * under[3] / 255 * (1 - alpha)) / out_alpha)
                                      for c, u in zip(color[:3], under[:3]))
                        pixels[column, row] = mixed + (round(out_alpha * 255),)

    def result(self):
        return self.image.resize(self.size, Image.LANCZOS)


def render_shape(canvas, payload, code, matrix=IDENTITY, keep=None):
    """Draw a shape; `keep` limits drawing to those fill style numbers."""
    for number, style, segments in shape_regions(payload, code):
        if keep is None or number in keep:
            canvas.fill(style, segments, matrix)
