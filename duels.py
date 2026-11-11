"""Live duel challenges, resolved by army strength on the server (phase 1).

Enabled only with SE_DUELS=on. A player with a portal or game page open holds
a WebSocket (`/duels/ws`); that makes them "online". The DuelHub keeps the
connections and the pending challenges in memory (one server process, like the
villages) and applies the rules:

  * nobody challenges themselves; a player sends or receives one challenge at
    a time; at most RATE_LIMIT challenges per player per RATE_WINDOW seconds;
  * a challenge expires after CHALLENGE_SECONDS without an answer;
  * if a participant has no open page for more than RECONNECT_GRACE seconds
    (a reloaded tab reconnects within that time), the challenge is cancelled.

An accepted challenge is resolved at once like the Rivals raids: each army's
strength is the sum of balance.pvp_unit_power over its ARMY_LIMIT strongest
combat troops (troops of the village's race, loose or sheltered). The stronger
army wins; equal strength is a draw. Villages are never modified by a duel.
Both players receive the same result message. Duels between two players whose
main village is level RANKED_MIN_LEVEL or more change their Elo rating
(start ELO_START, factor ELO_K); other duels are recorded as friendly.
Messages carry codes and numbers, never text: each page renders them in its
own language.
"""

from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import itertools
import sqlite3
import threading
import time

from balance import pvp_unit_power

CHALLENGE_SECONDS = 30
RECONNECT_GRACE = 5
RATE_LIMIT = 5
RATE_WINDOW = 60
ARMY_LIMIT = 30  # like the survival mode's "your 30 most powerful units"
RANKED_MIN_LEVEL = 25
ELO_START = 1000
ELO_K = 32
HISTORY_LIMIT = 20
RANKING_LIMIT = 20


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
    except (TypeError, ValueError):
        return default


def army_profile(save, limit=ARMY_LIMIT):
    """Strength of a village's duel army (read-only), with level and readiness."""
    from pvp import _combatant, _item, _main_map
    _, town = _main_map(save)
    race = town.get('race', 'h')
    powers = []
    for placed in town.get('items', []):
        if not isinstance(placed, list) or not placed:
            continue
        item = _item(placed[0])
        if item and _combatant(item, race):
            powers.append(pvp_unit_power(item))
        if item and item.get('type') == 'b' and len(placed) > 6 and isinstance(placed[6], list):
            for unit_id in placed[6]:
                unit = _item(unit_id)
                if unit and _combatant(unit, race):
                    powers.append(pvp_unit_power(unit))
    powers.sort(reverse=True)
    return {
        'power': sum(powers[:limit]),
        'troops': min(len(powers), limit),
        'level': max(1, _number(town.get('level'), 1)),
        'tutorial_complete': _number(save.get('playerInfo', {}).get('completed_tutorial')) == 1,
    }


def elo_update(rating_a, rating_b, score_a, k=ELO_K):
    """New (rating_a, rating_b); score_a is 1 (A wins), 0.5 (draw) or 0 (A loses)."""
    expected_a = 1 / (1 + 10 ** ((rating_b - rating_a) / 400))
    change = round(k * (score_a - expected_a))
    return rating_a + change, rating_b - change


class DuelStore:
    """Duel results and Elo ratings in SQLite (short transactions, like raids)."""

    def __init__(self, database_path):
        self.database_path = str(Path(database_path))
        Path(self.database_path).parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS duels (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    challenger_id INTEGER NOT NULL,
                    defender_id INTEGER NOT NULL,
                    challenger_power INTEGER NOT NULL,
                    defender_power INTEGER NOT NULL,
                    winner TEXT NOT NULL CHECK (winner IN ('challenger', 'defender', 'draw')),
                    ranked INTEGER NOT NULL CHECK (ranked IN (0, 1)),
                    challenger_rating_before INTEGER, challenger_rating_after INTEGER,
                    defender_rating_before INTEGER, defender_rating_after INTEGER,
                    created_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS duels_challenger ON duels (challenger_id, created_at);
                CREATE INDEX IF NOT EXISTS duels_defender ON duels (defender_id, created_at);
                CREATE TABLE IF NOT EXISTS ratings (
                    account_id INTEGER PRIMARY KEY,
                    rating INTEGER NOT NULL,
                    wins INTEGER NOT NULL DEFAULT 0,
                    losses INTEGER NOT NULL DEFAULT 0,
                    draws INTEGER NOT NULL DEFAULT 0
                );
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

    def record(self, challenger_id, defender_id, challenger_power, defender_power, ranked, now):
        """Store one resolved duel and, if ranked, update both ratings atomically."""
        if challenger_power > defender_power:
            winner, score = 'challenger', 1
        elif challenger_power < defender_power:
            winner, score = 'defender', 0
        else:
            winner, score = 'draw', 0.5
        with self._connection() as connection:
            connection.execute('BEGIN IMMEDIATE')
            ratings = [None, None, None, None]
            if ranked:
                before_c = self._rating(connection, challenger_id)
                before_d = self._rating(connection, defender_id)
                after_c, after_d = elo_update(before_c, before_d, score)
                ratings = [before_c, after_c, before_d, after_d]
                for account_id, rating, result in ((challenger_id, after_c, score), (defender_id, after_d, 1 - score)):
                    column = 'wins' if result == 1 else 'losses' if result == 0 else 'draws'
                    connection.execute(
                        f"""INSERT INTO ratings (account_id, rating, {column}) VALUES (?, ?, 1)
                            ON CONFLICT(account_id) DO UPDATE SET rating = excluded.rating, {column} = {column} + 1""",
                        (account_id, rating))
            cursor = connection.execute(
                """INSERT INTO duels (challenger_id, defender_id, challenger_power, defender_power, winner, ranked,
                       challenger_rating_before, challenger_rating_after, defender_rating_before, defender_rating_after,
                       created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (challenger_id, defender_id, challenger_power, defender_power, winner, int(bool(ranked)), *ratings, now))
            return dict(connection.execute('SELECT * FROM duels WHERE id = ?', (cursor.lastrowid,)).fetchone())

    def ranking(self, limit=RANKING_LIMIT):
        with self._connection() as connection:
            return [dict(row) for row in connection.execute(
                'SELECT * FROM ratings ORDER BY rating DESC, wins DESC, account_id LIMIT ?', (limit,))]

    def history(self, account_id, limit=HISTORY_LIMIT):
        with self._connection() as connection:
            return [dict(row) for row in connection.execute(
                """SELECT * FROM duels WHERE challenger_id = ? OR defender_id = ?
                   ORDER BY created_at DESC, id DESC LIMIT ?""", (account_id, account_id, limit))]

    def count(self):
        with self._connection() as connection:
            return connection.execute('SELECT COUNT(*) FROM duels').fetchone()[0]


class DuelHub:
    """Online players and pending challenges (in memory, thread-safe)."""

    def __init__(self, store, profile, clock=time.time):
        """`profile(account_id)` -> {'name', 'level', 'power', 'troops', 'tutorial_complete'} or None."""
        self.store = store
        self.profile = profile
        self.clock = clock
        self.lock = threading.RLock()
        self.connections = {}     # account_id -> {connection_id: send}
        self.names = {}           # account_id -> display name
        self.offline_since = {}   # account_id -> time its last page closed
        self.challenges = {}      # challenge id -> challenge dict
        self.sent_times = {}      # account_id -> [times of challenges sent]
        self._ids = itertools.count(1)

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

    def _online(self):
        busy = {player for challenge in self.challenges.values() for player in (challenge['from'], challenge['to'])}
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
            if self._pending_for(from_id):
                raise DuelError('busy')
            if self._pending_for(to_id):
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
            self.challenges.pop(challenge_id, None)
            return self._resolve(challenge)

    def cancel(self, account_id, challenge_id):
        with self.lock:
            challenge = self.challenges.get(challenge_id)
            if not challenge or challenge['from'] != account_id:
                raise DuelError('gone')
            self._close(challenge, 'cancelled', by=account_id)

    def _resolve(self, challenge):
        challenger, defender = challenge['from'], challenge['to']
        mine, theirs = self.profile(challenger), self.profile(defender)
        if not mine or not theirs or not mine['troops'] or not theirs['troops']:
            self._close(challenge, 'cancelled')
            return None
        ranked = mine['level'] >= RANKED_MIN_LEVEL and theirs['level'] >= RANKED_MIN_LEVEL
        duel = self.store.record(challenger, defender, mine['power'], theirs['power'], ranked, self.clock())
        result = {'type': 'duel_result', 'id': duel['id'], 'challenge_id': challenge['id'], 'ranked': bool(duel['ranked']),
                  'winner': duel['winner'],
                  'challenger': {'id': challenger, 'name': self.names.get(challenger, mine['name']), 'power': duel['challenger_power'],
                                 'troops': mine['troops'], 'level': mine['level'],
                                 'rating_before': duel['challenger_rating_before'], 'rating_after': duel['challenger_rating_after']},
                  'defender': {'id': defender, 'name': self.names.get(defender, theirs['name']), 'power': duel['defender_power'],
                               'troops': theirs['troops'], 'level': theirs['level'],
                               'rating_before': duel['defender_rating_before'], 'rating_after': duel['defender_rating_after']}}
        for account_id in (challenger, defender):  # the same message, sent to both
            self._send(account_id, result)
        self._broadcast_presence()
        return result

    def sweep(self):
        """Expire unanswered challenges and cancel those whose player left."""
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
