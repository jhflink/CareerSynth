"""File ingestion — discover and register job description files."""

import hashlib
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


SUPPORTED_EXTENSIONS = {".pdf", ".txt", ".html", ".htm", ".md"}


def ingest_file(conn: sqlite3.Connection, file_path: str) -> str | None:
    """Ingest a single file as a role.

    Returns role_id if newly ingested, or existing role_id if duplicate.
    """
    path = Path(file_path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    # Generate stable role_id from file content hash
    content_hash = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
    role_id = f"role_{content_hash}"

    # Check if already ingested
    cursor = conn.execute("SELECT role_id FROM roles WHERE role_id=?", (role_id,))
    if cursor.fetchone():
        return role_id

    conn.execute(
        """INSERT INTO roles (role_id, source_path, date_added, raw_text_path)
           VALUES (?, ?, ?, ?)""",
        (role_id, str(path), datetime.now(timezone.utc).isoformat(), str(path)),
    )
    conn.commit()
    return role_id


def ingest_path(conn: sqlite3.Connection, path: str) -> list[dict]:
    """Ingest a file or directory.

    Returns list of dicts with role_id and source_path.
    """
    p = Path(path).resolve()
    results = []

    if p.is_file():
        if p.suffix.lower() in SUPPORTED_EXTENSIONS:
            role_id = ingest_file(conn, str(p))
            results.append({"role_id": role_id, "source_path": str(p)})
    elif p.is_dir():
        for f in sorted(p.iterdir()):
            if f.is_file() and f.suffix.lower() in SUPPORTED_EXTENSIONS:
                role_id = ingest_file(conn, str(f))
                results.append({"role_id": role_id, "source_path": str(f)})
    else:
        raise FileNotFoundError(f"Path not found: {path}")

    return results
