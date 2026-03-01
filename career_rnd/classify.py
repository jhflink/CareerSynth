"""Atom distinctiveness classification — LLM-based semantic judge."""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from career_rnd.llm import _call_llm, _load_prompt


DEFAULT_REFERENCE_UNIVERSE = (
    "Game development and interactive media engineering roles, "
    "including XR/spatial computing, UX prototyping, and creative technology."
)

VALID_LABELS = {
    "TABLE_STAKES_SOFTWARE",
    "TABLE_STAKES_GAMEDEV",
    "DIFFERENTIATOR",
    "NICHE",
    "AMBIGUOUS",
}

CONFIDENCE_THRESHOLD = 0.6  # Below this, auto-set to AMBIGUOUS


def classify_atoms(
    conn: sqlite3.Connection,
    reference_universe: str | None = None,
) -> int:
    """Classify all mapped atoms by distinctiveness using LLM.

    Skips pinned atoms. Atoms with role_count == 0 are skipped.

    Returns the number of atoms classified.
    """
    universe = reference_universe or DEFAULT_REFERENCE_UNIVERSE

    # Gather atom stats for all atoms that have at least one mapping
    atom_stats = _gather_atom_stats(conn)
    if not atom_stats:
        return 0

    # Filter out pinned atoms
    pinned = _get_pinned_atom_ids(conn)
    to_classify = [a for a in atom_stats if a["atom_id"] not in pinned]

    if not to_classify:
        return 0

    # Classify in batches of 20
    now = datetime.now(timezone.utc).isoformat()
    count = 0

    for i in range(0, len(to_classify), 20):
        batch = to_classify[i : i + 20]
        classifications = _classify_batch(batch, universe)

        for c in classifications:
            atom_id = c.get("atom_id", "")
            label = c.get("label", "AMBIGUOUS")
            confidence = c.get("confidence", 0.0)
            rationale = c.get("rationale", "")

            # Validate label
            if label not in VALID_LABELS:
                label = "AMBIGUOUS"

            # Confidence gate
            if confidence < CONFIDENCE_THRESHOLD:
                label = "AMBIGUOUS"

            # Upsert into atom_classifications
            conn.execute(
                """INSERT OR REPLACE INTO atom_classifications
                   (atom_id, label, confidence, rationale, reference_universe,
                    classified_at, is_pinned)
                   VALUES (?, ?, ?, ?, ?, ?, 0)""",
                (atom_id, label, confidence, rationale, universe, now),
            )
            count += 1

        conn.commit()

    return count


def _gather_atom_stats(conn: sqlite3.Connection) -> list[dict]:
    """Gather enriched stats for all atoms with at least one mapping."""
    cursor = conn.execute("""
        SELECT a.atom_id, a.name, a.definition,
               COUNT(DISTINCT m.phrase_id) as phrase_count,
               COUNT(DISTINCT p.role_id) as role_count
        FROM atoms a
        JOIN mappings m ON a.atom_id = m.atom_id
        JOIN phrases p ON m.phrase_id = p.phrase_id
        WHERE m.decision IN ('SAME', 'CHILD')
        GROUP BY a.atom_id
        HAVING role_count > 0
        ORDER BY role_count DESC
    """)
    atoms = []
    for row in cursor.fetchall():
        atom_id = row[0] if isinstance(row, tuple) else row["atom_id"]
        atoms.append({
            "atom_id": atom_id,
            "name": row[1] if isinstance(row, tuple) else row["name"],
            "definition": row[2] if isinstance(row, tuple) else row["definition"],
            "phrase_count": row[3] if isinstance(row, tuple) else row["phrase_count"],
            "role_count": row[4] if isinstance(row, tuple) else row["role_count"],
        })

    # Enrich with section data and aliases
    total_roles = conn.execute("SELECT COUNT(*) FROM roles").fetchone()[0] or 1

    for atom in atoms:
        atom_id = atom["atom_id"]

        # Sections this atom appears in
        sections_cursor = conn.execute("""
            SELECT DISTINCT p.section
            FROM mappings m
            JOIN phrases p ON m.phrase_id = p.phrase_id
            WHERE m.atom_id = ? AND m.decision IN ('SAME', 'CHILD')
        """, (atom_id,))
        atom["sections"] = [
            r[0] if isinstance(r, tuple) else r["section"]
            for r in sections_cursor.fetchall()
        ]

        # Aliases / positive examples
        alias_cursor = conn.execute(
            "SELECT alias FROM atom_aliases WHERE atom_id = ?", (atom_id,)
        )
        atom["aliases"] = [
            r[0] if isinstance(r, tuple) else r["alias"]
            for r in alias_cursor.fetchall()
        ][:5]  # Limit to 5

        atom["frequency"] = round(atom["role_count"] / total_roles, 3)

    return atoms


def _classify_batch(atoms: list[dict], reference_universe: str) -> list[dict]:
    """Call LLM to classify a batch of atoms."""
    prompt_template = _load_prompt("classify_distinctiveness.md")
    prompt = prompt_template.replace("{reference_universe}", reference_universe)

    # Build atom context
    atoms_text = "\n".join(
        f"- {a['atom_id']}: {a['name']}\n"
        f"  Definition: {a['definition']}\n"
        f"  Examples: {', '.join(a.get('aliases', [])[:3])}\n"
        f"  Frequency: {a['frequency']} ({a['role_count']} roles)\n"
        f"  Sections: {', '.join(a.get('sections', []))}"
        for a in atoms
    )

    full_prompt = prompt + "\n\n---\n\nAtoms to classify:\n\n" + atoms_text

    try:
        response = _call_llm(
            full_prompt,
            system="You are a career analyst. Classify atoms by distinctiveness. Output valid JSON only.",
        )
        data = json.loads(response)
        return data.get("classifications", [])
    except Exception as e:
        # Fallback: mark all as AMBIGUOUS
        return [
            {
                "atom_id": a["atom_id"],
                "label": "AMBIGUOUS",
                "confidence": 0.0,
                "rationale": f"Classification failed: {e}",
            }
            for a in atoms
        ]


def get_classifications(conn: sqlite3.Connection) -> dict[str, dict]:
    """Get all atom classifications as a dict keyed by atom_id."""
    cursor = conn.execute(
        "SELECT atom_id, label, confidence, rationale, is_pinned "
        "FROM atom_classifications"
    )
    result = {}
    for row in cursor.fetchall():
        atom_id = row[0] if isinstance(row, tuple) else row["atom_id"]
        result[atom_id] = {
            "label": row[1] if isinstance(row, tuple) else row["label"],
            "confidence": row[2] if isinstance(row, tuple) else row["confidence"],
            "rationale": row[3] if isinstance(row, tuple) else row["rationale"],
            "is_pinned": row[4] if isinstance(row, tuple) else row["is_pinned"],
        }
    return result


def pin_atom(conn: sqlite3.Connection, atom_id: str, label: str) -> bool:
    """Pin an atom to a specific classification label.

    Returns True if successful, False if atom doesn't exist.
    """
    if label not in VALID_LABELS:
        raise ValueError(f"Invalid label: {label}. Must be one of {VALID_LABELS}")

    atom = conn.execute(
        "SELECT atom_id FROM atoms WHERE atom_id = ?", (atom_id,)
    ).fetchone()
    if not atom:
        return False

    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """INSERT OR REPLACE INTO atom_classifications
           (atom_id, label, confidence, rationale, reference_universe,
            classified_at, is_pinned)
           VALUES (?, ?, 1.0, 'User override (pinned)', 'N/A — user pinned', ?, 1)""",
        (atom_id, label, now),
    )
    conn.commit()
    return True


def unpin_atom(conn: sqlite3.Connection, atom_id: str) -> bool:
    """Remove pin from an atom, allowing reclassification.

    Returns True if the atom was pinned, False otherwise.
    """
    row = conn.execute(
        "SELECT is_pinned FROM atom_classifications WHERE atom_id = ?",
        (atom_id,),
    ).fetchone()
    if not row:
        return False

    is_pinned = row[0] if isinstance(row, tuple) else row["is_pinned"]
    if not is_pinned:
        return False

    conn.execute(
        "UPDATE atom_classifications SET is_pinned = 0 WHERE atom_id = ?",
        (atom_id,),
    )
    conn.commit()
    return True


def get_review_queue(conn: sqlite3.Connection) -> list[dict]:
    """Get atoms that need review (AMBIGUOUS or low confidence)."""
    cursor = conn.execute("""
        SELECT c.atom_id, a.name, c.label, c.confidence, c.rationale, c.is_pinned
        FROM atom_classifications c
        JOIN atoms a ON c.atom_id = a.atom_id
        WHERE c.label = 'AMBIGUOUS' OR (c.confidence < 0.8 AND c.is_pinned = 0)
        ORDER BY c.confidence ASC
    """)
    return [
        {
            "atom_id": row[0] if isinstance(row, tuple) else row["atom_id"],
            "name": row[1] if isinstance(row, tuple) else row["name"],
            "label": row[2] if isinstance(row, tuple) else row["label"],
            "confidence": row[3] if isinstance(row, tuple) else row["confidence"],
            "rationale": row[4] if isinstance(row, tuple) else row["rationale"],
            "is_pinned": row[5] if isinstance(row, tuple) else row["is_pinned"],
        }
        for row in cursor.fetchall()
    ]


def _get_pinned_atom_ids(conn: sqlite3.Connection) -> set[str]:
    """Get set of atom_ids that are pinned."""
    cursor = conn.execute(
        "SELECT atom_id FROM atom_classifications WHERE is_pinned = 1"
    )
    return {
        row[0] if isinstance(row, tuple) else row["atom_id"]
        for row in cursor.fetchall()
    }
