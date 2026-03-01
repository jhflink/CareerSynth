"""Report generation — CSV exports and HTML/MD dashboard."""

import csv
import sqlite3
from pathlib import Path

from career_rnd.overlap import compute_overlap_scores, compute_distinctive_scores, build_cooccurrence_graph, _detect_clusters
from career_rnd.classify import get_classifications
from career_rnd.llm import generate_synthesis_summary


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>CareerSynth — Career Distinctiveness Report</title>
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
        .synthesis {{ background: white; padding: 1.25rem 1.5rem; border-radius: 6px; margin: 1.5rem 0; box-shadow: 0 1px 3px rgba(0,0,0,0.1); border-left: 4px solid #228be6; line-height: 1.6; color: #495057; }}
        .role-description {{ padding: 0.75rem 1rem; color: #495057; font-size: 0.9rem; line-height: 1.5; border-bottom: 1px solid #dee2e6; background: #f8f9fa; }}
        .bar {{ display: inline-block; height: 12px; border-radius: 2px; }}
        .bar-diff {{ background: #228be6; }}
        .bar-ts {{ background: #adb5bd; }}
        .bar-niche {{ background: #fab005; }}
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
        .badge {{ display: inline-block; padding: 0.15rem 0.45rem; border-radius: 3px; font-size: 0.7rem; font-weight: 600; margin-left: 0.4rem; vertical-align: middle; }}
        .badge-diff {{ background: #d0ebff; color: #1864ab; }}
        .badge-ts-sw {{ background: #e9ecef; color: #495057; }}
        .badge-ts-gd {{ background: #e9ecef; color: #495057; }}
        .badge-niche {{ background: #fff3bf; color: #e67700; }}
        .badge-ambiguous {{ background: #fff4e6; color: #d9480f; }}
        .badge-pinned {{ background: #ffe8cc; color: #d9480f; font-size: 0.65rem; }}
        details {{ margin: 1rem 0; }}
        summary {{ cursor: pointer; font-weight: 600; color: #6c757d; padding: 0.5rem 0; }}
        summary:hover {{ color: #495057; }}
        .section-note {{ color: #868e96; font-size: 0.85rem; margin: 0.25rem 0 0.75rem 0; }}
    </style>
</head>
<body>
    <h1>🔬 CareerSynth — Career Distinctiveness Report</h1>
    <div class="meta">
        <p>Total roles: {total_roles} | Total atoms: {total_atoms} | Classified: {classified_count}</p>
    </div>

    {synthesis_summary}

    <h2>🎯 Differentiator Spine</h2>
    <p class="section-note">Skills that define what makes your role cluster unique. Ranked by Distinctive Score.</p>
    {differentiator_section}

    <details>
        <summary>📋 Table-Stakes Foundation ({table_stakes_count} skills)</summary>
        <p class="section-note">Expected baseline skills — important but not differentiating.</p>
        {table_stakes_section}
    </details>

    <details>
        <summary>🔍 Niche Signals ({niche_count} skills)</summary>
        <p class="section-note">Rare or emerging specializations — strategically interesting.</p>
        {niche_section}
    </details>

    {ambiguous_section}

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
        {description_block}
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


def _build_scored_table(scores: list[dict], bar_class: str = "bar-diff") -> str:
    """Build an HTML table from scored atoms."""
    if not scores:
        return "<p><em>No atoms in this category.</em></p>"

    max_score = max((s.get("distinctive_score", s["overlap_score"]) for s in scores), default=1.0) or 1.0
    rows = ""
    for i, s in enumerate(scores, 1):
        d_score = s.get("distinctive_score", s["overlap_score"])
        bar_width = int(200 * d_score / max_score)
        pin = ' <span class="badge badge-pinned">\U0001f4cc</span>' if s.get("is_pinned") else ""
        rationale = s.get("classification_rationale", "")[:100]
        rationale_td = f' <td class="rationale">{rationale}</td>' if rationale else '<td></td>'
        rows += f"""
            <tr>
                <td>{i}</td>
                <td>{s['name']}{pin}</td>
                <td class="score">{d_score:.4f}</td>
                <td><span class="bar {bar_class}" style="width:{bar_width}px"></span></td>
                <td>{s['overlap_score']:.4f}</td>
                <td>{s['role_count']}</td>
               {rationale_td}
            </tr>"""

    return f"""<table>
        <thead><tr>
            <th>#</th><th>Name</th><th>D-Score</th><th>Visual</th>
            <th>Overlap</th><th>Roles</th><th>Rationale</th>
        </tr></thead>
        <tbody>{rows}</tbody>
    </table>"""


def generate_html_report(conn: sqlite3.Connection, output_path: str) -> str:
    """Generate an HTML distinctiveness report."""
    d_scores = compute_distinctive_scores(conn)
    classifications = get_classifications(conn)
    has_classifications = bool(classifications)

    total_roles = conn.execute("SELECT COUNT(*) FROM roles").fetchone()[0]
    total_atoms = conn.execute("SELECT COUNT(*) FROM atoms").fetchone()[0]

    # Split atoms by classification label
    differentiators = [s for s in d_scores if s.get("label") == "DIFFERENTIATOR" and s["overlap_score"] > 0]
    table_stakes = [s for s in d_scores if s.get("label", "").startswith("TABLE_STAKES") and s["overlap_score"] > 0]
    niche = [s for s in d_scores if s.get("label") == "NICHE" and s["overlap_score"] > 0]
    ambiguous = [s for s in d_scores if s.get("label") == "AMBIGUOUS" and s["overlap_score"] > 0]

    # If no classifications exist, show all scored atoms as differentiators (fallback)
    if not has_classifications:
        differentiators = [s for s in d_scores if s["overlap_score"] > 0][:20]

    # Build sections
    differentiator_section = _build_scored_table(differentiators, "bar-diff")
    table_stakes_section = _build_scored_table(table_stakes, "bar-ts")
    niche_section = _build_scored_table(niche, "bar-niche")

    ambiguous_section = ""
    if ambiguous:
        ambiguous_section = f"""
        <details>
            <summary>\u2753 Ambiguous / Under Review ({len(ambiguous)} skills)</summary>
            <p class="section-note">Classification uncertain \u2014 consider reviewing with <code>career classify review</code>.</p>
            {_build_scored_table(ambiguous, "bar-ts")}
        </details>"""

    # Build cluster rows
    G = build_cooccurrence_graph(conn)
    cluster_map = _detect_clusters(G)
    clusters_info = {}
    for atom_id, cluster_id in cluster_map.items():
        clusters_info.setdefault(cluster_id, []).append(atom_id)

    cluster_rows = ""
    for cid, atom_ids in sorted(clusters_info.items()):
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

    # Generate synthesis summary via LLM (pass differentiators as top_scores)
    num_clusters = len(set(cluster_map.values())) if cluster_map else 0
    synthesis_input = differentiators[:8] if differentiators else [s for s in d_scores if s["overlap_score"] > 0][:8]
    try:
        synthesis_text = generate_synthesis_summary(
            total_roles=total_roles,
            total_atoms=total_atoms,
            top_scores=synthesis_input,
            num_clusters=num_clusters,
        )
        synthesis_html = f'<div class="synthesis">{synthesis_text}</div>'
    except Exception:
        synthesis_html = ""

    classified_count = len(classifications)

    html = HTML_TEMPLATE.format(
        total_roles=total_roles,
        total_atoms=total_atoms,
        classified_count=classified_count,
        synthesis_summary=synthesis_html,
        differentiator_section=differentiator_section,
        table_stakes_section=table_stakes_section,
        table_stakes_count=len(table_stakes),
        niche_section=niche_section,
        niche_count=len(niche),
        ambiguous_section=ambiguous_section,
        cluster_rows=cluster_rows or "<tr><td colspan='3'>No clusters detected yet</td></tr>",
        role_detail_cards=role_detail_cards or "<p>No roles ingested yet.</p>",
    )

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    return output_path


LABEL_BADGE_MAP = {
    "DIFFERENTIATOR": ("DIFF", "badge-diff"),
    "TABLE_STAKES_SOFTWARE": ("TS:SW", "badge-ts-sw"),
    "TABLE_STAKES_GAMEDEV": ("TS:GD", "badge-ts-gd"),
    "NICHE": ("NICHE", "badge-niche"),
    "AMBIGUOUS": ("?", "badge-ambiguous"),
}


def _build_role_detail_cards(conn: sqlite3.Connection) -> str:
    """Build HTML role detail cards for each ingested role."""
    classifications = get_classifications(conn)

    roles = conn.execute(
        "SELECT role_id, company, title, source_path, description FROM roles ORDER BY date_added"
    ).fetchall()

    cards = ""
    for role in roles:
        role_id = role[0] if isinstance(role, tuple) else role["role_id"]
        company = role[1] if isinstance(role, tuple) else role["company"]
        title = role[2] if isinstance(role, tuple) else role["title"]
        source_path = role[3] if isinstance(role, tuple) else role["source_path"]
        description = role[4] if isinstance(role, tuple) else role["description"]

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
            # Add classification badge if available
            badge_html = ""
            if atom_id and atom_id in classifications:
                cls_label = classifications[atom_id]["label"]
                badge_text, badge_class = LABEL_BADGE_MAP.get(cls_label, ("", ""))
                if badge_text:
                    badge_html = f' <span class="badge {badge_class}">{badge_text}</span>'
            atom_display = f"{atom_name}{badge_html}" if atom_name else "—"
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

        description_block = (
            f'<div class="role-description">{description}</div>'
            if description
            else ""
        )

        cards += ROLE_CARD_TEMPLATE.format(
            company=company or "Unknown",
            title=title or "Unknown",
            mapped_count=mapped_count,
            total_count=total_count,
            source_file=source_file,
            description_block=description_block,
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
