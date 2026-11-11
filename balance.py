"""Private-server balance: mission rewards and PvP raid strength.

Decisions (Tareas.txt point 20):
  * Missions: early rewards stay as in the original; later ones grow so they
    keep pace with unit prices (the last missions paid 454 gold while units
    at that stage cost 5,000-15,000). Applied to the game config after the
    patches, so the game shows and the server pays the same amount.
  * PvP raids keep the formula 10 x attack + 5 x defense + life, with
    fixes for units the formula overrated:
      - kamikaze units explode once: their attack counts x1, not x10;
      - siege units are built for walls and buildings: attack counts x5;
      - the Orc Battering Ram and the Imperial Elf Catapult are siege units
        the config files under combat groups, so they get the siege rule.
  * Units bought with cash are left unchanged (the owner's decision).
  * In-game stats: the Orc Battering Ram (14,000 gold) had attack 500 and
    life 5,000, over three times the damage of 15,000-gold units; it now
    has attack 150 and life 3,000, in battles and in raids alike.
"""

MISSION_REWARD_TOP = 454      # Highest original reward (the last missions).
MISSION_REWARD_GROWTH = 10    # The top reward ends up (1 + 10) times larger.
MISSION_REWARD_ROUNDING = 10  # Rewards above 100 are rounded to tens.

PVP_ATTACK_WEIGHT = 10
PVP_DEFENSE_WEIGHT = 5
KAMIKAZE_ATTACK_WEIGHT = 1
SIEGE_ATTACK_WEIGHT = 5
SIEGE_LIKE_UNITS = frozenset({2074, 2012})  # Orc Battering Ram, Imperial Elf Catapult
_BALANCED_CONFIGS = set()
# unit id -> {field: (original value, balanced value)}; originals guard against
# changing a different unit if the config ever changes.
UNIT_CHANGES = {
    2074: {'attack': (500, 150), 'life': (5000, 3000)},  # Orc Battering Ram
}


def _number(value, default=0):
    if isinstance(value, bool):
        return default
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def scaled_mission_reward(original):
    """Original gold reward -> balanced reward (small rewards barely change)."""
    original = _number(original)
    if original <= 0:
        return original
    ratio = min(original / MISSION_REWARD_TOP, 1.0)
    value = original * (1 + MISSION_REWARD_GROWTH * ratio * ratio)
    if value > 100:
        return int(round(value / MISSION_REWARD_ROUNDING) * MISSION_REWARD_ROUNDING)
    return int(round(value))


def apply_mission_rewards(config):
    """Rewrite each mission's reward in place, once; returns how many changed.

    The config sent to the client keeps its original structure (no new keys),
    so the configs already balanced are remembered here instead.
    """
    if id(config) in _BALANCED_CONFIGS:
        return 0
    changed = 0
    for mission in config.get('missions', []):
        if not isinstance(mission, dict) or 'reward' not in mission:
            continue
        reward = scaled_mission_reward(mission['reward'])
        # Keep the value's own type: the base config uses text, patches use numbers.
        balanced = reward if isinstance(mission['reward'], int) else str(reward)
        if mission['reward'] != balanced:
            mission['reward'] = balanced
            changed += 1
    _BALANCED_CONFIGS.add(id(config))
    return changed


def apply_unit_changes(config):
    """Change the listed unit stats in place, once; returns how many changed."""
    if ('units', id(config)) in _BALANCED_CONFIGS:
        return 0
    changed = 0
    for item in config.get('items', []):
        changes = UNIT_CHANGES.get(_number(item.get('id'), -1)) if isinstance(item, dict) else None
        for field, (original, balanced) in (changes or {}).items():
            if _number(item.get(field)) != original:
                raise ValueError(f"Unexpected {field} for unit {item.get('id')}: {item.get(field)!r}")
            item[field] = balanced if isinstance(item[field], int) else str(balanced)
            changed += 1
    _BALANCED_CONFIGS.add(('units', id(config)))
    return changed


def apply_balance(config):
    return apply_mission_rewards(config) + apply_unit_changes(config)


def unit_groups(item):
    return set(str(item.get('groups', '')).split())


def pvp_attack_weight(item):
    groups = unit_groups(item)
    if 'kamikaze' in groups:
        return KAMIKAZE_ATTACK_WEIGHT
    if 'siege' in groups or _number(item.get('id'), -1) in SIEGE_LIKE_UNITS:
        return SIEGE_ATTACK_WEIGHT
    return PVP_ATTACK_WEIGHT


def pvp_unit_power(item):
    """Raid strength of one unit or defensive structure."""
    return (pvp_attack_weight(item) * _number(item.get('attack'))
            + PVP_DEFENSE_WEIGHT * _number(item.get('defense'))
            + _number(item.get('life')))
