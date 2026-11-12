"""Build the duel arena map (config/duels/arena.json) from an adventure map.

The tournament arena of the original game (map 100000040) was never
published. The game places the two armies itself, at tiles (10, 59) and
(90, 59) (MapInitializer.spawnTournament), facing each other across the map,
so the arena only needs open ground: this copies a one-island adventure map
(the ground, size and island layout) and removes every item from it.

Usage: python tools/make_arena.py [template quest id] [output path]
"""
import copy
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = sys.argv[1] if len(sys.argv) > 1 else '100000002'
OUTPUT = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / 'config' / 'duels' / 'arena.json'
ARENA_ID = '100000040'
NAME = 'Arena'


def build(template):
    arena = copy.deepcopy(template)
    info = arena['playerInfo']
    info.update(pid=ARENA_ID, name=NAME, pic='', cash='0', map_names=[NAME] * len(info.get('map_names', [NAME])))
    private = arena['privateState']
    private['maps'] = [{'r': 'h', 's': 1, 'n': NAME}]
    for key in ('attacksSent', 'attacksReceived', 'spyings', 'gifts', 'neighborAssists'):
        private[key] = []
    town = arena['map']
    town.update(id='0', items=[], coins='0', stone='0', wood='0', food='0', xp=0, level='1', race='h')
    arena['neighbors'] = []
    return arena


if __name__ == '__main__':
    source = ROOT / 'villages' / 'quests' / f'{TEMPLATE}.json'
    arena = build(json.loads(source.read_text(encoding='utf-8')))
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(arena, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    print(f'Arena written to {OUTPUT} (template {TEMPLATE}, {len(arena["map"]["expansions"])} island)')
