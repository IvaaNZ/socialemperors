"""Free season pass (point 25 of block E, SE_SEASON_PASS): levels with rewards that last one season of Argentina.

What the owner chose:

  * a season is one of Argentina's seasons (seasons.season_of, the same that sets the village weather): the
    Summer, Autumn, Winter and Spring passes, about three months each;
  * players go up by playing (a few points per action, at most PLAY_POINTS_PER_DAY a day) and above all with
    challenges: DAILY_COUNT a day and WEEKLY_COUNT a week, the same for everybody, drawn from CHALLENGES;
  * rewards: gold, wood, food and stone on most levels, game cash every 5 levels and a unit of the season every
    10 (to the gifts, "Regalos"); level LEVELS gives the season's own unit;
  * a "Pase" button inside the game opens the window (season_pass_web.py, templates/js/season_pass_overlay.js).

Everything is kept in the player's village (privateState.seasonPass), so it is saved and backed up with it.
A new season starts from zero; rewards not claimed before the season ends are lost (the window says how many days
are left). Claiming changes the village while the game may be open: like the treasury and raids, it changes the
village revision, so the page pauses the game and asks to reload it to see the rewards.

Days and weeks follow Argentina's clock (UTC-3), like the day and night cycle.
"""

import datetime
import os
import random

from seasons import AUTUMN, SPRING, SUMMER, WINTER, season_of

ARGENTINA = datetime.timezone(datetime.timedelta(hours=-3))
LEVELS = 40
POINTS_PER_LEVEL = 600
PLAY_POINTS_PER_DAY = 300
SEEN_KEEP = 50  # raids and duels already counted (a repeated report counts once)

# Points for playing (before the daily cap).
EVENT_POINTS = {
    'collect': 2,          # collecting from a building
    'quest_win': 25,       # an adventure island won (+10 for each difficulty star above the first)
    'raid_win': 20,        # a raid won
    'world_attack_win': 25,  # a World Explorer attack won
    'duel_play': 10,       # a live duel finished
    'duel_win': 30,        # a live duel won (on top of duel_play)
}
EVENT_NAMES = tuple(EVENT_POINTS)

# Challenges: (id, event, how many, points). Daily ones from the first list, weekly from the second.
DAILY_CHALLENGES = (
    ('collect_15', 'collect', 15, 150),
    ('collect_30', 'collect', 30, 200),
    ('quest_1', 'quest_win', 1, 150),
    ('quest_2', 'quest_win', 2, 200),
    ('raid_1', 'raid_win', 1, 150),
    ('world_1', 'world_attack_win', 1, 150),
    ('duel_1', 'duel_play', 1, 150),
)
WEEKLY_CHALLENGES = (
    ('collect_150', 'collect', 150, 500),
    ('quest_8', 'quest_win', 8, 600),
    ('raid_5', 'raid_win', 5, 500),
    ('world_5', 'world_attack_win', 5, 500),
    ('duel_win_3', 'duel_win', 3, 600),
    ('duel_5', 'duel_play', 5, 500),
)
DAILY_COUNT = 3
WEEKLY_COUNT = 3

SEASON_NAMES = {SUMMER: 'Verão', AUTUMN: 'Outono', WINTER: 'Inverno', SPRING: 'Primavera'}
# The units of each season, for levels 10, 20, 30 and 40 (the last one, the season's own). All have pictures in the
# game and are not mobile-only.
SEASON_UNITS = {
    SUMMER: (613, 615, 722, 2178),   # Egyptian warrior, mummy, fire T-Rex, extreme fire baby dragon
    AUTUMN: (858, 752, 2029, 2334),  # boar rider, minotaur, boar rider with axe, extreme rock baby dragon
    WINTER: (666, 642, 741, 2184),   # yeti, black yeti, snowy Kong, extreme frost baby dragon
    SPRING: (627, 629, 635, 2009),   # elf archer, elf tiger, ent, imperial elf knight
}
RESOURCES = ('coins', 'wood', 'food', 'stone')


def season_pass_enabled():
    return os.environ.get('SE_SEASON_PASS', 'off').strip().lower() in ('on', '1', 'true', 'yes')


def now_in_argentina(now=None):
    if now is None:
        return datetime.datetime.now(ARGENTINA)
    if isinstance(now, (int, float)):
        return datetime.datetime.fromtimestamp(now, ARGENTINA)
    return now.astimezone(ARGENTINA)


def season_bounds(day):
    """(season, key, first day, last day) of the season a date is in."""
    season, key = season_of(day)
    start = day
    while season_of(start - datetime.timedelta(days=1))[1] == key:
        start -= datetime.timedelta(days=1)
    end = day
    while season_of(end + datetime.timedelta(days=1))[1] == key:
        end += datetime.timedelta(days=1)
    return season, key, start, end


def week_key(day):
    year, week, _ = day.isocalendar()
    return f'{year}-W{week:02d}'


def challenges_of(kind, period_key, season_key):
    """The challenges of one day or week: the same for every player, drawn from the list with the period as seed."""
    pool, count = (DAILY_CHALLENGES, DAILY_COUNT) if kind == 'daily' else (WEEKLY_CHALLENGES, WEEKLY_COUNT)
    chosen = random.Random(f'{season_key}|{kind}|{period_key}').sample(pool, count)
    return [{'id': cid, 'event': event, 'target': target, 'points': points} for cid, event, target, points in chosen]


def reward_of(season, level):
    """What a level gives: {'resource': name, 'amount': n} / {'cash': n} / {'unit': item id}."""
    level = int(level)
    if not 1 <= level <= LEVELS:
        raise ValueError('level')
    if level % 10 == 0:
        return {'unit': SEASON_UNITS[season][level // 10 - 1]}
    if level % 5 == 0:
        return {'cash': 5 if level < 25 else 10}
    resource = RESOURCES[(level - 1) % len(RESOURCES)]
    amount = (1000 + 250 * level) if resource == 'coins' else (500 + 150 * level)
    return {'resource': resource, 'amount': amount}


def level_of(points):
    return min(LEVELS, int(points) // POINTS_PER_LEVEL)


class SeasonPass:
    """The pass of one village (privateState.seasonPass), brought up to date with the clock on every use."""

    def __init__(self, save, now=None):
        self.save = save
        self.moment = now_in_argentina(now)
        self.day = self.moment.date()
        self.season, self.key, self.first_day, self.last_day = season_bounds(self.day)
        state = save.setdefault('privateState', {})
        data = state.get('seasonPass')
        if not isinstance(data, dict) or data.get('season') != self.key:
            data = {'season': self.key, 'points': 0, 'claimed': [], 'revision': (data or {}).get('revision', 0)
                    if isinstance(data, dict) else 0}
        state['seasonPass'] = data
        self.data = data
        today, week = self.day.isoformat(), week_key(self.day)
        if data.get('day') != today:
            data.update(day=today, daily={}, daily_done=[], play_today=0)
        if data.get('week') != week:
            data.update(week=week, weekly={}, weekly_done=[])
        self.daily = challenges_of('daily', today, self.key)
        self.weekly = challenges_of('weekly', week, self.key)

    @property
    def points(self):
        return int(self.data.get('points') or 0)

    @property
    def level(self):
        return level_of(self.points)

    def record(self, event, count=1, stars=1, once=None):
        """Count something the player did: play points (capped a day) and challenge progress. Returns points won.
        `once`: an id (a raid's, a duel's) counted only the first time it is reported."""
        if event not in EVENT_POINTS or count <= 0:
            return 0
        if once is not None:
            seen = self.data.setdefault('seen', [])
            mark = f'{event}:{once}'
            if mark in seen:
                return 0
            seen.append(mark)
            del seen[:-SEEN_KEEP]
        won = 0
        base = EVENT_POINTS[event] * count
        if event == 'quest_win':
            base += 10 * max(0, int(stars or 1) - 1) * count
        allowed = max(0, PLAY_POINTS_PER_DAY - int(self.data.get('play_today') or 0))
        play = min(base, allowed)
        self.data['play_today'] = int(self.data.get('play_today') or 0) + play
        won += play
        for kind, challenges in (('daily', self.daily), ('weekly', self.weekly)):
            progress, done = self.data[kind], self.data[f'{kind}_done']
            for challenge in challenges:
                if challenge['event'] != event or challenge['id'] in done:
                    continue
                progress[challenge['id']] = min(challenge['target'], int(progress.get(challenge['id']) or 0) + count)
                if progress[challenge['id']] >= challenge['target']:
                    done.append(challenge['id'])
                    won += challenge['points']
        self.data['points'] = self.points + won
        return won

    def claimable(self):
        claimed = set(self.data.get('claimed') or [])
        return [level for level in range(1, self.level + 1) if level not in claimed]

    def claim(self, levels=None):
        """Give the rewards of the reached levels not claimed yet (all of them, or the ones asked).
        Returns the rewards given, [(level, reward)]."""
        available = self.claimable()
        wanted = available if levels is None else [int(level) for level in levels if int(level) in available]
        given = []
        for level in wanted:
            reward = reward_of(self.season, level)
            _give(self.save, reward)
            self.data.setdefault('claimed', []).append(level)
            given.append((level, reward))
        if given:
            self.data['revision'] = int(self.data.get('revision') or 0) + 1
        return given

    def view(self):
        """Everything the window shows."""
        claimed = set(self.data.get('claimed') or [])
        level = self.level

        def challenge_view(kind, challenges):
            progress, done = self.data[kind], set(self.data[f'{kind}_done'])
            return [{**challenge, 'progress': int(progress.get(challenge['id']) or 0), 'done': challenge['id'] in done}
                    for challenge in challenges]

        tomorrow = datetime.datetime.combine(self.day + datetime.timedelta(days=1), datetime.time(), ARGENTINA)
        monday = self.day + datetime.timedelta(days=7 - self.day.weekday())
        next_week = datetime.datetime.combine(monday, datetime.time(), ARGENTINA)
        season_end = datetime.datetime.combine(self.last_day + datetime.timedelta(days=1), datetime.time(), ARGENTINA)
        return {
            'season': self.season, 'season_key': self.key, 'name': SEASON_NAMES[self.season],
            'year': int(self.key.split('-')[0]),
            'points': self.points, 'level': level, 'levels': LEVELS, 'per_level': POINTS_PER_LEVEL,
            'level_points': self.points - level * POINTS_PER_LEVEL if level < LEVELS else POINTS_PER_LEVEL,
            'play_today': int(self.data.get('play_today') or 0), 'play_cap': PLAY_POINTS_PER_DAY,
            'ends_in': int((season_end - self.moment).total_seconds()),
            'daily_in': int((tomorrow - self.moment).total_seconds()),
            'weekly_in': int((next_week - self.moment).total_seconds()),
            'rewards': [{'level': n, 'reward': reward_of(self.season, n), 'claimed': n in claimed,
                         'reached': n <= level} for n in range(1, LEVELS + 1)],
            'daily': challenge_view('daily', self.daily),
            'weekly': challenge_view('weekly', self.weekly),
        }


def _main_town(save):
    maps = save.get('maps') or []
    return maps[0] if maps else None


def _give(save, reward):
    if 'resource' in reward:
        town = _main_town(save)
        if town is not None:
            town[reward['resource']] = int(town.get(reward['resource']) or 0) + int(reward['amount'])
    elif 'cash' in reward:
        info = save.setdefault('playerInfo', {})
        info['cash'] = int(info.get('cash') or 0) + int(reward['cash'])
    elif 'unit' in reward:
        gifts = save.setdefault('privateState', {}).setdefault('gifts', [])
        item = int(reward['unit'])
        while len(gifts) <= item:
            gifts.append(0)
        gifts[item] = int(gifts[item] or 0) + 1


def record_event(save, event, count=1, stars=1, now=None, once=None):
    """Hook for the game's commands and the web services: counts an action when the pass is on."""
    if not season_pass_enabled() or not isinstance(save, dict):
        return 0
    return SeasonPass(save, now).record(event, count, stars, once)


def revision(save):
    """Changes when rewards are claimed (part of the village revision the game page watches)."""
    data = (save or {}).get('privateState', {}).get('seasonPass') if isinstance(save, dict) else None
    value = int(data.get('revision') or 0) if isinstance(data, dict) else 0
    return f'sp{value}' if value else ''
