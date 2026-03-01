"""Atom library management — loading, querying, and updating Skill Atoms."""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ATOMS_FILE = Path(__file__).parent.parent / "skill_library" / "atoms.json"


def load_seed_atoms(conn: sqlite3.Connection, atoms_path: str | None = None) -> int:
    """Load seed atoms from atoms.json into the database.

    Skips atoms that already exist (based on atom_id).

    Args:
        conn: SQLite connection.
        atoms_path: Optional path to atoms.json. Uses default if None.

    Returns:
        Number of atoms loaded.
    """
    path = Path(atoms_path) if atoms_path else ATOMS_FILE
    if not path.exists():
        raise FileNotFoundError(f"Seed atoms file not found: {path}")

    with open(path, encoding="utf-8") as f:
        atoms = json.load(f)

    now = datetime.now(timezone.utc).isoformat()
    count = 0

    for atom in atoms:
        atom_id = atom["atom_id"]

        # Skip if already exists
        existing = conn.execute(
            "SELECT atom_id FROM atoms WHERE atom_id=?", (atom_id,)
        ).fetchone()
        if existing:
            continue

        conn.execute(
            """INSERT INTO atoms (atom_id, name, definition, parent_atom_id, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                atom_id,
                atom["name"],
                atom["definition"],
                atom.get("parent_atom_id"),
                now,
                now,
            ),
        )

        # Insert aliases from positive examples
        for i, example in enumerate(atom.get("positive_examples", [])):
            alias_id = f"alias_{atom_id}_{i}"
            conn.execute(
                """INSERT OR IGNORE INTO atom_aliases (alias_id, atom_id, alias)
                   VALUES (?, ?, ?)""",
                (alias_id, atom_id, example),
            )

        count += 1

    conn.commit()
    return count


def get_all_atoms(conn: sqlite3.Connection) -> list[dict]:
    """Get all atoms from the database.

    Returns:
        List of atom dicts with id, name, definition, parent_atom_id.
    """
    cursor = conn.execute(
        "SELECT atom_id, name, definition, parent_atom_id FROM atoms ORDER BY atom_id"
    )
    return [
        {
            "atom_id": row[0] if isinstance(row, tuple) else row["atom_id"],
            "name": row[1] if isinstance(row, tuple) else row["name"],
            "definition": row[2] if isinstance(row, tuple) else row["definition"],
            "parent_atom_id": row[3] if isinstance(row, tuple) else row["parent_atom_id"],
        }
        for row in cursor.fetchall()
    ]


def get_atom_with_aliases(conn: sqlite3.Connection, atom_id: str) -> dict | None:
    """Get an atom with its aliases."""
    cursor = conn.execute(
        "SELECT atom_id, name, definition, parent_atom_id FROM atoms WHERE atom_id=?",
        (atom_id,),
    )
    row = cursor.fetchone()
    if not row:
        return None

    atom = {
        "atom_id": row[0] if isinstance(row, tuple) else row["atom_id"],
        "name": row[1] if isinstance(row, tuple) else row["name"],
        "definition": row[2] if isinstance(row, tuple) else row["definition"],
        "parent_atom_id": row[3] if isinstance(row, tuple) else row["parent_atom_id"],
    }

    alias_cursor = conn.execute(
        "SELECT alias FROM atom_aliases WHERE atom_id=?", (atom_id,)
    )
    atom["aliases"] = [
        r[0] if isinstance(r, tuple) else r["alias"]
        for r in alias_cursor.fetchall()
    ]

    return atom
