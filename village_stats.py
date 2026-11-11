"""Read-only unit and mission statistics for the administration pages.

Units are counted where the game keeps them: placed on any of the village's
maps, sheltered inside a building (the item's seventh field lists unit ids),
and stored in the warehouse (privateState.gifts holds a count per item id).
Missions come from privateState.completedMissions and rewardedMissions. Names
use the game config in the viewer's language. Nothing here changes a save.
"""

from collections import Counter
from functools import lru_cache

from get_game_config import get_game_config

RECENT_MISSIONS = 8
TOP_UNITS = 5


def _number(value):
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


@lru_cache(maxsize=None)
def _catalog(language):
    config = get_game_config(language)
    items = {}
    for item in config.get('items', []):
        item_id = _number(item.get('id'))
        if item_id is not None:
            items[item_id] = item
    missions = {}
    for mission in config.get('missions', []):
        mission_id = _number(mission.get('id'))
        if mission_id is not None:
            missions[mission_id] = mission.get('title') or str(mission_id)
    return items, missions


def _unit_kind(item):
    groups = set(str(item.get('groups', '')).split())
    if 'worker' in groups:
        return 'worker'
    if 'healer' in groups:
        return 'healer'
    if (_number(item.get('attack')) or 0) <= 0:
        return 'animal'  # Cows, horses and other units that never fight.
    return 'combat'


def unit_stats(save, language='en'):
    """Units of one village by type, with where they are and their totals."""
    items, _ = _catalog(language)
    on_map, sheltered, stored = Counter(), Counter(), Counter()

    def unit(item_id):
        item = items.get(_number(item_id))
        return item if item and item.get('type') == 'u' else None

    for game_map in save.get('maps', []):
        for placed in game_map.get('items', []) if isinstance(game_map, dict) else []:
            if not isinstance(placed, list) or not placed:
                continue
            if unit(placed[0]):
                on_map[_number(placed[0])] += 1
            if len(placed) > 6 and isinstance(placed[6], list):
                for inside in placed[6]:
                    if unit(inside):
                        sheltered[_number(inside)] += 1
    gifts = save.get('privateState', {}).get('gifts', [])
    for item_id, count in enumerate(gifts if isinstance(gifts, list) else []):
        count = _number(count)
        if count and count > 0 and unit(item_id):
            stored[item_id] += count

    rows = []
    totals = Counter()
    for item_id in set(on_map) | set(sheltered) | set(stored):
        item = items[item_id]
        total = on_map[item_id] + sheltered[item_id] + stored[item_id]
        kind = _unit_kind(item)
        rows.append({'id': item_id, 'name': item.get('name') or str(item_id), 'kind': kind,
                     'on_map': on_map[item_id], 'sheltered': sheltered[item_id], 'stored': stored[item_id],
                     'total': total})
        totals['units'] += total
        totals[kind] += total
        totals['stored'] += stored[item_id]
    rows.sort(key=lambda row: (-row['total'], row['name']))
    return {'units': rows, 'types': len(rows),
            'totals': {key: totals[key] for key in ('units', 'combat', 'worker', 'healer', 'animal', 'stored')}}


def _mission_ids(values):
    seen = []
    for value in values if isinstance(values, list) else []:
        number = _number(value)
        if number is not None and number not in seen:
            seen.append(number)
    return seen


def mission_stats(save, language='en'):
    """Completed, rewarded and pending missions of one village."""
    _, missions = _catalog(language)
    private = save.get('privateState', {})
    completed = _mission_ids(private.get('completedMissions'))
    rewarded = set(_mission_ids(private.get('rewardedMissions')))
    pending = [mission_id for mission_id in completed if mission_id not in rewarded]

    def named(ids):
        return [{'id': mission_id, 'name': missions.get(mission_id, str(mission_id))} for mission_id in ids]

    total = len(missions)
    return {
        'completed': len(completed), 'rewarded': len(rewarded & set(completed)), 'total': total,
        'percent': round(100 * len(completed) / total) if total else 0,
        'pending_rewards': named(pending),
        'recent': named(list(reversed(completed))[:RECENT_MISSIONS]),
    }


def village_stats(save, language='en'):
    return {'units': unit_stats(save, language), 'missions': mission_stats(save, language)}


def summary(stats_list):
    """Totals across villages for the administration overview."""
    units = Counter()
    names = {}
    totals = Counter()
    completed = []
    for stats in stats_list:
        for row in stats['units']['units']:
            if row['kind'] == 'combat':  # The ranking shows troops only.
                units[row['id']] += row['total']
                names[row['id']] = row['name']
        for key, value in stats['units']['totals'].items():
            totals[key] += value
        completed.append(stats['missions']['completed'])
    top = [{'id': item_id, 'name': names[item_id], 'total': count}
           for item_id, count in sorted(units.items(), key=lambda pair: (-pair[1], names[pair[0]]))[:TOP_UNITS]]
    return {
        'villages': len(stats_list), 'units': totals['units'], 'combat': totals['combat'],
        'worker': totals['worker'], 'healer': totals['healer'], 'animal': totals['animal'], 'top_units': top,
        'missions_average': round(sum(completed) / len(completed), 1) if completed else 0,
        'missions_best': max(completed, default=0),
    }
