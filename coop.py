"""Clan raids: the room where up to three members of a clan gather before an adventure (point 28, COOP_PLAN.md).

A room belongs to its host (the player who chose Clan before sailing to an island) and to one clan. The host
invites members of the same clan; each one accepts or declines and chooses at most TEAM_UNITS units with the
game's team window. A player is in one open room at a time. Rooms left alone for ROOM_IDLE_SECONDS close.
Stored in instance/coop.sqlite3 (short transactions, like the other stores).
"""

import json
import sqlite3
import threading
import time
from contextlib import closing

MAX_PLAYERS = 3
TEAM_UNITS = 10
ROOM_IDLE_SECONDS = 30 * 60
ACTIVE_STATES = ('host', 'invited', 'accepted')


class CoopError(Exception):
    """A room action the rules refuse; `code` names the reason for the page."""

    def __init__(self, code):
        super().__init__(code)
        self.code = code


def clean_team(team):
    """The unit ids of a team from the game's window (0 for an empty place): at most TEAM_UNITS real ones."""
    if not isinstance(team, list) or len(team) > 20:
        raise CoopError('team')
    units = []
    for unit in team:
        if isinstance(unit, bool) or not isinstance(unit, int) or not 0 <= unit < 1_000_000:
            raise CoopError('team')
        if unit:
            units.append(unit)
    if not units or len(units) > TEAM_UNITS:
        raise CoopError('team')
    return units


class CoopStore:
    def __init__(self, path, clock=time.time):
        self.path = str(path)
        self.clock = clock
        self.lock = threading.RLock()
        with self._connection() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS rooms (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    clan_id INTEGER NOT NULL,
                    host_id INTEGER NOT NULL,
                    quest_id TEXT NOT NULL,
                    status TEXT NOT NULL,            -- open, sailing, done, cancelled
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS room_players (
                    room_id INTEGER NOT NULL,
                    account_id INTEGER NOT NULL,
                    state TEXT NOT NULL,             -- host, invited, accepted, declined, left
                    team TEXT,                       -- JSON list of unit ids, NULL until chosen
                    updated_at REAL NOT NULL,
                    PRIMARY KEY (room_id, account_id)
                );
                CREATE INDEX IF NOT EXISTS room_players_account ON room_players (account_id);
            """)

    def _connection(self):
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        return closing(connection)

    # -- reading --
    def _expire(self, connection):
        cutoff = self.clock() - ROOM_IDLE_SECONDS
        connection.execute("UPDATE rooms SET status = 'cancelled', updated_at = ? WHERE status = 'open' AND updated_at < ?",
                           (self.clock(), cutoff))

    def _room(self, connection, room_id):
        row = connection.execute('SELECT * FROM rooms WHERE id = ?', (room_id,)).fetchone()
        if not row:
            return None
        room = dict(row)
        room['players'] = []
        for player in connection.execute('SELECT * FROM room_players WHERE room_id = ? ORDER BY rowid', (room_id,)):
            player = dict(player)
            player['team'] = json.loads(player['team']) if player['team'] else None
            room['players'].append(player)
        return room

    def _open_room_of(self, connection, account_id):
        row = connection.execute(
            f"""SELECT r.id FROM rooms r JOIN room_players p ON p.room_id = r.id
                WHERE p.account_id = ? AND r.status = 'open' AND p.state IN ('host', 'accepted')
                ORDER BY r.id DESC LIMIT 1""", (account_id,)).fetchone()
        return row['id'] if row else None

    def room_of(self, account_id):
        """The open room the player hosts or joined, or None."""
        with self.lock, self._connection() as connection, connection:
            self._expire(connection)
            room_id = self._open_room_of(connection, account_id)
            return self._room(connection, room_id) if room_id else None

    def invites_of(self, account_id):
        """The open rooms that invited the player and are waiting for an answer."""
        with self.lock, self._connection() as connection, connection:
            self._expire(connection)
            rows = connection.execute(
                """SELECT r.id FROM rooms r JOIN room_players p ON p.room_id = r.id
                   WHERE p.account_id = ? AND p.state = 'invited' AND r.status = 'open' ORDER BY r.id""",
                (account_id,)).fetchall()
            return [self._room(connection, row['id']) for row in rows]

    def room(self, room_id):
        with self.lock, self._connection() as connection:
            return self._room(connection, room_id)

    # -- acting --
    def _touch(self, connection, room_id):
        connection.execute('UPDATE rooms SET updated_at = ? WHERE id = ?', (self.clock(), room_id))

    def create(self, host_id, clan_id, quest_id, team):
        """A new room hosted by the player, with the host's team; one open room per player."""
        units = clean_team(team)
        quest = str(quest_id or '').strip()
        if not quest or len(quest) > 20:
            raise CoopError('quest')
        with self.lock, self._connection() as connection, connection:
            self._expire(connection)
            if self._open_room_of(connection, host_id):
                raise CoopError('busy')
            now = self.clock()
            room_id = connection.execute(
                "INSERT INTO rooms (clan_id, host_id, quest_id, status, created_at, updated_at) VALUES (?, ?, ?, 'open', ?, ?)",
                (clan_id, host_id, quest, now, now)).lastrowid
            connection.execute("INSERT INTO room_players (room_id, account_id, state, team, updated_at) VALUES (?, ?, 'host', ?, ?)",
                               (room_id, host_id, json.dumps(units), now))
            return self._room(connection, room_id)

    def invite(self, host_id, room_id, guest_id, guest_clan_id):
        with self.lock, self._connection() as connection, connection:
            self._expire(connection)
            room = self._room(connection, room_id)
            if not room or room['status'] != 'open':
                raise CoopError('gone')
            if room['host_id'] != host_id:
                raise CoopError('forbidden')
            if guest_id == host_id or guest_clan_id != room['clan_id']:
                raise CoopError('clan')
            active = [p for p in room['players'] if p['state'] in ACTIVE_STATES]
            if any(p['account_id'] == guest_id for p in active):
                raise CoopError('already')
            if len(active) >= MAX_PLAYERS:
                raise CoopError('full')
            connection.execute(
                """INSERT INTO room_players (room_id, account_id, state, team, updated_at) VALUES (?, ?, 'invited', NULL, ?)
                   ON CONFLICT (room_id, account_id) DO UPDATE SET state = 'invited', team = NULL, updated_at = excluded.updated_at""",
                (room_id, guest_id, self.clock()))
            self._touch(connection, room_id)
            return self._room(connection, room_id)

    def respond(self, account_id, room_id, accept):
        with self.lock, self._connection() as connection, connection:
            self._expire(connection)
            room = self._room(connection, room_id)
            if not room or room['status'] != 'open':
                raise CoopError('gone')
            me = next((p for p in room['players'] if p['account_id'] == account_id), None)
            if not me or me['state'] != 'invited':
                raise CoopError('forbidden')
            if accept:
                if self._open_room_of(connection, account_id):
                    raise CoopError('busy')
                if sum(1 for p in room['players'] if p['state'] in ('host', 'accepted')) >= MAX_PLAYERS:
                    raise CoopError('full')
            connection.execute('UPDATE room_players SET state = ?, updated_at = ? WHERE room_id = ? AND account_id = ?',
                               ('accepted' if accept else 'declined', self.clock(), room_id, account_id))
            self._touch(connection, room_id)
            return self._room(connection, room_id)

    def set_team(self, account_id, room_id, team):
        units = clean_team(team)
        with self.lock, self._connection() as connection, connection:
            room = self._room(connection, room_id)
            if not room or room['status'] != 'open':
                raise CoopError('gone')
            me = next((p for p in room['players'] if p['account_id'] == account_id), None)
            if not me or me['state'] not in ('host', 'accepted'):
                raise CoopError('forbidden')
            connection.execute('UPDATE room_players SET team = ?, updated_at = ? WHERE room_id = ? AND account_id = ?',
                               (json.dumps(units), self.clock(), room_id, account_id))
            self._touch(connection, room_id)
            return self._room(connection, room_id)

    def leave(self, account_id, room_id):
        """A guest leaves; the host leaving closes the room."""
        with self.lock, self._connection() as connection, connection:
            room = self._room(connection, room_id)
            if not room or room['status'] != 'open':
                raise CoopError('gone')
            me = next((p for p in room['players'] if p['account_id'] == account_id), None)
            if not me or me['state'] not in ACTIVE_STATES:
                raise CoopError('forbidden')
            if me['state'] == 'host':
                connection.execute("UPDATE rooms SET status = 'cancelled', updated_at = ? WHERE id = ?", (self.clock(), room_id))
            else:
                connection.execute("UPDATE room_players SET state = 'left', team = NULL, updated_at = ? WHERE room_id = ? AND account_id = ?",
                                   (self.clock(), room_id, account_id))
                self._touch(connection, room_id)
            return self._room(connection, room_id)

    def ready_to_sail(self, room):
        """At least one guest with a team, every accepted player with one, and the host's."""
        players = [p for p in room['players'] if p['state'] in ('host', 'accepted')]
        return (room['status'] == 'open' and len(players) >= 2 and all(p['team'] for p in players))
