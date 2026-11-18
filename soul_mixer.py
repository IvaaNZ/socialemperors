"""The Soul Mixer's rules (SE_SOUL_MIXER): two units in, one new unit out after a wait.

The game this server runs (0.9.26b) sells the Soul Mixer (building 1529) but has neither its window nor its rules;
the later version that had them is not available, and its content tables (each unit's rank and wait, the power-up
prices) were never preserved. The tables here, config/soulmixer_wiki.json, come from the fork
github.com/TamalAdebisi/socialemperors (GPL-3.0, like this project), which rebuilt them from the Social Empires Tips
Wiki's "Soul Mixer Combinations" page; the mixing rules follow its notes on the later original (its
docs/original/rules/soul-mixer.md), written again here for this server. DECISIONS.md, 18 November 2026.

The owner's choices (18 November 2026):
  * the two units ("parents") are used up: two in, one out;
  * finishing a mix early costs 1 cash for every hour (or part of one) still to wait, like the original;
  * the new unit goes to the gifts ("Regalos"), like the season pass's units;
  * one Soul Mixer per village (the game's own units_limit, in config/patch/soulmixer_temp.json), bought in the shop.

How a mix goes (all of it kept in the save, privateState['soulMixer']):
  1. the player picks two units standing in the village where the Soul Mixer is (two of the same kind are fine);
     the server rolls the result, shown as a silhouette ('preview'). Picking again rolls again, as in the original;
  2. power-ups (optional): each moves the result up, for the cash price of its tier (1, 2, 3 ... 7, then 7 each);
     they are paid when the mix starts;
  3. start: the power-ups are paid, the two parents leave the village and the wait begins ('mix');
  4. when the wait is over (or paid away), "Get unit" puts the new unit in the gifts.
Steps 3 and 4 and the speed-up change the village while the game is open: they raise 'changes', which is part of
the village's revision (server.village_revision), and the page asks to reload the game, as the season pass does.
"""

import json
import math
import random as _random
import time
from pathlib import Path

BUILDING = 1529
TABLES_FILE = Path(__file__).resolve().parent / 'config' / 'soulmixer_wiki.json'
# Galaxy, Rainbow, Crystal and Infernal Dragons: below level 20 they can be neither mixed nor a result.
LEGACY_DRAGONS = frozenset({2048, 2037, 777, 758})
LEGACY_LEVEL = 20
TOP_RANK = 400  # from here on (gods, colossi, the newest dragons) the original rolls a random result
UNITS_INSIDE = 6  # a placed building's list of the units sheltered in it


class MixerError(Exception):
    """A refused action; `code` names it for the page's text."""

    def __init__(self, code, **values):
        super().__init__(code)
        self.code = code
        self.values = values


class Tables:
    """The ranked units and the power-up prices."""

    def __init__(self, units, powerups, min_level):
        # units: [(item id, rank, seconds)], any order; powerups: [(cash, increment)] by tier
        self.units = sorted(units, key=lambda row: (row[1], row[0]))
        self.order = {unit: rank for unit, rank, _ in self.units}
        self.seconds = {unit: seconds for unit, _, seconds in self.units}
        self.powerups = list(powerups)
        self.min_level = int(min_level)
        if len(self.units) < 3 or not self.powerups or self.min_level < 1:
            raise ValueError('incomplete Soul Mixer tables')

    @classmethod
    def load(cls, items, path=TABLES_FILE):
        """The file's tables, keeping only the units the game config has (`items`: {id: config item})."""
        data = json.loads(Path(path).read_text(encoding='utf-8'))
        units = []
        for key, row in data['units'].items():
            item = items.get(int(key))
            if item and item.get('type') == 'u':
                units.append((int(key), int(row['breeding_order']), int(row['sm_training_time'])))
        globals_ = data['globals']
        powerups = [(int(row['cash_cost']), int(row['order_increment']))
                    for row in globals_['SOUL_MIXER_POWERUPS_LEVELS']['value']]
        return cls(units, powerups, globals_['SOUL_MIXER_MIN_LEVEL']['value'])

    def index_at(self, rank, excluded):
        """The first unit at least that rank that is not excluded; the last unit when none is (the original's)."""
        for index, (unit, order, _) in enumerate(self.units):
            if order >= rank and unit not in excluded:
                return index
        return len(self.units) - 1

    def top_roll(self, rand):
        return int(TOP_RANK + rand.random() * (self.units[-1][1] - TOP_RANK))

    def roll(self, parents, rand, excluded=()):
        """The original's result of two souls: 30 % of the weaker rank and 70 % of the stronger, plus 0 to 11."""
        ranks = [self.order[parent] for parent in parents]
        rank = max(10, math.ceil(min(ranks) * 0.3 + max(ranks) * 0.7)) + rand.randrange(12)
        if rank == max(ranks):
            rank += 1
        if rank > TOP_RANK:
            rank = self.top_roll(rand)
        return self.units[self.index_at(rank, set(parents) | set(excluded))][0]

    def powerup_price(self, upgrades):
        """The cash of the next power-up after `upgrades` of them."""
        return self.powerups[min(upgrades, len(self.powerups) - 1)][0]

    def powerups_cost(self, upgrades):
        return sum(self.powerup_price(level) for level in range(upgrades))

    def power_up(self, unit, upgrades, excluded, rand):
        """The result one power-up later, or None when no unit is left above it."""
        excluded = set(excluded) | {unit}
        if self.order[unit] >= TOP_RANK:
            index = self.index_at(self.top_roll(rand), excluded)
        else:
            index = (self.index_at(self.order[unit], excluded)
                     + self.powerups[min(upgrades + 1, len(self.powerups) - 1)][1])
            while index < len(self.units) and self.units[index][0] in excluded:
                index += 1
        if index >= len(self.units) or self.units[index][0] in excluded:
            return None
        return self.units[index][0]


def _number(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


class SoulMixer:
    """One village's Soul Mixer. `items`: {id: config item}; `now`: seconds; `rand`: random.Random."""

    def __init__(self, save, tables, items, now=None, rand=None):
        self.save = save
        self.tables = tables
        self.items = items
        self.now = int(time.time() if now is None else now)
        self.rand = rand or _random.Random()
        private = save.setdefault('privateState', {})
        state = private.get('soulMixer')
        if not isinstance(state, dict):
            state = private['soulMixer'] = {}
        self.state = state

    # ---- the village
    def town(self):
        """The village (map) that has a Soul Mixer, or None."""
        for town in self.save.get('maps') or []:
            if any(isinstance(row, list) and row and _number(row[0]) == BUILDING for row in town.get('items', [])):
                return town
        return None

    def level(self, town):
        return _number(town.get('level'), 1)

    def cash(self):
        return _number(self.save.get('playerInfo', {}).get('cash'))

    def _pay(self, cash):
        info = self.save.setdefault('playerInfo', {})
        info['cash'] = self.cash() - cash

    def _own(self, town, item):
        return item.get('race') in (town.get('race', 'h'), 'a')

    def eligible(self, town):
        """{unit id: how many} of the player's units standing in the village that can be mixed."""
        counts = {}
        legacy_ok = self.level(town) >= LEGACY_LEVEL
        for row in town.get('items', []):
            if not isinstance(row, list) or not row:
                continue
            unit = _number(row[0], -1)
            item = self.items.get(unit)
            if (unit in self.tables.order and item and self._own(town, item)
                    and (legacy_ok or unit not in LEGACY_DRAGONS)):
                counts[unit] = counts.get(unit, 0) + 1
        return counts

    def owned(self, town, unit):
        """How many of that unit the village has, standing or sheltered (for the result's units_limit)."""
        total = 0
        for row in town.get('items', []):
            if not isinstance(row, list) or not row:
                continue
            total += _number(row[0], -1) == unit
            if len(row) > UNITS_INSIDE and isinstance(row[UNITS_INSIDE], list):
                total += sum(_number(inside, -1) == unit for inside in row[UNITS_INSIDE])
        return total

    def _remove(self, town, unit):
        items = town['items']
        for index, row in enumerate(items):
            if isinstance(row, list) and row and _number(row[0], -1) == unit:
                del items[index]
                return
        raise MixerError('parents_gone')

    # ---- the state
    def mix(self):
        mix = self.state.get('mix')
        return mix if isinstance(mix, dict) else None

    def preview(self):
        preview = self.state.get('preview')
        return preview if isinstance(preview, dict) else None

    def remaining(self):
        mix = self.mix()
        if not mix:
            return None
        started = _number(mix.get('started'))
        return 0 if started <= 0 else max(0, started + _number(mix.get('seconds')) - self.now)

    def speed_up_price(self):
        remaining = self.remaining()
        return math.ceil(remaining / 3600) if remaining else 0

    def changes(self):
        return _number(self.state.get('changes'))

    def _changed(self):
        self.state['changes'] = self.changes() + 1

    def _need_mixer(self):
        town = self.town()
        if town is None:
            raise MixerError('no_mixer')
        if self.level(town) < self.tables.min_level:
            raise MixerError('level', level=self.tables.min_level)
        return town

    def _need_free(self):
        if self.mix():
            raise MixerError('busy')

    # ---- the actions
    def choose(self, first, second):
        """Pick two souls: the result is rolled (and shown as a silhouette)."""
        town = self._need_mixer()
        self._need_free()
        parents = [_number(first, -1), _number(second, -1)]
        counts = self.eligible(town)
        for parent in set(parents):
            if counts.get(parent, 0) < parents.count(parent):
                raise MixerError('not_owned')
        excluded = set() if self.level(town) >= LEGACY_LEVEL else set(LEGACY_DRAGONS)
        unit = self.tables.roll(parents, self.rand, excluded)
        self.state['preview'] = {'parents': parents, 'unit': unit, 'upgrades': 0,
                                 'excluded': sorted(set(parents) | excluded | {unit})}
        return self.state['preview']

    def clear(self):
        self.state.pop('preview', None)

    def power_up(self):
        """One power-up: the result moves up. Paid at the start, so the cash must cover them all."""
        self._need_mixer()
        self._need_free()
        preview = self.preview()
        if not preview:
            raise MixerError('no_preview')
        upgrades = _number(preview.get('upgrades'))
        if self.cash() < self.tables.powerups_cost(upgrades + 1):
            raise MixerError('cash')
        unit = self.tables.power_up(preview['unit'], upgrades, preview.get('excluded', []), self.rand)
        if unit is None:
            raise MixerError('no_more')
        preview.update(unit=unit, upgrades=upgrades + 1, excluded=sorted(set(preview.get('excluded', [])) | {unit}))
        return preview

    def start(self):
        town = self._need_mixer()
        self._need_free()
        preview = self.preview()
        if not preview:
            raise MixerError('no_preview')
        parents, unit = [int(parent) for parent in preview['parents']], int(preview['unit'])
        counts = self.eligible(town)
        for parent in set(parents):
            if counts.get(parent, 0) < parents.count(parent):
                raise MixerError('parents_gone')
        limit = _number(self.items.get(unit, {}).get('units_limit'))
        if limit and self.owned(town, unit) >= limit:
            raise MixerError('limit')
        cost = self.tables.powerups_cost(_number(preview.get('upgrades')))
        if self.cash() < cost:
            raise MixerError('cash')
        for parent in parents:  # their souls go into the new unit: they do not come back
            self._remove(town, parent)
        self._pay(cost)
        self.state['mix'] = {'parents': parents, 'unit': unit, 'started': self.now,
                             'seconds': self.tables.seconds[unit], 'powerups': _number(preview.get('upgrades'))}
        self.clear()
        self._changed()
        return self.state['mix']

    def speed_up(self):
        if not self.mix():
            raise MixerError('no_mix')
        price = self.speed_up_price()
        if not price:
            raise MixerError('ready')
        if self.cash() < price:
            raise MixerError('cash')
        self._pay(price)
        self.state['mix']['started'] = 0
        self._changed()
        return price

    def collect(self):
        """Get unit: the new unit goes to the gifts."""
        mix = self.mix()
        if not mix:
            raise MixerError('no_mix')
        if self.remaining():
            raise MixerError('not_ready')
        unit = int(mix['unit'])
        gifts = self.save.setdefault('privateState', {}).setdefault('gifts', [])
        while len(gifts) <= unit:
            gifts.append(0)
        gifts[unit] = _number(gifts[unit]) + 1
        self.state.pop('mix', None)
        self._changed()
        return unit


def revision(save):
    """'sm<n>' once the Soul Mixer changed the village (part of server.village_revision), else ''."""
    state = (save.get('privateState') or {}).get('soulMixer')
    changes = _number(state.get('changes')) if isinstance(state, dict) else 0
    return f'sm{changes}' if changes else ''
