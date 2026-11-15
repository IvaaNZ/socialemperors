"""World Editor (point 24 of block E): what the desktop app does, without the window (world_editor.py).

The owner asked for a desktop app to edit mission islands (including the 12 the game lists without a map), the
duel arena and players' villages. All three are the game's village format: privateState, playerInfo and the map
(one "map" in islands and the arena, a "maps" list in players' saves). A map item is
[item id, x, y, orientation, collected at, (level, contained units, attributes)]: x, y is its first tile on the
100 x 100 grid (Config.EI_MAP_WIDTH / HEIGHT) and it covers width x height tiles from the config (swapped when the
orientation is odd, as the game draws a turned building).

Saving keeps a backup of the first version opened in each session (file.bak-YYYYmmdd-HHMMSS). A player's village
lives in the server's memory while it runs, so it is only saved with the server stopped.
"""

import copy
import json
import os
import socket
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
QUESTS_DIR = ROOT / 'villages' / 'quests'
ARENA_FILE = ROOT / 'config' / 'duels' / 'arena.json'
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
TEMPLATE_ISLAND = '100000006'  # a new island starts as a copy of this one, without its items


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
        return cls.open_file(ARENA_FILE, 'arena', 'Arena de duelos')

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
    width, height = footprint(item, catalog)
    return {(int(item[1]) + dx, int(item[2]) + dy) for dx in range(width) for dy in range(height)}


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
    os.chdir(ROOT)  # the game config is read from paths relative to the project
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
