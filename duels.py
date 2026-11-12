"""Live duels: challenges in real time, then a battle in the tournament arena.

Enabled only with SE_DUELS=on. A player with a portal or game page open holds
a WebSocket (`/duels/ws`); that makes them "online". The DuelHub keeps the
connections, the pending challenges and the battles in memory (one server
process, like the villages) and applies the rules:

  * nobody challenges themselves; a player sends or receives one challenge at
    a time; at most RATE_LIMIT challenges per player per RATE_WINDOW seconds;
  * a challenge expires after CHALLENGE_SECONDS without an answer;
  * if a participant has no open page for more than RECONNECT_GRACE seconds
    (a reloaded tab reconnects within that time), the challenge is cancelled.

An accepted challenge starts a battle (phase 2, "option B"): both players
enter the game's tournament arena at once, each one commanding their own army
against the other player's army driven by the game's AI. Each army is the
village's ARMY_LIMIT strongest combat troops allowed in tournaments, chosen
here (the game places at most 20 per side). The game reports, through the
tournament services, when the battle starts and which percentage of the
enemy army it destroyed; the server times the battle with its own clock.

  * the higher percentage wins; equal percentages: the faster battle wins;
  * a report is rejected when the battle lasted less than
    BATTLE_MIN_SECONDS, the percentage is not a number from 0 to 100, the
    battle was never started, or the player already reported;
  * each player has BATTLE_DEADLINE_SECONDS from the launch to report. One
    valid report: its author wins. No valid report: the duel is void;
  * a result that is very unlikely for the armies' strengths (the winner's
    army is weaker than SUSPICIOUS_POWER_RATIO times the loser's) does not
    count for the ranking and waits for an administrator's review.

Strength is the sum of balance.pvp_unit_power over the battle army. Duels
between two players whose main village is level RANKED_MIN_LEVEL or more
change their Elo rating (start ELO_START, factor ELO_K); the others are
friendly. Villages are never modified by a duel: the arena fights with
copies; the game itself queues no commands outside its NORMAL mode
(CommandManager.addCommand), and while a player is in the battle the web side
also drops any unit-death command ("kill", "sell" for KILL) of that village.
Messages carry codes and numbers, never text: each page renders them in its
own language.
"""

from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import itertools
import math
import os
import sqlite3
import threading
import time

from balance import pvp_unit_power


def _setting(name, default):
    """A positive number from the environment (SE_DUEL_*), else the default."""
    try:
        value = float(os.environ.get(name, ''))
    except ValueError:
        return default
    return value if math.isfinite(value) and value > 0 else default


# ---- Battle settings: the only place to change them (see DECISIONS.md) ----
BATTLE_MIN_SECONDS = _setting('SE_DUEL_MIN_SECONDS', 20)          # shorter battles are rejected
BATTLE_DEADLINE_SECONDS = _setting('SE_DUEL_DEADLINE_SECONDS', 600)  # time to report, from the launch
SUSPICIOUS_POWER_RATIO = _setting('SE_DUEL_POWER_RATIO', 1 / 3)   # winner weaker than this x loser: review

CHALLENGE_SECONDS = 30
RECONNECT_GRACE = 5
RATE_LIMIT = 5
RATE_WINDOW = 60
ARMY_LIMIT = 20  # the game's tournament arena places at most 20 units per side
ARENA_MAP_ID = 100000040  # tournament_type 1 map in the game config
ARENA_TOURNAMENT_TYPE = 1
RANKED_MIN_LEVEL = 25
ELO_START = 1000
ELO_K = 32
HISTORY_LIMIT = 20
RANKING_LIMIT = 20
REVIEW_LIMIT = 50
UNSEEN_RESULT_SECONDS = 3600  # a result is sent again to a page that reconnects, until it confirms it

SIDES = ('challenger', 'defender')
STATUSES = ('playing', 'done', 'review', 'void')
REPORTS = ('ok', 'missing', 'too_fast', 'invalid', 'not_started')


class DuelError(ValueError):
    """A duel action the player cannot do now; `code` is sent to the page."""

    def __init__(self, code):
        super().__init__(code)
        self.code = code


def _number(value, default=0):
    if isinstance(value, bool):
        return default
    try:
        return int(float(value))
    except (TypeError, ValueError, OverflowError):
        return default


def _not_allowed_units():
    from get_game_config import get_game_config
    values = get_game_config().get('globals', {}).get('TOURNAMENT_UNITS_NOT_ALLOWED', [])
    return {_number(value, -1) for value in values} if isinstance(values, list) else set()


def army_profile(save, limit=ARMY_LIMIT):
    """The village's duel army (read-only): strongest units, strength, level, readiness."""
    from pvp import _combatant, _item, _main_map
    _, town = _main_map(save)
    race = town.get('race', 'h')
    excluded = _not_allowed_units()
    army = []

    def add(unit_id):
        unit = _item(unit_id)
        if unit and _combatant(unit, race) and _number(unit.get('id'), -1) not in excluded:
            army.append((pvp_unit_power(unit), _number(unit['id'])))

    for placed in town.get('items', []):
        if not isinstance(placed, list) or not placed:
            continue
        add(placed[0])
        item = _item(placed[0])
        if item and item.get('type') == 'b' and len(placed) > 6 and isinstance(placed[6], list):
            for unit_id in placed[6]:  # troops sheltered in a building
                add(unit_id)
    army.sort(key=lambda entry: (-entry[0], entry[1]))
    chosen = army[:limit]
    return {
        'power': sum(power for power, _ in chosen),
        'troops': len(chosen),
        'units': [unit_id for _, unit_id in chosen],
        'level': max(1, _number(town.get('level'), 1)),
        'tutorial_complete': _number(save.get('playerInfo', {}).get('completed_tutorial')) == 1,
    }


def elo_update(rating_a, rating_b, score_a, k=ELO_K):
    """New (rating_a, rating_b); score_a is 1 (A wins), 0.5 (draw) or 0 (A loses)."""
    expected_a = 1 / (1 + 10 ** ((rating_b - rating_a) / 400))
    change = round(k * (score_a - expected_a))
    return rating_a + change, rating_b - change


def decide(battle_reports, powers, ratio=None):
    """Outcome of a battle from both reports: (winner, status, review_reason).

    `battle_reports` maps side -> {'status', 'percent', 'seconds'}; `powers`
    maps side -> army strength. Pure function, used by the hub and the tests.
    """
    ratio = SUSPICIOUS_POWER_RATIO if ratio is None else ratio
    valid = [side for side in SIDES if battle_reports[side]['status'] == 'ok']
    if not valid:
        return None, 'void', 'no_reports'
    if len(valid) == 1:
        winner = valid[0]
    else:
        mine, theirs = (battle_reports[side] for side in SIDES)
        if round(mine['percent'], 2) != round(theirs['percent'], 2):
            winner = SIDES[0] if mine['percent'] > theirs['percent'] else SIDES[1]
        elif round(mine['seconds'], 1) != round(theirs['seconds'], 1):
            winner = SIDES[0] if mine['seconds'] < theirs['seconds'] else SIDES[1]
        else:
            return 'draw', 'done', None
    loser = SIDES[1] if winner == SIDES[0] else SIDES[0]
    if powers[winner] < powers[loser] * ratio:
        return winner, 'review', 'power'
    return winner, 'done', None


class DuelStore:
    """Duels and Elo ratings in SQLite (short transactions, like raids)."""

    COLUMNS = """
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        challenger_id INTEGER NOT NULL,
        defender_id INTEGER NOT NULL,
        challenger_power INTEGER NOT NULL,
        defender_power INTEGER NOT NULL,
        ranked INTEGER NOT NULL CHECK (ranked IN (0, 1)),
        status TEXT NOT NULL CHECK (status IN ('playing', 'done', 'review', 'void')),
        winner TEXT CHECK (winner IS NULL OR winner IN ('challenger', 'defender', 'draw')),
        rated INTEGER NOT NULL DEFAULT 0 CHECK (rated IN (0, 1)),
        challenger_report TEXT, defender_report TEXT,
        challenger_percent REAL, defender_percent REAL,
        challenger_seconds REAL, defender_seconds REAL,
        challenger_rating_before INTEGER, challenger_rating_after INTEGER,
        defender_rating_before INTEGER, defender_rating_after INTEGER,
        review_reason TEXT, resolved_by TEXT, resolved_at REAL,
        created_at REAL NOT NULL,
        finished_at REAL
    """

    def __init__(self, database_path):
        self.database_path = str(Path(database_path))
        Path(self.database_path).parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            columns = {row['name'] for row in connection.execute('PRAGMA table_info(duels)')}
            if columns and 'status' not in columns:
                self._migrate_strength_duels(connection)
            connection.executescript(
                f"""
                CREATE TABLE IF NOT EXISTS duels ({self.COLUMNS});
                CREATE INDEX IF NOT EXISTS duels_challenger ON duels (challenger_id, created_at);
                CREATE INDEX IF NOT EXISTS duels_defender ON duels (defender_id, created_at);
                CREATE INDEX IF NOT EXISTS duels_status ON duels (status);
                CREATE TABLE IF NOT EXISTS ratings (
                    account_id INTEGER PRIMARY KEY,
                    rating INTEGER NOT NULL,
                    wins INTEGER NOT NULL DEFAULT 0,
                    losses INTEGER NOT NULL DEFAULT 0,
                    draws INTEGER NOT NULL DEFAULT 0
                );
                """
            )

    def _migrate_strength_duels(self, connection):
        """Phase 1 rows (resolved by strength) become finished duels of the new table."""
        connection.executescript(
            f"""
            DROP INDEX IF EXISTS duels_challenger;
            DROP INDEX IF EXISTS duels_defender;
            ALTER TABLE duels RENAME TO duels_phase1;
            CREATE TABLE duels ({self.COLUMNS});
            INSERT INTO duels (id, challenger_id, defender_id, challenger_power, defender_power, ranked, status,
                               winner, rated, challenger_rating_before, challenger_rating_after,
                               defender_rating_before, defender_rating_after, created_at, finished_at)
                SELECT id, challenger_id, defender_id, challenger_power, defender_power, ranked, 'done',
                       winner, ranked, challenger_rating_before, challenger_rating_after,
                       defender_rating_before, defender_rating_after, created_at, created_at
                FROM duels_phase1;
            DROP TABLE duels_phase1;
            """
        )

    @contextmanager
    def _connection(self):
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    @staticmethod
    def _rating(connection, account_id):
        row = connection.execute('SELECT rating FROM ratings WHERE account_id = ?', (account_id,)).fetchone()
        return row['rating'] if row else ELO_START

    def rating(self, account_id):
        with self._connection() as connection:
            return self._rating(connection, account_id)

    def get(self, duel_id):
        with self._connection() as connection:
            row = connection.execute('SELECT * FROM duels WHERE id = ?', (duel_id,)).fetchone()
            return dict(row) if row else None

    def create(self, challenger_id, defender_id, challenger_power, defender_power, ranked, now):
        """A duel whose battle is starting (status 'playing'); returns its id."""
        with self._connection() as connection:
            cursor = connection.execute(
                """INSERT INTO duels (challenger_id, defender_id, challenger_power, defender_power, ranked, status,
                       created_at) VALUES (?, ?, ?, ?, ?, 'playing', ?)""",
                (challenger_id, defender_id, challenger_power, defender_power, int(bool(ranked)), now))
            return cursor.lastrowid

    def _apply_rating(self, connection, duel):
        """Update both Elo ratings for a finished ranked duel and store before/after."""
        score = {'challenger': 1, 'defender': 0, 'draw': 0.5}[duel['winner']]
        before_c = self._rating(connection, duel['challenger_id'])
        before_d = self._rating(connection, duel['defender_id'])
        after_c, after_d = elo_update(before_c, before_d, score)
        for account_id, rating, result in ((duel['challenger_id'], after_c, score), (duel['defender_id'], after_d, 1 - score)):
            column = 'wins' if result == 1 else 'losses' if result == 0 else 'draws'
            connection.execute(
                f"""INSERT INTO ratings (account_id, rating, {column}) VALUES (?, ?, 1)
                    ON CONFLICT(account_id) DO UPDATE SET rating = excluded.rating, {column} = {column} + 1""",
                (account_id, rating))
        connection.execute(
            """UPDATE duels SET rated = 1, challenger_rating_before = ?, challenger_rating_after = ?,
                   defender_rating_before = ?, defender_rating_after = ? WHERE id = ?""",
            (before_c, after_c, before_d, after_d, duel['id']))

    def finish(self, duel_id, winner, status, review_reason, reports, now):
        """Close a playing duel with its outcome; ranked 'done' duels change the ratings."""
        with self._connection() as connection:
            connection.execute('BEGIN IMMEDIATE')
            row = connection.execute("SELECT * FROM duels WHERE id = ? AND status = 'playing'", (duel_id,)).fetchone()
            if not row:
                return None
            connection.execute(
                """UPDATE duels SET status = ?, winner = ?, review_reason = ?, finished_at = ?,
                       challenger_report = ?, challenger_percent = ?, challenger_seconds = ?,
                       defender_report = ?, defender_percent = ?, defender_seconds = ? WHERE id = ?""",
                (status, winner, review_reason, now,
                 reports['challenger']['status'], reports['challenger']['percent'], reports['challenger']['seconds'],
                 reports['defender']['status'], reports['defender']['percent'], reports['defender']['seconds'], duel_id))
            duel = dict(connection.execute('SELECT * FROM duels WHERE id = ?', (duel_id,)).fetchone())
            if status == 'done' and duel['ranked']:
                self._apply_rating(connection, duel)
            return dict(connection.execute('SELECT * FROM duels WHERE id = ?', (duel_id,)).fetchone())

    def resolve(self, duel_id, action, admin_name, now):
        """An administrator validates ('validate') or voids ('void') a duel under review."""
        if action not in ('validate', 'void'):
            raise DuelError('invalid')
        with self._connection() as connection:
            connection.execute('BEGIN IMMEDIATE')
            row = connection.execute("SELECT * FROM duels WHERE id = ? AND status = 'review'", (duel_id,)).fetchone()
            if not row:
                raise DuelError('gone')
            status = 'done' if action == 'validate' else 'void'
            connection.execute('UPDATE duels SET status = ?, resolved_by = ?, resolved_at = ? WHERE id = ?',
                               (status, admin_name, now, duel_id))
            duel = dict(connection.execute('SELECT * FROM duels WHERE id = ?', (duel_id,)).fetchone())
            if status == 'done' and duel['ranked'] and duel['winner']:
                self._apply_rating(connection, duel)
            return dict(connection.execute('SELECT * FROM duels WHERE id = ?', (duel_id,)).fetchone())

    def void_unfinished(self, now):
        """Battles cut by a server restart cannot be finished: void them."""
        with self._connection() as connection:
            return connection.execute(
                """UPDATE duels SET status = 'void', review_reason = 'restart', finished_at = ?
                   WHERE status = 'playing'""", (now,)).rowcount

    def reviews(self, limit=REVIEW_LIMIT):
        """Duels waiting for review first, then the latest resolved by an administrator."""
        with self._connection() as connection:
            pending = [dict(row) for row in connection.execute(
                "SELECT * FROM duels WHERE status = 'review' ORDER BY created_at, id LIMIT ?", (limit,))]
            resolved = [dict(row) for row in connection.execute(
                """SELECT * FROM duels WHERE resolved_by IS NOT NULL
                   ORDER BY resolved_at DESC, id DESC LIMIT ?""", (limit,))]
            return pending, resolved

    def ranking(self, limit=RANKING_LIMIT):
        with self._connection() as connection:
            return [dict(row) for row in connection.execute(
                'SELECT * FROM ratings ORDER BY rating DESC, wins DESC, account_id LIMIT ?', (limit,))]

    def history(self, account_id, limit=HISTORY_LIMIT):
        with self._connection() as connection:
            return [dict(row) for row in connection.execute(
                """SELECT * FROM duels WHERE (challenger_id = ? OR defender_id = ?) AND status != 'playing'
                   ORDER BY created_at DESC, id DESC LIMIT ?""", (account_id, account_id, limit))]

    def count(self, status=None):
        with self._connection() as connection:
            if status:
                return connection.execute('SELECT COUNT(*) FROM duels WHERE status = ?', (status,)).fetchone()[0]
            return connection.execute('SELECT COUNT(*) FROM duels').fetchone()[0]


def parse_percent(value):
    """The percentage a game reported, or None when it is not a number from 0 to 100."""
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(number) or number < 0 or number > 100:
        return None
    return number


class DuelHub:
    """Online players, pending challenges and battles (in memory, thread-safe)."""

    def __init__(self, store, profile, clock=time.time):
        """`profile(account_id)` -> {'name', 'level', 'power', 'troops', 'units', 'tutorial_complete'} or None."""
        self.store = store
        self.profile = profile
        self.clock = clock
        self.lock = threading.RLock()
        self.connections = {}     # account_id -> {connection_id: send}
        self.names = {}           # account_id -> display name
        self.offline_since = {}   # account_id -> time its last page closed
        self.challenges = {}      # challenge id -> challenge dict
        self.battles = {}         # duel id -> battle dict
        self.sent_times = {}      # account_id -> [times of challenges sent]
        self.arena_until = {}     # account_id -> time until which arena commands are dropped
        self.unseen = {}          # account_id -> (time, result message) not yet confirmed by a page
        self._ids = itertools.count(1)
        store.void_unfinished(clock())

    # -- connections --
    def connect(self, account_id, name, send):
        with self.lock:
            connection_id = next(self._ids)
            self.connections.setdefault(account_id, {})[connection_id] = send
            self.names[account_id] = name
            self.offline_since.pop(account_id, None)
            self._send_one(send, {'type': 'hello', 'you': account_id, 'online': self._online()})
            for challenge in self.challenges.values():  # a reloaded page gets its pending challenge back
                if account_id in (challenge['from'], challenge['to']):
                    self._send_one(send, self._challenge_message(challenge, account_id))
            battle = self._battle_for(account_id)
            if battle:  # ... and its battle: the arena again, or the wait for the rival
                self._send_one(send, self._battle_message(battle, account_id))
            unseen = self.unseen.get(account_id)
            if unseen and self.clock() - unseen[0] < UNSEEN_RESULT_SECONDS:  # ... or a result it missed
                self._send_one(send, unseen[1])
            self._broadcast_presence()
            return connection_id

    def disconnect(self, account_id, connection_id):
        with self.lock:
            pages = self.connections.get(account_id, {})
            pages.pop(connection_id, None)
            if not pages:
                self.connections.pop(account_id, None)
                self.offline_since[account_id] = self.clock()
            self._broadcast_presence()

    def is_online(self, account_id):
        with self.lock:
            return bool(self.connections.get(account_id))

    def _busy_players(self):
        busy = {player for challenge in self.challenges.values() for player in (challenge['from'], challenge['to'])}
        busy.update(player for battle in self.battles.values() for player in battle['players'].values())
        return busy

    def _online(self):
        busy = self._busy_players()
        return [{'id': account_id, 'name': self.names.get(account_id, ''), 'busy': account_id in busy}
                for account_id in sorted(self.connections)]

    # -- sending --
    @staticmethod
    def _send_one(send, message):
        try:
            send(message)
        except Exception:  # a closing socket must never break the hub
            pass

    def _send(self, account_id, message):
        for send in list(self.connections.get(account_id, {}).values()):
            self._send_one(send, message)

    def _broadcast_presence(self):
        message = {'type': 'presence', 'online': self._online()}
        for account_id in list(self.connections):
            self._send(account_id, message)

    def _challenge_message(self, challenge, viewer):
        sent = viewer == challenge['from']
        other = challenge['to'] if sent else challenge['from']
        return {'type': 'challenge_sent' if sent else 'challenge_received', 'id': challenge['id'],
                'other': {'id': other, 'name': self.names.get(other, '')},
                'expires_in': max(0, round(challenge['expires_at'] - self.clock()))}

    # -- challenges --
    def _pending_for(self, account_id):
        return next((c for c in self.challenges.values() if account_id in (c['from'], c['to'])), None)

    def challenge(self, from_id, to_id):
        with self.lock:
            now = self.clock()
            if from_id == to_id:
                raise DuelError('self')
            if not self.connections.get(to_id):
                raise DuelError('offline')
            if self._pending_for(from_id) or self._battle_for(from_id):
                raise DuelError('busy')
            if self._pending_for(to_id) or self._battle_for(to_id):
                raise DuelError('target_busy')
            recent = [t for t in self.sent_times.get(from_id, []) if now - t < RATE_WINDOW]
            if len(recent) >= RATE_LIMIT:
                raise DuelError('rate_limited')
            mine, theirs = self.profile(from_id), self.profile(to_id)
            if not mine or not mine['tutorial_complete']:
                raise DuelError('tutorial')
            if not mine['troops']:
                raise DuelError('no_troops')
            if not theirs or not theirs['tutorial_complete'] or not theirs['troops']:
                raise DuelError('target_not_ready')
            recent.append(now)
            self.sent_times[from_id] = recent
            challenge = {'id': next(self._ids), 'from': from_id, 'to': to_id, 'created_at': now,
                         'expires_at': now + CHALLENGE_SECONDS}
            self.challenges[challenge['id']] = challenge
            self._send(from_id, self._challenge_message(challenge, from_id))
            self._send(to_id, self._challenge_message(challenge, to_id))
            self._broadcast_presence()
            return challenge

    def _close(self, challenge, reason, by=None):
        self.challenges.pop(challenge['id'], None)
        message = {'type': 'challenge_closed', 'id': challenge['id'], 'reason': reason}
        if by is not None:
            message['by'] = {'id': by, 'name': self.names.get(by, '')}
        for account_id in (challenge['from'], challenge['to']):
            self._send(account_id, message)
        self._broadcast_presence()

    def respond(self, account_id, challenge_id, accept):
        with self.lock:
            challenge = self.challenges.get(challenge_id)
            if not challenge or challenge['to'] != account_id:
                raise DuelError('gone')
            if not accept:
                self._close(challenge, 'declined', by=account_id)
                return None
            return self._launch(challenge)

    def cancel(self, account_id, challenge_id):
        with self.lock:
            challenge = self.challenges.get(challenge_id)
            if not challenge or challenge['from'] != account_id:
                raise DuelError('gone')
            self._close(challenge, 'cancelled', by=account_id)

    # -- battles --
    def _battle_for(self, account_id):
        return next((b for b in self.battles.values() if account_id in b['players'].values()), None)

    @staticmethod
    def _side_of(battle, account_id):
        return 'challenger' if battle['players']['challenger'] == account_id else 'defender'

    def _launch(self, challenge):
        """Both players enter the arena: create the duel and send each one both armies."""
        challenger, defender = challenge['from'], challenge['to']
        mine, theirs = self.profile(challenger), self.profile(defender)
        if not mine or not theirs or not mine['troops'] or not theirs['troops']:
            self._close(challenge, 'cancelled')
            return None
        self.challenges.pop(challenge['id'], None)
        now = self.clock()
        ranked = mine['level'] >= RANKED_MIN_LEVEL and theirs['level'] >= RANKED_MIN_LEVEL
        duel_id = self.store.create(challenger, defender, mine['power'], theirs['power'], ranked, now)
        battle = {
            'id': duel_id, 'challenge_id': challenge['id'], 'ranked': ranked, 'launched_at': now,
            'deadline': now + BATTLE_DEADLINE_SECONDS,
            'players': {'challenger': challenger, 'defender': defender},
            'profiles': {'challenger': mine, 'defender': theirs},
            'started': {'challenger': None, 'defender': None},
            'reports': {side: {'status': None, 'percent': None, 'seconds': None, 'at': None} for side in SIDES},
        }
        self.battles[duel_id] = battle
        for account_id in (challenger, defender):
            self._send(account_id, self._battle_message(battle, account_id))
        self._broadcast_presence()
        return battle

    def _battle_message(self, battle, viewer):
        side = self._side_of(battle, viewer)
        other = 'defender' if side == 'challenger' else 'challenger'
        seconds_left = max(0, round(battle['deadline'] - self.clock()))
        if battle['reports'][side]['status']:
            return {'type': 'duel_waiting', 'id': battle['id'], 'seconds_left': seconds_left,
                    'other': {'id': battle['players'][other], 'name': self.names.get(battle['players'][other], '')}}
        return {'type': 'duel_start', 'id': battle['id'], 'side': side, 'seconds_left': seconds_left,
                'you': {'id': viewer, 'name': self.names.get(viewer, battle['profiles'][side]['name'])},
                'ranked': battle['ranked'], 'arena': ARENA_MAP_ID, 'tournament_type': ARENA_TOURNAMENT_TYPE,
                'other': {'id': battle['players'][other],
                          'name': self.names.get(battle['players'][other], battle['profiles'][other]['name'])},
                'army': list(battle['profiles'][side]['units']),
                'enemy_army': list(battle['profiles'][other]['units'])}

    def start_match(self, account_id):
        """The game opened the battle (start_tournament_match): start this player's clock once."""
        with self.lock:
            battle = self._battle_for(account_id)
            if not battle:
                raise DuelError('no_battle')
            side = self._side_of(battle, account_id)
            if battle['reports'][side]['status']:
                raise DuelError('already_reported')
            now = self.clock()
            if battle['started'][side] is None:
                battle['started'][side] = now
            self.arena_until[account_id] = battle['deadline']
            return battle

    def report(self, account_id, percent_value):
        """The game finished the battle (finish_tournament_match) with this percentage."""
        with self.lock:
            battle = self._battle_for(account_id)
            if not battle:
                raise DuelError('no_battle')
            side = self._side_of(battle, account_id)
            entry = battle['reports'][side]
            if entry['status']:
                raise DuelError('already_reported')
            now = self.clock()
            started = battle['started'][side]
            percent = parse_percent(percent_value)
            if started is None:
                entry['status'] = 'not_started'
            elif percent is None:
                entry['status'] = 'invalid'
            elif now - started < BATTLE_MIN_SECONDS:
                entry['status'] = 'too_fast'
            else:
                entry.update(status='ok', percent=round(percent, 2), seconds=round(now - started, 1))
            entry['at'] = now
            self.arena_until.pop(account_id, None)  # back to the village: its commands count again
            if all(battle['reports'][s]['status'] for s in SIDES):
                return self._finish(battle)
            self._send(account_id, self._battle_message(battle, account_id))
            return None

    def _finish(self, battle):
        """Decide, store and tell both players the same result."""
        self.battles.pop(battle['id'], None)
        for account_id in battle['players'].values():
            self.arena_until.pop(account_id, None)
        now = self.clock()
        reports = {side: {'status': battle['reports'][side]['status'] or 'missing',
                          'percent': battle['reports'][side]['percent'],
                          'seconds': battle['reports'][side]['seconds']} for side in SIDES}
        powers = {side: battle['profiles'][side]['power'] for side in SIDES}
        winner, status, reason = decide(reports, powers)
        duel = self.store.finish(battle['id'], winner, status, reason, reports, now)
        if duel is None:
            return None
        result = self.result_message(duel, battle['profiles'])
        self.deliver_result(result)
        self._broadcast_presence()
        return result

    def deliver_result(self, result):
        """Send a result to both players and keep it until a page of each confirms it ('seen')."""
        with self.lock:
            for side in SIDES:
                account_id = result[side]['id']
                self.unseen[account_id] = (self.clock(), result)
                self._send(account_id, result)

    def seen(self, account_id, duel_id):
        with self.lock:
            unseen = self.unseen.get(account_id)
            if unseen and unseen[1]['id'] == duel_id:
                self.unseen.pop(account_id, None)

    def result_message(self, duel, profiles=None):
        """The same result message for both players (codes and numbers only)."""
        message = {'type': 'duel_result', 'id': duel['id'], 'ranked': bool(duel['ranked']), 'rated': bool(duel['rated']),
                   'status': duel['status'], 'winner': duel['winner'], 'review_reason': duel['review_reason']}
        for side in SIDES:
            account_id = duel[f'{side}_id']
            profile = (profiles or {}).get(side) or {}
            message[side] = {'id': account_id, 'name': self.names.get(account_id, profile.get('name', '')),
                             'power': duel[f'{side}_power'], 'troops': profile.get('troops'), 'level': profile.get('level'),
                             'report': duel[f'{side}_report'], 'percent': duel[f'{side}_percent'],
                             'seconds': duel[f'{side}_seconds'],
                             'rating_before': duel[f'{side}_rating_before'], 'rating_after': duel[f'{side}_rating_after']}
        return message

    def guards_commands(self, account_id):
        """True while the player is in the arena battle (from "start" to the report or the deadline)."""
        with self.lock:
            return self.clock() < self.arena_until.get(account_id, 0)

    def sweep(self):
        """Expire unanswered challenges, cancel those whose player left, close late battles."""
        with self.lock:
            now = self.clock()
            for challenge in list(self.challenges.values()):
                if now >= challenge['expires_at']:
                    self._close(challenge, 'expired')
                    continue
                for account_id in (challenge['from'], challenge['to']):
                    left = self.offline_since.get(account_id)
                    if not self.connections.get(account_id) and left is not None and now - left >= RECONNECT_GRACE:
                        self._close(challenge, 'disconnected', by=account_id)
                        break
            for battle in list(self.battles.values()):
                if now >= battle['deadline']:
                    self._finish(battle)

    def handle(self, account_id, message):
        """Apply one message from a page; errors go back to that player only."""
        try:
            if not isinstance(message, dict):
                raise DuelError('invalid')
            kind = message.get('type')
            if kind == 'challenge':
                self.challenge(account_id, _number(message.get('to'), -1))
            elif kind == 'respond':
                self.respond(account_id, _number(message.get('id'), -1), bool(message.get('accept')))
            elif kind == 'cancel':
                self.cancel(account_id, _number(message.get('id'), -1))
            elif kind == 'seen':
                self.seen(account_id, _number(message.get('id'), -1))
            elif kind != 'ping':
                raise DuelError('invalid')
        except DuelError as error:
            with self.lock:
                self._send(account_id, {'type': 'error', 'code': error.code})


def start_sweeper(hub, interval=1.0):
    """Background thread calling hub.sweep() every `interval` seconds."""
    def run():
        while True:
            time.sleep(interval)
            try:
                hub.sweep()
            except Exception:
                pass
    thread = threading.Thread(target=run, name='duel-sweeper', daemon=True)
    thread.start()
    return thread


def utc_label(timestamp):
    return datetime.fromtimestamp(timestamp, timezone.utc).strftime('%d/%m/%Y %H:%M UTC')
