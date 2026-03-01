"""Overlap scoring, co-occurrence graph, and role clustering."""

import sqlite3
from collections import defaultdict
from itertools import combinations

import networkx as nx
import numpy as np


def calculate_overlap_score(
    frequency: float, centrality: float, cluster_coverage: float
) -> float:
    """Compute the overlap score for an atom.

    OverlapScore = 0.45*frequency + 0.35*centrality + 0.20*cluster_coverage

    All inputs should be normalized to [0, 1].
    """
    return 0.45 * frequency + 0.35 * centrality + 0.20 * cluster_coverage


def build_cooccurrence_graph(conn: sqlite3.Connection) -> nx.Graph:
    """Build a co-occurrence graph from role-atom mappings.

    Nodes = atoms, edges = co-occurrence in the same role.
    Edge weight = number of roles where both atoms co-occur.
    """
    # Get atom-to-role mappings
    cursor = conn.execute("""
        SELECT DISTINCT m.atom_id, p.role_id
        FROM mappings m
        JOIN phrases p ON m.phrase_id = p.phrase_id
        WHERE m.decision IN ('SAME', 'CHILD')
    """)
    rows = cursor.fetchall()

    # Group atoms by role
    role_atoms: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        atom_id = row[0] if isinstance(row, tuple) else row["atom_id"]
        role_id = row[1] if isinstance(row, tuple) else row["role_id"]
        role_atoms[role_id].add(atom_id)

    # Build graph
    G = nx.Graph()

    # Add all mapped atoms as nodes
    all_atoms = set()
    for atoms in role_atoms.values():
        all_atoms.update(atoms)
    G.add_nodes_from(all_atoms)

    # Add edges for co-occurrence
    edge_weights: dict[tuple, int] = defaultdict(int)
    for role_id, atoms in role_atoms.items():
        for a1, a2 in combinations(sorted(atoms), 2):
            edge_weights[(a1, a2)] += 1

    for (a1, a2), weight in edge_weights.items():
        G.add_edge(a1, a2, weight=weight)

    return G


def _detect_clusters(G: nx.Graph) -> dict[str, int]:
    """Detect communities/clusters in the co-occurrence graph.

    Uses greedy modularity community detection.

    Returns a dict mapping node (atom_id) to cluster_id.
    """
    if G.number_of_nodes() == 0:
        return {}

    try:
        communities = nx.community.greedy_modularity_communities(G)
        cluster_map = {}
        for cluster_id, community in enumerate(communities):
            for node in community:
                cluster_map[node] = cluster_id
        return cluster_map
    except Exception:
        # Fallback: each connected component is a cluster
        cluster_map = {}
        for cluster_id, component in enumerate(nx.connected_components(G)):
            for node in component:
                cluster_map[node] = cluster_id
        return cluster_map


def compute_overlap_scores(conn: sqlite3.Connection) -> list[dict]:
    """Compute overlap scores for all atoms.

    Returns a list of dicts with atom_id, name, overlap_score, and component scores.
    """
    G = build_cooccurrence_graph(conn)
    cluster_map = _detect_clusters(G)

    # Get atom frequency (number of roles containing atom, weighted)
    cursor = conn.execute("""
        SELECT m.atom_id, COUNT(DISTINCT p.role_id) as role_count,
               SUM(p.weight) as weighted_count
        FROM mappings m
        JOIN phrases p ON m.phrase_id = p.phrase_id
        WHERE m.decision IN ('SAME', 'CHILD')
        GROUP BY m.atom_id
    """)
    freq_data = {}
    for row in cursor.fetchall():
        atom_id = row[0] if isinstance(row, tuple) else row["atom_id"]
        freq_data[atom_id] = {
            "role_count": row[1] if isinstance(row, tuple) else row["role_count"],
            "weighted_count": row[2] if isinstance(row, tuple) else row["weighted_count"],
        }

    # Total roles for normalization
    total_roles = conn.execute("SELECT COUNT(*) FROM roles").fetchone()[0]
    if total_roles == 0:
        total_roles = 1

    # Centrality
    if G.number_of_nodes() > 0:
        try:
            centrality = nx.degree_centrality(G)
        except Exception:
            centrality = {n: 0.0 for n in G.nodes()}
    else:
        centrality = {}

    # Number of clusters
    num_clusters = max(cluster_map.values()) + 1 if cluster_map else 1

    # Get all atoms
    atoms_cursor = conn.execute("SELECT atom_id, name FROM atoms")
    all_atoms = atoms_cursor.fetchall()

    scores = []
    for row in all_atoms:
        atom_id = row[0] if isinstance(row, tuple) else row["atom_id"]
        name = row[1] if isinstance(row, tuple) else row["name"]

        # Frequency (normalized)
        freq_info = freq_data.get(atom_id, {"role_count": 0, "weighted_count": 0.0})
        frequency = freq_info["role_count"] / total_roles

        # Centrality (already normalized by networkx)
        cent = centrality.get(atom_id, 0.0)

        # Cluster coverage: how many clusters contain this atom
        atom_cluster = cluster_map.get(atom_id)
        if atom_cluster is not None:
            # Find co-occurring atoms and their clusters
            atom_clusters = set()
            if atom_id in G:
                for neighbor in G.neighbors(atom_id):
                    if neighbor in cluster_map:
                        atom_clusters.add(cluster_map[neighbor])
                atom_clusters.add(atom_cluster)
            else:
                atom_clusters = {atom_cluster}
            cluster_cov = len(atom_clusters) / max(num_clusters, 1)
        else:
            cluster_cov = 0.0

        overlap = calculate_overlap_score(frequency, cent, cluster_cov)

        scores.append({
            "atom_id": atom_id,
            "name": name,
            "overlap_score": round(overlap, 4),
            "frequency": round(frequency, 4),
            "centrality": round(cent, 4),
            "cluster_coverage": round(cluster_cov, 4),
            "role_count": freq_info["role_count"],
        })

    # Sort by overlap score descending
    scores.sort(key=lambda x: x["overlap_score"], reverse=True)
    return scores


# Distinctiveness multipliers by classification label
DISTINCTIVENESS_MULTIPLIERS = {
    "DIFFERENTIATOR": 1.5,
    "NICHE": 1.2,
    "AMBIGUOUS": 1.0,
    "TABLE_STAKES_GAMEDEV": 0.4,
    "TABLE_STAKES_SOFTWARE": 0.2,
}


def compute_distinctive_scores(conn: sqlite3.Connection) -> list[dict]:
    """Compute distinctive scores = OverlapScore × distinctiveness multiplier.

    Enriches each atom with classification label and reranks.
    Falls back gracefully if no classifications exist (returns overlap scores as-is).
    """
    from career_rnd.classify import get_classifications

    scores = compute_overlap_scores(conn)
    classifications = get_classifications(conn)

    if not classifications:
        # No classifications yet — return overlap scores with empty label
        for s in scores:
            s["label"] = ""
            s["distinctive_score"] = s["overlap_score"]
            s["is_pinned"] = 0
        return scores

    for s in scores:
        cls = classifications.get(s["atom_id"], {})
        label = cls.get("label", "")
        s["label"] = label
        s["classification_rationale"] = cls.get("rationale", "")
        s["is_pinned"] = cls.get("is_pinned", 0)

        multiplier = DISTINCTIVENESS_MULTIPLIERS.get(label, 1.0)
        s["distinctive_score"] = round(s["overlap_score"] * multiplier, 4)

    # Sort by distinctive_score descending
    scores.sort(key=lambda x: x["distinctive_score"], reverse=True)
    return scores


def run_overlap_analysis(conn: sqlite3.Connection) -> dict:
    """Run the complete overlap analysis pipeline.

    Returns a summary dict.
    """
    G = build_cooccurrence_graph(conn)
    cluster_map = _detect_clusters(G)
    scores = compute_overlap_scores(conn)

    num_clusters = len(set(cluster_map.values())) if cluster_map else 0
    atoms_scored = len([s for s in scores if s["overlap_score"] > 0])

    return {
        "atoms_scored": atoms_scored,
        "clusters_found": num_clusters,
        "top_atoms": scores[:20],
        "graph_nodes": G.number_of_nodes(),
        "graph_edges": G.number_of_edges(),
    }
