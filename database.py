"""SQLite locally and PostgreSQL on hosted deployments."""
from __future__ import annotations

import os
import re
import sqlite3
import threading
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_PG_POOL = None
_PG_POOL_LOCK = threading.Lock()


def _normalize_postgres_url(value: str) -> str:
    value = value.replace("postgres://", "postgresql://", 1) if value.startswith("postgres://") else value
    parts = urlsplit(value)
    # Supabase's Vercel integration appends `supa` as provider metadata. It is
    # not a libpq option, so passing it through makes psycopg reject the DSN.
    query = urlencode([(key, val) for key, val in parse_qsl(parts.query, keep_blank_values=True)
                       if key.lower() != "supa"])
    return urlunsplit(parts._replace(query=query))


def postgres_url() -> str:
    value = (os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL")
             or os.environ.get("POSTGRES_URL_NON_POOLING") or "").strip()
    return _normalize_postgres_url(value)


def pg_dump_url() -> str:
    value = (os.environ.get("POSTGRES_URL_NON_POOLING") or os.environ.get("DATABASE_URL")
             or os.environ.get("POSTGRES_URL") or "").strip()
    return _normalize_postgres_url(value)


def hosted_database_enabled() -> bool:
    return bool(postgres_url())


class HybridRow:
    """A result row addressable by either numeric index or column name."""
    def __init__(self, values, names):
        self._values = tuple(values)
        self._names = tuple(names)

    def __getitem__(self, key):
        if isinstance(key, str):
            try:
                key = self._names.index(key)
            except ValueError as exc:
                raise KeyError(key) from exc
        return self._values[key]

    def __iter__(self):
        return iter(self._values)

    def __len__(self):
        return len(self._values)

    def keys(self):
        return self._names

    def get(self, key, default=None):
        try:
            return self[key]
        except (KeyError, IndexError):
            return default


class PostgresCursor:
    def __init__(self, cursor):
        self._cursor = cursor

    @property
    def description(self):
        return self._cursor.description

    @property
    def rowcount(self):
        return self._cursor.rowcount

    @property
    def lastrowid(self):
        return getattr(self._cursor, "lastrowid", None)

    def _row(self, row):
        if row is None:
            return None
        names = [column.name for column in self._cursor.description or ()]
        return HybridRow(row, names)

    def fetchone(self):
        return self._row(self._cursor.fetchone())

    def fetchall(self):
        return [self._row(row) for row in self._cursor.fetchall()]

    def __iter__(self):
        for row in self._cursor:
            yield self._row(row)

    def close(self):
        self._cursor.close()


class PostgresConnection:
    """Small sqlite3-style adapter for the app's qmark SQL and row access."""
    def __init__(self, connection, release=None):
        self._connection = connection
        self._release = release
        self._closed = False
        self.row_factory = None

    @staticmethod
    def _sql(sql):
        out = []
        quote = None
        line_comment = False
        block_comment = False
        index = 0
        while index < len(sql):
            char = sql[index]
            next_char = sql[index + 1] if index + 1 < len(sql) else ""
            if line_comment:
                out.append(char)
                if char == "\n": line_comment = False
            elif block_comment:
                out.append(char)
                if char == "*" and next_char == "/":
                    out.append(next_char); index += 1; block_comment = False
            elif quote:
                out.append(char)
                if char == quote:
                    if next_char == quote:
                        out.append(next_char); index += 1
                    else:
                        quote = None
            elif char in ("'", '"'):
                quote = char; out.append(char)
            elif char == "-" and next_char == "-":
                out.extend((char, next_char)); index += 1; line_comment = True
            elif char == "/" and next_char == "*":
                out.extend((char, next_char)); index += 1; block_comment = True
            elif char == "?":
                out.append("%s")
            else:
                out.append(char)
            index += 1
        return "".join(out)

    def execute(self, sql, parameters=()):
        return PostgresCursor(self._connection.execute(self._sql(sql), parameters))

    def executemany(self, sql, parameters):
        cursor = self._connection.cursor()
        cursor.executemany(self._sql(sql), parameters)
        return PostgresCursor(cursor)

    def executescript(self, script):
        cursor = None
        pending = ""
        for line in script.splitlines(keepends=True):
            pending += line
            if sqlite3.complete_statement(pending):
                statement = pending.strip()
                pending = ""
                if statement:
                    cursor = self._connection.execute(self._sql(statement))
        if pending.strip():
            cursor = self._connection.execute(self._sql(pending.strip()))
        return PostgresCursor(cursor) if cursor is not None else None

    def commit(self):
        self._connection.commit()

    def rollback(self):
        self._connection.rollback()

    def close(self):
        if self._closed:
            return
        self._closed = True
        if self._release:
            self._release(self._connection)
        else:
            self._connection.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            self.rollback() if exc_type else self.commit()
        finally:
            self.close()
        return False


def connect(database_path=None):
    url = postgres_url()
    if not url:
        if database_path is None:
            raise RuntimeError("A SQLite database path is required when PostgreSQL is not configured")
        connection = sqlite3.connect(database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    global _PG_POOL
    try:
        from psycopg_pool import ConnectionPool
    except ImportError as exc:
        raise RuntimeError("Install psycopg with its pool extra to connect to the hosted PostgreSQL database") from exc
    if _PG_POOL is None:
        with _PG_POOL_LOCK:
            if _PG_POOL is None:
                _PG_POOL = ConnectionPool(
                    conninfo=url,
                    min_size=1,
                    max_size=4,
                    timeout=8,
                    max_waiting=12,
                    kwargs={"connect_timeout": 10, "prepare_threshold": None},
                )
    pool = _PG_POOL
    connection = pool.getconn()
    return PostgresConnection(connection, release=pool.putconn)


def schema_for_backend(schema: str) -> str:
    if not hosted_database_enabled():
        return schema
    schema = schema.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "BIGSERIAL PRIMARY KEY").replace(
        " UNIQUE COLLATE NOCASE", " UNIQUE")
    return re.sub(r"\bREAL\b", "DOUBLE PRECISION", schema)


def table_column_names(connection, table_name: str):
    if not hosted_database_enabled():
        return {row[1] for row in connection.execute("PRAGMA table_info(" + table_name + ")")}
    rows = connection.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema=current_schema() AND table_name=?", (table_name,)
    ).fetchall()
    return {row["column_name"] for row in rows}
