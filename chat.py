"""The global chat (block G, SE_CHAT): one chat room for every player of the server.

The owner's choices (18 November 2026):
  * the last KEEP (100) messages are kept; older ones are deleted by themselves;
  * a message of up to LENGTH (200) characters, one every INTERVAL_SECONDS (3) per player;
  * words of a list the owner edits (config/chat_filter.txt, one word or phrase per line) become "***";
  * an administrator deletes any message (it disappears for everyone) and mutes a player for a while or for good;
  * each message shows "[TAG] Name (level)": the clan's tag and the village's level when it was written.
Each player's last read message is kept too, so the chat's dot is red when someone else wrote after it.

Everything lives in instance/chat.sqlite3.
"""

import re
import sqlite3
import time
import unicodedata
from contextlib import contextmanager
from pathlib import Path

KEEP = 100
LENGTH = 200
INTERVAL_SECONDS = 3
FILTER_FILE = Path(__file__).resolve().parent / 'config' / 'chat_filter.txt'
MUTE_CHOICES = {'hour': 3600, 'day': 86400, 'week': 7 * 86400, 'forever': None}


class ChatError(Exception):
    def __init__(self, code, **values):
        super().__init__(code)
        self.code = code
        self.values = values


def _plain(text):
    """Lower case without accents, for the word filter (so "Pútå" matches "puta")."""
    return ''.join(c for c in unicodedata.normalize('NFD', text.lower()) if unicodedata.category(c) != 'Mn')


class WordFilter:
    """The owner's list of words: each one, as a whole word and in any case or accent, becomes ***."""

    def __init__(self, path=FILTER_FILE):
        self.path = Path(path)
        self._stamp = None
        self._pattern = None

    def _load(self):
        try:
            stamp = self.path.stat().st_mtime
        except OSError:
            self._stamp, self._pattern = None, None
            return
        if stamp == self._stamp:
            return
        words = []
        for line in self.path.read_text(encoding='utf-8-sig').splitlines():
            word = _plain(line.strip())
            if word and not word.startswith('#'):
                words.append(re.escape(word).replace(r'\ ', r'\s+'))
        self._stamp = stamp
        self._pattern = re.compile(r'(?<!\w)(' + '|'.join(sorted(words, key=len, reverse=True)) + r')(?!\w)') if words else None

    def clean(self, text):
        self._load()
        if not self._pattern:
            return text
        plain = _plain(text)
        if len(plain) != len(text):  # a letter that changes length when its accent goes: compare letter by letter
            plain = ''.join(_plain(c)[:1] or c for c in text)
        out, last = [], 0
        for match in self._pattern.finditer(plain):
            out.append(text[last:match.start()])
            out.append('***')
            last = match.end()
        out.append(text[last:])
        return ''.join(out)


class ChatStore:
    def __init__(self, database_path, clock=time.time, word_filter=None):
        self.database_path = str(Path(database_path))
        self.clock = clock
        self.filter = word_filter or WordFilter()
        Path(self.database_path).parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS chat_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    tag TEXT NOT NULL DEFAULT '',
                    level INTEGER NOT NULL DEFAULT 0,
                    text TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS chat_reads (
                    account_id INTEGER PRIMARY KEY,
                    last_read INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS chat_mutes (
                    account_id INTEGER PRIMARY KEY,
                    until REAL,
                    reason TEXT NOT NULL DEFAULT '',
                    by_name TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS chat_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    action TEXT NOT NULL,
                    admin_name TEXT NOT NULL,
                    target_name TEXT NOT NULL DEFAULT '',
                    detail TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL
                );
                """)

    @contextmanager
    def _connection(self):
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    # ---- players
    def muted_until(self, account_id):
        """None: may write. 0: muted for good. Else the time the mute ends."""
        with self._connection() as connection:
            row = connection.execute('SELECT until FROM chat_mutes WHERE account_id = ?', (account_id,)).fetchone()
        if not row:
            return None
        if row['until'] is None:
            return 0
        return row['until'] if row['until'] > self.clock() else None

    def post(self, account_id, name, tag, level, text):
        text = ' '.join(str(text or '').split())
        if not text:
            raise ChatError('empty')
        if len(text) > LENGTH:
            raise ChatError('too_long', length=LENGTH)
        muted = self.muted_until(account_id)
        if muted is not None:
            raise ChatError('muted_forever' if muted == 0 else 'muted', until=muted)
        text = self.filter.clean(text)
        with self._connection() as connection:
            connection.execute('BEGIN IMMEDIATE')
            now = self.clock()
            last = connection.execute('SELECT MAX(created_at) FROM chat_messages WHERE account_id = ?',
                                      (account_id,)).fetchone()[0]
            if last is not None and now - last < INTERVAL_SECONDS:
                raise ChatError('too_fast', seconds=INTERVAL_SECONDS)
            cursor = connection.execute(
                'INSERT INTO chat_messages (account_id, name, tag, level, text, created_at) VALUES (?, ?, ?, ?, ?, ?)',
                (account_id, name or '?', tag or '', int(level or 0), text, now))
            connection.execute('DELETE FROM chat_messages WHERE id NOT IN '
                               '(SELECT id FROM chat_messages ORDER BY id DESC LIMIT ?)', (KEEP,))
            connection.execute('INSERT INTO chat_reads (account_id, last_read) VALUES (?, ?) '
                               'ON CONFLICT(account_id) DO UPDATE SET last_read = excluded.last_read',
                               (account_id, cursor.lastrowid))  # one's own message is read
            row = connection.execute('SELECT * FROM chat_messages WHERE id = ?', (cursor.lastrowid,)).fetchone()
        return dict(row)

    def recent(self, limit=KEEP):
        with self._connection() as connection:
            rows = connection.execute('SELECT * FROM chat_messages ORDER BY id DESC LIMIT ?', (limit,)).fetchall()
        return [dict(row) for row in reversed(rows)]

    def mark_read(self, account_id, last_id):
        with self._connection() as connection:
            newest = connection.execute('SELECT MAX(id) FROM chat_messages').fetchone()[0] or 0
            last_id = max(0, min(int(last_id or 0), newest))
            connection.execute('INSERT INTO chat_reads (account_id, last_read) VALUES (?, ?) '
                               'ON CONFLICT(account_id) DO UPDATE SET last_read = MAX(last_read, excluded.last_read)',
                               (account_id, last_id))

    def unread(self, account_id):
        """True when someone else wrote after the player's last read message."""
        with self._connection() as connection:
            row = connection.execute('SELECT last_read FROM chat_reads WHERE account_id = ?', (account_id,)).fetchone()
            last = row['last_read'] if row else 0
            return connection.execute('SELECT 1 FROM chat_messages WHERE id > ? AND account_id != ? LIMIT 1',
                                      (last, account_id)).fetchone() is not None

    # ---- administrators
    def _log(self, connection, action, admin_name, target_name='', detail=''):
        connection.execute('INSERT INTO chat_log (action, admin_name, target_name, detail, created_at) '
                           'VALUES (?, ?, ?, ?, ?)', (action, admin_name, target_name, detail, self.clock()))

    def delete(self, message_id, admin_name):
        with self._connection() as connection:
            row = connection.execute('SELECT * FROM chat_messages WHERE id = ?', (message_id,)).fetchone()
            if not row:
                raise ChatError('not_found')
            connection.execute('DELETE FROM chat_messages WHERE id = ?', (message_id,))
            self._log(connection, 'delete', admin_name, row['name'], row['text'][:120])
        return dict(row)

    def mute(self, account_id, target_name, choice, admin_name, reason=''):
        if choice not in MUTE_CHOICES:
            raise ChatError('bad_choice')
        seconds = MUTE_CHOICES[choice]
        until = None if seconds is None else self.clock() + seconds
        with self._connection() as connection:
            connection.execute('INSERT INTO chat_mutes (account_id, until, reason, by_name, created_at) '
                               'VALUES (?, ?, ?, ?, ?) ON CONFLICT(account_id) DO UPDATE SET until = excluded.until, '
                               'reason = excluded.reason, by_name = excluded.by_name, created_at = excluded.created_at',
                               (account_id, until, str(reason or '')[:200], admin_name, self.clock()))
            self._log(connection, 'mute', admin_name, target_name, choice + (f' · {reason}' if reason else ''))

    def unmute(self, account_id, target_name, admin_name):
        with self._connection() as connection:
            connection.execute('DELETE FROM chat_mutes WHERE account_id = ?', (account_id,))
            self._log(connection, 'unmute', admin_name, target_name)

    def mutes(self):
        """The players muted now: [{account_id, until (None: for good), reason, by_name, created_at}]."""
        with self._connection() as connection:
            rows = connection.execute('SELECT * FROM chat_mutes WHERE until IS NULL OR until > ? ORDER BY created_at DESC',
                                      (self.clock(),)).fetchall()
        return [dict(row) for row in rows]

    def log(self, limit=30):
        with self._connection() as connection:
            rows = connection.execute('SELECT * FROM chat_log ORDER BY id DESC LIMIT ?', (limit,)).fetchall()
        return [dict(row) for row in rows]
