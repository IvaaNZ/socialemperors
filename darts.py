"""Daily darts (SE_DAILY_DARTS, on by default).

Asked by the owner: the darts game felt weekly. In the game, the board (its 25
balloons and 6 prizes) only starts over when a new entry of the config's
`darts_items` begins, and those entries are a week apart and end in September
2012 (the last one has no prizes, so with today's date there is no game at
all). The free dart is already daily (Utils.isSameDay), but only until every
balloon is popped. The server also did not handle the darts commands, so the
popped balloons, the free dart and the prizes were lost on reload.

This module:
  * daily_darts_items(today): one entry per day, from a few days back to
    DAYS_AHEAD days ahead, cycling through the game's own prize sets. The game
    reads only the date of `start_date` (Utils.getTimeStampFromString: local
    midnight), so the board starts over at the player's midnight, and the
    countdown shows the time left until the next day;
  * with_daily_darts(config): the config with those entries and texts saying
    "tomorrow"/"every day" instead of "next week"/"each week";
  * apply_darts_command(save, cmd, args): darts_reset, darts_new_free,
    darts_shoot_balloon (a paid dart costs DART_COST_CASH) and
    store_add_items (the prize goes to the storage, like store_item).
"""

import datetime
import json
import os

from constants import Constant

DAYS_BACK = 3
DAYS_AHEAD = 60
DEFAULT_DART_COST = 20
DARTS_COMMANDS = (Constant.CMD_DARTS_RESET, Constant.CMD_DARTS_NEW_FREE, Constant.CMD_DARTS_SHOOT_BALLOON,
                  Constant.CMD_STORE_ADD_ITEMS)

# Texts of the darts window: "next week" becomes "tomorrow" (every language the config may carry).
DAILY_TEXTS = {
    'DARTS_COME_BACK': [
        ('Come back next week for new prizes!', 'Come back tomorrow for new prizes!'),
        ('¡Vuelve la próxima semana para ver premios nuevos!', '¡Vuelve mañana para ver premios nuevos!'),
        ('Volte na próxima semana para novos prêmios!', 'Volte amanhã para novos prêmios!'),
    ],
    'TITLE_DESCRIPTION_DARTS': [
        ('New Game prizes are introduced each week!', 'New prizes are introduced every day!'),
        ('¡Cada semana hay premios nuevos!', '¡Cada día hay premios nuevos!'),
        ('Novos prêmios chegam toda semana!', 'Novos prêmios chegam todo dia!'),
    ],
}


def daily_darts_enabled():
    return os.environ.get('SE_DAILY_DARTS', 'on').strip().lower() in ('on', '1', 'true', 'yes')


def prize_sets(config):
    return [entry for entry in config.get('darts_items', []) if entry.get('items')]


def daily_darts_items(today, sets):
    """One darts entry per day around `today`, each with the next prize set."""
    if not sets:
        return []
    entries = []
    for offset in range(-DAYS_BACK, DAYS_AHEAD + 1):
        day = today + datetime.timedelta(days=offset)
        prizes = sets[day.toordinal() % len(sets)]
        entries.append({'id': day.toordinal(), 'start_date': day.strftime('%Y-%m-%d') + ' 00:00:00',
                        'items': list(prizes['items']), 'extra_item': prizes['extra_item']})
    return entries


def _daily_text(entry):
    text = entry.get('text', '')
    for old, new in DAILY_TEXTS.get(entry.get('name'), ()):
        text = text.replace(old, new)
    return text


def with_daily_darts(config, today=None):
    """The game config with a darts board that starts over every day (a copy; `config` is not changed)."""
    if not daily_darts_enabled():
        return config
    entries = daily_darts_items(today or datetime.date.today(), prize_sets(config))
    if not entries:
        return config
    result = dict(config)
    result['darts_items'] = entries
    if 'localization_strings' in config:
        # Some patched entries are lists, not texts: they are kept as they are.
        result['localization_strings'] = [dict(entry, text=_daily_text(entry))
                                          if isinstance(entry, dict) and entry.get('name') in DAILY_TEXTS else entry
                                          for entry in config['localization_strings']]
    return result


def _add_gift(save, item_id):
    gifts = save['privateState'].setdefault('gifts', [])
    if len(gifts) <= item_id:
        gifts.extend([0] * (item_id - len(gifts) + 1))
    gifts[item_id] += 1


def apply_darts_command(save, cmd, args, now, dart_cost=DEFAULT_DART_COST):
    """Apply one darts command to the save. Returns a short description for the log."""
    state = save['privateState']
    if cmd == Constant.CMD_DARTS_RESET:
        state['timeStampDartsReset'] = now
        state['timeStampDartsNewFree'] = now
        state['dartsBalloonsShot'] = []
        state['dartsRandomSeed'] = int(args[0]) if args else state.get('dartsRandomSeed', 0)
        state['dartsHasFree'] = True
        state['dartsGotExtra'] = False
        return 'new darts board'
    if cmd == Constant.CMD_DARTS_NEW_FREE:
        state['timeStampDartsNewFree'] = now
        state['dartsHasFree'] = True
        return 'free dart'
    if cmd == Constant.CMD_DARTS_SHOOT_BALLOON:
        balloon, paid, got_extra = int(args[0]), int(args[1]), int(args[2])
        shot = state.setdefault('dartsBalloonsShot', [])
        if balloon not in shot:
            shot.append(balloon)
        if paid:
            save['playerInfo']['cash'] = max(save['playerInfo'].get('cash', 0) - dart_cost, 0)
        state['dartsHasFree'] = False
        if got_extra:
            state['dartsGotExtra'] = True
        return f'balloon {balloon}' + (f' for {dart_cost} cash' if paid else ' (free dart)')
    if cmd == Constant.CMD_STORE_ADD_ITEMS:
        items = json.loads(args[0]) if isinstance(args[0], str) else args[0]
        for item_id in items:
            _add_gift(save, int(item_id))
        return f'stored {items}'
    raise ValueError(f'Not a darts command: {cmd}')
