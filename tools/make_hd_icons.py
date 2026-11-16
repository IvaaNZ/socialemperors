"""Make the HD icons of the game (config/hd_icons), used by swf_hd_icons.py when the game movie is built.

Every picture swf_hd_icons.eligible_bitmaps accepts and that is an icon (at most MAX_ICON_SIDE pixels a side) is
enlarged 4x with Real-ESRGAN (its anime model, made for drawn art) and reduced to exactly HD_FACTOR times its size:
sharper than enlarging to 2x directly. Pictures a language translates (swf_bitmap_art) are enlarged from the
translated art, into config/hd_icons/<language>/.

Real-ESRGAN (realesrgan-ncnn-vulkan, portable, uses the graphics card) goes in tools/realesrgan (not in git):
https://github.com/xinntao/Real-ESRGAN/releases (realesrgan-ncnn-vulkan-...-windows.zip).

Run from the repository root:  .venv/Scripts/python tools/make_hd_icons.py
"""

from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'WorldEditor'))

import sprites  # noqa: E402
from swf_hd_icons import BITMAP_TAGS, HD_DIR, HD_FACTOR, MAX_ICON_SIDE, eligible_bitmaps  # noqa: E402

GAME = ROOT / 'assets' / 'flash' / 'SocialEmpires0926bsec.swf'
ARTWORK = ROOT / 'config' / 'locales' / 'artwork'
ENGINE = ROOT / 'tools' / 'realesrgan' / 'realesrgan-ncnn-vulkan.exe'
MODEL = 'realesrgan-x4plus-anime'
LANGUAGES = ('es', 'pt-BR')


def decode(code, data, start, length, tables):
    """The picture of a bitmap tag, plain RGBA (DefineBits uses the movie's shared JPEG tables)."""
    if code == 6:
        import io
        payload = data[start + 2:start + length]
        if payload[:4] == b'\xff\xd9\xff\xd8':
            payload = payload[4:]
        merged = tables[:-2] + payload[2:] if tables else payload
        return Image.open(io.BytesIO(merged)).convert('RGBA')
    return sprites._bitmap(code, data, start, length)


def sources():
    """{relative output path: picture} of every icon to enlarge."""
    from swf_bitmap_art import BITMAP_DIMENSIONS, LANGUAGE_BITMAP_DIMENSIONS
    from swf_localization import decode_swf, iter_tags
    raw = GAME.read_bytes()
    body, header_length = decode_swf(raw)
    tags = list(iter_tags(body, header_length))
    eligible = eligible_bitmaps([(code, payload) for code, payload, _ in tags])
    data, first = sprites._decode_swf(raw)
    tables = None
    found = {}
    for code, start, length in sprites._tags(data, first, len(data)):
        if code == 8:
            tables = data[start:start + length]
            if tables[:4] == b'\xff\xd9\xff\xd8':
                tables = tables[4:]
        elif code in BITMAP_TAGS:
            character_id = struct.unpack_from('<H', data, start)[0]
            if character_id not in eligible:
                continue
            picture = decode(code, data, start, length, tables)
            if picture is not None and max(picture.size) <= MAX_ICON_SIDE:
                found[character_id] = picture
    out = {f'{character_id}.png': picture for character_id, picture in found.items()}
    for language in LANGUAGES:
        translated = set(BITMAP_DIMENSIONS) | set(LANGUAGE_BITMAP_DIMENSIONS.get(language, {}))
        for character_id in sorted(translated & set(found)):
            art = ARTWORK / f'{language}-{character_id}.png'
            if not art.exists():
                art = ARTWORK / f'pt-BR-{character_id}.png'
            if art.exists():
                out[f'{language}/{character_id}.png'] = Image.open(art).convert('RGBA')
    return out


def main():
    import contextlib
    import io
    import os
    os.chdir(ROOT)
    if not ENGINE.exists():
        raise SystemExit(f'Real-ESRGAN is missing: {ENGINE} (see this file)')
    with contextlib.redirect_stdout(io.StringIO()):
        pictures = sources()
    print(f'{len(pictures)} icons to enlarge')
    with tempfile.TemporaryDirectory() as folder:
        inbox, outbox = Path(folder) / 'in', Path(folder) / 'out'
        inbox.mkdir()
        outbox.mkdir()
        names = {}
        for number, (target, picture) in enumerate(sorted(pictures.items())):
            name = f'{number:04d}.png'
            names[name] = (target, picture.size)
            picture.save(inbox / name)
        result = subprocess.run([str(ENGINE), '-i', str(inbox), '-o', str(outbox), '-n', MODEL, '-f', 'png'],
                                cwd=ENGINE.parent, capture_output=True, text=True)
        if result.returncode != 0:
            raise SystemExit(result.stderr[-2000:])
        if HD_DIR.exists():
            shutil.rmtree(HD_DIR)
        for name, (target, (width, height)) in names.items():
            enlarged = Image.open(outbox / name).convert('RGBA')
            final = enlarged.resize((width * HD_FACTOR, height * HD_FACTOR), Image.LANCZOS)
            path = HD_DIR / target
            path.parent.mkdir(parents=True, exist_ok=True)
            final.save(path, optimize=True)
    print('wrote', len(names), 'icons in', HD_DIR)


if __name__ == '__main__':
    main()
