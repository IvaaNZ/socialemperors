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
RAID_SECONDS = 2 * 60 * 60  # a raid at sea that never reported its end closes after this
# Point 30 (the owner's choices, 2026-11-17): each raid player gets the island's reward -30%; alone, +20%. The
# island's enemies get +50% life and attack for each player beyond the first.
CLAN_REWARD, SOLO_REWARD, DIFFICULTY_STEP = 0.7, 1.2, 0.5
# Point 29: prestige for the clan: an island won alone, or a clan raid won with 2 or 3 players.
PRESTIGE_SOLO, PRESTIGE_GROUP = 5, 15
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
                CREATE TABLE IF NOT EXISTS room_deaths (   -- phase 5: each unit lost once, by its owner
                    room_id INTEGER NOT NULL,
                    handle INTEGER NOT NULL,
                    account_id INTEGER NOT NULL,
                    unit_id INTEGER NOT NULL,
                    at REAL NOT NULL,
                    PRIMARY KEY (room_id, handle)
                );
                CREATE TABLE IF NOT EXISTS village_changes (  -- a village changed by a raid: its open game reloads
                    village_id TEXT PRIMARY KEY,
                    changes INTEGER NOT NULL
                );
            """)

    def _connection(self):
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        return closing(connection)

    # -- reading --
    def _expire(self, connection):
        now = self.clock()
        connection.execute("UPDATE rooms SET status = 'cancelled', updated_at = ? WHERE status = 'open' AND updated_at < ?",
                           (now, now - ROOM_IDLE_SECONDS))
        connection.execute("UPDATE rooms SET status = 'done', updated_at = ? WHERE status = 'sailing' AND updated_at < ?",
                           (now, now - RAID_SECONDS))

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
                WHERE p.account_id = ? AND r.status IN ('open', 'sailing') AND p.state IN ('host', 'accepted')
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

    def sail(self, host_id, room_id):
        """The host sets sail: the room is at sea until its end. Returns the room."""
        with self.lock, self._connection() as connection, connection:
            self._expire(connection)
            room = self._room(connection, room_id)
            if not room or room['status'] != 'open':
                raise CoopError('gone')
            if room['host_id'] != host_id:
                raise CoopError('forbidden')
            if not self.ready_to_sail(room):
                raise CoopError('not_ready')
            connection.execute("UPDATE rooms SET status = 'sailing', updated_at = ? WHERE id = ?", (self.clock(), room_id))
            # invitations nobody answered lapse
            connection.execute("UPDATE room_players SET state = 'declined', updated_at = ? WHERE room_id = ? AND state = 'invited'",
                               (self.clock(), room_id))
            return self._room(connection, room_id)

    @staticmethod
    def army(room):
        """The units that land: the host's team first, then each guest's, as the game's unit ids."""
        players = [p for p in room['players'] if p['state'] in ('host', 'accepted') and p['team']]
        players.sort(key=lambda p: p['state'] != 'host')
        return [unit for p in players for unit in p['team']]

    def sailing_room_of(self, account_id):
        """The raid at sea the player takes part in, or None."""
        room = self.room_of(account_id)
        return room if room and room['status'] == 'sailing' else None

    def leave(self, account_id, room_id):
        """A guest leaves; the host leaving closes the room (a raid at sea ends)."""
        with self.lock, self._connection() as connection, connection:
            room = self._room(connection, room_id)
            if not room or room['status'] not in ('open', 'sailing'):
                raise CoopError('gone')
            me = next((p for p in room['players'] if p['account_id'] == account_id), None)
            if not me or me['state'] not in ACTIVE_STATES:
                raise CoopError('forbidden')
            if me['state'] == 'host':
                connection.execute("UPDATE rooms SET status = ?, updated_at = ? WHERE id = ?",
                                   ('done' if room['status'] == 'sailing' else 'cancelled', self.clock(), room_id))
            else:
                connection.execute("UPDATE room_players SET state = 'left', team = NULL, updated_at = ? WHERE room_id = ? AND account_id = ?",
                                   (self.clock(), room_id, account_id))
                self._touch(connection, room_id)
            return self._room(connection, room_id)

    # -- phase 5 --
    def record_death(self, host_id, room_id, handle, owner_id, unit_id):
        """A unit of the raid died (reported by the host's page, which knows whose it is): True the first time.
        Only units of the owner's team, never more of a kind than it brought."""
        with self.lock, self._connection() as connection, connection:
            room = self._room(connection, room_id)
            if not room or room['status'] != 'sailing':
                raise CoopError('gone')
            if room['host_id'] != host_id:
                raise CoopError('forbidden')
            owner = next((p for p in room['players'] if p['account_id'] == owner_id and p['state'] in ('host', 'accepted')), None)
            if not owner or not owner['team'] or unit_id not in owner['team']:
                raise CoopError('forbidden')
            if connection.execute('SELECT 1 FROM room_deaths WHERE room_id = ? AND handle = ?', (room_id, handle)).fetchone():
                return False
            lost = connection.execute('SELECT COUNT(*) AS n FROM room_deaths WHERE room_id = ? AND account_id = ? AND unit_id = ?',
                                      (room_id, owner_id, unit_id)).fetchone()['n']
            if lost >= owner['team'].count(unit_id):
                raise CoopError('forbidden')
            connection.execute('INSERT INTO room_deaths (room_id, handle, account_id, unit_id, at) VALUES (?, ?, ?, ?, ?)',
                               (room_id, handle, owner_id, unit_id, self.clock()))
            return True

    def deaths(self, room_id):
        with self.lock, self._connection() as connection:
            return [dict(row) for row in connection.execute('SELECT * FROM room_deaths WHERE room_id = ? ORDER BY at', (room_id,))]

    def finish(self, room_id):
        """The host's island ended: the raid is over. Returns the room, or None when it was not at sea."""
        with self.lock, self._connection() as connection, connection:
            room = self._room(connection, room_id)
            if not room or room['status'] != 'sailing':
                return None
            connection.execute("UPDATE rooms SET status = 'done', updated_at = ? WHERE id = ?", (self.clock(), room_id))
            return self._room(connection, room_id)

    def village_changed(self, village_id):
        with self.lock, self._connection() as connection, connection:
            connection.execute("""INSERT INTO village_changes (village_id, changes) VALUES (?, 1)
                                  ON CONFLICT (village_id) DO UPDATE SET changes = changes + 1""", (village_id,))

    def revision(self, village_id):
        """'' until a raid changed the village; then a number that grows with each change."""
        with self.lock, self._connection() as connection:
            row = connection.execute('SELECT changes FROM village_changes WHERE village_id = ?', (village_id,)).fetchone()
            return f'coop{row["changes"]}' if row else ''

    def ready_to_sail(self, room):
        """At least one guest with a team, every accepted player with one, and the host's."""
        players = [p for p in room['players'] if p['state'] in ('host', 'accepted')]
        return (room['status'] == 'open' and len(players) >= 2 and all(p['team'] for p in players))
