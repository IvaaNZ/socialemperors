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
                    payload = payload[:offset] + translated.encode('utf-8') + b'\0'
            elif code == 39:  # DefineSprite: ID + frame count + its own tag stream
                payload = payload[:4] + rewrite_tags(payload[4:])
            elif code in (11, 33):  # DefineText / DefineText2 embedded glyph labels
                payload = localize_static_text(payload, fonts, catalog, code)
            elif code == 36 and use_bitmap_art:  # Allowlisted translated Lossless2 UI images
                payload = localize_bitmap_art(payload)
            elif code in (2, 22, 32, 83) and use_bitmap_art:
                payload = upgrade_shape_bitmap_fill(payload, code)
            rewritten.append(encode_tag(code, payload, long_length))
        return b''.join(rewritten)

    localized_body = body[:header_length] + rewrite_tags(body[header_length:])
    header = data[:4] + struct.pack('<I', len(localized_body) + 8)
    return header + (zlib.compress(localized_body) if data[:3] == b'CWS' else localized_body)
