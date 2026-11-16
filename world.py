"""The game's World Explorer against real players (SE_WORLD_EXPLORER, on by default).

The owner chose "contra jugadores reales": the explorer's islands are filled with the villages of approved
players, attacks are fought in the game (ActionScript, as the game always did) and the server keeps what happens.
The rules and numbers are the game's own (Config, ExplorationsManager, Assault, Base.processAttacks):

  * Islands go from 50 (MAX_LEVEL, where everybody starts) to 1. Each island is shown as continents of 8
    territories (posicion 0-7); every player has one. Conquering the 7 others (map.universAttackWin) moves the
    player to the next island (privateState.worldChange = 1), whose reward (level_ranking_reward) the game asks
    for with apply_rewards_ranking. A territory without a player can be bought (buy_pvp_territory,
    PVP_BUY_TERRITORY_CASH).
  * Attacks: ATTACKS_MAX every ATTACKS_PERIOD_HOURS, the same player once every ATTACKS_SAME_PLAYER_HOURS; the
    game counts them from privateState.attacksSent. A bought pack (attacksPack) gives ATTACKS_PACK_SIZE.
    Spyings likewise (SPYINGS_MAX every SPYINGS_PERIOD_HOURS, privateState.spyings, spyingsPack).
  * end_attack: the game reports the gold and experience won and the gold the victim lost. The battle runs in
    the attacker's browser, so the server only accepts it after its own attack_player and caps it: the attacker
    earns at most MAX_GOLD_ASSAULT gold and MAX_XP_ASSAULT experience (the game pays the gold of what was
    destroyed even after a retreat); the victim loses gold only to a winner, at most LOOT_PERCENT of it (like
    the raids page), and not again within DEFENDER_PROTECTION_SECONDS of a lost battle. Both players get the
    battle in their history (attacksSent / attacksReceived, PopupAssaultHistory reads it from "description").
"""

import json
import os

from constants import Constant

ATTACKS_MAX = 3                 # Config.ATTACKS_MAX
ATTACKS_PERIOD_HOURS = 6        # Config.ATTACKS_PERIOD_HOURS
ATTACKS_SAME_PLAYER_HOURS = 4   # Config.ATTACKS_SAME_PLAYER_HOURS
SPYINGS_MAX = 3                 # Config.SPYINGS_MAX
SPYINGS_PERIOD_HOURS = 24       # Config.SPYINGS_PERIOD_HOURS
COST_BUY_ATTACK = 30            # Config.COST_BUY_ATTACK (cash)
COST_BUY_SPYINGS = 15           # Config.COST_BUY_SPYINGS (cash)
ATTACKS_PACK_SIZE = 50          # Config.ATTACKS_PACK_SIZE
SPYINGS_PACK_SIZE = 50          # Config.SPYINGS_PACK_SIZE
MAX_LEVEL, MIN_LEVEL = 50, 1    # ExplorationsManager.MAX_LEVEL / MIN_LEVEL
EXPLORER_LEVEL = 6              # "Alcanza el nivel 6 para desbloquear el explorador del mundo"
TERRITORIES = 8                 # posicion 0-7; 7 to conquer (ExplorationsManager.checkAnimationConquered)
LOOT_PERCENT = 20               # the raids page's RAID_LOOT_PERCENT
MAX_XP_ASSAULT = 2000           # the game sends no limit; a cap so a forged result cannot level a player up
DEFENDER_PROTECTION_SECONDS = 60 * 60
RESULT_WINDOW_SECONDS = 2 * 60 * 60  # end_attack must follow its attack_player within this time
HISTORY_LIMIT = 50

WORLD_COMMANDS = (Constant.CMD_ATTACK_PLAYER, Constant.CMD_END_ATTACK, Constant.CMD_SPY, Constant.CMD_CLEAN_ATTACKS,
                  Constant.CMD_BUY_ATTACKS_PACK, Constant.CMD_BUY_SPYINGS_PACK, Constant.CMD_PVP_BUY_TERRITORY,
                  Constant.CMD_MODIFY_POSITION_UNIVERSE, Constant.CMD_RESET_POSITION_UNIVERSE,
                  Constant.CMD_RESET_ISLAND_CHANGE, Constant.CMD_APPLY_REWARDS_RANKING)

_eligible = lambda: set()  # set by the server: the approved players' village ids


class WorldError(ValueError):
    """A world command that cannot be applied: nothing changes."""


def world_explorer_enabled():
    return os.environ.get('SE_WORLD_EXPLORER', 'on').strip().lower() in ('on', '1', 'true', 'yes')


def set_eligible(function):
    global _eligible
    _eligible = function


def _sessions():
    import sessions
    return sessions


def _state(save):
    state = save['privateState']
    for key in ('attacksSent', 'attacksReceived', 'spyings'):
        if not isinstance(state.get(key), list):
            state[key] = []
    state.setdefault('attacksPack', 0)
    state.setdefault('spyingsPack', 0)
    state.setdefault('worldChange', 0)
    if not isinstance(state.get('worldLevel'), int):
        state['worldLevel'] = MAX_LEVEL
    return state


def _won(save):
    town = save['maps'][0]
    if not isinstance(town.get('universAttackWin'), list):
        town['universAttackWin'] = []
    return town['universAttackWin']


def _player(userid):
    """A village that can be in the explorer: an approved player who finished the tutorial and reached the level
    that unlocks the explorer (lower players cannot open it, so they cannot be attacked in it either)."""
    if str(userid) not in _eligible():
        return None
    save = _sessions().session(str(userid))
    if save is None or int(save['playerInfo'].get('completed_tutorial') or 0) != 1:
        return None
    if int(save['maps'][0].get('level') or 0) < EXPLORER_LEVEL:
        return None
    return save


def _entry(userid, save, level, position):
    info = save['playerInfo']
    town = save['maps'][0]
    name = info.get('map_names', [''])[0] if isinstance(info.get('map_names'), list) and info.get('map_names') else ''
    return {'posicion': position, 'nivel': level, 'user_id': str(userid), 'name': name or info.get('name', ''),
            'level': int(town.get('level', 1)), 'race': town.get('race', 'h'), 'world_id': 0,
            'map': 0}  # the island the game loads to attack it (ExplorationsManager.doAttack)


def _members(level):
    """{(continent, position): userid} of the players on an island."""
    taken = {}
    for userid in sorted(_eligible()):
        save = _player(userid)
        if save is None:
            continue
        state = _state(save)
        if state['worldLevel'] == level and isinstance(state.get('worldContinent'), int) \
                and isinstance(state.get('worldPosition'), int):
            taken.setdefault((state['worldContinent'], state['worldPosition']), str(userid))
    return taken


def _place(userid, save):
    """Give the player a continent and a territory on its island if it has none (or someone else holds it)."""
    state = _state(save)
    level = state['worldLevel']
    taken = _members(level)
    spot = (state.get('worldContinent'), state.get('worldPosition'))
    if taken.get(spot) == str(userid):
        return spot
    continent = 0
    while True:
        free = [p for p in range(TERRITORIES) if (continent, p) not in taken]
        if free:
            state['worldContinent'], state['worldPosition'] = continent, free[0]
            return continent, free[0]
        continent += 1


def _place_everybody():
    """Players who never opened the explorer still live on an island: give them a territory (and keep it)."""
    for userid in sorted(_eligible()):
        save = _player(userid)
        if save is None:
            continue
        state = _state(save)
        if not (isinstance(state.get('worldContinent'), int) and isinstance(state.get('worldPosition'), int)):
            _place(userid, save)
            _sessions().save_session(str(userid))


def continent(userid, level_id=None, relocate=False):
    """get_continent_ranking.php: the 8 territories of the player's continent, or of island level_id."""
    save = _sessions().session(str(userid))
    state = _state(save)
    if relocate:
        state.pop('worldContinent', None)
        state.pop('worldPosition', None)
    own_continent, _ = _place(userid, save)
    _place_everybody()
    level = state['worldLevel']
    if level_id not in (None, '', 0, '0'):
        level = max(MIN_LEVEL, min(MAX_LEVEL, int(level_id)))
    shown = own_continent if level == state['worldLevel'] else 0
    taken = _members(level)
    territories = []
    for position in range(TERRITORIES):
        holder = taken.get((shown, position))
        holder_save = _player(holder) if holder else None
        territories.append(_entry(holder, holder_save, level, position) if holder_save
                           else {'posicion': position, 'nivel': level})
    return {'world_id': 0, 'continent': territories}


def _recent(entries, seconds, now):
    return [entry for entry in entries if isinstance(entry, dict) and now - int(entry.get('time', 0)) < seconds]


def _advance_if_conquered(save):
    """Seven territories conquered: next island (the game shows its reward and sends reset_world_change)."""
    won, state = _won(save), _state(save)
    if len(set(won)) < TERRITORIES - 1:
        return False
    state['worldLevel'] = max(MIN_LEVEL, state['worldLevel'] - 1)
    state['worldChange'] = 1
    state.pop('worldContinent', None)
    state.pop('worldPosition', None)
    won.clear()
    return True


def _attacker_won(received):
    if 'attackerWon' in received:
        return bool(received['attackerWon'])
    return int((received.get('description') or {}).get('win') or 0) == 1  # written before attackerWon


def _oponent(userid):
    """The other player in a battle as PopupAssaultHistory shows it (name and picture)."""
    save = _sessions().session(str(userid))
    info = save['playerInfo'] if save else {}
    names = info.get('map_names') if isinstance(info.get('map_names'), list) else []
    return {'user_id': str(userid), 'name': (names[0] if names else '') or info.get('name', ''),
            'pic': info.get('pic', '')}


def _trim(entries):
    del entries[:-HISTORY_LIMIT]


def apply_world_command(userid, save, cmd, args, config, now):
    """Apply one World Explorer command for the player `userid`. Returns a short description for the log."""
    globals_ = config.get('globals', {})
    state = _state(save)
    cash = save['playerInfo']
    if cmd == Constant.CMD_ATTACK_PLAYER:
        victim = str(args[0])
        pack = int(state.get('attacksPack') or 0)
        if not pack and len(_recent(state['attacksSent'], ATTACKS_PERIOD_HOURS * 3600, now)) >= ATTACKS_MAX:
            raise WorldError('no attacks left')
        if any(str(entry.get('victim_id')) == victim for entry in _recent(state['attacksSent'], ATTACKS_SAME_PLAYER_HOURS * 3600, now)):
            raise WorldError(f'{victim} was attacked less than {ATTACKS_SAME_PLAYER_HOURS} hours ago')
        if pack:
            state['attacksPack'] = pack - 1
        # A pending attack has no description: the history window lists only finished battles.
        state['attacksSent'].append({'victim_id': victim, 'time': int(now), 'pending': True})
        _trim(state['attacksSent'])
        return f'attack on {victim}'
    if cmd == Constant.CMD_END_ATTACK:
        return _end_attack(userid, save, args, globals_, now)
    if cmd == Constant.CMD_SPY:
        victim = str(args[0])
        pack = int(state.get('spyingsPack') or 0)
        if not pack and len(_recent(state['spyings'], SPYINGS_PERIOD_HOURS * 3600, now)) >= SPYINGS_MAX:
            raise WorldError('no spyings left')
        if pack:
            state['spyingsPack'] = pack - 1
        state['spyings'].append({'victim_id': victim, 'time': int(now)})
        _trim(state['spyings'])
        return f'spying on {victim}'
    if cmd == Constant.CMD_CLEAN_ATTACKS:
        for entry in state['attacksReceived']:
            if isinstance(entry, dict):
                entry.pop('viewPending', None)  # the window marks "NEW" while the field exists, whatever its value
        return 'battle results seen'
    if cmd in (Constant.CMD_BUY_ATTACKS_PACK, Constant.CMD_BUY_SPYINGS_PACK):
        attacks = cmd == Constant.CMD_BUY_ATTACKS_PACK
        cost = COST_BUY_ATTACK if attacks else COST_BUY_SPYINGS
        if int(cash.get('cash', 0)) < cost:
            raise WorldError('not enough cash')
        cash['cash'] = int(cash['cash']) - cost
        state['attacksPack' if attacks else 'spyingsPack'] = ATTACKS_PACK_SIZE if attacks else SPYINGS_PACK_SIZE
        return f"{'attacks' if attacks else 'spyings'} pack for {cost} cash"
    if cmd == Constant.CMD_PVP_BUY_TERRITORY:
        position = int(args[0])
        cost = int(globals_.get('PVP_BUY_TERRITORY_CASH', 5))
        # The game offers "Conquistar" on a player's territory (ExplorationsManager.tweenScaleOver): it is taken
        # for cash, without a battle and without loot. Free territories have no icon in the game.
        _, own = _place(userid, save)
        if not 0 <= position < TERRITORIES or position == own or position in _won(save):
            raise WorldError(f'territory {position} cannot be bought')
        if int(cash.get('cash', 0)) < cost:
            raise WorldError('not enough cash')
        cash['cash'] = int(cash['cash']) - cost
        _won(save).append(position)
        advanced = _advance_if_conquered(save)
        return f'territory {position} bought for {cost} cash' + (', next island' if advanced else '')
    if cmd == Constant.CMD_MODIFY_POSITION_UNIVERSE:
        new, old = int(args[0]), int(args[1])
        continent_id, own = _place(userid, save)
        if own != old or not 0 <= new < TERRITORIES or (continent_id, new) in _members(state['worldLevel']):
            raise WorldError(f'cannot move from {old} to {new}')
        state['worldPosition'] = new
        return f'territory {old} -> {new}'
    if cmd == Constant.CMD_RESET_POSITION_UNIVERSE:
        _won(save).clear()
        state.pop('worldContinent', None)
        state.pop('worldPosition', None)
        return 'moved to another continent'
    if cmd == Constant.CMD_RESET_ISLAND_CHANGE:
        state['worldChange'] = 0
        return 'island change seen'
    if cmd == Constant.CMD_APPLY_REWARDS_RANKING:
        return _island_reward(save, args, config)
    raise WorldError(f'not a world command: {cmd}')


def _end_attack(userid, save, args, globals_, now):
    results = json.loads(args[0]) if isinstance(args[0], str) else args[0]
    if not isinstance(results, dict) or not isinstance(results.get('victim'), dict):
        raise WorldError('no battle result')
    state = _state(save)
    victim_id = str(results['victim'].get('user_id'))
    pending = next((entry for entry in reversed(state['attacksSent']) if isinstance(entry, dict)
                    and entry.get('pending') and str(entry.get('victim_id')) == victim_id
                    and now - int(entry.get('time', 0)) < RESULT_WINDOW_SECONDS), None)
    if pending is None:
        raise WorldError(f'no attack on {victim_id} to finish')
    won = int(results.get('win') or 0) == 1
    if won:  # SE_SEASON_PASS: an attack won counts for the season pass
        from season_pass import record_event
        record_event(save, 'world_attack_win')
    max_gold = int(globals_.get('MAX_GOLD_ASSAULT', 20000))
    gold = max(0, min(int((results.get('resources') or {}).get('g') or 0), max_gold))
    xp = max(0, min(int((results.get('resources') or {}).get('x') or 0), MAX_XP_ASSAULT))
    victim = _player(victim_id) if victim_id != str(userid) else None
    lost = 0
    if victim is not None and won:
        victim_state = _state(victim)
        protected = any(_attacker_won(entry) for entry in
                        _recent(victim_state['attacksReceived'], DEFENDER_PROTECTION_SECONDS, now))
        victim_town = victim['maps'][0]
        reported = int((results.get('resources_victim') or {}).get('g') or 0)
        lost = 0 if protected else max(0, min(reported, max_gold, int(victim_town.get('coins', 0)) * LOOT_PERCENT // 100))
        victim_town['coins'] = int(victim_town.get('coins', 0)) - lost
    # As in the game, the attacker earns the gold of what it destroyed even after a retreat (Assault.iGoldGained),
    # capped by MAX_GOLD_ASSAULT; the victim only loses gold when the attacker wins (resources_victim).
    town = save['maps'][0]
    town['coins'] = int(town.get('coins', 0)) + gold
    town['xp'] = int(town.get('xp', 0)) + xp
    record = {key: value for key, value in results.items() if key not in ('attacker_units', 'victim_units')}
    record.update({'resources': {'g': gold, 'x': xp}, 'resources_victim': {'g': lost},
                   'attacker_units': results.get('attacker_units', []), 'victim_units': results.get('victim_units', [])})
    # PopupAssaultHistory: {time, viewPending, description: the battle, with the other player as "oponent"}
    pending.clear()
    pending.update({'victim_id': victim_id, 'time': int(now), 'description': dict(record, oponent=_oponent(victim_id))})
    conquered = ''
    if won and victim is not None:
        victim_state = _state(victim)
        attacker_state = state
        _place(userid, save)
        same_place = (victim_state.get('worldLevel'), victim_state.get('worldContinent')) == \
                     (attacker_state['worldLevel'], attacker_state.get('worldContinent'))
        position = victim_state.get('worldPosition')
        if same_place and isinstance(position, int) and position not in _won(save):
            _won(save).append(position)
            conquered = f', territory {position}' + (', next island' if _advance_if_conquered(save) else '')
    if victim is not None:
        # The history window shows "win" from its reader's side: the defender won when the attacker lost.
        received = {'attacker_id': str(userid), 'time': int(now), 'viewPending': True, 'attackerWon': won,
                    'description': dict(record, oponent=_oponent(userid), win=0 if won else 1)}
        _state(victim)['attacksReceived'].append(received)
        _trim(_state(victim)['attacksReceived'])
        _sessions().save_session(victim_id)
    return f"{'won' if won else 'lost'} against {victim_id}: {gold} gold, {xp} xp, victim lost {lost}{conquered}"


def _island_reward(save, args, config):
    level, cash, items = int(args[0]), int(args[1]), args[2]
    items = json.loads(items) if isinstance(items, str) else (items or {})
    state = _state(save)
    claimed = state.setdefault('islandRewards', [])
    rewards = {int(entry['level']): entry for entry in config.get('level_ranking_reward', [])}
    if level not in rewards or level < state['worldLevel'] or level in claimed:
        raise WorldError(f'no reward for island {level}')
    reward = rewards[level]
    if cash != int(reward.get('cash') or 0) or {str(k): int(v) for k, v in (items or {}).items()} != \
            {str(k): int(v) for k, v in (reward.get('units') or {}).items()}:
        raise WorldError(f'not the reward of island {level}')
    claimed.append(level)
    save['playerInfo']['cash'] = int(save['playerInfo'].get('cash', 0)) + cash
    gifts = state.setdefault('gifts', [])
    for unit, count in (reward.get('units') or {}).items():
        while len(gifts) <= int(unit):
            gifts.append(0)
        gifts[int(unit)] += int(count)
    return f'island {level} reward: {cash} cash and units {reward.get("units")}'


def prepare_world(save):
    """The explorer's fields the game reads at load (Base.processAttacks): adds the missing ones. True if any."""
    state = save['privateState']
    before = {key: key in state for key in ('attacksSent', 'attacksReceived', 'spyings', 'attacksPack', 'spyingsPack',
                                             'worldChange', 'worldLevel')}
    _state(save)
    won_missing = not isinstance(save['maps'][0].get('universAttackWin'), list)
    _won(save)
    repaired = False
    for key, other in (('attacksSent', lambda entry: entry.get('victim_id')),
                       ('attacksReceived', lambda entry: (entry.get('attacker') or {}).get('user_id'))):
        for index, entry in enumerate(state[key]):  # flat records written before the history window was known
            if not isinstance(entry, dict) or isinstance(entry.get('description'), dict):
                continue
            keep = {name: entry[name] for name in ('victim_id', 'time', 'pending', 'viewPending', 'attacker_id')
                    if name in entry}
            battle = {name: value for name, value in entry.items() if name not in keep and name != 'description'}
            if 'win' in battle:
                keep['description'] = dict(battle, oponent=_oponent(other(entry) or ''))
                keep.pop('pending', None)
            state[key][index] = keep
            repaired = True
    for entry in state['attacksReceived']:
        if isinstance(entry, dict) and entry.get('viewPending') is False:  # "seen" written as false before
            del entry['viewPending']
            repaired = True
    for entry in state['attacksReceived']:  # written before the defender's side was shown: flip once
        if isinstance(entry, dict) and 'attackerWon' not in entry and isinstance(entry.get('description'), dict):
            entry['attackerWon'] = int(entry['description'].get('win') or 0) == 1
            entry['description']['win'] = 0 if entry['attackerWon'] else 1
            repaired = True
    return won_missing or repaired or not all(before.values())
