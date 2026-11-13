"""Blocked accounts keep a reason; older databases gain the column without losing accounts."""

from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest

from auth import AccountError, AccountStore


class AccountBlockingTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'accounts.sqlite3'

    def test_the_reason_stays_only_while_blocked(self):
        store = AccountStore(self.path)
        account = store.create_account('Jogador', 'player@example.com', 'secret-password', status='approved')
        self.assertIsNone(account['block_reason'])
        blocked = store.set_status(account['id'], 'rejected', '  Trapaça\n repetida ')
        self.assertEqual((blocked['status'], blocked['block_reason']), ('rejected', 'Trapaça repetida'))
        self.assertEqual(store.get(account['id'])['block_reason'], 'Trapaça repetida')
        self.assertIsNone(store.set_status(account['id'], 'approved', 'ignorado')['block_reason'])
        self.assertIsNone(store.set_status(account['id'], 'rejected')['block_reason'])  # a refused registration
        for reason in ('', 'ab', 'x' * 201, 7):
            with self.assertRaises(AccountError):
                store.set_status(account['id'], 'rejected', reason)

    def test_an_older_database_gains_the_column_and_keeps_its_accounts(self):
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.executescript('''
                CREATE TABLE accounts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, email TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected')),
                    is_admin INTEGER NOT NULL DEFAULT 0 CHECK (is_admin IN (0, 1)), village_id TEXT UNIQUE,
                    created_at TEXT NOT NULL, language TEXT, CHECK (is_admin = 0 OR status = 'approved'));
                INSERT INTO accounts (name, email, password_hash, status, is_admin, created_at)
                    VALUES ('Antigo', 'old@example.com', 'hash', 'approved', 0, '2026-01-01T00:00:00+00:00');
            ''')
        store = AccountStore(self.path)
        account = store.list_accounts()[0]
        self.assertEqual((account['name'], account['status'], account['block_reason']), ('Antigo', 'approved', None))
        self.assertEqual(store.set_status(account['id'], 'rejected', 'Motivo')['block_reason'], 'Motivo')


if __name__ == '__main__':
    unittest.main()
