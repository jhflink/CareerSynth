"""Phrase → Atom mapping pipeline (embedding similarity + LLM merge judge)."""

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DECISIONS_LOG = Path(__file__).parent.parent / "skill_library" / "decisions.jsonl"

# Similarity thresholds
HIGH_THRESHOLD = 0.82  # Auto-map as SAME
LOW_THRESHOLD = 0.55   # Below this, propose NEW


def _get_mapping_decisions(
    conn: sqlite3.Connection, role_id: str, phrases: list[dict]
) -> list[dict]:
    """Get mapping decisions for phrases using the two-stage hybrid approach.

    Stage 1: Embedding similarity for fast candidate selection
    Stage 2: LLM merge judge for borderline cases

    Returns list of decision dicts.
    """
    from career_rnd.atoms import get_all_atoms
    from career_rnd.embeddings import compute_embeddings_batch, cosine_similarity

    atoms = get_all_atoms(conn)
    if not atoms:
        return [
            {
                "phrase": p["phrase"],
                "atom_id": None,
                "decision": "NEW",
                "confidence": 0.5,
                "rationale": "No atoms in library yet",
            }
            for p in phrases
        ]

    # Build atom text representations and batch-embed them
    atom_texts = []
    for atom in atoms:
        atom_texts.append(f"{atom['name']}: {atom['definition']}")

    print(f"  Computing embeddings for {len(atoms)} atoms + {len(phrases)} phrases...")
    atom_embeddings = compute_embeddings_batch(atom_texts)

    # Batch-embed all phrases too
    phrase_texts = [p["phrase"] for p in phrases]
    phrase_embeddings = compute_embeddings_batch(phrase_texts)

    decisions = []
    for i, phrase_data in enumerate(phrases):
        phrase = phrase_data["phrase"]

        try:
            phrase_emb = phrase_embeddings[i]

            # Compare to all atoms
            best_match = None
            best_sim = -1.0

            for j, atom in enumerate(atoms):
                sim = cosine_similarity(phrase_emb, atom_embeddings[j])
                if sim > best_sim:
                    best_sim = sim
                    best_match = atom

            if best_sim >= HIGH_THRESHOLD:
                decisions.append({
                    "phrase": phrase,
                    "atom_id": best_match["atom_id"],
                    "decision": "SAME",
                    "confidence": round(best_sim, 3),
                    "rationale": f"High similarity ({best_sim:.3f}) to '{best_match['name']}'",
                })
            elif best_sim >= LOW_THRESHOLD:
                # Send to LLM judge for borderline cases
                decision = _llm_judge(phrase, best_match, best_sim, atoms[:5])
                decisions.append(decision)
            else:
                decisions.append({
                    "phrase": phrase,
                    "atom_id": None,
                    "decision": "NEW",
                    "confidence": round(1.0 - best_sim, 3),
                    "rationale": f"Low similarity ({best_sim:.3f}) to nearest atom '{best_match['name']}'",
                })
        except Exception as e:
            decisions.append({
                "phrase": phrase,
                "atom_id": None,
                "decision": "AMBIGUOUS",
                "confidence": 0.0,
                "rationale": f"Error during matching: {e}",
            })

    print(f"  Decisions: {len([d for d in decisions if d['decision']=='SAME'])} SAME, "
          f"{len([d for d in decisions if d['decision']=='CHILD'])} CHILD, "
          f"{len([d for d in decisions if d['decision']=='NEW'])} NEW, "
          f"{len([d for d in decisions if d['decision']=='AMBIGUOUS'])} AMBIGUOUS")

    return decisions


def _llm_judge(
    phrase: str, best_atom: dict, similarity: float, top_atoms: list[dict]
) -> dict:
    """Use LLM to make a borderline mapping decision."""
    from career_rnd.llm import _call_llm, _load_prompt

    prompt_template = _load_prompt("map_to_atoms.md")
    atoms_context = "\n".join(
        f"- {a['atom_id']}: {a['name']} — {a['definition']}"
        for a in top_atoms
    )
    prompt = (
        prompt_template
        + f"\n\n---\n\nPhrase: \"{phrase}\"\n"
        + f"Best match: {best_atom['atom_id']} ({best_atom['name']}, similarity: {similarity:.3f})\n"
        + f"\nTop candidate atoms:\n{atoms_context}\n"
        + "\nDecide: SAME, CHILD, NEW, or AMBIGUOUS. Respond with JSON."
    )

    try:
        response = _call_llm(prompt, system="You are a skill taxonomy judge. Output valid JSON.")
        data = json.loads(response)
        return {
            "phrase": phrase,
            "atom_id": data.get("atom_id", best_atom["atom_id"]),
            "decision": data.get("decision", "AMBIGUOUS"),
            "confidence": data.get("confidence", 0.5),
            "rationale": data.get("rationale", "LLM judge decision"),
        }
    except Exception as e:
        return {
            "phrase": phrase,
            "atom_id": best_atom["atom_id"],
            "decision": "AMBIGUOUS",
            "confidence": 0.3,
            "rationale": f"LLM judge failed: {e}",
        }


def map_phrases_to_atoms(
    conn: sqlite3.Connection, role_id: str, phrases: list[dict]
) -> list[dict]:
    """Map a list of phrases to atoms and store decisions.

    Args:
        conn: SQLite connection.
        role_id: The role these phrases belong to.
        phrases: List of dicts with phrase, section, weight.

    Returns:
        List of decision dicts.
    """
    decisions = _get_mapping_decisions(conn, role_id, phrases)

    now = datetime.now(timezone.utc).isoformat()
    for decision in decisions:
        atom_id = decision.get("atom_id")
        if not atom_id:
            continue

        # Validate atom exists in DB
        atom_exists = conn.execute(
            "SELECT 1 FROM atoms WHERE atom_id=?", (atom_id,)
        ).fetchone()
        if not atom_exists:
            continue

        # Look up actual phrase_id from DB by matching phrase text + role
        phrase_text = decision["phrase"]
        row = conn.execute(
            "SELECT phrase_id FROM phrases WHERE role_id=? AND phrase=?",
            (role_id, phrase_text),
        ).fetchone()

        if not row:
            continue

        phrase_id = row[0] if isinstance(row, tuple) else row["phrase_id"]
        mapping_id = f"map_{hashlib.sha256(f'{phrase_id}:{atom_id}'.encode()).hexdigest()[:16]}"

        conn.execute(
            """INSERT OR IGNORE INTO mappings
               (mapping_id, phrase_id, atom_id, decision, confidence, rationale, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                mapping_id,
                phrase_id,
                atom_id,
                decision["decision"],
                decision.get("confidence", 0.0),
                decision.get("rationale", ""),
                now,
            ),
        )

    conn.commit()

    # Log decisions to JSONL
    _log_decisions(decisions, role_id)

    return decisions


def map_all_unmapped(conn: sqlite3.Connection) -> int:
    """Map all unmapped phrases to atoms.

    Returns count of phrases mapped.
    """
    # Find phrases without mappings
    cursor = conn.execute("""
        SELECT p.phrase_id, p.role_id, p.phrase, p.section, p.weight
        FROM phrases p
        LEFT JOIN mappings m ON p.phrase_id = m.phrase_id
        WHERE m.mapping_id IS NULL
    """)
    unmapped = cursor.fetchall()

    if not unmapped:
        return 0

    # Group by role
    by_role: dict[str, list[dict]] = {}
    for row in unmapped:
        role_id = row[1] if isinstance(row, tuple) else row["role_id"]
        phrase_data = {
            "phrase": row[2] if isinstance(row, tuple) else row["phrase"],
            "section": row[3] if isinstance(row, tuple) else row["section"],
            "weight": row[4] if isinstance(row, tuple) else row["weight"],
        }
        by_role.setdefault(role_id, []).append(phrase_data)

    total = 0
    for role_id, phrases in by_role.items():
        results = map_phrases_to_atoms(conn, role_id, phrases)
        total += len(results)

    return total


def _log_decisions(decisions: list[dict], role_id: str) -> None:
    """Append decisions to the JSONL log."""
    DECISIONS_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(DECISIONS_LOG, "a", encoding="utf-8") as f:
        for d in decisions:
            entry = {**d, "role_id": role_id, "timestamp": datetime.now(timezone.utc).isoformat()}
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
