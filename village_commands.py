"""Village commands the game sends and the server used to ignore (SE_VILLAGE_COMMANDS, on by default).

Asked by the owner ("que todo funcione correctamente"): these commands were
"Unhandled", so what they did was lost on reload. The arguments and the rules
come from the game's own code (the movie's ActionScript), so the server keeps
the same numbers the game showed:

  * use_magic [spell]: casting costs the spell's mana and counts one use
    (privateState.magics[spell] = uses; MagicSpell.castSpell);
  * buy_magic [spell, town, 1 cash | 0 gold]: the spell is learned
    (magics[spell] = 0) and its first charge of mana comes with it
    (SelectedMagic.updateMagicEntry);
  * buy_mana [town, 1 cash | 0 gold]: MANA_PER_PURCHASE mana for
    COST_MANA_CASH cash or COST_MANA_GOLD gold (PopupBuyMana);
  * level up: from START_LEVEL_MANA_REWARD on, each level gives
    MANA_REWARD_PER_LEVEL mana (MagicManager.onLevelUp). Players who passed
    those levels before this fix get that mana once (grant_missed_level_mana);
  * trade_resource [town, resource, 1 sell | 0 buy, amount]: the market price
    is MARKET_BASE_COSTS[resource] * amount / 100, raised by MARKET_INCREMENT
    for each step of map.resourcesTraded[resource]; selling pays
    MARKET_SELL_PERCENTAGE of it. Buying moves the step up, selling down,
    between -MARKET_MAX_DECREMENTS and MARKET_MAX_INCREMENTS
    (ButtonMarket.refreshCost / onTrade);
  * unlock_building [item]: an early unlock costs ceil(min_level / 3) cash
    (Config.MULTIPLIER_UNLOCK = 1/3) and is kept in
    privateState.unlockedEarlyBuildings (PopupUnlockBuilding.onYes);
  * increase_population [town]: one more population increase in
    map.increasedPopulation (PopupRecruitmentPopulation.onRecruitComplete);
  * place_stored_item / sell_stored_item: an item put in the storage during
    this session is placed or sold like a gift (the server keeps every stored
    item in privateState.gifts, see store_item).
  * unlock_skin [weather]: COST_UNLOCK_SKIN cash, kept in
    privateState.unlockedSkins; set_skin [town, weather]: the island's
    map.skin. The game reloads the map right after, so the server must keep
    them at once (PopupWeather.onUnlock / onApply).

The unit warehouse (building 1284) keeps troops per map in map.warehousedUnits
({unit id: count}) up to map.warehouseAditionalCapacitySingle units
(Base.loadPlayerInfoSuccess):

  * add_unit_warehouse [x, y, town, unit]: the unit leaves the map for the
    warehouse, if there is room (IsoBuilding.pushUnitToWarehause);
  * place_warehoused_item [unit, x, y, 0, town]: it comes back to the map
    (PopupUnitWarehouse.onUseClick);
  * buy_warehouse_capacity_single [town]: one more place for
    WAREHOUSE_CAPACITY_INCREASE_PRICE_SINGLE cash, up to WAREHOUSE_MAX_CAPACITY
    (PopupUnitWarehouse.onBuyMoreSlots);
  * reset_warehouse [town]: the warehouse itself was stored; its units go to
    the storage (Base.storeItem).
"""

import copy
import json
import math
import os

from constants import Constant

TRADE_RESOURCES = {'w': 'wood', 's': 'stone', 'f': 'food'}
CASH, GOLD = 1, 0
UNLOCK_MULTIPLIER = 1 / 3  # the game's Config.MULTIPLIER_UNLOCK
MARKET_MAX_NUM_TRADES = 20  # the game's Config.MARKET_MAX_NUM_TRADES
WAREHOUSE_START_CAPACITY = 20  # map.warehouseAditionalCapacitySingle of the original villages (villages/quests)
# Read by the game; missing, the market shows NaN and the unit warehouse has no room (capacity NaN).
# Missing, the allies' market reads "undefined": it shows cash as its product instead of asking for a resource
# (RecuadroInfo.openAlliesMarket asks only when it is "n").
MAP_DEFAULTS = {'numTradesDone': 0, 'timestampLastTrade': 0,
                'warehouseAditionalCapacitySingle': WAREHOUSE_START_CAPACITY, 'warehousedUnits': {},
                'resourceAlliesMarket': 'n'}

# Weathers (PopupWeather.themeIds); 0 is always available. The popup shows a weather as unlocked when
# unlockedSkins[id] == "true", a string comparison: a JSON true would show it locked again.
SKINS = (0, 1, 2, 4, 5, 6)
DEFAULT_SKIN = 0
SKIN_UNLOCKED = 'true'

VILLAGE_COMMANDS = (Constant.CMD_USE_MAGIC, Constant.CMD_BUY_MAGIC, Constant.CMD_BUY_MANA, Constant.CMD_TRADE_RESOURCE,
                    Constant.CMD_UNLOCK_BUILDING, Constant.CMD_INCREASE_POPULATION, Constant.CMD_PLACE_STORED_ITEM,
                    Constant.CMD_SELL_STORED, Constant.CMD_UNLOCK_SKIN, Constant.CMD_SET_SKIN)


class VillageCommandError(ValueError):
    """A command that cannot be applied (unknown spell, resource...): the save is left as it was."""


def village_commands_enabled():
    return os.environ.get('SE_VILLAGE_COMMANDS', 'on').strip().lower() in ('on', '1', 'true', 'yes')


def _spell(config, spell_id):
    for spell in config.get('magics', []):
        if int(spell['id']) == int(spell_id):
            return spell
    raise VillageCommandError(f'unknown spell {spell_id}')


def _pay(save, town, currency, cash_cost, gold_cost):
    if int(currency) == CASH:
        save['playerInfo']['cash'] = max(save['playerInfo'].get('cash', 0) - int(cash_cost), 0)
    else:
        town['coins'] = max(town.get('coins', 0) - int(gold_cost), 0)


def _town(save, town_id):
    try:
        return save['maps'][int(town_id)]
    except (IndexError, ValueError, TypeError):
        raise VillageCommandError(f'unknown town {town_id}') from None


def level_mana(level, globals_):
    """Mana the game gives for reaching `level` (MagicManager.onLevelUp)."""
    return int(globals_.get('MANA_REWARD_PER_LEVEL', 0)) if int(level) >= int(globals_.get('START_LEVEL_MANA_REWARD', 0)) else 0


def grant_level_mana(save, previous_level, new_level, globals_):
    """Mana for every level passed from previous_level to new_level. Returns the mana given."""
    gained = sum(level_mana(level, globals_) for level in range(int(previous_level) + 1, int(new_level) + 1))
    if gained:
        state = save['privateState']
        state['mana'] = int(state.get('mana', 0)) + gained
    state = save['privateState']
    state['manaRewardLevel'] = max(int(state.get('manaRewardLevel', 0)), int(new_level))
    return gained


def grant_missed_level_mana(save, globals_):
    """Once per save: the level-up mana of the levels reached before the server counted it."""
    state = save.get('privateState')
    if not isinstance(state, dict) or 'manaRewardLevel' in state:
        return 0
    level = int(save['maps'][0].get('level', 0))
    return grant_level_mana(save, 0, level, globals_)


def market_price(globals_, resource, amount, traded, sell):
    base = float(globals_['MARKET_BASE_COSTS'][resource]) * int(amount) / 100
    cost = round(base + base * int(traded) * float(globals_['MARKET_INCREMENT']))
    return round(cost * float(globals_['MARKET_SELL_PERCENTAGE'])) if sell else cost


def fill_map_defaults(save):
    """Map fields the game reads but older saves lack (the market's trades left showed \"NaN\"). Returns True if any was added."""
    added = False
    for town in save.get('maps', []):
        for key, value in MAP_DEFAULTS.items():
            if key not in town or (key == 'warehousedUnits' and town[key] == []):
                town[key] = copy.deepcopy(value)
                added = True
    return added


def apply_village_command(save, cmd, args, config, now=0):
    """Apply one village command to the save. Returns a short description for the log."""
    globals_ = config.get('globals', {})
    state = save['privateState']
    if cmd == Constant.CMD_USE_MAGIC:
        spell = _spell(config, args[0])
        magics = state.setdefault('magics', {})
        key = str(int(spell['id']))
        magics[key] = int(magics.get(key, 0)) + 1
        state['mana'] = max(int(state.get('mana', 0)) - int(spell['mana']), 0)
        return f"cast {spell['name']} (-{spell['mana']} mana, {state['mana']} left)"
    if cmd == Constant.CMD_BUY_MAGIC:
        spell = _spell(config, args[0])
        _pay(save, _town(save, args[1]), args[2], spell['cash'], spell['gold'])
        state.setdefault('magics', {})[str(int(spell['id']))] = 0
        state['mana'] = int(state.get('mana', 0)) + int(spell['mana'])
        return f"learned {spell['name']} with {'cash' if int(args[2]) == CASH else 'gold'}"
    if cmd == Constant.CMD_BUY_MANA:
        _pay(save, _town(save, args[0]), args[1], globals_.get('COST_MANA_CASH', 1), globals_.get('COST_MANA_GOLD', 20000))
        state['mana'] = int(state.get('mana', 0)) + int(globals_.get('MANA_PER_PURCHASE', 5))
        return f"bought mana ({state['mana']})"
    if cmd == Constant.CMD_TRADE_RESOURCE:
        town = _town(save, args[0])
        resource, sell, amount = str(args[1]), int(args[2]) == 1, int(args[3])
        if resource not in TRADE_RESOURCES or amount <= 0:
            raise VillageCommandError(f'cannot trade {amount} {resource}')
        # Trades per market period (Base.processAttacks: numTradesDone starts over MARKET_PERIOD_HOURS after
        # timestampLastTrade, which only the server sets; at most MARKET_MAX_NUM_TRADES, Config: 20).
        now = int(now or 0)
        if now - int(town.get('timestampLastTrade') or 0) > int(globals_.get('MARKET_PERIOD_HOURS', 20)) * 3600:
            town['numTradesDone'] = 0
            town['timestampLastTrade'] = now
        if int(town.get('numTradesDone') or 0) >= MARKET_MAX_NUM_TRADES:
            raise VillageCommandError('no trades left in this market period')
        town['numTradesDone'] = int(town.get('numTradesDone') or 0) + 1
        traded = town.setdefault('resourcesTraded', {})
        if isinstance(traded, list):  # an empty JSON object can come back as []
            traded = town['resourcesTraded'] = {}
        step = int(traded.get(resource, 0))
        price = market_price(globals_, resource, amount, step, sell)
        field = TRADE_RESOURCES[resource]
        if sell:
            town[field] = max(int(town.get(field, 0)) - amount, 0)
            town['coins'] = int(town.get('coins', 0)) + price
        else:
            town[field] = int(town.get(field, 0)) + amount
            town['coins'] = max(int(town.get('coins', 0)) - price, 0)
        step = step - 1 if sell else step + 1
        traded[resource] = max(-int(globals_.get('MARKET_MAX_DECREMENTS', 25)),
                               min(step, int(globals_.get('MARKET_MAX_INCREMENTS', 200))))
        return f"{'sold' if sell else 'bought'} {amount} {field} for {price} gold"
    if cmd == Constant.CMD_UNLOCK_BUILDING:
        from get_game_config import get_item_from_id
        item = get_item_from_id(int(args[0]))
        if not item:
            raise VillageCommandError(f'unknown item {args[0]}')
        cost = math.ceil(int(item.get('min_level') or 0) * UNLOCK_MULTIPLIER)
        save['playerInfo']['cash'] = max(save['playerInfo'].get('cash', 0) - cost, 0)
        unlocked = state.setdefault('unlockedEarlyBuildings', {})
        if isinstance(unlocked, list):
            unlocked = state['unlockedEarlyBuildings'] = {}
        unlocked[str(int(args[0]))] = True
        return f"unlocked {item.get('name')} for {cost} cash"
    if cmd == Constant.CMD_INCREASE_POPULATION:
        town = _town(save, args[0])
        town['increasedPopulation'] = int(town.get('increasedPopulation', 0)) + 1
        return f"population increase {town['increasedPopulation']}"
    if cmd == Constant.CMD_UNLOCK_SKIN:
        skin = _skin(args[0])
        unlocked = _unlocked_skins(state)
        if skin == DEFAULT_SKIN or unlocked.get(str(skin)) == SKIN_UNLOCKED:
            return f'weather {skin} already unlocked'
        cost = int(globals_.get('COST_UNLOCK_SKIN', 20))
        save['playerInfo']['cash'] = max(int(save['playerInfo'].get('cash', 0)) - cost, 0)
        unlocked[str(skin)] = SKIN_UNLOCKED
        return f'weather {skin} unlocked for {cost} cash'
    if cmd == Constant.CMD_SET_SKIN:
        town, skin = _town(save, args[0]), _skin(args[1])
        if skin != DEFAULT_SKIN and _unlocked_skins(state).get(str(skin)) != SKIN_UNLOCKED:
            raise VillageCommandError(f'weather {skin} is locked')
        town['skin'] = skin
        return f'weather {skin} on the island'
    raise VillageCommandError(f'not a village command: {cmd}')


def _skin(value):
    skin = int(value)
    if skin not in SKINS:
        raise VillageCommandError(f'unknown weather {skin}')
    return skin


def _unlocked_skins(state):
    """privateState.unlockedSkins as {id: "true"}; the original villages kept a list ([true] = weather 0)."""
    unlocked = state.get('unlockedSkins')
    if not isinstance(unlocked, dict):
        unlocked = state['unlockedSkins'] = {}
    return unlocked


SOCIAL_COMMANDS = (Constant.CMD_BUY_SI_HELP, Constant.CMD_FINISH_SI)


def social_item(config, item_id):
    """The config's social_items entry (workers to hire) of a building, or None."""
    for entry in config.get('social_items', []):
        if int(entry['id']) == int(item_id):
            return entry
    return None


def start_social_building(item, config):
    """A social building just bought (market, harbor, zeppelin tower...) still needs its workers: the game keeps
    them in the item's attributes as "si" (one entry per hired worker) and opens it when finish_si comes
    (Base.IsBeingBuilt: a social building with attrs.si is still being built)."""
    entry = social_item(config, item[0])
    if entry is None or int(entry.get('worker_cost') or 0) <= 0:
        return False  # no workers to pay for (or friends only): open at once, as before
    while len(item) < 8:
        item.append([] if len(item) == 6 else {})
    if not isinstance(item[7], dict):
        item[7] = {}
    item[7]['si'] = []
    return True


def _placed_item(town, x, y, item_id):
    for item in town.get('items', []):
        if int(item[0]) == int(item_id) and int(item[1]) == int(x) and int(item[2]) == int(y):
            return item
    raise VillageCommandError(f'no item {item_id} at ({x},{y})')


def apply_social_command(save, cmd, args, config):
    """buy_si_help [x, y, town, building(, free)] hires one worker: worker_cost cash, unless the game gives it
    (free = 1, Base.countAllBuildings). finish_si [x, y, town, building] opens the building."""
    town = _town(save, args[2])
    item = _placed_item(town, args[0], args[1], args[3])
    attrs = item[7] if len(item) > 7 and isinstance(item[7], dict) else None
    if cmd == Constant.CMD_BUY_SI_HELP:
        entry = social_item(config, args[3])
        free = len(args) > 4 and int(args[4]) == 1
        cost = 0 if free or entry is None else int(entry.get('worker_cost') or 0)
        save['playerInfo']['cash'] = max(int(save['playerInfo'].get('cash', 0)) - cost, 0)
        if attrs is not None and isinstance(attrs.get('si'), list):
            attrs['si'].append(0)
        return f"worker hired for {cost} cash" + (' (given by the game)' if free else '')
    if cmd == Constant.CMD_FINISH_SI:
        if attrs is not None:
            attrs.pop('si', None)
        return 'social building opened'
    raise VillageCommandError(f'not a social building command: {cmd}')


def buy_unit_with_cash(save, args, now, already_stored=False):
    """A unit paid with cash: trained at once in a building (IsoBuilding.OnTrainingTimer) or bought in the heroes'
    shop (PopupHeroes.onBuyItem). Arguments: [unit, x, y, frame, town].

    It costs the unit's cost_unit_cash and gives its xp. The unit is placed at (x, y), unless the game has just
    put it in the storage in this same batch (no altar: store_add_items comes first), where it already is.
    """
    from get_game_config import get_item_from_id
    unit_id, x, y, town = int(args[0]), int(args[1]), int(args[2]), _town(save, args[4])
    unit = get_item_from_id(unit_id)
    if not unit:
        raise VillageCommandError(f'unknown unit {unit_id}')
    cost = int(unit.get('cost_unit_cash') or 0)
    save['playerInfo']['cash'] = max(int(save['playerInfo'].get('cash', 0)) - cost, 0)
    town['xp'] = int(town.get('xp', 0)) + int(unit.get('xp') or 0)
    if already_stored:
        return f"{unit.get('name')} for {cost} cash, in the storage"
    town.setdefault('items', []).append([unit_id, x, y, 0, now, 0])
    return f"{unit.get('name')} for {cost} cash at ({x},{y})"


WAREHOUSE_COMMANDS = (Constant.CMD_ADD_UNIT_WAREHOUSE, Constant.CMD_PLACE_WAREHOUSED_ITEM,
                      Constant.CMD_BUY_WAREHOUSE_CAPACITY_NEW, Constant.CMD_RESET_WAREHOUSE)


def _warehouse(town):
    units = town.get('warehousedUnits')
    if not isinstance(units, dict):
        units = town['warehousedUnits'] = {}
    return units


def _add_gift(save, item_id, count=1):
    gifts = save['privateState'].setdefault('gifts', [])
    while len(gifts) <= item_id:
        gifts.append(0)
    gifts[item_id] += count


def apply_warehouse_command(save, cmd, args, config, now=0):
    """Apply one unit warehouse command. Returns a short description for the log."""
    globals_ = config.get('globals', {})
    if cmd == Constant.CMD_ADD_UNIT_WAREHOUSE:
        x, y, town, unit_id = int(args[0]), int(args[1]), _town(save, args[2]), int(args[3])
        units = _warehouse(town)
        capacity = int(town.get('warehouseAditionalCapacitySingle', WAREHOUSE_START_CAPACITY))
        if sum(int(n) for n in units.values()) >= capacity:
            raise VillageCommandError(f'the unit warehouse is full ({capacity})')
        town['items'].remove(_placed_item(town, x, y, unit_id))
        units[str(unit_id)] = int(units.get(str(unit_id), 0)) + 1
        return f'unit {unit_id} into the warehouse ({units[str(unit_id)]} of it)'
    if cmd == Constant.CMD_PLACE_WAREHOUSED_ITEM:
        unit_id, x, y, town = int(args[0]), int(args[1]), int(args[2]), _town(save, args[4])
        units = _warehouse(town)
        if int(units.get(str(unit_id), 0)) <= 0:
            raise VillageCommandError(f'no unit {unit_id} in the warehouse')
        units[str(unit_id)] = int(units[str(unit_id)]) - 1
        if units[str(unit_id)] == 0:
            del units[str(unit_id)]
        town.setdefault('items', []).append([unit_id, x, y, 0, now, 0])
        return f'unit {unit_id} out of the warehouse at ({x},{y})'
    if cmd == Constant.CMD_BUY_WAREHOUSE_CAPACITY_NEW:
        town = _town(save, args[0])
        capacity = int(town.get('warehouseAditionalCapacitySingle', WAREHOUSE_START_CAPACITY))
        if capacity >= int(globals_.get('WAREHOUSE_MAX_CAPACITY', 1000)):
            raise VillageCommandError('the unit warehouse is at its maximum')
        cost = int(globals_.get('WAREHOUSE_CAPACITY_INCREASE_PRICE_SINGLE', 2))
        save['playerInfo']['cash'] = max(int(save['playerInfo'].get('cash', 0)) - cost, 0)
        town['warehouseAditionalCapacitySingle'] = capacity + 1
        return f'warehouse capacity {capacity + 1} for {cost} cash'
    if cmd == Constant.CMD_RESET_WAREHOUSE:
        town = _town(save, args[0])
        units = _warehouse(town)
        total = 0
        for unit_id, count in units.items():
            _add_gift(save, int(unit_id), int(count))
            total += int(count)
        units.clear()
        return f'{total} warehoused units to the storage'
    raise VillageCommandError(f'not a unit warehouse command: {cmd}')


# Collections (CollectableManager). privateState.collections[collection] is [traded in (1), count of piece 1..5];
# Base.processAttacks reads it back. Rewards: globals.COLLECTION_REWARDS[collection]. The cash price is the game's
# own Config.PRIZE_COLLECTIONS_CASH, one less per piece already owned (at least 1), except collections 10 and 20,
# whose price is fixed (CollectableManager.getRealPrice).
PRIZE_COLLECTIONS_CASH = (0,) + (5,) * 9 + (15,) + (5,) * 9 + (20, 400, 400, 999)
FIXED_PRICE_COLLECTIONS = (10, 20)
PIECES_PER_COLLECTION = 5
COLLECTION_COMMANDS = (Constant.CMD_ADD_COLLECTABLE, Constant.CMD_FINISH_COLLECTION,
                       Constant.CMD_UNIT_COLLECTION_COMPLETED, Constant.CMD_ACTIVATE)
UNIT_COLLECTION_CASH = 1  # PopupAllUnits.getCollectionReward: +1 cash


def _collection(state, globals_, collection):
    collection = int(collection)
    if not 1 <= collection < len(globals_.get('COLLECTION_REWARDS', [])):
        raise VillageCommandError(f'unknown collection {collection}')
    collections = state.get('collections')
    if not isinstance(collections, list):
        collections = state['collections'] = []
    while len(collections) <= collection:
        collections.append([])
    entry = collections[collection]
    if not isinstance(entry, list):
        entry = collections[collection] = []
    if not entry:
        entry.append(0)
    while len(entry) <= PIECES_PER_COLLECTION:
        entry.append(0)
    return collection, entry


def collection_price(entry, collection):
    price = PRIZE_COLLECTIONS_CASH[collection]
    if collection in FIXED_PRICE_COLLECTIONS:
        return price
    owned = sum(1 for count in entry[1:PIECES_PER_COLLECTION + 1] if int(count) >= 1)
    return max(price - owned, 1)


def _complete_collection(save, globals_, collection, entry):
    for piece in range(1, PIECES_PER_COLLECTION + 1):
        if int(entry[piece]) > 0:
            entry[piece] = int(entry[piece]) - 1
    entry[0] = 1
    reward = int(globals_['COLLECTION_REWARDS'][collection])
    _add_gift(save, reward)
    completed = save['privateState'].setdefault('collectionsCompleted', [])
    if not isinstance(completed, list):
        completed = save['privateState']['collectionsCompleted'] = []
    completed.append(collection)
    return reward


def apply_collection_command(save, cmd, args, config, now=0):
    """Apply one collection command. Returns a short description for the log."""
    globals_ = config.get('globals', {})
    state = save['privateState']
    if cmd == Constant.CMD_ADD_COLLECTABLE:
        piece = int(args[1])
        if not 1 <= piece <= PIECES_PER_COLLECTION:
            raise VillageCommandError(f'unknown piece {piece} of collection {args[0]}')
        collection, entry = _collection(state, globals_, args[0])
        entry[piece] = int(entry[piece]) + 1
        return f'piece {piece} of collection {collection} ({entry[piece]} of it)'
    if cmd == Constant.CMD_FINISH_COLLECTION:
        collection, entry = _collection(state, globals_, args[0])
        if len(args) > 1 and int(args[1]) == 1:  # bought with cash (popupCollections.onBuy)
            if int(entry[0]) == 1:
                raise VillageCommandError(f'collection {collection} was already traded in')
            price = collection_price(entry, collection)
            save['playerInfo']['cash'] = max(int(save['playerInfo'].get('cash', 0)) - price, 0)
            reward = _complete_collection(save, globals_, collection, entry)
            return f'collection {collection} bought for {price} cash: item {reward} to the storage'
        if any(int(count) < 1 for count in entry[1:PIECES_PER_COLLECTION + 1]):
            raise VillageCommandError(f'collection {collection} is not complete')
        reward = _complete_collection(save, globals_, collection, entry)
        return f'collection {collection} traded in: item {reward} to the storage'
    if cmd == Constant.CMD_UNIT_COLLECTION_COMPLETED:
        category = int(args[0])
        entry = config.get('units_collections_categories', {}).get(str(category))
        if entry is None:
            raise VillageCommandError(f'unknown unit collection {category}')
        completed = state.get('unitCollectionsCompleted')
        if not isinstance(completed, list):
            completed = state['unitCollectionsCompleted'] = []
        if category in [int(done) for done in completed]:
            raise VillageCommandError(f'unit collection {category} was already rewarded')
        completed.append(category)
        # The reward is the cash alone: the popup shows only it ("rewards" is the collection's last unit).
        save['playerInfo']['cash'] = int(save['playerInfo'].get('cash', 0)) + UNIT_COLLECTION_CASH
        return f'unit collection {category}: {UNIT_COLLECTION_CASH} cash'
    if cmd == Constant.CMD_ACTIVATE:
        town = _town(save, args[2])
        item = _placed_item(town, args[0], args[1], args[3])
        while len(item) < 8:
            item.append([] if len(item) == 6 else {})
        if not isinstance(item[7], dict):
            item[7] = {}
        item[7]['cp'] = int(args[4])
        if item[7]['cp'] > 0:  # choosing a production starts its time now (IsoElement.initCollectTimer)
            item[4] = int(now)
        return f"building {args[3]} at ({args[0]},{args[1]}) set to {item[7]['cp']}"
    raise VillageCommandError(f'not a collection command: {cmd}')


def record_obtained_unit(save, item_id):
    """privateState.boughtUnits: the ids of every unit the player has had, a list (UnitCollectionsManager walks it
    by position; a dictionary there leaves the game stuck on "Loading"). The game only counts the units on the map at
    load, so a unit that died or was sold dropped out of its collection. Enemy camp units are added with free buys
    and are not recorded."""
    from get_game_config import get_item_from_id
    item = get_item_from_id(int(item_id))
    if not item or item.get('type') != 'u':
        return False
    state = save['privateState']
    obtained = state.get('boughtUnits')
    if isinstance(obtained, dict):  # written by an earlier version of this function
        obtained = state['boughtUnits'] = [int(unit) for unit in obtained]
    elif not isinstance(obtained, list):
        obtained = state['boughtUnits'] = []
    if int(item_id) not in obtained:
        obtained.append(int(item_id))
    return True


# Map missions and treasures (QuestsInMap, CustomQuestNew) and help with collections.
MAP_QUEST_COMMANDS = (Constant.CMD_SET_QUEST_VAR, Constant.CMD_COLLECT_TREASURE, Constant.CMD_PERFORM_CITY_QUEST,
                      Constant.CMD_ACCEPT_COLLECT_HELP, Constant.CMD_SET_RESOURCE_ALLIES)
QUEST_VARS = ('spawned', 'activators', 'boss', 'treasure')  # CustomQuestNew.questStatus, read as map.currentQuestVars
# The most a treasure gives (QuestsInMap.finalizeQuest): 750 gold and 100 xp from level 26, times
# REWARD_QUESTS_CHAPTERS_MULTIPLIER, which the game keeps between 0 and 2. Food and stone are 0 in practice.
TREASURE_MAX = {'gold': 1500, 'xp': 200, 'food': 1500, 'stone': 1500}
ALLIES_MARKET_RESOURCES = ('n', 'w', 's', 'f', 'g')  # 'n': none chosen (IsoElement.collect)


def apply_map_quest_command(save, cmd, args, config, now=0):
    """Apply one map mission / treasure / collection help command. Returns a short description for the log."""
    globals_ = config.get('globals', {})
    if cmd == Constant.CMD_SET_QUEST_VAR:
        town, name = _town(save, args[0]), str(args[1])
        if name not in QUEST_VARS:
            raise VillageCommandError(f'unknown mission variable {name}')
        value = json.loads(args[2]) if isinstance(args[2], str) else args[2]
        quest_vars = town.get('currentQuestVars')
        if not isinstance(quest_vars, dict):
            quest_vars = town['currentQuestVars'] = {}
        quest_vars[name] = value
        return f'mission {name} = {json.dumps(value)[:60]}'
    if cmd == Constant.CMD_COLLECT_TREASURE:
        # [gold, xp, next mission, food, stone, town]; [0, 0, mission, 0, 0, town] only sets the mission
        # (MapInitializer.setCorrectQuest).
        gold, xp, quest, food, stone = (int(value) for value in args[:5])
        town = _town(save, args[5])
        amounts = {'gold': gold, 'xp': xp, 'food': food, 'stone': stone}
        for name, amount in amounts.items():
            if not 0 <= amount <= TREASURE_MAX[name]:
                raise VillageCommandError(f'a treasure gives at most {TREASURE_MAX[name]} {name}, not {amount}')
        if quest < 0:
            raise VillageCommandError(f'unknown mission {quest}')
        town['idCurrentTreasure'] = quest
        if not any(amounts.values()):
            return f'map mission {quest}'
        town['coins'] = int(town.get('coins', 0)) + gold
        town['xp'] = int(town.get('xp', 0)) + xp
        town['food'] = int(town.get('food', 0)) + food
        town['stone'] = int(town.get('stone', 0)) + stone
        town['timestampLastTreasure'] = int(now)
        return f'treasure: {gold} gold, {xp} xp, {food} food, {stone} stone; next mission {quest}'
    if cmd == Constant.CMD_PERFORM_CITY_QUEST:
        # [x, y, town, quest]: a city mission building is collected and its timer starts again (IsoElement.collect).
        item = _item_at(save, args)
        while len(item) < 5:
            item.append(0)
        item[4] = int(now)
        return f'city mission {args[3]} at ({args[0]},{args[1]})'
    if cmd == Constant.CMD_ACCEPT_COLLECT_HELP:
        # [x, y, town, building, friend]: a friend's help brings the collection COLLECT_HELP_SECONDS closer.
        item = _placed_item(_town(save, args[2]), args[0], args[1], args[3])
        item[4] = int(item[4] if len(item) > 4 else now) - int(globals_.get('COLLECT_HELP_SECONDS', 3600))
        # attrs.hc holds the friends' helps as "u<friend>": false (IsoElement.addHurryUpCollect skips true ones);
        # the game marks the used help true under the friend's id without the "u".
        if len(item) > 7 and isinstance(item[7], dict) and isinstance(item[7].get('hc'), dict):
            helps, friend = item[7]['hc'], str(args[4])
            for key in ('u' + friend, friend):
                if key in helps:
                    helps[key] = True
        return f'help from {args[4]} on building {args[3]}'
    if cmd == Constant.CMD_SET_RESOURCE_ALLIES:
        # [resource, x, y, town, building]: the resource the allies' market collects next.
        resource = str(args[0])
        if resource not in ALLIES_MARKET_RESOURCES:
            raise VillageCommandError(f'unknown resource {resource}')
        town = _town(save, args[3])
        town['resourceAlliesMarket'] = resource
        if resource != 'n':  # choosing one starts the market's 24 hours again (PopupSelectResource.onSelect)
            item = _placed_item(town, args[1], args[2], args[4])
            while len(item) < 5:
                item.append(0)
            item[4] = int(now)
        return f"allies' market resource {resource}"
    raise VillageCommandError(f'not a map mission command: {cmd}')


def _item_at(save, args):
    """The item at (x, y) on the town of a [x, y, town, ...] command, whatever its id."""
    town = _town(save, args[2])
    for item in town.get('items', []):
        if int(item[1]) == int(args[0]) and int(item[2]) == int(args[1]):
            return item
    raise VillageCommandError(f'nothing at ({args[0]},{args[1]})')


# Mills and mines (globals.COLLECT_VARIABLE_IDS) produce what the player chose in "Elegir tiempo": attrs.cp 1-4,
# 5 min / 1 h / 4 h / 8 h, times Config.COLLECT_MULTIPLIER (IsoElement.collect). The game sends 1 as the
# multiplier of collect_new, so the server applies the choice itself.
COLLECT_MULTIPLIER = (0.5, 1, 2, 3)


def chosen_production_multiplier(town, x, y, item_id, config):
    if int(item_id) not in [int(i) for i in config.get('globals', {}).get('COLLECT_VARIABLE_IDS', [])]:
        return 1
    for item in town.get('items', []):
        if int(item[0]) == int(item_id) and int(item[1]) == int(x) and int(item[2]) == int(y):
            attrs = item[7] if len(item) > 7 and isinstance(item[7], dict) else {}
            choice = int(attrs.get('cp') or 0)
            return COLLECT_MULTIPLIER[choice - 1] if 1 <= choice <= len(COLLECT_MULTIPLIER) else 1
    return 1


# Mission difficulty (PopupLoadingQuest.setDifficulty): 1 to 3 stars, chosen before sailing. The game offers 2 stars
# once the island was won with 1, and 3 once won with 2, from privateState.questsRank[island id]. The server never
# kept it, so every island stayed at 1 star.
MAX_QUEST_STARS = 3


def record_quest_rank(save, quest_id, difficulty):
    """An island won at `difficulty` stars: keep the best (the next star unlocks). Returns the island's rank."""
    state = save['privateState']
    ranks = state.get('questsRank')
    if isinstance(ranks, str):  # new villages store it as the text '{}'
        try:
            ranks = json.loads(ranks)
        except ValueError:
            ranks = {}
    if not isinstance(ranks, dict):
        ranks = {}
    stars = max(1, min(int(difficulty or 1), MAX_QUEST_STARS))
    key = str(int(quest_id))
    ranks[key] = max(int(ranks.get(key, 0)), stars)
    state['questsRank'] = ranks
    return ranks[key]


# The adventure route (PopupQuestsManager.goToIsland): unlockedQuestIndex is the position of the next island the
# player may sail to. The server used to store the island's id + 1 there (100000007 after any end_quest, even a
# defeat), which opened every island at once.
QUEST_ROUTE = ('100000003', '100000002', '100000006', '100000007', '100000008', '100000012', '100000021',
               '100000022', '100000028', '100000011', '100000013', '100000014', '100000019', '100000020',
               '100000018', '100000015', '100000023', '100000033', '100000041', '100000042', '100000043',
               '100000044', '100000045', '100000046', '100000047', '100000090', '100000091', '100000092')


def unlock_next_island(save, quest_id):
    """A won island opens the next one on the route. Returns the unlocked index."""
    state = save['privateState']
    current = int(state.get('unlockedQuestIndex') or 0)
    key = str(int(quest_id))
    if key in QUEST_ROUTE:
        current = max(current, QUEST_ROUTE.index(key) + 1)
    state['unlockedQuestIndex'] = current
    return current
