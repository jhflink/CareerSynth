"""SQLite database schema and helper functions for CareerSynth."""

import sqlite3
from pathlib import Path

DEFAULT_DB_PATH = "data/career_rnd.db"


def init_db(db_path: str | None = None) -> sqlite3.Connection:
    """Initialize the database and create tables if they don't exist.

    Args:
        db_path: Path to the SQLite database file. If None, uses default.

    Returns:
        sqlite3.Connection to the initialized database.
    """
    if db_path is None:
        db_path = DEFAULT_DB_PATH

    # Ensure parent directory exists
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")

    _create_tables(conn)
    _migrate(conn)
    return conn


def _create_tables(conn: sqlite3.Connection) -> None:
    """Create all tables if they don't exist."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS roles (
            role_id TEXT PRIMARY KEY,
            source_path TEXT,
            company TEXT,
            title TEXT,
            location TEXT,
            date_added TEXT,
            raw_text_path TEXT,
            lang TEXT,
            description TEXT
        );

        CREATE TABLE IF NOT EXISTS phrases (
            phrase_id TEXT PRIMARY KEY,
            role_id TEXT,
            phrase TEXT,
            section TEXT,
            weight REAL,
            embedding_json TEXT,
            FOREIGN KEY (role_id) REFERENCES roles(role_id)
        );

        CREATE TABLE IF NOT EXISTS atoms (
            atom_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            definition TEXT NOT NULL,
            parent_atom_id TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (parent_atom_id) REFERENCES atoms(atom_id)
        );

        CREATE TABLE IF NOT EXISTS atom_aliases (
            alias_id TEXT PRIMARY KEY,
            atom_id TEXT NOT NULL,
            alias TEXT NOT NULL,
            source_role_id TEXT,
            FOREIGN KEY (atom_id) REFERENCES atoms(atom_id),
            FOREIGN KEY (source_role_id) REFERENCES roles(role_id)
        );

        CREATE TABLE IF NOT EXISTS mappings (
            mapping_id TEXT PRIMARY KEY,
            phrase_id TEXT NOT NULL,
            atom_id TEXT NOT NULL,
            decision TEXT NOT NULL,
            confidence REAL,
            rationale TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (phrase_id) REFERENCES phrases(phrase_id),
            FOREIGN KEY (atom_id) REFERENCES atoms(atom_id)
        );

        CREATE INDEX IF NOT EXISTS idx_phrases_role ON phrases(role_id);
        CREATE INDEX IF NOT EXISTS idx_mappings_phrase ON mappings(phrase_id);
        CREATE INDEX IF NOT EXISTS idx_mappings_atom ON mappings(atom_id);
        CREATE INDEX IF NOT EXISTS idx_aliases_atom ON atom_aliases(atom_id);
    """)
    conn.commit()


def _migrate(conn: sqlite3.Connection) -> None:
    """Apply lightweight migrations for schema changes."""
    # Add description column if missing (added in v2)
    cursor = conn.execute("PRAGMA table_info(roles)")
    columns = {row[1] for row in cursor.fetchall()}
    if "description" not in columns:
        conn.execute("ALTER TABLE roles ADD COLUMN description TEXT")
        conn.commit()


def get_db(db_path: str | None = None) -> sqlite3.Connection:
    """Get a database connection, initializing if needed."""
    return init_db(db_path)
