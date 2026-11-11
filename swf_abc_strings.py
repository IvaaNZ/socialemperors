"""Translate a few display strings that the game hardcodes in its AS3 bytecode.

Most client text comes from the game config or from SWF text fields; these few
titles are string constants in the DoABC constant pool instead. Only exact,
allowlisted constants are replaced, and only display strings (checked by hand
in the decompiled code), so no identifier or comparison changes meaning.

Run this after the audited bytecode patches (swf_private_economy, swf_tutorial):
they pin the ABC checksum, and a constant-pool edit changes it. Method bodies
refer to strings by index, so a longer or shorter string keeps every offset the
code uses valid.
"""

import struct
import zlib

from localization import normalize_locale
from swf_localization import decode_swf, encode_tag, iter_tags

# English constant -> translation. 'Gods & Colossus' is the lore popup title
# (GuiManager.openLore, PopupNews.onGoToStore, AdminPanel.testLore).
ABC_STRING_TRANSLATIONS = {
    'pt-BR': {'Gods & Colossus': 'Deuses e Colossos'},
    'es': {'Gods & Colossus': 'Dioses y Colosos'},
}
DO_ABC = 82


def _read_u30(data, pos):
    value = shift = 0
    for _ in range(5):
        byte = data[pos]
        pos += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, pos
        shift += 7
    raise ValueError('Invalid U30 in ABC constant pool')


def _write_u30(value):
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def replace_abc_strings(abc, replacements):
    """Return the ABC block with exact string-pool constants replaced."""
    pos = 4  # minor and major version
    for _ in ('int', 'uint'):
        count, pos = _read_u30(abc, pos)
        for _ in range(max(count - 1, 0)):
            _, pos = _read_u30(abc, pos)
    count, pos = _read_u30(abc, pos)
    pos += 8 * max(count - 1, 0)
    count, pos = _read_u30(abc, pos)
    pieces = [abc[:pos]]
    found = set()
    for _ in range(max(count - 1, 0)):
        length, start = _read_u30(abc, pos)
        end = start + length
        text = abc[start:end].decode('utf-8', errors='surrogateescape')
        if text in replacements:
            found.add(text)
            encoded = replacements[text].encode('utf-8')
            pieces.append(_write_u30(len(encoded)) + encoded)
        else:
            pieces.append(abc[pos:end])
        pos = end
    missing = set(replacements) - found
    if missing:
        raise ValueError(f'ABC string constants not found: {sorted(missing)}')
    pieces.append(abc[pos:])
    return b''.join(pieces)


def localize_abc_strings(data, language='pt-BR'):
    """Return the movie with the allowlisted bytecode strings translated."""
    replacements = ABC_STRING_TRANSLATIONS.get(normalize_locale(language))
    if not replacements:
        return data
    body, header_length = decode_swf(data)
    tags = []
    for code, payload, long_length in iter_tags(body, header_length):
        if code == DO_ABC:
            offset = payload.index(b'\0', 4) + 1
            payload = payload[:offset] + replace_abc_strings(payload[offset:], replacements)
        tags.append(encode_tag(code, payload, long_length))
    patched = body[:header_length] + b''.join(tags)
    header = data[:4] + struct.pack('<I', len(patched) + 8)
    return header + (zlib.compress(patched) if data[:3] == b'CWS' else patched)
