"""Load the translated button images for the derived game movie.

The original SWF and every other bitmap remain intact. Two unexported textures
use four times as many pixels on each axis, with matching shape matrices from
swf_hd_art. Exported BitmapData retains its dimensions for AS3 compatibility.
Assets contain Flash format-5 premultiplied ARGB pixels, packed in preparation.

BITMAP_DIMENSIONS lists the images translated for every language (Portuguese
art, reused when Spanish spells the word the same). LANGUAGE_BITMAP_DIMENSIONS
lists images only one language replaces; the rest keep the original English art.
Some of those originals are JPEG bitmaps (DefineBits or DefineBitsJPEG3); their
translation is served as a lossless bitmap with the same character id and size.
"""

from pathlib import Path
import struct
import zlib

from bundle import CONFIG_DIR
from localization import normalize_locale
from swf_hd_art import HD_BITMAP_IDS, HD_SCALE


ARTWORK_DIR = Path(CONFIG_DIR) / 'locales' / 'artwork'
BITMAP_DIMENSIONS = {31: (63, 68), 220: (118, 33), 3948: (71, 99), 3967: (157, 59)}
BITMAP_RENDER_DIMENSIONS = {
    character_id: tuple(value * HD_SCALE for value in size) if character_id in HD_BITMAP_IDS else size
    for character_id, size in BITMAP_DIMENSIONS.items()
}
LANGUAGE_BITMAP_DIMENSIONS = {
    'es': {
        147: (83, 82), 149: (93, 85), 233: (128, 29), 234: (238, 27), 792: (157, 59),
        798: (62, 75), 1028: (63, 44), 1034: (105, 47), 1038: (84, 52), 1042: (111, 105),
        1529: (159, 33), 1534: (159, 33), 2421: (186, 60), 3431: (49, 48), 3545: (54, 55),
        3491: (124, 99), 3524: (130, 25), 3582: (157, 59),
    },
}
LOSSLESS2 = 36
JPEG3 = 35


def artwork_path(character_id, language='pt-BR'):
    """Packed artwork for a language, or the Portuguese one when the word is shared."""
    suffix = '-hd' if character_id in HD_BITMAP_IDS else ''
    localized = ARTWORK_DIR / f'{normalize_locale(language)}-{character_id}{suffix}.argb.zlib'
    return localized if localized.exists() else ARTWORK_DIR / f'pt-BR-{character_id}{suffix}.argb.zlib'


def _validated(compressed, character_id, width, height):
    try:
        pixels = zlib.decompress(compressed)
    except zlib.error as error:
        raise ValueError(f'Invalid translated artwork for SWF bitmap {character_id}') from error
    if len(pixels) != width * height * 4:
        raise ValueError(f'Incorrect translated artwork size for SWF bitmap {character_id}')
    # Flash Lossless2 format 5 expects alpha, red, green, blue, with each color
    # component multiplied by alpha. Validate the packed artifact at its boundary.
    if any(max(pixels[offset + 1:offset + 4]) > pixels[offset] for offset in range(0, len(pixels), 4)):
        raise ValueError(f'Artwork for SWF bitmap {character_id} is not premultiplied ARGB')
    return compressed


def load_bitmap_art(character_id, language='pt-BR'):
    if character_id in BITMAP_DIMENSIONS:
        width, height = BITMAP_RENDER_DIMENSIONS[character_id]
        return _validated(artwork_path(character_id, language).read_bytes(), character_id, width, height)
    width, height = LANGUAGE_BITMAP_DIMENSIONS[normalize_locale(language)][character_id]
    path = ARTWORK_DIR / f'{normalize_locale(language)}-{character_id}.argb.zlib'
    return _validated(path.read_bytes(), character_id, width, height)


def localize_bitmap_art(payload, language='pt-BR', tag_code=LOSSLESS2):
    """Return a translated Lossless2 payload, or the original payload unchanged."""
    character_id = struct.unpack_from('<H', payload)[0]
    if character_id in BITMAP_DIMENSIONS and tag_code == LOSSLESS2:
        bitmap_format, width, height = struct.unpack_from('<BHH', payload, 2)
        if bitmap_format != 5 or (width, height) != BITMAP_DIMENSIONS[character_id]:
            raise ValueError(f'Unexpected original SWF bitmap layout for {character_id}')
        render_width, render_height = BITMAP_RENDER_DIMENSIONS[character_id]
        return struct.pack('<HBHH', character_id, bitmap_format, render_width, render_height) + load_bitmap_art(character_id, language)
    dimensions = LANGUAGE_BITMAP_DIMENSIONS.get(normalize_locale(language), {}).get(character_id)
    if dimensions is None:
        return payload
    if tag_code == LOSSLESS2:
        bitmap_format, width, height = struct.unpack_from('<BHH', payload, 2)
        if bitmap_format != 5 or (width, height) != dimensions:
            raise ValueError(f'Unexpected original SWF bitmap layout for {character_id}')
    return struct.pack('<HBHH', character_id, 5, *dimensions) + load_bitmap_art(character_id, language)
