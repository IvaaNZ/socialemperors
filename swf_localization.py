"""Translate editable SWF labels while retaining the original client artifact.

The legacy movie includes visible labels in editable text and static glyph tags,
outside the game-config catalog. Rebuilding tag lengths (also inside sprites)
avoids touching ActionScript bytecode or technical identifiers.
"""

import json
import re
import struct
import zlib
from pathlib import Path

from bundle import CONFIG_DIR
from localization import load_catalog, normalize_locale
from swf_bitmap_art import localize_bitmap_art
from swf_hd_art import upgrade_shape_bitmap_fill
from swf_layout_fixes import fix_sprite_layout
from swf_vector_art import localize_vector_art
from swf_static_text import build_font_maps, localize_static_text


def _rect_size(data, offset=0):
    return (5 + 4 * (data[offset] >> 3) + 7) // 8


def _cstring_end(data, offset):
    return data.index(b'\0', offset)


def edit_text_offset(payload):
    """Return InitialText's byte offset, or None when HasText is unset."""
    offset = 2 + _rect_size(payload, 2)
    flags, flags2 = payload[offset:offset + 2]
    offset += 2
    if flags & 1:  # HasFont
        offset += 2
    if flags2 & 128:  # HasFontClass
        offset = _cstring_end(payload, offset) + 1
    if flags & 1:
        offset += 2  # FontHeight
    if flags & 4:
        offset += 4  # RGBA
    if flags & 2:
        offset += 2  # MaxLength
    if flags2 & 32:
        offset += 9  # alignment, margins, indent and leading
    offset = _cstring_end(payload, offset) + 1  # VariableName remains unchanged
    return offset if flags & 128 else None


def _rect(data, offset):
    """Return (xmin, xmax, ymin, ymax) in twips from a SWF RECT."""
    bits = data[offset] >> 3
    total = 5 + 4 * bits
    length = (total + 7) // 8
    value = int.from_bytes(data[offset:offset + length], 'big')
    shift = length * 8 - 5
    values = []
    for _ in range(4):
        shift -= bits
        raw = (value >> shift) & ((1 << bits) - 1)
        values.append(raw - (1 << bits) if bits and raw & (1 << (bits - 1)) else raw)
    return tuple(values)


def edit_text_layout(payload):
    """Read the geometry needed to keep a translated label inside its field."""
    xmin, xmax, ymin, ymax = _rect(payload, 2)
    offset = 2 + _rect_size(payload, 2)
    flags, flags2 = payload[offset:offset + 2]
    offset += 2
    font_id = font_height_offset = None
    if flags & 1:
        font_id = struct.unpack_from('<H', payload, offset)[0]
        offset += 2
    if flags2 & 128:
        offset = _cstring_end(payload, offset) + 1
    if flags & 1:
        font_height_offset = offset
        offset += 2
    if flags & 4:
        offset += 4
    if flags & 2:
        offset += 2
    margins = 0
    if flags2 & 32:
        left, right = struct.unpack_from('<HH', payload, offset + 1)
        margins = left + right
    return {
        'width': xmax - xmin - margins - 80,  # Flash keeps a 2 px gutter on each side.
        'height': ymax - ymin,
        'font_id': font_id,
        'font_height_offset': font_height_offset,
        'font_height': struct.unpack_from('<H', payload, font_height_offset)[0] if font_height_offset else None,
        'word_wrap': bool(flags & 0x40),
        'multiline': bool(flags & 0x20),
        'outlines': bool(flags2 & 1),
        'html': bool(flags2 & 2),
    }


_HTML_SIZE = re.compile(r'(<font\b[^>]*\bsize=")(\d+)(")', re.I)
_LINE_BREAK = re.compile(r'</p>|<br\s*/?>|\r|\n', re.I)


def _visible_lines(text, html):
    lines = _LINE_BREAK.split(text) if html else re.split(r'\r|\n', text)
    return [re.sub(r'<[^>]+>', '', line) if html else line for line in lines]


def _text_width(text, html, font, font_height):
    """Widest line in twips, using the embedded font's advances."""
    if html:
        sizes = [int(size) * 20 for _, size, _ in _HTML_SIZE.findall(text)]
        font_height = sizes[0] if sizes else font_height
    return max((sum(font['advances'][font['indices'][letter]] for letter in line if letter in font['indices'])
                * font_height / font['scale'] for line in _visible_lines(text, html)), default=0)


def fit_edit_text(payload, source, translated, fonts):
    """Return (text, font_height) for a translated field, or None to keep the source.

    Embedded fonts only contain some glyphs; a translation needing a missing
    letter keeps the original label instead of rendering an incomplete word.
    Labels that cannot wrap onto a visible second line shrink their font size
    so the translation stays inside the original field, like static text.
    """
    layout = edit_text_layout(payload)
    font = fonts.get(layout['font_id'])
    if not layout['outlines'] or font is None or font.get('advances') is None or not layout['font_height']:
        return translated, None
    visible = ''.join(_visible_lines(translated, layout['html']))
    if any(letter not in font['indices'] for letter in visible if not letter.isspace()):
        return None
    width = _text_width(translated, layout['html'], font, layout['font_height'])
    # Measurements ignore kerning and renderer rounding, so keep a small margin.
    allowed = max(layout['width'] * 0.95, _text_width(source, layout['html'], font, layout['font_height']))
    line_height = layout['font_height'] * 1.15
    can_wrap = layout['word_wrap'] and layout['multiline'] and layout['height'] >= 2 * line_height
    if width <= allowed or can_wrap or allowed <= 0:
        return translated, None
    ratio = allowed / width
    # The field's own height is also the format the game uses for text it sets at runtime.
    font_height = max(20, int(layout['font_height'] * ratio))
    if layout['html']:
        return _HTML_SIZE.sub(lambda m: f'{m.group(1)}{max(1, int(int(m.group(2)) * ratio))}{m.group(3)}', translated), font_height
    return translated, font_height


def iter_tags(data, offset=0):
    """Yield (tag code, payload, original long-length format)."""
    while offset < len(data):
        tag = struct.unpack_from('<H', data, offset)[0]
        offset += 2
        length = tag & 63
        long_length = length == 63
        if long_length:
            length = struct.unpack_from('<I', data, offset)[0]
            offset += 4
        end = offset + length
        if end > len(data):
            raise ValueError('SWF tag exceeds its containing stream')
        yield tag >> 6, data[offset:end], long_length
        offset = end


def encode_tag(code, payload, long_length=False):
    length = len(payload)
    if long_length or length >= 63:
        return struct.pack('<HI', (code << 6) | 63, length) + payload
    return struct.pack('<H', (code << 6) | length) + payload


def decode_swf(data):
    if data[:3] == b'CWS':
        body = zlib.decompress(data[8:])
    elif data[:3] == b'FWS':
        body = data[8:]
    else:
        raise ValueError('Expected a zlib-compressed or uncompressed SWF')
    if len(body) + 8 != struct.unpack_from('<I', data, 4)[0]:
        raise ValueError('SWF file length does not match its header')
    return body, _rect_size(body) + 4


def load_swf_catalog(language='pt-BR'):
    locale = normalize_locale(language)
    catalog = load_catalog(locale)
    if not catalog:
        return catalog
    for filename in (f'{locale}-swf.json', f'{locale}-static.json'):
        with (Path(CONFIG_DIR) / 'locales' / filename).open(encoding='utf-8') as stream:
            catalog.update(json.load(stream))
    return catalog


def translate_edit_text(text, catalog):
    if text in catalog:
        return catalog[text]
    # Existing config translations also cover HTML-wrapped editor defaults.
    # Tags and attributes are never translated or serialized again.
    def translate_node(node):
        if node in catalog:
            return catalog[node]
        normalized = node.replace('\r\n', '\n').replace('\r', '\n')
        if normalized in catalog:
            return catalog[normalized]
        stripped = node.strip()
        if stripped and stripped in catalog:
            start = len(node) - len(node.lstrip())
            return node[:start] + catalog[stripped] + node[len(node.rstrip()):]
        return node
    return ''.join(
        node if node.startswith('<') else translate_node(node)
        for node in re.split(r'(<[^>]+>)', text)
    )


def localize_swf(data, catalog=None, language='pt-BR'):
    """Return a derivative movie; never overwrite or mutate the source bytes."""
    use_bitmap_art = catalog is None
    catalog = load_swf_catalog(language) if catalog is None else catalog
    body, header_length = decode_swf(data)
    fonts = build_font_maps(body)

    def rewrite_tags(stream):
        rewritten = []
        for code, payload, long_length in iter_tags(stream):
            if code == 37:  # DefineEditText
                offset = edit_text_offset(payload)
                if offset is not None:
                    end = _cstring_end(payload, offset)
                    if end + 1 != len(payload):
                        raise ValueError('Unexpected data after SWF editable text')
                    source = payload[offset:end].decode('utf-8')
                    translated = translate_edit_text(source, catalog)
                    fitted = fit_edit_text(payload, source, translated, fonts) if translated != source else (source, None)
                    if fitted is not None:
                        translated, font_height = fitted
                        if font_height is not None:
                            height_offset = edit_text_layout(payload)['font_height_offset']
                            payload = payload[:height_offset] + struct.pack('<H', font_height) + payload[height_offset + 2:]
                        payload = payload[:offset] + translated.encode('utf-8') + b'\0'
            elif code == 39:  # DefineSprite: ID + frame count + its own tag stream
                payload = payload[:4] + rewrite_tags(payload[4:])
                if use_bitmap_art:
                    payload = fix_sprite_layout(payload, encode_tag)
            elif code in (11, 33):  # DefineText / DefineText2 embedded glyph labels
                payload = localize_static_text(payload, fonts, catalog, code)
            elif code in (6, 35, 36) and use_bitmap_art:  # Allowlisted translated UI images
                localized = localize_bitmap_art(payload, language, code)
                if localized is not payload:
                    code = 36  # A translated JPEG bitmap is served as Lossless2.
                payload = localized
            elif code in (2, 22, 32, 83) and use_bitmap_art:
                replaced = localize_vector_art(code, payload, language)
                if len(replaced) > 1:  # Lettering drawn as shapes: bitmap first, then the shape using it.
                    for extra_code, extra_payload in replaced[:-1]:
                        rewritten.append(encode_tag(extra_code, extra_payload))
                    code, payload = replaced[-1]
                    long_length = False
                else:
                    payload = upgrade_shape_bitmap_fill(payload, code)
            rewritten.append(encode_tag(code, payload, long_length))
        return b''.join(rewritten)

    localized_body = body[:header_length] + rewrite_tags(body[header_length:])
    header = data[:4] + struct.pack('<I', len(localized_body) + 8)
    return header + (zlib.compress(localized_body) if data[:3] == b'CWS' else localized_body)
