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

Recruitment: a clan is either open (an eligible player joins at once) or by
request (the default). Either way a player's main village must be at least
the clan's minimum level. The recruitment language is shown and used to
filter, not enforced. The Guild Master edits the emblem, motto, announcement
and recruitment.

A player who leaves (or is removed from) a clan waits REJOIN_SECONDS before
joining or creating another, so nobody hops between clans during a challenge.
Join requests expire after REQUEST_SECONDS; a player keeps at most
MAX_OPEN_REQUESTS open at once. Every change is logged in `clan_log`.
Villages are never touched. Errors carry codes; the web side shows them in the
viewer's language.

Clan challenges (phase 2): a Guild Master challenges another clan to the best
of 3, 5 or 7 duels; the other Guild Master has CHALLENGE_ANSWER_SECONDS to
accept. Once accepted, every finished duel (status 'done', not a draw)
between members of the two clans counts one win for the winner's clan; only
the members of each clan when the challenge was accepted count (its
roster). The first clan to the majority (2, 3 or 4 wins) wins. Either Guild
Master may surrender (the other clan wins); a clan dissolved during a
challenge loses it. A clan has one pending or active challenge at a time and
may challenge again, the same clan or another, as soon as it ends.

Chat (in-game window): each clan has a channel, and an alliance has one shared
by its two clans. Messages of up to CHAT_LENGTH characters, one every
CHAT_INTERVAL_SECONDS per player, the last CHAT_KEEP kept per channel.
Nobody deletes messages (the owner's decision); the oldest drop off by themselves.

Alliance: a Guild Master proposes it to another clan and that clan's Guild
Master accepts or declines (the proposer may cancel it while pending). A clan
has one alliance at a time, pending or active. Allies cannot challenge each
other, and two clans with a pending or active challenge between them cannot
ally. Either Guild Master may end it; a dissolved clan ends it.
"""

from contextlib import contextmanager
import os
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
EMBLEMS = 12                       # emblem 1..12 (own art, templates/js/clan_overlay.js)
# SE_CLAN_CREST: the Guild Master builds the clan's shield from pieces (templates/js/clan_overlay.js, CREST_*):
# shape, division, first colour, second colour, emblem and the emblem's colour, each 1..its count. Stored as
# "1.2.14.6.1.21"; '' is a clan that has not built one yet (it shows a shield made from its old emblem).
CREST_PARTS = (21, 21, 24, 24, 25, 24)
ANNOUNCEMENT_LENGTH = 500
RECRUIT_LANGUAGES = ('all', 'es', 'pt-BR', 'en')
CHAT_LENGTH = 300
CHAT_KEEP = 200                    # messages kept per channel
CHAT_INTERVAL_SECONDS = 2          # one message per player every 2 seconds
CHALLENGE_SIZES = (3, 5, 7)        # best of N duels
CHALLENGE_ANSWER_SECONDS = 10 * 60  # time the challenged clan has to accept

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


def clean_announcement(value):
    text = unicodedata.normalize('NFC', str(value or '').replace('\r\n', '\n').strip())
    text = '\n'.join(' '.join(line.split()) for line in text.split('\n'))
    while '\n\n\n' in text:
        text = text.replace('\n\n\n', '\n\n')
    if len(text) > ANNOUNCEMENT_LENGTH:
        raise ClanError('bad_announcement')
    return text


def crest_enabled():
    return os.environ.get('SE_CLAN_CREST', 'off').strip().lower() in ('on', '1', 'true', 'yes')


def clean_crest(value):
    """The canonical crest ("1.2.14.6.1.21") or ClanError('bad_settings'); '' stays '' (no crest built)."""
    text = str(value if value is not None else '').strip()
    if not text:
        return ''
    parts = text.split('.')
    if len(parts) != len(CREST_PARTS) or not all(part.isdigit() for part in parts):
        raise ClanError('bad_settings')
    numbers = [int(part) for part in parts]
    if not all(1 <= number <= limit for number, limit in zip(numbers, CREST_PARTS)):
        raise ClanError('bad_settings')
    return '.'.join(str(number) for number in numbers)


def clean_settings(emblem, recruit_open, min_level, language):
    try:
        emblem, min_level = int(emblem), int(min_level)
    except (TypeError, ValueError):
        raise ClanError('bad_settings') from None
    if not 1 <= emblem <= EMBLEMS or not 1 <= min_level <= 99 or language not in RECRUIT_LANGUAGES:
        raise ClanError('bad_settings')
    return emblem, 1 if recruit_open in (True, 1, '1', 'on', 'true', 'yes') else 0, min_level, language


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
                CREATE TABLE IF NOT EXISTS clan_challenges (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    challenger_clan INTEGER NOT NULL,
                    challenger_name TEXT NOT NULL,
                    challenger_tag TEXT NOT NULL,
                    defender_clan INTEGER NOT NULL,
                    defender_name TEXT NOT NULL,
                    defender_tag TEXT NOT NULL,
                    best_of INTEGER NOT NULL CHECK (best_of IN (3, 5, 7)),
                    status TEXT NOT NULL CHECK (status IN ('pending', 'active', 'done', 'declined', 'expired', 'cancelled')),
                    challenger_wins INTEGER NOT NULL DEFAULT 0,
                    defender_wins INTEGER NOT NULL DEFAULT 0,
                    winner_clan INTEGER,
                    ending TEXT CHECK (ending IS NULL OR ending IN ('majority', 'surrender', 'dissolved')),
                    created_by INTEGER NOT NULL,
                    answered_by INTEGER,
                    ended_by INTEGER,
                    created_at REAL NOT NULL,
                    accepted_at REAL,
                    finished_at REAL
                );
                CREATE INDEX IF NOT EXISTS clan_challenges_status ON clan_challenges (status);
                CREATE TABLE IF NOT EXISTS clan_challenge_rosters (
                    challenge_id INTEGER NOT NULL,
                    account_id INTEGER NOT NULL,
                    clan_id INTEGER NOT NULL,
                    PRIMARY KEY (challenge_id, account_id)
                );
                CREATE TABLE IF NOT EXISTS clan_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel TEXT NOT NULL,
                    clan_id INTEGER NOT NULL,
                    account_id INTEGER NOT NULL,
                    author_name TEXT NOT NULL,
                    text TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS clan_messages_channel ON clan_messages (channel, id);
                CREATE TABLE IF NOT EXISTS clan_alliances (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    proposer_clan INTEGER NOT NULL,
                    proposer_name TEXT NOT NULL,
                    proposer_tag TEXT NOT NULL,
                    partner_clan INTEGER NOT NULL,
                    partner_name TEXT NOT NULL,
                    partner_tag TEXT NOT NULL,
                    status TEXT NOT NULL CHECK (status IN ('pending', 'active', 'declined', 'cancelled', 'ended')),
                    proposed_by INTEGER NOT NULL,
                    answered_by INTEGER,
                    ended_by INTEGER,
                    created_at REAL NOT NULL,
                    accepted_at REAL,
                    ended_at REAL
                );
                CREATE INDEX IF NOT EXISTS clan_alliances_status ON clan_alliances (status);
                CREATE TABLE IF NOT EXISTS clan_challenge_duels (
                    duel_id INTEGER PRIMARY KEY,
                    challenge_id INTEGER NOT NULL,
                    winner_id INTEGER NOT NULL,
                    loser_id INTEGER NOT NULL,
                    winner_clan INTEGER NOT NULL,
                    counted_at REAL NOT NULL
                );
                """
            )
        self._migrate()

    NEW_CLAN_COLUMNS = (
        ('emblem', 'INTEGER NOT NULL DEFAULT 1'),
        ('announcement', "TEXT NOT NULL DEFAULT ''"),
        ('recruit_open', 'INTEGER NOT NULL DEFAULT 0'),
        ('recruit_min_level', 'INTEGER NOT NULL DEFAULT 1'),
        ('recruit_language', "TEXT NOT NULL DEFAULT 'all'"),
        ('prestige', 'INTEGER NOT NULL DEFAULT 0'),  # point 29: adventures won by its members
        ('crest', "TEXT NOT NULL DEFAULT ''"),  # SE_CLAN_CREST: the shield built from pieces (clean_crest)
    )

    def add_prestige(self, clan_id, points):
        """Point 29: an adventure island won by a member adds prestige to its clan (5 alone, 15 in a clan raid).
        Returns the clan's prestige, or None when the clan no longer exists."""
        with self._connection() as connection:
            updated = connection.execute('UPDATE clans SET prestige = prestige + ? WHERE id = ?', (int(points), clan_id))
            if not updated.rowcount:
                return None
            return connection.execute('SELECT prestige FROM clans WHERE id = ?', (clan_id,)).fetchone()['prestige']

    def _migrate(self):
        """Columns added after the first version: an existing database gets them with their defaults."""
        with self._connection() as connection:
            present = {row['name'] for row in connection.execute('PRAGMA table_info(clans)')}
            for name, definition in self.NEW_CLAN_COLUMNS:
                if name not in present:
                    connection.execute(f'ALTER TABLE clans ADD COLUMN {name} {definition}')

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
            connection.execute("""UPDATE clan_challenges SET status = 'expired', finished_at = created_at + ?
                                  WHERE status = 'pending' AND created_at <= ?""",
                               (CHALLENGE_ANSWER_SECONDS, now - CHALLENGE_ANSWER_SECONDS))
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
    def create(self, actor_id, name, tag, description='', actor_name=None, emblem=1, crest=''):
        name, tag, description = clean_name(name), clean_tag(tag), clean_description(description)
        emblem = clean_settings(emblem, 0, 1, 'all')[0]
        crest = clean_crest(crest)
        with self._write() as (connection, now):
            if self._member(connection, actor_id):
                raise ClanError('already_in_clan')
            self._check_rejoin(connection, actor_id, now)
            if connection.execute('SELECT 1 FROM clans WHERE name_key = ?', (name_key(name),)).fetchone():
                raise ClanError('name_taken')
            if connection.execute('SELECT 1 FROM clans WHERE tag = ?', (tag,)).fetchone():
                raise ClanError('tag_taken')
            cursor = connection.execute(
                'INSERT INTO clans (name, name_key, tag, description, emblem, crest, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                (name, name_key(name), tag, description, emblem, crest, actor_id, now))
            connection.execute("INSERT INTO clan_members (account_id, clan_id, role, joined_at) VALUES (?, ?, 'master', ?)",
                               (actor_id, cursor.lastrowid, now))
            connection.execute('DELETE FROM clan_requests WHERE account_id = ?', (actor_id,))
            clan = self._clan(connection, cursor.lastrowid)
            self._log(connection, clan, actor_id, actor_name, 'create', now)
            return clan

    def request_join(self, actor_id, clan_id, level=None):
        """Ask to join a clan (`level`: the player's main village level, checked against the minimum)."""
        with self._write() as (connection, now):
            clan = self._clan(connection, clan_id)
            if self._member(connection, actor_id):
                raise ClanError('already_in_clan')
            self._check_rejoin(connection, actor_id, now)
            if level is not None and level < clan['recruit_min_level']:
                raise ClanError('level_too_low')
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

    def join(self, actor_id, clan_id, level, actor_name=None):
        """Join an open clan at once (the minimum level still applies)."""
        with self._write() as (connection, now):
            clan = self._clan(connection, clan_id)
            if not clan['recruit_open']:
                raise ClanError('not_open')
            if self._member(connection, actor_id):
                raise ClanError('already_in_clan')
            self._check_rejoin(connection, actor_id, now)
            if level < clan['recruit_min_level']:
                raise ClanError('level_too_low')
            if self._count(connection, clan_id) >= MAX_MEMBERS:
                raise ClanError('clan_full')
            connection.execute("INSERT INTO clan_members (account_id, clan_id, role, joined_at) VALUES (?, ?, 'member', ?)",
                               (actor_id, clan_id, now))
            connection.execute('DELETE FROM clan_requests WHERE account_id = ?', (actor_id,))
            self._log(connection, clan, actor_id, actor_name, 'join', now)
            return clan

    def settings(self, actor_id, emblem, description, announcement, recruit_open, min_level, language, actor_name=None,
                 crest=None):
        """The Guild Master edits the emblem (or the crest: None keeps it), motto, announcement and recruitment."""
        description, announcement = clean_description(description), clean_announcement(announcement)
        emblem, recruit_open, min_level, language = clean_settings(emblem, recruit_open, min_level, language)
        crest = None if crest is None else clean_crest(crest)
        with self._write() as (connection, now):
            actor = self._member(connection, actor_id)
            if not actor or actor['role'] != 'master':
                raise ClanError('forbidden')
            connection.execute(
                """UPDATE clans SET emblem = ?, description = ?, announcement = ?, recruit_open = ?, recruit_min_level = ?,
                       recruit_language = ? WHERE id = ?""",
                (emblem, description, announcement, recruit_open, min_level, language, actor['clan_id']))
            if crest is not None:
                connection.execute('UPDATE clans SET crest = ? WHERE id = ?', (crest, actor['clan_id']))
            clan = self._clan(connection, actor['clan_id'])
            self._log(connection, clan, actor_id, actor_name, 'edit', now)
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
        connection.execute("""UPDATE clan_challenges SET status = 'cancelled', finished_at = ?
                              WHERE status = 'pending' AND (challenger_clan = ? OR defender_clan = ?)""",
                           (now, clan['id'], clan['id']))
        for row in connection.execute("""SELECT * FROM clan_challenges WHERE status = 'active'
                                          AND (challenger_clan = ? OR defender_clan = ?)""", (clan['id'], clan['id'])).fetchall():
            other = row['defender_clan'] if row['challenger_clan'] == clan['id'] else row['challenger_clan']
            self._end_challenge(connection, row['id'], other, 'dissolved', actor_id, now)
        connection.execute("""UPDATE clan_alliances SET status = CASE status WHEN 'pending' THEN 'cancelled' ELSE 'ended' END,
                                  ended_by = ?, ended_at = ? WHERE status IN ('pending', 'active')
                                  AND (proposer_clan = ? OR partner_clan = ?)""", (actor_id, now, clan['id'], clan['id']))
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

    # -- clan challenges --
    @staticmethod
    def _open_challenge(connection, clan_id):
        row = connection.execute("""SELECT * FROM clan_challenges WHERE status IN ('pending', 'active')
                                    AND (challenger_clan = ? OR defender_clan = ?)""", (clan_id, clan_id)).fetchone()
        return dict(row) if row else None

    def _master_of(self, connection, actor_id):
        actor = self._member(connection, actor_id)
        if not actor or actor['role'] != 'master':
            raise ClanError('forbidden')
        return actor

    @staticmethod
    def _end_challenge(connection, challenge_id, winner_clan, ending, actor_id, now):
        connection.execute("""UPDATE clan_challenges SET status = 'done', winner_clan = ?, ending = ?, ended_by = ?,
                                  finished_at = ? WHERE id = ?""", (winner_clan, ending, actor_id, now, challenge_id))

    @staticmethod
    def _challenge_row(connection, challenge_id):
        row = connection.execute('SELECT * FROM clan_challenges WHERE id = ?', (challenge_id,)).fetchone()
        return dict(row) if row else None

    def challenge(self, actor_id, target_clan_id, best_of, actor_name=None):
        """The Guild Master challenges another clan to the best of 3, 5 or 7 duels."""
        try:
            best_of = int(best_of)
        except (TypeError, ValueError):
            raise ClanError('bad_size') from None
        if best_of not in CHALLENGE_SIZES:
            raise ClanError('bad_size')
        with self._write() as (connection, now):
            actor = self._master_of(connection, actor_id)
            if actor['clan_id'] == target_clan_id:
                raise ClanError('own_clan')
            own, target = self._clan(connection, actor['clan_id']), self._clan(connection, target_clan_id)
            if self._alliance_between(connection, own['id'], target['id']):
                raise ClanError('allied')
            if self._open_challenge(connection, own['id']):
                raise ClanError('challenge_busy')
            if self._open_challenge(connection, target['id']):
                raise ClanError('target_challenge_busy')
            cursor = connection.execute(
                """INSERT INTO clan_challenges (challenger_clan, challenger_name, challenger_tag, defender_clan,
                       defender_name, defender_tag, best_of, status, created_by, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)""",
                (own['id'], own['name'], own['tag'], target['id'], target['name'], target['tag'], best_of, actor_id, now))
            self._log(connection, own, actor_id, actor_name, 'challenge', now, detail='[%s] %s' % (target['tag'], target['name']))
            return self._challenge_row(connection, cursor.lastrowid)

    def answer_challenge(self, actor_id, challenge_id, accept, actor_name=None):
        with self._write() as (connection, now):
            row = self._challenge_row(connection, challenge_id)
            if not row or row['status'] != 'pending':
                raise ClanError('gone')
            actor = self._master_of(connection, actor_id)
            if actor['clan_id'] != row['defender_clan']:
                raise ClanError('forbidden')
            if accept and self._alliance_between(connection, row['challenger_clan'], row['defender_clan']):
                raise ClanError('allied')
            clan = self._clan(connection, row['defender_clan'])
            rival = '[%s] %s' % (row['challenger_tag'], row['challenger_name'])
            if not accept:
                connection.execute("""UPDATE clan_challenges SET status = 'declined', answered_by = ?, finished_at = ?
                                      WHERE id = ?""", (actor_id, now, challenge_id))
                self._log(connection, clan, actor_id, actor_name, 'decline', now, detail=rival)
                return self._challenge_row(connection, challenge_id)
            connection.execute("""UPDATE clan_challenges SET status = 'active', answered_by = ?, accepted_at = ?
                                  WHERE id = ?""", (actor_id, now, challenge_id))
            connection.execute("""INSERT INTO clan_challenge_rosters (challenge_id, account_id, clan_id)
                                  SELECT ?, account_id, clan_id FROM clan_members WHERE clan_id IN (?, ?)""",
                               (challenge_id, row['challenger_clan'], row['defender_clan']))
            self._log(connection, clan, actor_id, actor_name, 'accept_challenge', now, detail=rival)
            return self._challenge_row(connection, challenge_id)

    def cancel_challenge(self, actor_id, challenge_id, actor_name=None):
        with self._write() as (connection, now):
            row = self._challenge_row(connection, challenge_id)
            if not row or row['status'] != 'pending':
                raise ClanError('gone')
            actor = self._master_of(connection, actor_id)
            if actor['clan_id'] != row['challenger_clan']:
                raise ClanError('forbidden')
            connection.execute("UPDATE clan_challenges SET status = 'cancelled', ended_by = ?, finished_at = ? WHERE id = ?",
                               (actor_id, now, challenge_id))

    def surrender(self, actor_id, challenge_id, actor_name=None):
        """A Guild Master gives up an active challenge: the other clan wins it."""
        with self._write() as (connection, now):
            row = self._challenge_row(connection, challenge_id)
            if not row or row['status'] != 'active':
                raise ClanError('gone')
            actor = self._master_of(connection, actor_id)
            if actor['clan_id'] not in (row['challenger_clan'], row['defender_clan']):
                raise ClanError('forbidden')
            other = row['defender_clan'] if actor['clan_id'] == row['challenger_clan'] else row['challenger_clan']
            self._end_challenge(connection, challenge_id, other, 'surrender', actor_id, now)
            self._log(connection, self._clan(connection, actor['clan_id']), actor_id, actor_name, 'surrender', now)
            return self._challenge_row(connection, challenge_id)

    def record_duel(self, duel):
        """Count a finished duel for the active challenge between its two players' clans, if any.

        `duel` is a duels.sqlite3 row. Only status 'done' with a winner (not a draw)
        counts, each duel once, and only between roster members of opposite clans.
        Returns the challenge after counting, or None.
        """
        if duel.get('status') != 'done' or duel.get('winner') not in ('challenger', 'defender'):
            return None
        winner = duel['challenger_id'] if duel['winner'] == 'challenger' else duel['defender_id']
        loser = duel['defender_id'] if duel['winner'] == 'challenger' else duel['challenger_id']
        with self._write() as (connection, now):
            if connection.execute('SELECT 1 FROM clan_challenge_duels WHERE duel_id = ?', (duel['id'],)).fetchone():
                return None
            row = connection.execute(
                """SELECT c.*, w.clan_id AS winner_side FROM clan_challenges c
                   JOIN clan_challenge_rosters w ON w.challenge_id = c.id AND w.account_id = ?
                   JOIN clan_challenge_rosters l ON l.challenge_id = c.id AND l.account_id = ?
                   WHERE c.status = 'active' AND w.clan_id != l.clan_id""", (winner, loser)).fetchone()
            if not row:
                return None
            column = 'challenger_wins' if row['winner_side'] == row['challenger_clan'] else 'defender_wins'
            connection.execute('UPDATE clan_challenges SET %s = %s + 1 WHERE id = ?' % (column, column), (row['id'],))
            connection.execute("""INSERT INTO clan_challenge_duels (duel_id, challenge_id, winner_id, loser_id, winner_clan,
                                      counted_at) VALUES (?, ?, ?, ?, ?, ?)""",
                               (duel['id'], row['id'], winner, loser, row['winner_side'], now))
            challenge = self._challenge_row(connection, row['id'])
            if challenge[column] >= challenge['best_of'] // 2 + 1:
                self._end_challenge(connection, row['id'], row['winner_side'], 'majority', None, now)
                challenge = self._challenge_row(connection, row['id'])
            return challenge

    def current_challenge(self, clan_id):
        """The clan's pending (not yet expired) or active challenge, with its duels and roster, or None."""
        now = self.clock()
        with self._connection() as connection:
            row = connection.execute(
                """SELECT * FROM clan_challenges WHERE (challenger_clan = ? OR defender_clan = ?)
                   AND (status = 'active' OR (status = 'pending' AND created_at > ?))""",
                (clan_id, clan_id, now - CHALLENGE_ANSWER_SECONDS)).fetchone()
            if not row:
                return None
            challenge = dict(row)
            challenge['expires_in'] = max(0, round(challenge['created_at'] + CHALLENGE_ANSWER_SECONDS - now))
            challenge['duels'] = [dict(d) for d in connection.execute(
                'SELECT * FROM clan_challenge_duels WHERE challenge_id = ? ORDER BY counted_at, duel_id', (challenge['id'],))]
            challenge['roster'] = {r['account_id']: r['clan_id'] for r in connection.execute(
                'SELECT * FROM clan_challenge_rosters WHERE challenge_id = ?', (challenge['id'],))}
            return challenge

    def challenge_history(self, clan_id, limit=10):
        """Ended challenges, newest first (a pending one past its answer time shows as expired)."""
        cutoff = self.clock() - CHALLENGE_ANSWER_SECONDS
        with self._connection() as connection:
            rows = [dict(row) for row in connection.execute(
                """SELECT *, COALESCE(finished_at, created_at + ?) AS ended_at FROM clan_challenges
                   WHERE (challenger_clan = ? OR defender_clan = ?)
                   AND NOT (status = 'active' OR (status = 'pending' AND created_at > ?))
                   ORDER BY ended_at DESC, id DESC LIMIT ?""",
                (CHALLENGE_ANSWER_SECONDS, clan_id, clan_id, cutoff, limit))]
        for row in rows:
            if row['status'] == 'pending':
                row['status'] = 'expired'
        return rows

    def ranking(self, limit=20):
        """Existing clans by challenges won, then duel wins in challenges; with their record."""
        with self._connection() as connection:
            return [dict(row) for row in connection.execute(
                """SELECT clans.id, clans.name, clans.tag,
                       SUM(CASE WHEN c.winner_clan = clans.id THEN 1 ELSE 0 END) AS won,
                       SUM(CASE WHEN c.winner_clan != clans.id THEN 1 ELSE 0 END) AS lost,
                       SUM(CASE WHEN c.challenger_clan = clans.id THEN c.challenger_wins ELSE c.defender_wins END) AS duel_wins
                   FROM clans JOIN clan_challenges c ON c.status = 'done'
                        AND (c.challenger_clan = clans.id OR c.defender_clan = clans.id)
                   GROUP BY clans.id ORDER BY won DESC, duel_wins DESC, lost ASC, clans.name_key LIMIT ?""", (limit,))]

    # -- alliance --
    @staticmethod
    def _alliance_of(connection, clan_id):
        row = connection.execute("""SELECT * FROM clan_alliances WHERE status IN ('pending', 'active')
                                    AND (proposer_clan = ? OR partner_clan = ?)""", (clan_id, clan_id)).fetchone()
        return dict(row) if row else None

    @staticmethod
    def _alliance_between(connection, first, second):
        return connection.execute("""SELECT 1 FROM clan_alliances WHERE status = 'active' AND
                                     ((proposer_clan = ? AND partner_clan = ?) OR (proposer_clan = ? AND partner_clan = ?))""",
                                  (first, second, second, first)).fetchone() is not None

    @staticmethod
    def _challenge_between(connection, first, second):
        """True when the two clans have a pending or active challenge against each other."""
        return connection.execute("""SELECT 1 FROM clan_challenges WHERE status IN ('pending', 'active') AND
                                     ((challenger_clan = ? AND defender_clan = ?) OR (challenger_clan = ? AND defender_clan = ?))""",
                                  (first, second, second, first)).fetchone() is not None

    @staticmethod
    def _alliance_row(connection, alliance_id):
        row = connection.execute('SELECT * FROM clan_alliances WHERE id = ?', (alliance_id,)).fetchone()
        return dict(row) if row else None

    def propose_alliance(self, actor_id, target_clan_id, actor_name=None):
        with self._write() as (connection, now):
            actor = self._master_of(connection, actor_id)
            if actor['clan_id'] == target_clan_id:
                raise ClanError('own_clan')
            own, target = self._clan(connection, actor['clan_id']), self._clan(connection, target_clan_id)
            if self._alliance_of(connection, own['id']):
                raise ClanError('alliance_busy')
            if self._alliance_of(connection, target['id']):
                raise ClanError('target_alliance_busy')
            if self._challenge_between(connection, own['id'], target['id']):
                raise ClanError('challenge_between')  # rivals of an open challenge do not ally
            cursor = connection.execute(
                """INSERT INTO clan_alliances (proposer_clan, proposer_name, proposer_tag, partner_clan, partner_name, partner_tag,
                       status, proposed_by, created_at) VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?)""",
                (own['id'], own['name'], own['tag'], target['id'], target['name'], target['tag'], actor_id, now))
            self._log(connection, own, actor_id, actor_name, 'propose_alliance', now, detail='[%s] %s' % (target['tag'], target['name']))
            return self._alliance_row(connection, cursor.lastrowid)

    def answer_alliance(self, actor_id, alliance_id, accept, actor_name=None):
        with self._write() as (connection, now):
            row = self._alliance_row(connection, alliance_id)
            if not row or row['status'] != 'pending':
                raise ClanError('gone')
            actor = self._master_of(connection, actor_id)
            if actor['clan_id'] != row['partner_clan']:
                raise ClanError('forbidden')
            if accept and self._challenge_between(connection, row['proposer_clan'], row['partner_clan']):
                raise ClanError('challenge_between')  # challenged each other after the proposal
            status = 'active' if accept else 'declined'
            connection.execute("""UPDATE clan_alliances SET status = ?, answered_by = ?, accepted_at = ?, ended_at = ?
                                  WHERE id = ?""", (status, actor_id, now if accept else None, None if accept else now, alliance_id))
            clan = self._clan(connection, row['partner_clan'])
            self._log(connection, clan, actor_id, actor_name, 'accept_alliance' if accept else 'decline_alliance', now,
                      detail='[%s] %s' % (row['proposer_tag'], row['proposer_name']))
            return self._alliance_row(connection, alliance_id)

    def end_alliance(self, actor_id, alliance_id, actor_name=None):
        """The proposer cancels a pending alliance, or either Guild Master ends an active one."""
        with self._write() as (connection, now):
            row = self._alliance_row(connection, alliance_id)
            if not row or row['status'] not in ('pending', 'active'):
                raise ClanError('gone')
            actor = self._master_of(connection, actor_id)
            allowed = ((row['status'] == 'pending' and actor['clan_id'] == row['proposer_clan'])
                       or (row['status'] == 'active' and actor['clan_id'] in (row['proposer_clan'], row['partner_clan'])))
            if not allowed:
                raise ClanError('forbidden')
            status = 'cancelled' if row['status'] == 'pending' else 'ended'
            connection.execute('UPDATE clan_alliances SET status = ?, ended_by = ?, ended_at = ? WHERE id = ?',
                               (status, actor_id, now, alliance_id))
            self._log(connection, self._clan(connection, actor['clan_id']), actor_id, actor_name, 'end_alliance', now)
            return self._alliance_row(connection, alliance_id)

    def alliance(self, clan_id):
        """The clan's pending or active alliance, or None."""
        with self._connection() as connection:
            return self._alliance_of(connection, clan_id)

    # -- chat --
    def _channel_for(self, connection, actor_id, channel):
        """The channel key and the actor's membership, if the actor may read and write it."""
        actor = self._member(connection, actor_id)
        if not actor:
            raise ClanError('not_in_clan')
        if channel == 'clan':
            return 'clan:%d' % actor['clan_id'], actor
        if channel == 'alliance':
            alliance = self._alliance_of(connection, actor['clan_id'])
            if not alliance or alliance['status'] != 'active':
                raise ClanError('no_alliance')
            return 'alliance:%d' % alliance['id'], actor
        raise ClanError('forbidden')

    def post_message(self, actor_id, channel, text, actor_name):
        text = ' '.join(str(text or '').split())
        if not text or len(text) > CHAT_LENGTH:
            raise ClanError('bad_message')
        with self._write() as (connection, now):
            key, actor = self._channel_for(connection, actor_id, channel)
            last = connection.execute('SELECT MAX(created_at) FROM clan_messages WHERE account_id = ?', (actor_id,)).fetchone()[0]
            if last is not None and now - last < CHAT_INTERVAL_SECONDS:
                raise ClanError('chat_too_fast')
            cursor = connection.execute(
                """INSERT INTO clan_messages (channel, clan_id, account_id, author_name, text, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""", (key, actor['clan_id'], actor_id, actor_name or '?', text, now))
            connection.execute("""DELETE FROM clan_messages WHERE channel = ? AND id NOT IN
                                  (SELECT id FROM clan_messages WHERE channel = ? ORDER BY id DESC LIMIT ?)""",
                               (key, key, CHAT_KEEP))
            return cursor.lastrowid

    def messages(self, actor_id, channel, after=0, limit=CHAT_KEEP):
        with self._connection() as connection:
            key, actor = self._channel_for(connection, actor_id, channel)
            rows = connection.execute("""SELECT m.*, c.tag FROM clan_messages m LEFT JOIN clans c ON c.id = m.clan_id
                                         WHERE m.channel = ? AND m.id > ? ORDER BY m.id DESC LIMIT ?""",
                                      (key, int(after or 0), limit)).fetchall()
            return [dict(row) for row in reversed(rows)]

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

    def member_tags(self):
        """account id -> clan tag, for every clan member."""
        with self._connection() as connection:
            return {row['account_id']: row['tag'] for row in connection.execute(
                'SELECT clan_members.account_id, clans.tag FROM clan_members JOIN clans ON clans.id = clan_members.clan_id')}

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
