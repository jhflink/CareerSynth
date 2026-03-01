"""Embedding computation, caching, and similarity functions."""

import json
import os
import sqlite3
from typing import Optional

import numpy as np


def _call_embedding_api(text: str, model: str = "text-embedding-3-small") -> list[float]:
    """Call the OpenAI embedding API.

    Args:
        text: Text to embed.
        model: Embedding model name.

    Returns:
        Embedding vector as a list of floats.
    """
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "OPENAI_API_KEY environment variable is required for embeddings. "
            "Set it with: export OPENAI_API_KEY=your-key"
        )

    from openai import OpenAI

    client = OpenAI(api_key=api_key)
    response = client.embeddings.create(input=[text], model=model)
    return response.data[0].embedding


def compute_embedding(text: str, model: str = "text-embedding-3-small") -> list[float]:
    """Compute an embedding for the given text.

    Args:
        text: Text to embed.
        model: Embedding model name.

    Returns:
        Embedding vector as a list of floats.
    """
    return _call_embedding_api(text, model)


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors.

    Args:
        a: First vector.
        b: Second vector.

    Returns:
        Cosine similarity (float between -1 and 1).
    """
    a_np = np.array(a, dtype=np.float64)
    b_np = np.array(b, dtype=np.float64)

    dot = np.dot(a_np, b_np)
    norm_a = np.linalg.norm(a_np)
    norm_b = np.linalg.norm(b_np)

    if norm_a == 0 or norm_b == 0:
        return 0.0

    return float(dot / (norm_a * norm_b))


def get_cached_embedding(conn: sqlite3.Connection, phrase_id: str) -> Optional[list[float]]:
    """Get a cached embedding from the database."""
    cursor = conn.execute(
        "SELECT embedding_json FROM phrases WHERE phrase_id=? AND embedding_json IS NOT NULL",
        (phrase_id,),
    )
    row = cursor.fetchone()
    if row:
        return json.loads(row[0] if isinstance(row, tuple) else row["embedding_json"])
    return None


def cache_embedding(conn: sqlite3.Connection, phrase_id: str, embedding: list[float]) -> None:
    """Cache an embedding in the database."""
    conn.execute(
        "UPDATE phrases SET embedding_json=? WHERE phrase_id=?",
        (json.dumps(embedding), phrase_id),
    )
    conn.commit()
