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
"""

import math
import os

from constants import Constant

TRADE_RESOURCES = {'w': 'wood', 's': 'stone', 'f': 'food'}
CASH, GOLD = 1, 0
UNLOCK_MULTIPLIER = 1 / 3  # the game's Config.MULTIPLIER_UNLOCK

VILLAGE_COMMANDS = (Constant.CMD_USE_MAGIC, Constant.CMD_BUY_MAGIC, Constant.CMD_BUY_MANA, Constant.CMD_TRADE_RESOURCE,
                    Constant.CMD_UNLOCK_BUILDING, Constant.CMD_INCREASE_POPULATION, Constant.CMD_PLACE_STORED_ITEM,
                    Constant.CMD_SELL_STORED)


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


def apply_village_command(save, cmd, args, config):
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
    raise VillageCommandError(f'not a village command: {cmd}')


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
