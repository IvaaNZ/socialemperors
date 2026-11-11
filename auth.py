"""Persistent accounts and browser-session security for the game server."""

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import hmac
from pathlib import Path
import re
import secrets
import sqlite3
import time
import threading

from flask import abort, request, session
from werkzeug.security import check_password_hash, generate_password_hash

from localization import SUPPORTED_LOCALES


ACCOUNT_STATUSES = frozenset({"pending", "approved", "rejected"})
LOGIN_WINDOW_SECONDS = 15 * 60
LOGIN_EMAIL_LIMIT = 5
LOGIN_IP_LIMIT = 30
MAX_LOGIN_BUCKETS = 10_000
_DUMMY_PASSWORD_HASH = generate_password_hash(secrets.token_hex(32))
_SCHEMA_LOCK = threading.Lock()


class AccountError(ValueError):
    """An account operation the user can correct or retry later."""


def _normalized_email(email):
    return email.strip().casefold() if isinstance(email, str) else ""


def _public_account(row):
    if row is None:
        return None
    return {
        "id": row["id"],
        "name": row["name"],
        "email": row["email"],
        "status": row["status"],
        "is_admin": bool(row["is_admin"]),
        "village_id": row["village_id"],
        "created_at": row["created_at"],
        # None means the server's default language.
        "language": row["language"] if "language" in row.keys() else None,
    }


class AccountStore:
    """Use short SQLite transactions so approvals persist across server workers."""

    def __init__(self, database_path):
        self.database_path = str(Path(database_path).expanduser())
        Path(self.database_path).parent.mkdir(parents=True, exist_ok=True)
        # SQLite's initial switch to WAL can return SQLITE_BUSY immediately
        # when two threads initialize the same fresh database at once.
        with _SCHEMA_LOCK, self._connection() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS accounts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    email TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'approved', 'rejected')),
                    is_admin INTEGER NOT NULL DEFAULT 0 CHECK (is_admin IN (0, 1)),
                    village_id TEXT UNIQUE,
                    created_at TEXT NOT NULL,
                    CHECK (is_admin = 0 OR status = 'approved')
                );
                CREATE TABLE IF NOT EXISTS login_throttles (
                    bucket TEXT PRIMARY KEY,
                    failures INTEGER NOT NULL,
                    window_started REAL NOT NULL,
                    blocked_until REAL NOT NULL,
                    expires_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS login_throttles_expiry
                    ON login_throttles (expires_at);
                """
            )
            columns = {row["name"] for row in connection.execute("PRAGMA table_info(accounts)")}
            if "language" not in columns:  # Databases created before the language selector.
                connection.execute("ALTER TABLE accounts ADD COLUMN language TEXT")

    @contextmanager
    def _connection(self):
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def create_account(self, name, email, password, *, is_admin=False, status="pending", language=None):
        return self._create_account(name, email, password, is_admin, status, None, language)

    def _create_account(self, name, email, password, is_admin, status, village_id, language=None):
        name = name.strip() if isinstance(name, str) else ""
        email = _normalized_email(email)
        if not 2 <= len(name) <= 60:
            raise AccountError("O nome deve ter entre 2 e 60 caracteres.")
        if len(email) > 254 or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
            raise AccountError("Informe um e-mail válido.")
        if not isinstance(password, str) or not 10 <= len(password) <= 128:
            raise AccountError("A senha deve ter entre 10 e 128 caracteres.")
        self._validate_status(status)
        if is_admin and status != "approved":
            raise AccountError("A conta de administrador deve estar aprovada.")
        if village_id is not None:
            village_id = self._validate_village_id(village_id)
        language = self._validate_language(language)

        password_hash = generate_password_hash(password)
        created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        try:
            with self._connection() as connection:
                cursor = connection.execute(
                    """INSERT INTO accounts
                       (name, email, password_hash, status, is_admin, village_id, created_at, language)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (name, email, password_hash, status, int(bool(is_admin)), village_id, created_at, language),
                )
                row = connection.execute(
                    "SELECT * FROM accounts WHERE id = ?", (cursor.lastrowid,)
                ).fetchone()
        except sqlite3.IntegrityError as error:
            if "village_id" in str(error):
                raise AccountError("Esta vila já pertence a outra conta.") from error
            raise AccountError("Já existe uma conta com este e-mail.") from error
        return _public_account(row)

    def create_admin(self, name, email, password, village_id=None):
        # Insert the account and its optional existing village atomically.
        return self._create_account(name, email, password, True, "approved", village_id)

    def authenticate(self, email, password):
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM accounts WHERE email = ?", (_normalized_email(email),)
            ).fetchone()
        password_hash = row["password_hash"] if row is not None else _DUMMY_PASSWORD_HASH
        if not isinstance(password, str) or len(password) > 128:
            return None
        if not check_password_hash(password_hash, password) or row is None:
            return None
        return _public_account(row)

    def get(self, account_id):
        with self._connection() as connection:
            return _public_account(
                connection.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
            )

    def list_accounts(self):
        with self._connection() as connection:
            rows = connection.execute(
                """SELECT * FROM accounts
                   ORDER BY CASE status WHEN 'pending' THEN 0 WHEN 'approved' THEN 1 ELSE 2 END,
                            created_at, id"""
            ).fetchall()
        return [_public_account(row) for row in rows]

    @staticmethod
    def _validate_language(language):
        if language is None:
            return None
        if not isinstance(language, str) or language not in SUPPORTED_LOCALES:
            raise AccountError("O idioma escolhido não é válido.")
        return language

    def set_language(self, account_id, language):
        """Store the account's language; None returns it to the server default."""
        language = self._validate_language(language)
        with self._connection() as connection:
            cursor = connection.execute("UPDATE accounts SET language = ? WHERE id = ?", (language, account_id))
            if cursor.rowcount != 1:
                raise AccountError("Conta não encontrada.")
            return _public_account(
                connection.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
            )

    @staticmethod
    def _validate_status(status):
        if not isinstance(status, str) or status not in ACCOUNT_STATUSES:
            raise AccountError("O status da conta é inválido.")

    def set_status(self, account_id, status):
        self._validate_status(status)
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM accounts WHERE id = ?", (account_id,)
            ).fetchone()
            if row is None:
                raise AccountError("Conta não encontrada.")
            if row["is_admin"] and status != "approved":
                raise AccountError("A conta de administrador não pode ser desativada.")
            connection.execute(
                "UPDATE accounts SET status = ? WHERE id = ?", (status, account_id)
            )
            return _public_account(
                connection.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
            )

    @staticmethod
    def _validate_village_id(village_id):
        if not isinstance(village_id, (str, int)) or isinstance(village_id, bool):
            raise AccountError("O identificador da vila é inválido.")
        village_id = str(village_id).strip()
        if not village_id or len(village_id) > 128:
            raise AccountError("O identificador da vila é inválido.")
        return village_id

    def bind_village(self, account_id, village_id):
        village_id = self._validate_village_id(village_id)
        try:
            with self._connection() as connection:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    "SELECT * FROM accounts WHERE id = ?", (account_id,)
                ).fetchone()
                if row is None:
                    raise AccountError("Conta não encontrada.")
                if row["village_id"] == village_id:
                    return _public_account(row)
                if row["village_id"] is not None:
                    raise AccountError("Esta conta já possui uma vila vinculada.")
                connection.execute(
                    "UPDATE accounts SET village_id = ? WHERE id = ?", (village_id, account_id)
                )
                return _public_account(
                    connection.execute(
                        "SELECT * FROM accounts WHERE id = ?", (account_id,)
                    ).fetchone()
                )
        except sqlite3.IntegrityError as error:
            raise AccountError("Esta vila já pertence a outra conta.") from error

    @staticmethod
    def _login_buckets(email, remote_addr):
        # The throttle database does not need to keep submitted e-mails or IPs.
        values = (
            ("email", _normalized_email(email), LOGIN_EMAIL_LIMIT),
            ("ip", str(remote_addr or "unknown"), LOGIN_IP_LIMIT),
        )
        return [
            (kind + ":" + hashlib.sha256(value.encode("utf-8")).hexdigest(), limit)
            for kind, value, limit in values
        ]

    def check_login_allowed(self, email, remote_addr):
        now = time.time()
        buckets = self._login_buckets(email, remote_addr)
        with self._connection() as connection:
            connection.execute("DELETE FROM login_throttles WHERE expires_at <= ?", (now,))
            row = connection.execute(
                """SELECT 1 FROM login_throttles
                   WHERE bucket IN (?, ?) AND blocked_until > ? LIMIT 1""",
                (buckets[0][0], buckets[1][0], now),
            ).fetchone()
        if row is not None:
            raise AccountError("Muitas tentativas de login. Aguarde alguns minutos e tente novamente.")

    def record_login_failure(self, email, remote_addr):
        now = time.time()
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("DELETE FROM login_throttles WHERE expires_at <= ?", (now,))
            for bucket, limit in self._login_buckets(email, remote_addr):
                row = connection.execute(
                    "SELECT * FROM login_throttles WHERE bucket = ?", (bucket,)
                ).fetchone()
                failures = row["failures"] + 1 if row else 1
                started = row["window_started"] if row else now
                blocked_until = row["blocked_until"] if row else 0
                if failures >= limit and blocked_until <= now:
                    blocked_until = now + LOGIN_WINDOW_SECONDS
                expires_at = max(started + LOGIN_WINDOW_SECONDS, blocked_until)
                connection.execute(
                    """INSERT INTO login_throttles
                       (bucket, failures, window_started, blocked_until, expires_at)
                       VALUES (?, ?, ?, ?, ?)
                       ON CONFLICT(bucket) DO UPDATE SET failures = excluded.failures,
                           window_started = excluded.window_started,
                           blocked_until = excluded.blocked_until,
                           expires_at = excluded.expires_at""",
                    (bucket, failures, started, blocked_until, expires_at),
                )
            connection.execute(
                """DELETE FROM login_throttles WHERE bucket IN (
                       SELECT bucket FROM login_throttles
                       ORDER BY expires_at DESC, bucket LIMIT -1 OFFSET ?
                   )""",
                (MAX_LOGIN_BUCKETS,),
            )

    def clear_login_failures(self, email, remote_addr=None):
        """Clear the account counter; a valid login must not erase IP abuse history."""
        email_bucket = self._login_buckets(email, remote_addr)[0][0]
        with self._connection() as connection:
            connection.execute("DELETE FROM login_throttles WHERE bucket = ?", (email_bucket,))


def csrf_token():
    token = session.get("_csrf_token")
    if not isinstance(token, str):
        token = secrets.token_urlsafe(32)
        session["_csrf_token"] = token
    return token


def validate_csrf():
    expected = session.get("_csrf_token")
    submitted = request.form.get("csrf_token")
    if (
        not isinstance(expected, str)
        or not isinstance(submitted, str)
        or not hmac.compare_digest(expected.encode("utf-8"), submitted.encode("utf-8"))
    ):
        abort(400, description="O formulário expirou. Atualize a página e tente novamente.")
