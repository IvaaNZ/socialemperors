"""World Editor (point 24 of block E): what the desktop app does, without the window (WorldEditor/world_editor.py).

The owner asked for a desktop app to edit mission islands (including the 12 the game lists without a map), the
duel arena and players' villages. All three are the game's village format: privateState, playerInfo and the map
(one "map" in islands and the arena, a "maps" list in players' saves). A map item is
[item id, x, y, orientation, collected at, (level, contained units, attributes)] on the 100 x 100 grid
(Config.EI_MAP_WIDTH / HEIGHT). x, y is the item's LAST tile: it covers width x height tiles (from the config,
swapped when the orientation is odd) going back from there, x - width + 1 .. x and y - height + 1 .. y, as
Base.setOccupiedGrid marks them (it counts tx down).

Saving keeps a backup of the first version opened in each session (file.bak-YYYYmmdd-HHMMSS). A player's village
lives in the server's memory while it runs, so it is only saved with the server stopped.
"""

import copy
import json
import os
import re
import socket
import sys
import time
from pathlib import Path

# The project: this file (or "WorldEditor.exe") lives in its WorldEditor folder.
FROZEN = bool(getattr(sys, 'frozen', False))
ROOT = (Path(sys.executable) if FROZEN else Path(__file__)).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))  # the game's config and texts are read with the server's own modules
QUESTS_DIR = ROOT / 'villages' / 'quests'
ARENA_FILE = ROOT / 'config' / 'duels' / 'arena.json'  # the tournament arena (and the duels' when there is no PvP one)
ARENAS_DIR = ROOT / 'config' / 'duels' / 'arenas'  # PvP arenas: each duel is fought on one of them, at random
# The players' saves: the same folder the server uses (SOCIAL_EMPIRES_SAVES_DIR or SOCIAL_EMPIRES_DATA_DIR/saves).
SAVES_DIR = Path(os.environ.get('SOCIAL_EMPIRES_SAVES_DIR')
                 or (Path(os.environ['SOCIAL_EMPIRES_DATA_DIR']) / 'saves' if os.environ.get('SOCIAL_EMPIRES_DATA_DIR')
                     else ROOT / 'saves'))
MAP_SIZE = 100  # Config.EI_MAP_WIDTH / EI_MAP_HEIGHT

# Every mission island the game knows (Constants.QUEST_*), in id order, with a readable name.
QUEST_ISLANDS = {
    '100000002': 'Jefe Yeti (Ártica)', '100000003': 'Jefe Gólem (Desierto)', '100000005': 'Barco viejo',
    '100000006': 'Isla de trolls 1', '100000007': 'Isla de trolls 2', '100000008': 'Isla de trolls 3',
    '100000009': 'Barco', '100000011': 'Jefe Gusano (Mineral)', '100000012': 'Isla de trolls 4',
    '100000013': 'Isla asiática', '100000014': 'Isla azteca', '100000015': 'Isla humana',
    '100000016': 'Barco 2', '100000018': 'Isla de héroes', '100000019': 'Isla humana 2',
    '100000020': 'Isla kamikaze', '100000021': 'Isla vikinga', '100000022': 'Isla egipcia',
    '100000023': 'Atlántida', '100000024': 'Isla Ruben', '100000025': 'Isla Kaspar', '100000026': 'Isla del huevo 2',
    '100000027': 'Isla del huevo 1', '100000028': 'Jefe Dragón 1', '100000033': 'Jefe Dragón 2',
    '100000035': 'Supervivencia 1', '100000036': 'Supervivencia 2', '100000037': 'Supervivencia 3',
    '100000038': 'Supervivencia 4', '100000039': 'Supervivencia 5', '100000041': 'Difícil 1',
    '100000042': 'Difícil 2', '100000043': 'Difícil 3', '100000044': 'Difícil 4', '100000045': 'Difícil 5',
    '100000046': 'Inferno 1', '100000047': 'Inferno 2', '100000048': 'Inferno 3', '100000049': 'Inferno 4',
    '100000090': 'Dioses 1', '100000091': 'Dioses 2', '100000092': 'Dioses 3',
}
TEMPLATE_ISLAND = '100000006'
ARENA_FILE_NAME = re.compile(r'^[a-z0-9][a-z0-9_-]{0,63}$')  # the names the server accepts (duels_web.ARENA_NAME)  # a new island starts as a copy of this one, without its items


class EditorError(ValueError):
    """Something the editor refuses to do (the window shows the message)."""


def server_running(port=None, host='127.0.0.1'):
    """True when something answers on the server's port (the game server keeps villages in memory)."""
    port = int(port or os.environ.get('PORT') or 5050)
    try:
        with socket.create_connection((host, port), timeout=0.3):
            return True
    except OSError:
        return False


def quest_islands():
    """[(id, name, has a map)] of every island the game knows, then the other island files of the folder."""
    out = [(qid, name, (QUESTS_DIR / f'{qid}.json').exists()) for qid, name in QUEST_ISLANDS.items()]
    for path in sorted(QUESTS_DIR.glob('*.json')):
        if path.stem not in QUEST_ISLANDS and path.stem.isdigit():
            out.append((path.stem, f'Isla extra {path.stem}', True))
    return out


def pvp_arenas(folder=None):
    """[(path, name)] of the PvP arenas, by name."""
    out = []
    for path in sorted(Path(folder or ARENAS_DIR).glob('*.json')):
        if not ARENA_FILE_NAME.match(path.stem):
            continue
        try:
            name = json.loads(path.read_text(encoding='utf-8'))['playerInfo'].get('name') or path.stem
        except (OSError, ValueError, KeyError, TypeError):
            continue
        out.append((path, name))
    return sorted(out, key=lambda pair: str(pair[1]).lower())


def arena_file_name(name, folder=None):
    """A free file name (letters, numbers and dashes, as the server accepts) for a new PvP arena."""
    import unicodedata
    plain = unicodedata.normalize('NFKD', str(name)).encode('ascii', 'ignore').decode().lower()
    stem = re.sub(r'[^a-z0-9]+', '-', plain).strip('-')[:50] or 'arena'
    folder = Path(folder or ARENAS_DIR)
    candidate, number = stem, 2
    while (folder / f'{candidate}.json').exists():
        candidate, number = f'{stem}-{number}', number + 1
    return candidate


def delete_arena(path):
    """Removes a PvP arena from the duels; its file is kept as a backup (name.json.bak-YYYYmmdd-HHMMSS)."""
    path = Path(path)
    if path.parent.resolve() != Path(ARENAS_DIR).resolve() or path.suffix != '.json':
        raise EditorError('Solo se pueden borrar arenas PvP')
    backup = path.with_name(f"{path.name}.bak-{time.strftime('%Y%m%d-%H%M%S')}")
    os.replace(path, backup)
    return backup


def player_villages(folder=None):
    """[(path, empire name, level)] of the players' saves."""
    out = []
    for path in sorted(Path(folder or SAVES_DIR).glob('*.save.json')):
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
            names = data['playerInfo'].get('map_names') or ['']
            out.append((path, names[0], int(data['maps'][0].get('level') or 0)))
        except (OSError, ValueError, KeyError, IndexError, TypeError):
            continue
    return out


class Document:
    """One open village file: its data, which map is edited, and what changed."""

    def __init__(self, path, data, kind, title, map_index=0):
        self.path, self.data, self.kind, self.title = Path(path), data, kind, title
        self.map_index = map_index
        self.dirty = False
        self.backed_up = False
        self.history = []
        self.indent = None  # the file's own layout, kept when saving: islands are one line, saves use 4 spaces
        self.escaped_slashes = False
        self.newline = '\n'

    # --- opening ---
    @classmethod
    def open_file(cls, path, kind, title=None):
        path = Path(path)
        text = path.read_bytes().decode('utf-8')  # bytes: line endings as they are in the file
        data = json.loads(text)
        if not isinstance(data, dict) or not ('map' in data or 'maps' in data):
            raise EditorError(f'{path.name} no es una aldea del juego')
        doc = cls(path, data, kind, title or path.stem)
        doc.indent = layout_of(text)
        doc.escaped_slashes = '\\/' in text  # the original islands were written by PHP: "http:\/\/..."
        doc.newline = '\r\n' if '\r\n' in text else '\n'
        return doc

    @classmethod
    def open_island(cls, quest_id):
        quest_id = str(quest_id)
        path = QUESTS_DIR / f'{quest_id}.json'
        if path.exists():
            return cls.open_file(path, 'island', QUEST_ISLANDS.get(quest_id, f'Isla extra {quest_id}'))
        if quest_id not in QUEST_ISLANDS:
            raise EditorError(f'El juego no tiene la isla {quest_id}')
        return cls.new_island(quest_id)

    @classmethod
    def new_island(cls, quest_id):
        """An island the game lists without a map: a copy of the template's settings, with no items."""
        template = json.loads((QUESTS_DIR / f'{TEMPLATE_ISLAND}.json').read_text(encoding='utf-8'))
        data = copy.deepcopy(template)
        data['map']['items'] = []
        data['playerInfo']['pid'] = str(quest_id)
        data['playerInfo']['name'] = QUEST_ISLANDS.get(str(quest_id), 'Isla')
        data['playerInfo']['pic'] = ''
        doc = cls(QUESTS_DIR / f'{quest_id}.json', data, 'island', QUEST_ISLANDS.get(str(quest_id), str(quest_id)))
        doc.dirty = True
        return doc

    @classmethod
    def open_arena(cls):
        """The tournament arena (also the duels' while there is no PvP arena)."""
        return cls.open_file(ARENA_FILE, 'arena', 'Arena de torneos')

    @classmethod
    def open_pvp_arena(cls, path):
        doc = cls.open_file(path, 'pvp')
        doc.title = doc.data['playerInfo'].get('name') or doc.path.stem
        return doc

    @classmethod
    def new_arena(cls, name, folder=None):
        """A new PvP arena: the tournament arena's settings and terrain, with no objects. It is written on saving."""
        name = str(name).strip()
        if not name:
            raise EditorError('La arena necesita un nombre')
        folder = Path(folder or ARENAS_DIR)
        template = cls.open_file(ARENA_FILE, 'arena')
        data = copy.deepcopy(template.data)
        data['map']['items'] = []
        data['playerInfo']['name'] = name
        doc = cls(folder / f'{arena_file_name(name, folder)}.json', data, 'pvp', name)
        doc.indent, doc.newline, doc.escaped_slashes = template.indent, template.newline, template.escaped_slashes
        doc.dirty = True
        return doc

    @classmethod
    def open_village(cls, path, map_index=0):
        doc = cls.open_file(path, 'village')
        names = doc.data['playerInfo'].get('map_names') or [doc.path.stem]
        doc.title = names[0] or doc.path.stem
        doc.select_map(map_index)
        return doc

    # --- the edited map ---
    @property
    def maps(self):
        return self.data['maps'] if 'maps' in self.data else [self.data['map']]

    def select_map(self, index):
        if not 0 <= int(index) < len(self.maps):
            raise EditorError(f'La aldea no tiene la isla {index}')
        self.map_index = int(index)

    @property
    def town(self):
        return self.maps[self.map_index]

    @property
    def items(self):
        return self.town.setdefault('items', [])

    # --- editing ---
    def _remember(self):
        self.history.append(copy.deepcopy(self.items))
        del self.history[:-100]
        self.dirty = True

    def undo(self):
        if not self.history:
            return False
        self.town['items'] = self.history.pop()
        self.dirty = True
        return True

    def add(self, item_id, x, y, orientation=0, now=None):
        x, y = clamp_tile(x), clamp_tile(y)
        self._remember()
        item = [int(item_id), x, y, int(orientation), int(now if now is not None else time.time())]
        self.items.append(item)
        return len(self.items) - 1

    def move(self, index, x, y):
        self._remember()
        self.items[index][1], self.items[index][2] = clamp_tile(x), clamp_tile(y)

    def rotate(self, index):
        self._remember()
        self.items[index][3] = (int(self.items[index][3]) + 1) % 2

    def delete(self, index):
        self._remember()
        return self.items.pop(index)

    def set_name(self, name):
        name = str(name).strip()
        if not name:
            raise EditorError('El nombre no puede quedar vacío')
        self.dirty = True
        if self.kind == 'village':
            self.data['playerInfo'].setdefault('map_names', [''])[0] = name
        else:
            self.data['playerInfo']['name'] = name
        self.title = name

    # --- saving ---
    def dumps(self):
        separators = (',', ':') if self.indent is None else None
        text = json.dumps(self.data, indent=self.indent, separators=separators)
        if self.escaped_slashes:
            text = text.replace('/', '\\/')  # '/' only appears inside strings
        return text.replace('\n', self.newline)  # a JSON string never holds a raw line break

    def save(self, server_up=None):
        if self.kind == 'village' and (server_running() if server_up is None else server_up):
            raise EditorError('El servidor está prendido: guarda las aldeas en memoria y pisaría este cambio. '
                              'Apagalo y volvé a guardar.')
        if self.path.exists() and not self.backed_up:
            stamp = time.strftime('%Y%m%d-%H%M%S')
            backup = self.path.with_name(f'{self.path.name}.bak-{stamp}')
            backup.write_bytes(self.path.read_bytes())
            self.backed_up = True
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(self.path.name + '.tmp')
        temporary.write_bytes(self.dumps().encode('utf-8'))
        os.replace(temporary, self.path)
        self.dirty = False
        return self.path


def layout_of(text):
    """The indent of a JSON file: None when it is all on one line."""
    lines = text.lstrip().splitlines()
    if len(lines) < 2:
        return None
    second = lines[1]
    return len(second) - len(second.lstrip(' ')) or None


def clamp_tile(value):
    return max(0, min(MAP_SIZE - 1, int(value)))


def footprint(item, catalog):
    """(width, height) in tiles of a map item; turned (odd orientation) buildings swap them."""
    entry = catalog.get(int(item[0])) or {}
    width, height = int(entry.get('width') or 1), int(entry.get('height') or 1)
    if len(item) > 3 and int(item[3]) % 2 == 1:
        width, height = height, width
    return width, height


def tiles_of(item, catalog):
    """The tiles an item covers: back from its position (its last tile), as the game marks them."""
    width, height = footprint(item, catalog)
    return {(int(item[1]) - dx, int(item[2]) - dy) for dx in range(width) for dy in range(height)}


def overlapping(items, catalog):
    """Indexes of the items that share a tile with another (units stand anywhere, so they are left out)."""
    owner, clash = {}, set()
    for index, item in enumerate(items):
        if (catalog.get(int(item[0])) or {}).get('type') == 'u':
            continue
        for tile in tiles_of(item, catalog):
            if tile in owner:
                clash.update((owner[tile], index))
            owner[tile] = index
    return clash


def item_at(items, catalog, x, y):
    """Index of the topmost item covering tile (x, y), or None."""
    for index in range(len(items) - 1, -1, -1):
        if (int(x), int(y)) in tiles_of(items[index], catalog):
            return index
    return None


def load_catalog():
    """{item id: config entry} of every item, with its Spanish name when the game has one."""
    import contextlib
    import io
    if not (ROOT / 'config' / 'game_config_20120826.json').exists():
        raise EditorError(f'No se encontró el proyecto del juego en {ROOT}. '
                          'El World Editor tiene que estar en la carpeta WorldEditor del proyecto.')
    os.chdir(ROOT)  # the game config is read from paths relative to the project
    if FROZEN:  # inside the .exe, bundle.py would point at the .exe's temporary folder: use the project's
        import bundle
        bundle.CONFIG_DIR = str(ROOT / 'config')
        bundle.CONFIG_PATCH_DIR = str(ROOT / 'config' / 'patch')
        bundle.MODS_DIR = str(ROOT / 'mods')
    with contextlib.redirect_stdout(io.StringIO()):
        from get_game_config import get_game_config
        config = get_game_config()
    try:
        from localization import load_catalog as texts
        spanish = texts('es') or {}
    except Exception:  # the editor still works with the config's names
        spanish = {}
    catalog = {}
    for entry in config['items']:
        entry = dict(entry)
        entry['label'] = spanish.get(entry.get('name'), entry.get('name'))
        catalog[int(entry['id'])] = entry
    return catalog


# --- the game's perspective (Base.addElement): a tile is 108 x 54 pixels and tile (x, y) has its top corner at
# screen (54 * (x - y), 27 * (x + y)). The editor shifts x by the map width so the whole map is on positive pixels.
HALF_WIDTH, HALF_HEIGHT = 54, 27


def iso_point(x, y):
    """Screen pixel (at scale 1) of the top corner of tile (x, y); fractions give points inside a tile."""
    return HALF_WIDTH * (x - y + MAP_SIZE), HALF_HEIGHT * (x + y)


def iso_tile(px, py):
    """Tile (x, y) under a screen pixel (at scale 1)."""
    across = px / HALF_WIDTH - MAP_SIZE  # x - y
    down = py / HALF_HEIGHT  # x + y
    return int((across + down) // 2), int((down - across) // 2)


def iso_footprint(item, catalog):
    """The four corners (top, right, bottom, left) of an item's base on screen, at scale 1."""
    width, height = footprint(item, catalog)
    x0, y0 = int(item[1]) - width + 1, int(item[2]) - height + 1
    x1, y1 = int(item[1]) + 1, int(item[2]) + 1
    return iso_point(x0, y0), iso_point(x1, y0), iso_point(x1, y1), iso_point(x0, y1)


def depth_order(items, catalog):
    """Indexes in drawing order for the perspective view: farther (smaller x + y of the base's bottom) first,
    and among equals, buildings before units."""
    def key(index):
        item = items[index]
        unit = (catalog.get(int(item[0])) or {}).get('type') == 'u'
        bottom = int(item[1]) + int(item[2]) + (1 if unit else 2)  # a unit stands in the middle of its tile
        return bottom, unit, index
    return sorted(range(len(items)), key=key)


def island_area(items, catalog, margin=3):
    """(x0, y0, x1, y1) of the land to draw: what the items use, at least the centre of the map."""
    x0, y0, x1, y1 = 30, 30, 70, 70
    for item in items:
        width, height = footprint(item, catalog)
        x0, y0 = min(x0, int(item[1]) - width + 1 - margin), min(y0, int(item[2]) - height + 1 - margin)
        x1, y1 = max(x1, int(item[1]) + 1 + margin), max(y1, int(item[2]) + 1 + margin)
    return max(0, x0), max(0, y0), min(MAP_SIZE, x1), min(MAP_SIZE, y1)


# --- terrain: the map is 5 x 5 zones of 20 x 20 tiles (Config.EI_TILES_IN_BIGTILE). A map's "expansions" are the
# zones it owns, numbered 1 to 25 row by row (Base.purchaseLand: column (n - 1) % 5, row (n - 1) / 5). The game
# draws each owned zone with the terrain item 1000 + the map's skin (Base.addExpandedTileBuilding) and fills the
# rest with the skin's background colour (Config.BG_SKIN_COLORS). Mission islands are sand in the sea instead.
ZONE = 20
ZONES_PER_ROW = MAP_SIZE // ZONE
TERRAINS = {  # skin: (name, terrain item's picture, background colour of the rest of the map)
    0: ('Pradera', 'terreno', '#669c2c'),
    1: ('Desierto', 'terrenodesierto', '#eabc4c'),
    2: ('Hielo', 'terrenohielo', '#dfecf2'),
    3: ('Mar', 'terrenomar2', '#2e94e6'),
    4: ('Mineral', 'terrenomineral', '#863814'),
    5: ('Selva', 'terrenoselva', '#398a00'),
    6: ('Nubes', 'terrenonubes', '#ffffff'),
}


def terrain_of(town):
    """(name, picture, background colour) of a map's skin; unknown skins are meadow."""
    try:
        skin = int(town.get('skin') or 0)
    except (TypeError, ValueError):
        skin = 0
    return TERRAINS.get(skin, TERRAINS[0])


def owned_zones(town):
    """[(zone number, first tile x, first tile y)] of the zones a map owns."""
    out = []
    for number in town.get('expansions') or []:
        try:
            number = int(number)
        except (TypeError, ValueError):
            continue
        if 1 <= number <= ZONES_PER_ROW * ZONES_PER_ROW:
            index = number - 1
            out.append((number, (index % ZONES_PER_ROW) * ZONE, (index // ZONES_PER_ROW) * ZONE))
    return out
