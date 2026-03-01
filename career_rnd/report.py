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
        .role-card {{ background: white; border-radius: 6px; margin: 1rem 0; box-shadow: 0 1px 3px rgba(0,0,0,0.1); overflow: hidden; }}
        .role-header {{ padding: 1rem; cursor: pointer; display: flex; align-items: center; gap: 0.75rem; background: #f1f3f5; border-bottom: 1px solid #dee2e6; }}
        .role-header:hover {{ background: #e9ecef; }}
        .role-stats {{ margin-left: auto; color: #868e96; font-size: 0.85rem; }}
        .toggle {{ font-size: 0.7rem; transition: transform 0.2s; }}
        .role-card.open .toggle {{ transform: rotate(90deg); }}
        .role-body {{ display: none; padding: 0; }}
        .role-card.open .role-body {{ display: block; }}
        .role-body table {{ margin: 0; box-shadow: none; }}
        .decision-same {{ color: #2b8a3e; font-weight: 600; }}
        .decision-child {{ color: #1971c2; font-weight: 600; }}
        .decision-new {{ color: #e8590c; }}
        .decision-ambiguous {{ color: #868e96; }}
        td.rationale {{ font-size: 0.8rem; color: #868e96; max-width: 300px; }}
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

    <h2>Role Details</h2>
    {role_detail_cards}
</body>
</html>
"""

ROLE_CARD_TEMPLATE = """
<div class="role-card">
    <div class="role-header" onclick="this.parentElement.classList.toggle('open')">
        <span class="toggle">&#9654;</span>
        <strong>{company}</strong> — {title}
        <span class="role-stats">{mapped_count}/{total_count} mapped | source: {source_file}</span>
    </div>
    <div class="role-body">
        <table>
            <thead>
                <tr>
                    <th>Section</th>
                    <th>Weight</th>
                    <th>Phrase</th>
                    <th>Decision</th>
                    <th>Atom</th>
                    <th>Confidence</th>
                    <th>Rationale</th>
                </tr>
            </thead>
            <tbody>
                {phrase_rows}
            </tbody>
        </table>
    </div>
</div>
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

    # Build role detail cards
    role_detail_cards = _build_role_detail_cards(conn)

    html = HTML_TEMPLATE.format(
        total_roles=total_roles,
        total_atoms=total_atoms,
        top_count=len(top_scores),
        spine_rows=spine_rows,
        cluster_rows=cluster_rows or "<tr><td colspan='3'>No clusters detected yet</td></tr>",
        role_detail_cards=role_detail_cards or "<p>No roles ingested yet.</p>",
    )

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    return output_path


def _build_role_detail_cards(conn: sqlite3.Connection) -> str:
    """Build HTML role detail cards for each ingested role."""
    roles = conn.execute(
        "SELECT role_id, company, title, source_path FROM roles ORDER BY date_added"
    ).fetchall()

    cards = ""
    for role in roles:
        role_id = role[0] if isinstance(role, tuple) else role["role_id"]
        company = role[1] if isinstance(role, tuple) else role["company"]
        title = role[2] if isinstance(role, tuple) else role["title"]
        source_path = role[3] if isinstance(role, tuple) else role["source_path"]

        # Get phrases with their mapping decisions
        phrase_rows_data = conn.execute("""
            SELECT p.phrase, p.section, p.weight,
                   m.decision, m.atom_id, m.confidence, m.rationale,
                   a.name as atom_name
            FROM phrases p
            LEFT JOIN mappings m ON p.phrase_id = m.phrase_id
            LEFT JOIN atoms a ON m.atom_id = a.atom_id
            WHERE p.role_id = ?
            ORDER BY
                CASE p.section
                    WHEN 'must' THEN 1
                    WHEN 'responsibility' THEN 2
                    WHEN 'want' THEN 3
                    WHEN 'profile' THEN 4
                    ELSE 5
                END,
                p.phrase
        """, (role_id,)).fetchall()

        total_count = len(phrase_rows_data)
        mapped_count = sum(
            1 for r in phrase_rows_data
            if (r[3] if isinstance(r, tuple) else r["decision"]) in ("SAME", "CHILD")
        )

        source_file = Path(source_path).name if source_path else "unknown"

        phrase_rows = ""
        for r in phrase_rows_data:
            phrase = r[0] if isinstance(r, tuple) else r["phrase"]
            section = r[1] if isinstance(r, tuple) else r["section"]
            weight = r[2] if isinstance(r, tuple) else r["weight"]
            decision = r[3] if isinstance(r, tuple) else r["decision"]
            atom_id = r[4] if isinstance(r, tuple) else r["atom_id"]
            confidence = r[5] if isinstance(r, tuple) else r["confidence"]
            rationale = r[6] if isinstance(r, tuple) else r["rationale"]
            atom_name = r[7] if isinstance(r, tuple) else r["atom_name"]

            decision_str = decision or "—"
            decision_class = f"decision-{(decision or 'new').lower()}"
            atom_display = f"{atom_name}" if atom_name else "—"
            conf_display = f"{confidence:.2f}" if confidence is not None else "—"
            rationale_display = (rationale or "—")[:120]

            phrase_rows += f"""
                <tr>
                    <td>{section or 'other'}</td>
                    <td>{weight or 0:.1f}</td>
                    <td>{phrase}</td>
                    <td class="{decision_class}">{decision_str}</td>
                    <td>{atom_display}</td>
                    <td>{conf_display}</td>
                    <td class="rationale">{rationale_display}</td>
                </tr>"""

        cards += ROLE_CARD_TEMPLATE.format(
            company=company or "Unknown",
            title=title or "Unknown",
            mapped_count=mapped_count,
            total_count=total_count,
            source_file=source_file,
            phrase_rows=phrase_rows or "<tr><td colspan='7'>No phrases extracted</td></tr>",
        )

    return cards


def generate_role_details_csv(conn: sqlite3.Connection, output_path: str) -> str:
    """Generate role_details.csv with one row per phrase."""
    rows = conn.execute("""
        SELECT r.role_id, r.company, r.title,
               p.phrase, p.section, p.weight,
               m.atom_id, a.name as atom_name,
               m.decision, m.confidence, m.rationale
        FROM phrases p
        JOIN roles r ON p.role_id = r.role_id
        LEFT JOIN mappings m ON p.phrase_id = m.phrase_id
        LEFT JOIN atoms a ON m.atom_id = a.atom_id
        ORDER BY r.role_id, p.section, p.phrase
    """).fetchall()

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "role_id", "company", "title", "phrase", "section", "weight",
            "atom_id", "atom_name", "decision", "confidence", "rationale"
        ])
        for row in rows:
            writer.writerow([
                row[0] if isinstance(row, tuple) else row["role_id"],
                row[1] if isinstance(row, tuple) else row["company"],
                row[2] if isinstance(row, tuple) else row["title"],
                row[3] if isinstance(row, tuple) else row["phrase"],
                row[4] if isinstance(row, tuple) else row["section"],
                row[5] if isinstance(row, tuple) else row["weight"],
                row[6] if isinstance(row, tuple) else row["atom_id"],
                row[7] if isinstance(row, tuple) else row["atom_name"],
                row[8] if isinstance(row, tuple) else row["decision"],
                row[9] if isinstance(row, tuple) else row["confidence"],
                row[10] if isinstance(row, tuple) else row["rationale"],
            ])

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
        paths.append(generate_role_details_csv(conn, str(out / "role_details.csv")))

    if fmt in ("html", "all"):
        paths.append(generate_html_report(conn, str(out / "report.html")))

    return paths
