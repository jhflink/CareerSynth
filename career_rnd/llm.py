"""LLM integration for skill extraction, atom mapping, and merge suggestions."""

import json
import os
import sqlite3
from pathlib import Path
from typing import Any


PROMPTS_DIR = Path(__file__).parent / "prompts"


def _call_llm(prompt: str, system: str = "", model: str = "gpt-4o-mini") -> str:
    """Call the OpenAI Chat Completion API.

    Args:
        prompt: User prompt.
        system: System prompt.
        model: Model name.

    Returns:
        Response text.
    """
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "OPENAI_API_KEY environment variable is required. "
            "Set it with: export OPENAI_API_KEY=your-key"
        )

    from openai import OpenAI

    client = OpenAI(api_key=api_key)
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    response = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=0.2,
        response_format={"type": "json_object"},
    )
    return response.choices[0].message.content


def _load_prompt(name: str) -> str:
    """Load a prompt template from the prompts directory."""
    path = PROMPTS_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"Prompt template not found: {path}")
    return path.read_text(encoding="utf-8")


def extract_skills_from_text(text: str) -> dict:
    """Extract skill phrases from job description text using LLM.

    Args:
        text: Raw job description text.

    Returns:
        Dict with keys: company, title, location, language,
        skills_must, skills_want, responsibilities, traits.
    """
    prompt_template = _load_prompt("extract_skills.md")
    prompt = prompt_template + "\n\n---\n\nJob Description:\n\n" + text

    response = _call_llm(prompt, system="You are a skill extraction assistant. Output valid JSON only.")
    return json.loads(response)


def extract_skills_for_roles(conn: sqlite3.Connection) -> int:
    """Extract skills for all roles that don't have phrases yet.

    Returns the number of roles processed.
    """
    # Find roles without phrases
    cursor = conn.execute("""
        SELECT r.role_id, r.raw_text_path
        FROM roles r
        LEFT JOIN phrases p ON r.role_id = p.role_id
        WHERE p.phrase_id IS NULL AND r.raw_text_path IS NOT NULL
        GROUP BY r.role_id
    """)
    roles = cursor.fetchall()
    count = 0

    for role in roles:
        role_id = role[0] if isinstance(role, tuple) else role["role_id"]
        raw_path = role[1] if isinstance(role, tuple) else role["raw_text_path"]

        try:
            from career_rnd.extract import extract_text
            text = extract_text(raw_path)
            skills = extract_skills_from_text(text)

            # Update role metadata
            conn.execute(
                "UPDATE roles SET company=?, title=?, location=?, lang=?, description=? WHERE role_id=?",
                (
                    skills.get("company", ""),
                    skills.get("title", ""),
                    skills.get("location", ""),
                    skills.get("language", "en"),
                    skills.get("summary", ""),
                    role_id,
                ),
            )

            # Insert phrases with section and weight
            import hashlib
            section_map = {
                "skills_must": ("must", 1.0),
                "skills_want": ("want", 0.6),
                "responsibilities": ("responsibility", 0.8),
                "traits": ("profile", 0.5),
            }

            for section_key, (section_name, weight) in section_map.items():
                for phrase_text in skills.get(section_key, []):
                    phrase_id = hashlib.sha256(
                        f"{role_id}:{phrase_text}".encode()
                    ).hexdigest()[:16]
                    phrase_id = f"phr_{phrase_id}"

                    conn.execute(
                        """INSERT OR IGNORE INTO phrases
                           (phrase_id, role_id, phrase, section, weight)
                           VALUES (?, ?, ?, ?, ?)""",
                        (phrase_id, role_id, phrase_text, section_name, weight),
                    )

            conn.commit()
            count += 1
        except Exception as e:
            print(f"Warning: Failed to extract skills for {role_id}: {e}")

    return count


def generate_role_description(raw_text: str) -> str:
    """Generate a 1-2 sentence description of a role from its raw text.

    Used to backfill descriptions for roles ingested before the summary
    field was added to the extract_skills prompt.
    """
    prompt = (
        "Given the following job description, write a 1-2 sentence summary "
        "describing the role's core focus, team context, and what makes it "
        "distinctive. Be specific — mention the domain, key technologies, "
        "and the type of work. Output JSON: {\"summary\": \"...\"}\n\n"
        "---\n\n" + raw_text[:3000]
    )
    response = _call_llm(prompt, system="You are a concise job description summarizer. Output valid JSON only.")
    data = json.loads(response)
    return data.get("summary", "")


def generate_synthesis_summary(
    total_roles: int,
    total_atoms: int,
    top_scores: list[dict],
    num_clusters: int,
) -> str:
    """Generate a narrative synthesis of the overlap analysis data.

    Returns a 2-4 sentence summary suitable for the HTML report header.
    """
    # Build a compact data summary for the LLM
    top_atoms_text = ", ".join(
        f"{s['name']} (score={s['overlap_score']}, {s['role_count']} roles)"
        for s in top_scores[:8]
    )
    prompt = (
        f"You are summarizing a career skill overlap analysis. "
        f"Data: {total_roles} roles analyzed, {total_atoms} skill atoms in library, "
        f"{num_clusters} role cluster(s) detected.\n"
        f"Top overlapping atoms: {top_atoms_text}\n\n"
        f"Write a 2-4 sentence narrative synthesis of what this data reveals "
        f"about the user's career focus and skill convergence across these roles. "
        f"Be specific about which skill areas dominate and what patterns emerge. "
        f"Output JSON: {{\"synthesis\": \"...\"}}"
    )
    response = _call_llm(prompt, system="You are a career analyst. Output valid JSON only.")
    data = json.loads(response)
    return data.get("synthesis", "")


def suggest_merges(conn: sqlite3.Connection) -> list[dict]:
    """Suggest atom merges/renames/splits based on current data.

    Returns a list of suggestions with action and description.
    """
    # Get atom stats
    cursor = conn.execute("""
        SELECT a.atom_id, a.name, a.definition,
               COUNT(DISTINCT m.phrase_id) as phrase_count,
               COUNT(DISTINCT p.role_id) as role_count
        FROM atoms a
        LEFT JOIN mappings m ON a.atom_id = m.atom_id
        LEFT JOIN phrases p ON m.phrase_id = p.phrase_id
        GROUP BY a.atom_id
        HAVING phrase_count > 0
        ORDER BY phrase_count DESC
    """)
    atoms_with_stats = cursor.fetchall()

    if not atoms_with_stats:
        return []

    prompt_template = _load_prompt("merge_suggestions.md")
    atoms_text = "\n".join(
        f"- {row[0]}: {row[1]} (definition: {row[2]}, phrases: {row[3]}, roles: {row[4]})"
        for row in atoms_with_stats
    )

    prompt = prompt_template + "\n\n---\n\nAtom Library:\n\n" + atoms_text

    try:
        response = _call_llm(prompt, system="You are a taxonomy advisor. Output valid JSON only.")
        data = json.loads(response)
        return data.get("suggestions", [])
    except Exception:
        return []
