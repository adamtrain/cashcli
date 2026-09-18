"""Database path resolution, connections, and migrations."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from cashcli.errors import CashError
from cashcli.migrations import LATEST_VERSION, MIGRATIONS

ENV_VAR = "CASHCLI_DB"


def default_path() -> Path:
    """~/.config/cashcli/budget.sqlite, honouring $XDG_CONFIG_HOME when it is set."""
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".config"
    return base / "cashcli" / "budget.sqlite"


DEFAULT_PATH = default_path()


def resolve_db_path(cli_arg: str | None) -> Path:
    if cli_arg:
        return Path(cli_arg).expanduser()
    env = os.environ.get(ENV_VAR)
    if env:
        return Path(env).expanduser()
    return default_path()


def _open(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path, isolation_level=None)  # autocommit; explicit BEGIN where needed
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def current_version(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
    ).fetchone()
    if row is None:
        return 0
    v = conn.execute("SELECT max(version) FROM schema_version").fetchone()[0]
    return int(v or 0)


def migrate(conn: sqlite3.Connection) -> int:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_version "
        "(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
    )
    current = current_version(conn)
    if current > LATEST_VERSION:
        raise CashError(
            f"database schema version {current} is newer than this cashcli ({LATEST_VERSION}); "
            "upgrade cashcli",
            "db_newer_than_cli",
        )
    for version, sql in MIGRATIONS:
        if version <= current:
            continue
        script = (
            "BEGIN;\n"
            + sql
            + f"\nINSERT INTO schema_version(version, applied_at) VALUES ({int(version)}, "
            "strftime('%Y-%m-%dT%H:%M:%SZ','now'));\nCOMMIT;"
        )
        try:
            conn.executescript(script)
        except Exception:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        current = version
    return current


def connect(path: Path, *, create: bool = False) -> sqlite3.Connection:
    """Open (and migrate) the budget database. Non-init commands require the file to exist."""
    if not path.exists():
        if not create:
            raise CashError(
                f"database {path} does not exist; run `cash init` (or pass --db / set {ENV_VAR})",
                "db_not_found",
            )
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = _open(path)
    migrate(conn)
    return conn


def readonly_connect(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise CashError(f"database {path} does not exist", "db_not_found")
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = 1")
    return conn
