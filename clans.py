"""Clans (SE_CLANS=on): members, roles, join requests and permissions.

A clan has one Guild Master ('master'), up to MAX_ASSISTS Assists ('assist')
and members ('member'), MAX_MEMBERS in all. A player belongs to one clan at a
time and joins by request: the Guild Master or an Assist approves it.

Permissions (checked here, inside each transaction, never only on the page):

  * Guild Master: everything; names and removes Assists, transfers the lead,
    edits the description, dissolves the clan. To leave, they transfer the
    lead first (a Guild Master alone in the clan dissolves it by leaving).
  * Assist: approves or rejects requests and removes plain members.
  * Member: leaves the clan.

A player who leaves (or is removed from) a clan waits REJOIN_SECONDS before
joining or creating another, so nobody hops between clans during a challenge.
Join requests expire after REQUEST_SECONDS; a player keeps at most
MAX_OPEN_REQUESTS open at once. Every change is logged in `clan_log`.
Villages are never touched. Errors carry codes; the web side shows them in the
viewer's language.
"""

from contextlib import contextmanager
from pathlib import Path
import re
import sqlite3
import time
import unicodedata

MAX_MEMBERS = 70
MAX_ASSISTS = 3
MAX_OPEN_REQUESTS = 3
REQUEST_SECONDS = 7 * 24 * 3600
REJOIN_SECONDS = 3600
NAME_LENGTH = (3, 24)
TAG_LENGTH = (2, 5)
DESCRIPTION_LENGTH = 200
ROLES = ('master', 'assist', 'member')

_NAME_PATTERN = re.compile(r"^[\w][\w .'\-]*$", re.UNICODE)
_TAG_PATTERN = re.compile(r'^[A-Z0-9]+$')


class ClanError(ValueError):
    """An action the player cannot do; `code` is shown to them in their language."""

    def __init__(self, code):
        super().__init__(code)
        self.code = code


def clean_name(value):
    text = unicodedata.normalize('NFC', ' '.join(str(value or '').split()))
    if not NAME_LENGTH[0] <= len(text) <= NAME_LENGTH[1] or not _NAME_PATTERN.match(text):
        raise ClanError('bad_name')
    return text


def clean_tag(value):
    text = str(value or '').strip().upper()
    if not TAG_LENGTH[0] <= len(text) <= TAG_LENGTH[1] or not _TAG_PATTERN.match(text):
        raise ClanError('bad_tag')
    return text


def clean_description(value):
    text = unicodedata.normalize('NFC', ' '.join(str(value or '').split()))
    if len(text) > DESCRIPTION_LENGTH:
        raise ClanError('bad_description')
    return text


def name_key(value):
    """Case- and accent-insensitive key: 'Los Ñandúes' and 'los nandues' are the same name."""
    text = unicodedata.normalize('NFKD', value).casefold()
    return ''.join(char for char in text if not unicodedata.combining(char))


class ClanStore:
    """Clans in SQLite; every action is one short transaction with its permission check."""

    def __init__(self, database_path, clock=time.time):
        self.database_path = str(Path(database_path))
        self.clock = clock
        Path(self.database_path).parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS clans (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    name_key TEXT NOT NULL UNIQUE,
                    tag TEXT NOT NULL UNIQUE,
                    description TEXT NOT NULL DEFAULT '',
                    created_by INTEGER NOT NULL,
                    created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS clan_members (
                    account_id INTEGER PRIMARY KEY,
                    clan_id INTEGER NOT NULL REFERENCES clans(id) ON DELETE CASCADE,
                    role TEXT NOT NULL CHECK (role IN ('master', 'assist', 'member')),
                    joined_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS clan_members_clan ON clan_members (clan_id, role);
                CREATE TABLE IF NOT EXISTS clan_requests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    clan_id INTEGER NOT NULL REFERENCES clans(id) ON DELETE CASCADE,
                    account_id INTEGER NOT NULL,
                    created_at REAL NOT NULL,
                    UNIQUE (clan_id, account_id)
                );
                CREATE TABLE IF NOT EXISTS clan_departures (
                    account_id INTEGER PRIMARY KEY,
                    left_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS clan_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    clan_id INTEGER NOT NULL,
                    clan_name TEXT NOT NULL,
                    actor_id INTEGER,
                    actor_name TEXT,
                    action TEXT NOT NULL,
                    target_id INTEGER,
                    detail TEXT,
                    created_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS clan_log_clan ON clan_log (clan_id, created_at);
                """
            )

    @contextmanager
    def _connection(self):
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute('PRAGMA foreign_keys = ON')
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    @contextmanager
    def _write(self):
        """One transaction, with expired requests removed first."""
        with self._connection() as connection:
            connection.execute('BEGIN IMMEDIATE')
            now = self.clock()
            connection.execute('DELETE FROM clan_requests WHERE created_at <= ?', (now - REQUEST_SECONDS,))
            yield connection, now

    # -- helpers --
    @staticmethod
    def _member(connection, account_id):
        row = connection.execute('SELECT * FROM clan_members WHERE account_id = ?', (account_id,)).fetchone()
        return dict(row) if row else None

    @staticmethod
    def _clan(connection, clan_id):
        row = connection.execute('SELECT * FROM clans WHERE id = ?', (clan_id,)).fetchone()
        if not row:
            raise ClanError('no_clan')
        return dict(row)

    @staticmethod
    def _count(connection, clan_id, role=None):
        if role:
            return connection.execute('SELECT COUNT(*) FROM clan_members WHERE clan_id = ? AND role = ?',
                                      (clan_id, role)).fetchone()[0]
        return connection.execute('SELECT COUNT(*) FROM clan_members WHERE clan_id = ?', (clan_id,)).fetchone()[0]

    @staticmethod
    def _check_rejoin(connection, account_id, now):
        row = connection.execute('SELECT left_at FROM clan_departures WHERE account_id = ?', (account_id,)).fetchone()
        if row and now - row['left_at'] < REJOIN_SECONDS:
            raise ClanError('rejoin_wait')

    @staticmethod
    def _log(connection, clan, actor_id, actor_name, action, now, target_id=None, detail=None):
        connection.execute(
            """INSERT INTO clan_log (clan_id, clan_name, actor_id, actor_name, action, target_id, detail, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (clan['id'], clan['name'], actor_id, actor_name, action, target_id, detail, now))

    def _role_in(self, connection, account_id, clan_id):
        member = self._member(connection, account_id)
        return member['role'] if member and member['clan_id'] == clan_id else None

    def _depart(self, connection, account_id, now):
        connection.execute('DELETE FROM clan_members WHERE account_id = ?', (account_id,))
        connection.execute("""INSERT INTO clan_departures (account_id, left_at) VALUES (?, ?)
                              ON CONFLICT(account_id) DO UPDATE SET left_at = excluded.left_at""", (account_id, now))

    # -- actions --
    def create(self, actor_id, name, tag, description='', actor_name=None):
        name, tag, description = clean_name(name), clean_tag(tag), clean_description(description)
        with self._write() as (connection, now):
            if self._member(connection, actor_id):
                raise ClanError('already_in_clan')
            self._check_rejoin(connection, actor_id, now)
            if connection.execute('SELECT 1 FROM clans WHERE name_key = ?', (name_key(name),)).fetchone():
                raise ClanError('name_taken')
            if connection.execute('SELECT 1 FROM clans WHERE tag = ?', (tag,)).fetchone():
                raise ClanError('tag_taken')
            cursor = connection.execute(
                'INSERT INTO clans (name, name_key, tag, description, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?)',
                (name, name_key(name), tag, description, actor_id, now))
            connection.execute("INSERT INTO clan_members (account_id, clan_id, role, joined_at) VALUES (?, ?, 'master', ?)",
                               (actor_id, cursor.lastrowid, now))
            connection.execute('DELETE FROM clan_requests WHERE account_id = ?', (actor_id,))
            clan = self._clan(connection, cursor.lastrowid)
            self._log(connection, clan, actor_id, actor_name, 'create', now)
            return clan

    def request_join(self, actor_id, clan_id):
        with self._write() as (connection, now):
            clan = self._clan(connection, clan_id)
            if self._member(connection, actor_id):
                raise ClanError('already_in_clan')
            self._check_rejoin(connection, actor_id, now)
            if self._count(connection, clan_id) >= MAX_MEMBERS:
                raise ClanError('clan_full')
            if connection.execute('SELECT 1 FROM clan_requests WHERE clan_id = ? AND account_id = ?',
                                  (clan_id, actor_id)).fetchone():
                raise ClanError('already_requested')
            if connection.execute('SELECT COUNT(*) FROM clan_requests WHERE account_id = ?',
                                  (actor_id,)).fetchone()[0] >= MAX_OPEN_REQUESTS:
                raise ClanError('too_many_requests')
            connection.execute('INSERT INTO clan_requests (clan_id, account_id, created_at) VALUES (?, ?, ?)',
                               (clan_id, actor_id, now))
            return clan

    def cancel_request(self, actor_id, clan_id):
        with self._write() as (connection, now):
            if not connection.execute('DELETE FROM clan_requests WHERE clan_id = ? AND account_id = ?',
                                      (clan_id, actor_id)).rowcount:
                raise ClanError('gone')

    def answer_request(self, actor_id, request_id, accept, actor_name=None):
        with self._write() as (connection, now):
            request = connection.execute('SELECT * FROM clan_requests WHERE id = ?', (request_id,)).fetchone()
            if not request:
                raise ClanError('gone')
            clan = self._clan(connection, request['clan_id'])
            if self._role_in(connection, actor_id, clan['id']) not in ('master', 'assist'):
                raise ClanError('forbidden')
            applicant = request['account_id']
            if not accept:
                connection.execute('DELETE FROM clan_requests WHERE id = ?', (request_id,))
                self._log(connection, clan, actor_id, actor_name, 'reject', now, applicant)
                return None
            if self._member(connection, applicant):  # joined another clan meanwhile
                connection.execute('DELETE FROM clan_requests WHERE id = ?', (request_id,))
                raise ClanError('gone')
            if self._count(connection, clan['id']) >= MAX_MEMBERS:
                raise ClanError('clan_full')
            connection.execute("INSERT INTO clan_members (account_id, clan_id, role, joined_at) VALUES (?, ?, 'member', ?)",
                               (applicant, clan['id'], now))
            connection.execute('DELETE FROM clan_requests WHERE account_id = ?', (applicant,))
            self._log(connection, clan, actor_id, actor_name, 'accept', now, applicant)
            return applicant

    def kick(self, actor_id, target_id, actor_name=None):
        with self._write() as (connection, now):
            actor, target = self._member(connection, actor_id), self._member(connection, target_id)
            if not actor or not target or actor['clan_id'] != target['clan_id'] or actor_id == target_id:
                raise ClanError('forbidden')
            allowed = actor['role'] == 'master' or (actor['role'] == 'assist' and target['role'] == 'member')
            if not allowed:
                raise ClanError('forbidden')
            clan = self._clan(connection, actor['clan_id'])
            self._depart(connection, target_id, now)
            self._log(connection, clan, actor_id, actor_name, 'kick', now, target_id)

    def set_role(self, actor_id, target_id, role, actor_name=None):
        if role not in ('assist', 'member'):
            raise ClanError('forbidden')
        with self._write() as (connection, now):
            actor, target = self._member(connection, actor_id), self._member(connection, target_id)
            if (not actor or actor['role'] != 'master' or not target or target['clan_id'] != actor['clan_id']
                    or target['role'] == 'master'):
                raise ClanError('forbidden')
            if target['role'] == role:
                return
            if role == 'assist' and self._count(connection, actor['clan_id'], 'assist') >= MAX_ASSISTS:
                raise ClanError('too_many_assists')
            connection.execute('UPDATE clan_members SET role = ? WHERE account_id = ?', (role, target_id))
            clan = self._clan(connection, actor['clan_id'])
            self._log(connection, clan, actor_id, actor_name, 'promote' if role == 'assist' else 'demote', now, target_id)

    def transfer(self, actor_id, target_id, actor_name=None):
        """The Guild Master hands the lead to another member and becomes a plain member."""
        with self._write() as (connection, now):
            actor, target = self._member(connection, actor_id), self._member(connection, target_id)
            if (not actor or actor['role'] != 'master' or not target or target['clan_id'] != actor['clan_id']
                    or actor_id == target_id):
                raise ClanError('forbidden')
            connection.execute("UPDATE clan_members SET role = 'master' WHERE account_id = ?", (target_id,))
            connection.execute("UPDATE clan_members SET role = 'member' WHERE account_id = ?", (actor_id,))
            clan = self._clan(connection, actor['clan_id'])
            self._log(connection, clan, actor_id, actor_name, 'transfer', now, target_id)

    def edit(self, actor_id, description, actor_name=None):
        description = clean_description(description)
        with self._write() as (connection, now):
            actor = self._member(connection, actor_id)
            if not actor or actor['role'] != 'master':
                raise ClanError('forbidden')
            connection.execute('UPDATE clans SET description = ? WHERE id = ?', (description, actor['clan_id']))
            clan = self._clan(connection, actor['clan_id'])
            self._log(connection, clan, actor_id, actor_name, 'edit', now)

    def leave(self, actor_id, actor_name=None):
        """Returns 'left', or 'dissolved' when a Guild Master alone in the clan leaves."""
        with self._write() as (connection, now):
            actor = self._member(connection, actor_id)
            if not actor:
                raise ClanError('not_in_clan')
            clan = self._clan(connection, actor['clan_id'])
            if actor['role'] == 'master':
                if self._count(connection, clan['id']) > 1:
                    raise ClanError('transfer_first')
                self._dissolve(connection, clan, actor_id, actor_name, now, 'last member left')
                return 'dissolved'
            self._depart(connection, actor_id, now)
            self._log(connection, clan, actor_id, actor_name, 'leave', now)
            return 'left'

    def _dissolve(self, connection, clan, actor_id, actor_name, now, reason):
        for row in connection.execute('SELECT account_id FROM clan_members WHERE clan_id = ?', (clan['id'],)).fetchall():
            connection.execute("""INSERT INTO clan_departures (account_id, left_at) VALUES (?, ?)
                                  ON CONFLICT(account_id) DO UPDATE SET left_at = excluded.left_at""",
                               (row['account_id'], now - REJOIN_SECONDS))  # a dissolved clan imposes no wait
        connection.execute('DELETE FROM clan_members WHERE clan_id = ?', (clan['id'],))
        connection.execute('DELETE FROM clan_requests WHERE clan_id = ?', (clan['id'],))
        connection.execute('DELETE FROM clans WHERE id = ?', (clan['id'],))
        self._log(connection, clan, actor_id, actor_name, 'dissolve', now, detail=reason)

    def dissolve(self, actor_id, actor_name=None):
        with self._write() as (connection, now):
            actor = self._member(connection, actor_id)
            if not actor or actor['role'] != 'master':
                raise ClanError('forbidden')
            self._dissolve(connection, self._clan(connection, actor['clan_id']), actor_id, actor_name, now, '')

    def admin_dissolve(self, clan_id, admin_id, admin_name, reason):
        reason = ' '.join(str(reason or '').split())
        if not reason:
            raise ClanError('reason_required')
        with self._write() as (connection, now):
            self._dissolve(connection, self._clan(connection, clan_id), admin_id, admin_name, now, reason[:200])

    # -- reading --
    def clan(self, clan_id):
        with self._connection() as connection:
            row = connection.execute('SELECT * FROM clans WHERE id = ?', (clan_id,)).fetchone()
            if not row:
                return None
            clan = dict(row)
            clan['members'] = [dict(m) for m in connection.execute(
                """SELECT * FROM clan_members WHERE clan_id = ?
                   ORDER BY CASE role WHEN 'master' THEN 0 WHEN 'assist' THEN 1 ELSE 2 END, joined_at, account_id""",
                (clan_id,))]
            return clan

    def membership(self, account_id):
        with self._connection() as connection:
            member = self._member(connection, account_id)
            if not member:
                return None
            member['clan'] = dict(connection.execute('SELECT * FROM clans WHERE id = ?', (member['clan_id'],)).fetchone())
            return member

    def clans(self, search=''):
        key = name_key(' '.join(str(search or '').split()))
        with self._connection() as connection:
            rows = connection.execute(
                """SELECT clans.*, COUNT(clan_members.account_id) AS member_count FROM clans
                   LEFT JOIN clan_members ON clan_members.clan_id = clans.id
                   GROUP BY clans.id ORDER BY member_count DESC, clans.name_key""").fetchall()
        result = [dict(row) for row in rows]
        if key:
            result = [clan for clan in result if key in clan['name_key'] or key.upper() in clan['tag']]
        return result

    def requests_for(self, clan_id):
        now = self.clock()
        with self._connection() as connection:
            return [dict(row) for row in connection.execute(
                'SELECT * FROM clan_requests WHERE clan_id = ? AND created_at > ? ORDER BY created_at',
                (clan_id, now - REQUEST_SECONDS))]

    def requests_of(self, account_id):
        now = self.clock()
        with self._connection() as connection:
            return [dict(row) for row in connection.execute(
                """SELECT clan_requests.*, clans.name, clans.tag FROM clan_requests JOIN clans ON clans.id = clan_requests.clan_id
                   WHERE account_id = ? AND clan_requests.created_at > ? ORDER BY clan_requests.created_at""",
                (account_id, now - REQUEST_SECONDS))]

    def rejoin_wait(self, account_id):
        """Seconds until this player may join or create a clan (0: now)."""
        with self._connection() as connection:
            row = connection.execute('SELECT left_at FROM clan_departures WHERE account_id = ?', (account_id,)).fetchone()
        return max(0, round(row['left_at'] + REJOIN_SECONDS - self.clock())) if row else 0

    def log(self, clan_id=None, limit=50):
        with self._connection() as connection:
            if clan_id is None:
                rows = connection.execute('SELECT * FROM clan_log ORDER BY created_at DESC, id DESC LIMIT ?', (limit,))
            else:
                rows = connection.execute('SELECT * FROM clan_log WHERE clan_id = ? ORDER BY created_at DESC, id DESC LIMIT ?',
                                          (clan_id, limit))
            return [dict(row) for row in rows]
