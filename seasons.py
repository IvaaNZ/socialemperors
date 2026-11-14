"""Seasons (SE_SEASONS, on by default): the village's weather follows Argentina's seasons.

Asked by the owner: "que las estaciones de clima se cambien automáticamente por temporadas como en Argentina".
The game's weathers (PopupWeather.themeIds) chosen for each season, by the owner:

  * summer, 21 Dec - 20 Mar: Desierto Soleado (1)
  * autumn, 21 Mar - 20 Jun: Montañas Rocosas (4)
  * winter, 21 Jun - 22 Sep: Llanuras Nevadas (2)
  * spring, 23 Sep - 20 Dec: Praderas Verdes (0)

When a season starts (the first time the player enters in it) every island takes its weather. A weather the
player picks in the Weather Machine stays until the next season. The season's weather is free while the season
lasts: it is marked unlocked ("true", what the weather popup compares with) and taken back when the season ends,
unless the player had bought it before.
"""

import datetime
import os

from village_commands import SKIN_UNLOCKED, _unlocked_skins

SUMMER, AUTUMN, WINTER, SPRING = 'summer', 'autumn', 'winter', 'spring'
SEASON_SKINS = {SUMMER: 1, AUTUMN: 4, WINTER: 2, SPRING: 0}
# (month, day) each season starts on, in calendar order.
SEASON_STARTS = ((3, 21, AUTUMN), (6, 21, WINTER), (9, 23, SPRING), (12, 21, SUMMER))


def seasons_enabled():
    return os.environ.get('SE_SEASONS', 'on').strip().lower() in ('on', '1', 'true', 'yes')


def season_of(day):
    """(season, key) of a date. The key names one season of one year ("2026-summer" lasts into March 2027)."""
    season, start_year = SUMMER, day.year - 1  # 1 Jan - 20 Mar: the summer that began last December
    for month, start_day, name in SEASON_STARTS:
        if (day.month, day.day) >= (month, start_day):
            season, start_year = name, day.year
    return season, f'{start_year}-{season}'


def apply_season(save, day=None):
    """Give every island the season's weather once per season. Returns the season's name if anything changed."""
    season, key = season_of(day or datetime.date.today())
    state = save.get('privateState')
    if not isinstance(state, dict) or state.get('seasonKey') == key:
        return None
    skin = SEASON_SKINS[season]
    unlocked = _unlocked_skins(state)
    granted = state.get('seasonSkinGranted')
    if granted is not None and int(granted) != skin:
        unlocked.pop(str(int(granted)), None)  # last season's free weather goes back
        granted = None
    if skin != 0 and unlocked.get(str(skin)) != SKIN_UNLOCKED:
        unlocked[str(skin)] = SKIN_UNLOCKED
        granted = skin
    state['seasonSkinGranted'] = granted
    state['seasonKey'] = key
    for town in save.get('maps', []):
        town['skin'] = skin
    return season
