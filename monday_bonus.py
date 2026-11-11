"""Monday bonus chest ("weekly_reward"): one mystery reward per Monday.

The client shows the chest on Mondays when privateState.timeStampMondayBonus is
not from the same day, picks one entry of MONDAY_BONUS_REWARDS at random and
sends [type, value]: 'g' gold, 'c' cash, or 'u' with a unit id taken from
MONDAY_BONUS_UNITS (stored in the warehouse). The server checks the day on its
own clock, takes gold and cash amounts from the game config rather than the
client, and records the claim so a reload neither repeats nor loses it.
"""

from datetime import datetime

from economy import MAX_CASH
from get_game_config import get_game_config

MONDAY = 0  # datetime.weekday()
HOME_TOWN = 0  # The chest opens while the home village loads.


class MondayBonusError(ValueError):
    """A Monday bonus claim the server does not accept."""


def _local_day(timestamp):
    return datetime.fromtimestamp(int(timestamp)).date()


def _config_rewards():
    config_globals = get_game_config()['globals']
    rewards = {reward['type']: reward['value'] for reward in config_globals['MONDAY_BONUS_REWARDS']}
    units = {int(unit) for unit in config_globals['MONDAY_BONUS_UNITS']}
    return rewards, units


def _int_argument(value):
    if isinstance(value, bool):
        raise MondayBonusError('Invalid Monday bonus value')
    try:
        return int(value)
    except (TypeError, ValueError):
        raise MondayBonusError('Invalid Monday bonus value') from None


def is_monday_bonus_available(save, now):
    """True on a Monday (server clock) when today's chest has not been opened."""
    if _local_day(now).weekday() != MONDAY:
        return False
    last = save['privateState'].get('timeStampMondayBonus')
    try:
        return last is None or _local_day(last) != _local_day(now)
    except (TypeError, ValueError, OverflowError, OSError):
        return True


def claim_monday_bonus(save, args, now):
    """Apply one validated Monday reward to the save and return a description."""
    if not isinstance(args, (list, tuple)) or len(args) < 2:
        raise MondayBonusError('Monday bonus needs a reward type and value')
    reward_type, value = args[0], _int_argument(args[1])
    if not is_monday_bonus_available(save, now):
        raise MondayBonusError('The Monday bonus is not available now')
    rewards, units = _config_rewards()
    if reward_type not in rewards:
        raise MondayBonusError(f'Unknown Monday bonus type {reward_type!r}')

    if reward_type == 'g':
        amount = int(rewards['g'])
        if value != amount:
            raise MondayBonusError('Monday gold does not match the game config')
        town = save['maps'][HOME_TOWN]
        town['coins'] = int(town.get('coins', 0)) + amount
        result = f'{amount} gold'
    elif reward_type == 'c':
        amount = int(rewards['c'])
        if value != amount:
            raise MondayBonusError('Monday cash does not match the game config')
        player = save['playerInfo']
        player['cash'] = min(int(player.get('cash', 0)) + amount, MAX_CASH)
        result = f'{amount} cash'
    else:
        if value not in units:
            raise MondayBonusError(f'Unit {value} is not a Monday bonus unit')
        gifts = save['privateState'].setdefault('gifts', [])
        if len(gifts) <= value:
            gifts.extend([0] * (value - len(gifts) + 1))
        gifts[value] += 1
        result = f'unit {value} in the warehouse'

    save['privateState']['timeStampMondayBonus'] = int(now)
    return result
