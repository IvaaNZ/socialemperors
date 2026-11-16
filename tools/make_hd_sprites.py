"""Make HD versions of the buildings, decorations and map resources (assets_hd/buildingsprites, not in git).

The owner chose buildings and resources first (units later): the pictures of every building-type item's sprite
(assets/buildingsprites/<img_name>.swf, items of type "b" in the game config) are enlarged like the icons
(swf_hd_icons: Real-ESRGAN 4x with its anime model, reduced to exactly 2x) and the sprite is written again with
them (swf_hd_icons.replace_pictures: same ids, every shape fill rescaled, so nothing moves). Pictures bigger than
MAX_SIDE on a side (the terrain textures) stay as they are: twice their pixels would cost a lot of memory.

It takes hours: it works in batches and skips the sprites already made, so it can be stopped and run again.
Progress goes to assets_hd/progreso.txt.

    .venv/Scripts/python tools/make_hd_sprites.py            # everything still to do
    .venv/Scripts/python tools/make_hd_sprites.py --limit 20 # only 20 sprites (to try)
    .venv/Scripts/python tools/make_hd_sprites.py casa1 molino1
    .venv/Scripts/python tools/make_hd_sprites.py --recursos    # only the map's resources (SE_HD_SPRITES=recursos)
"""

from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import time

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'WorldEditor'))
sys.path.insert(0, str(ROOT / 'tools'))

import sprites  # noqa: E402
from make_hd_icons import ENGINE, MODEL, decode  # noqa: E402
from swf_hd_icons import BITMAP_TAGS, HD_FACTOR, eligible_bitmaps, replace_pictures  # noqa: E402

SOURCE = ROOT / 'assets' / 'buildingsprites'
TARGET = ROOT / 'assets_hd' / 'buildingsprites'
PROGRESS = ROOT / 'assets_hd' / 'progreso.txt'
MAX_SIDE = 1024
BATCH_SPRITES = 25


def building_sprites(resources_only=False):
    import contextlib
    import io
    from swf_hd_icons import resource_sprite_names
    with contextlib.redirect_stdout(io.StringIO()):
        from get_game_config import get_game_config
        items = get_game_config()['items']
    if resources_only:
        names = sorted(resource_sprite_names(items))
    else:
        names = sorted({item['img_name'] for item in items if item.get('type') == 'b'})
    return [SOURCE / f'{name}.swf' for name in names if (SOURCE / f'{name}.swf').exists()]


def pictures_of(path):
    """{id: picture} of a sprite's pictures that can be enlarged."""
    from swf_localization import decode_swf, iter_tags
    raw = path.read_bytes()
    body, header_length = decode_swf(raw)
    eligible = eligible_bitmaps([(code, payload) for code, payload, _ in iter_tags(body, header_length)], own_hd=set())
    data, first = sprites._decode_swf(raw)
    tables, found = None, {}
    for code, start, length in sprites._tags(data, first, len(data)):
        if code == 8:
            tables = data[start:start + length]
            if tables[:4] == b'\xff\xd9\xff\xd8':
                tables = tables[4:]
        elif code in BITMAP_TAGS:
            character_id = struct.unpack_from('<H', data, start)[0]
            if character_id in eligible:
                picture = decode(code, data, start, length, tables)
                if picture is not None and max(picture.size) <= MAX_SIDE:
                    found[character_id] = picture
    return found


def log(text):
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {text}"
    print(line, flush=True)
    PROGRESS.parent.mkdir(parents=True, exist_ok=True)
    with open(PROGRESS, 'a', encoding='utf-8') as stream:
        stream.write(line + '\n')


def run_batch(batch):
    """Enlarge the pictures of some sprites in one Real-ESRGAN run and write their HD sprites."""
    jobs = []  # (sprite path, {id: picture})
    for path in batch:
        try:
            jobs.append((path, pictures_of(path)))
        except Exception as error:  # a sprite this reader does not understand: copied as it is
            log(f'  {path.name}: no se pudo leer ({error}); queda el original')
            jobs.append((path, {}))
    with tempfile.TemporaryDirectory() as folder:
        inbox, outbox = Path(folder) / 'in', Path(folder) / 'out'
        inbox.mkdir()
        outbox.mkdir()
        names = {}
        for number, (path, pictures) in enumerate(jobs):
            for character_id, picture in pictures.items():
                name = f'{number:03d}_{character_id}.png'
                names[name] = (number, character_id, picture.size)
                picture.save(inbox / name)
        if names:
            result = subprocess.run([str(ENGINE), '-i', str(inbox), '-o', str(outbox), '-n', MODEL, '-f', 'png'],
                                    cwd=ENGINE.parent, capture_output=True, text=True)
            if result.returncode != 0:
                raise SystemExit(result.stderr[-2000:])
        enlarged = {}
        for name, (number, character_id, (width, height)) in names.items():
            picture = Image.open(outbox / name).convert('RGBA')
            enlarged.setdefault(number, {})[character_id] = picture.resize(
                (width * HD_FACTOR, height * HD_FACTOR), Image.LANCZOS)
        for number, (path, pictures) in enumerate(jobs):
            target = TARGET / path.name
            temporary = target.with_name(target.name + '.tmp')
            data = path.read_bytes()
            if enlarged.get(number):
                data = replace_pictures(data, enlarged[number])
            temporary.write_bytes(data)
            temporary.replace(target)
    return sum(len(pictures) for _, pictures in jobs)


def main():
    import os
    os.chdir(ROOT)
    if not ENGINE.exists():
        raise SystemExit(f'Real-ESRGAN is missing: {ENGINE}')
    arguments = sys.argv[1:]
    limit = None
    resources_only = '--recursos' in arguments
    arguments = [argument for argument in arguments if argument != '--recursos']
    if arguments[:1] == ['--limit']:
        limit, arguments = int(arguments[1]), arguments[2:]
    todo = [SOURCE / f'{name}.swf' for name in arguments] if arguments else building_sprites(resources_only)
    TARGET.mkdir(parents=True, exist_ok=True)
    todo = [path for path in todo if not (TARGET / path.name).exists()]
    if limit:
        todo = todo[:limit]
    log(f'{len(todo)} edificios por hacer')
    started, done, pictures = time.time(), 0, 0
    for index in range(0, len(todo), BATCH_SPRITES):
        batch = todo[index:index + BATCH_SPRITES]
        pictures += run_batch(batch)
        done += len(batch)
        elapsed = time.time() - started
        left = elapsed / done * (len(todo) - done)
        log(f'{done}/{len(todo)} edificios, {pictures} imágenes; faltan unos {left / 60:.0f} min')
    log('terminado')


if __name__ == '__main__':
    main()
