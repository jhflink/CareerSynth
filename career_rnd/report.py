"""Report generation — CSV exports and HTML/MD dashboard."""

import csv
import sqlite3
from pathlib import Path

from career_rnd.overlap import compute_overlap_scores, build_cooccurrence_graph, _detect_clusters


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>CareerSynth — Overlap Spine Report</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; margin: 2rem; background: #f8f9fa; color: #212529; }}
        h1 {{ color: #495057; border-bottom: 2px solid #dee2e6; padding-bottom: 0.5rem; }}
        h2 {{ color: #6c757d; margin-top: 2rem; }}
        table {{ border-collapse: collapse; width: 100%; margin: 1rem 0; background: white; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
        th, td {{ padding: 0.75rem; text-align: left; border-bottom: 1px solid #dee2e6; }}
        th {{ background: #495057; color: white; font-weight: 600; }}
        tr:hover {{ background: #f1f3f5; }}
        .score {{ font-weight: bold; color: #228be6; }}
        .meta {{ color: #868e96; font-size: 0.9rem; margin-bottom: 2rem; }}
        .bar {{ display: inline-block; height: 12px; background: #228be6; border-radius: 2px; }}
    </style>
</head>
<body>
    <h1>🔬 CareerSynth — Overlap Spine Report</h1>
    <div class="meta">
        <p>Total roles: {total_roles} | Total atoms: {total_atoms} | Top atoms shown: {top_count}</p>
    </div>

    <h2>Overlap Spine (Top Atoms by Overlap Score)</h2>
    <table>
        <thead>
            <tr>
                <th>#</th>
                <th>Atom ID</th>
                <th>Name</th>
                <th>Score</th>
                <th>Visual</th>
                <th>Frequency</th>
                <th>Centrality</th>
                <th>Cluster Coverage</th>
                <th>Roles</th>
            </tr>
        </thead>
        <tbody>
            {spine_rows}
        </tbody>
    </table>

    <h2>Role Clusters</h2>
    <table>
        <thead>
            <tr>
                <th>Cluster</th>
                <th>Roles</th>
                <th>Top Atoms</th>
            </tr>
        </thead>
        <tbody>
            {cluster_rows}
        </tbody>
    </table>
</body>
</html>
"""


def generate_overlap_spine_csv(conn: sqlite3.Connection, output_path: str) -> str:
    """Generate overlap_spine.csv.

    Args:
        conn: SQLite connection.
        output_path: Path for the CSV file.

    Returns:
        Path to the generated file.
    """
    scores = compute_overlap_scores(conn)

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["atom_id", "name", "overlap_score", "frequency",
                         "centrality", "cluster_coverage", "role_count"],
        )
        writer.writeheader()
        for score in scores[:20]:  # Top 20
            writer.writerow(score)

    return output_path


def generate_role_cluster_csv(conn: sqlite3.Connection, output_path: str) -> str:
    """Generate role_cluster_summary.csv."""
    G = build_cooccurrence_graph(conn)
    cluster_map = _detect_clusters(G)

    # Get role-atom mapping
    cursor = conn.execute("""
        SELECT DISTINCT p.role_id, m.atom_id
        FROM mappings m
        JOIN phrases p ON m.phrase_id = p.phrase_id
        WHERE m.decision IN ('SAME', 'CHILD')
    """)
    role_atoms = {}
    for row in cursor.fetchall():
        role_id = row[0] if isinstance(row, tuple) else row["role_id"]
        atom_id = row[1] if isinstance(row, tuple) else row["atom_id"]
        role_atoms.setdefault(role_id, set()).add(atom_id)

    # Assign roles to clusters based on their dominant atom cluster
    role_clusters = {}
    for role_id, atoms in role_atoms.items():
        cluster_votes = {}
        for atom_id in atoms:
            if atom_id in cluster_map:
                c = cluster_map[atom_id]
                cluster_votes[c] = cluster_votes.get(c, 0) + 1
        if cluster_votes:
            role_clusters[role_id] = max(cluster_votes, key=cluster_votes.get)

    # Get role metadata
    roles_meta = {}
    for row in conn.execute("SELECT role_id, company, title FROM roles").fetchall():
        rid = row[0] if isinstance(row, tuple) else row["role_id"]
        roles_meta[rid] = {
            "company": row[1] if isinstance(row, tuple) else row["company"],
            "title": row[2] if isinstance(row, tuple) else row["title"],
        }

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["cluster_id", "role_id", "company", "title"])
        for role_id, cluster_id in sorted(role_clusters.items(), key=lambda x: x[1]):
            meta = roles_meta.get(role_id, {})
            writer.writerow([
                cluster_id,
                role_id,
                meta.get("company", ""),
                meta.get("title", ""),
            ])

    return output_path


def generate_heatmap_csv(conn: sqlite3.Connection, output_path: str) -> str:
    """Generate role_skill_heatmap.csv."""
    # Get all roles and top atoms
    scores = compute_overlap_scores(conn)
    top_atoms = [s["atom_id"] for s in scores[:20]]

    cursor = conn.execute("SELECT role_id, title FROM roles")
    roles = cursor.fetchall()

    # Build role-atom matrix
    role_atom_map = {}
    for row in conn.execute("""
        SELECT p.role_id, m.atom_id, m.confidence
        FROM mappings m
        JOIN phrases p ON m.phrase_id = p.phrase_id
        WHERE m.decision IN ('SAME', 'CHILD')
    """).fetchall():
        role_id = row[0] if isinstance(row, tuple) else row["role_id"]
        atom_id = row[1] if isinstance(row, tuple) else row["atom_id"]
        confidence = row[2] if isinstance(row, tuple) else row["confidence"]
        role_atom_map.setdefault(role_id, {})[atom_id] = confidence

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["role_id", "title"] + top_atoms)
        for role in roles:
            role_id = role[0] if isinstance(role, tuple) else role["role_id"]
            title = role[1] if isinstance(role, tuple) else role["title"]
            row_data = [role_id, title or ""]
            for atom_id in top_atoms:
                row_data.append(role_atom_map.get(role_id, {}).get(atom_id, 0))
            writer.writerow(row_data)

    return output_path


def generate_html_report(conn: sqlite3.Connection, output_path: str) -> str:
    """Generate an HTML overlap spine report."""
    scores = compute_overlap_scores(conn)
    top_scores = scores[:20]

    total_roles = conn.execute("SELECT COUNT(*) FROM roles").fetchone()[0]
    total_atoms = conn.execute("SELECT COUNT(*) FROM atoms").fetchone()[0]

    # Build spine rows
    spine_rows = ""
    max_score = max((s["overlap_score"] for s in top_scores), default=1.0) or 1.0
    for i, s in enumerate(top_scores, 1):
        bar_width = int(200 * s["overlap_score"] / max_score)
        spine_rows += f"""
            <tr>
                <td>{i}</td>
                <td>{s['atom_id']}</td>
                <td>{s['name']}</td>
                <td class="score">{s['overlap_score']:.4f}</td>
                <td><span class="bar" style="width:{bar_width}px"></span></td>
                <td>{s['frequency']:.3f}</td>
                <td>{s['centrality']:.3f}</td>
                <td>{s['cluster_coverage']:.3f}</td>
                <td>{s['role_count']}</td>
            </tr>"""

    # Build cluster rows
    G = build_cooccurrence_graph(conn)
    cluster_map = _detect_clusters(G)
    clusters_info = {}
    for atom_id, cluster_id in cluster_map.items():
        clusters_info.setdefault(cluster_id, []).append(atom_id)

    cluster_rows = ""
    for cid, atom_ids in sorted(clusters_info.items()):
        # Get atom names
        atom_names = []
        for aid in atom_ids[:5]:
            row = conn.execute("SELECT name FROM atoms WHERE atom_id=?", (aid,)).fetchone()
            if row:
                atom_names.append(row[0] if isinstance(row, tuple) else row["name"])
        cluster_rows += f"""
            <tr>
                <td>Cluster {cid}</td>
                <td>{len(atom_ids)} atoms</td>
                <td>{', '.join(atom_names)}</td>
            </tr>"""

    html = HTML_TEMPLATE.format(
        total_roles=total_roles,
        total_atoms=total_atoms,
        top_count=len(top_scores),
        spine_rows=spine_rows,
        cluster_rows=cluster_rows or "<tr><td colspan='3'>No clusters detected yet</td></tr>",
    )

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    return output_path


def generate_reports(
    conn: sqlite3.Connection, output_dir: str, fmt: str = "all"
) -> list[str]:
    """Generate all reports.

    Args:
        conn: SQLite connection.
        output_dir: Directory for output files.
        fmt: Report format — csv, html, md, or all.

    Returns:
        List of generated file paths.
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths = []

    if fmt in ("csv", "all"):
        paths.append(generate_overlap_spine_csv(conn, str(out / "overlap_spine.csv")))
        paths.append(generate_role_cluster_csv(conn, str(out / "role_cluster_summary.csv")))
        paths.append(generate_heatmap_csv(conn, str(out / "role_skill_heatmap.csv")))

    if fmt in ("html", "all"):
        paths.append(generate_html_report(conn, str(out / "report.html")))

    return paths
