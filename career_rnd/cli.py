"""CLI entry point for CareerSynth — Career R&D Dashboard."""

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from career_rnd.db import get_db, DEFAULT_DB_PATH

app = typer.Typer(
    name="career",
    help="Career R&D Dashboard — skill extraction, normalization, and overlap analysis.",
)
skills_app = typer.Typer(help="Skill extraction and mapping commands.")
atoms_app = typer.Typer(help="Atom library management commands.")
app.add_typer(skills_app, name="skills")
app.add_typer(atoms_app, name="atoms")

console = Console()


@app.command()
def ingest(
    path: str = typer.Argument(..., help="Path to file or directory to ingest."),
    db: str = typer.Option(DEFAULT_DB_PATH, help="Database path."),
):
    """Ingest job descriptions from files or directories."""
    from career_rnd.ingest import ingest_path

    conn = get_db(db)
    results = ingest_path(conn, path)
    console.print(f"[green]Ingested {len(results)} role(s).[/green]")
    for r in results:
        console.print(f"  • {r['role_id']}: {r['source_path']}")
    conn.close()


@app.command()
def extract(
    db: str = typer.Option(DEFAULT_DB_PATH, help="Database path."),
    sectionize: bool = typer.Option(True, help="Detect sections and assign weights."),
):
    """Extract text from ingested files and detect sections."""
    from career_rnd.extract import extract_and_store

    conn = get_db(db)
    count = extract_and_store(conn, do_sectionize=sectionize)
    console.print(f"[green]Extracted text for {count} role(s).[/green]")
    conn.close()


@skills_app.command("extract")
def skills_extract(
    db: str = typer.Option(DEFAULT_DB_PATH, help="Database path."),
):
    """Extract skill phrases from role texts using LLM."""
    from career_rnd.llm import extract_skills_for_roles

    conn = get_db(db)
    count = extract_skills_for_roles(conn)
    console.print(f"[green]Extracted skills for {count} role(s).[/green]")
    conn.close()


@skills_app.command("map")
def skills_map(
    db: str = typer.Option(DEFAULT_DB_PATH, help="Database path."),
):
    """Map extracted phrases to Skill Atoms."""
    from career_rnd.map_skills import map_all_unmapped

    conn = get_db(db)
    count = map_all_unmapped(conn)
    console.print(f"[green]Mapped {count} phrase(s) to atoms.[/green]")
    conn.close()


@app.command("analyze")
def analyze_overlap(
    db: str = typer.Option(DEFAULT_DB_PATH, help="Database path."),
):
    """Compute overlap scores, co-occurrence graph, and role clusters."""
    from career_rnd.overlap import run_overlap_analysis

    conn = get_db(db)
    results = run_overlap_analysis(conn)
    console.print(f"[green]Overlap analysis complete.[/green]")
    console.print(f"  Atoms scored: {results['atoms_scored']}")
    console.print(f"  Role clusters: {results['clusters_found']}")
    conn.close()


@app.command()
def report(
    db: str = typer.Option(DEFAULT_DB_PATH, help="Database path."),
    output_dir: str = typer.Option("data/exports", help="Export directory."),
    fmt: str = typer.Option("all", help="Report format: csv, html, md, or all."),
):
    """Generate reports (CSV exports + HTML/MD dashboard)."""
    from career_rnd.report import generate_reports

    conn = get_db(db)
    paths = generate_reports(conn, output_dir, fmt)
    console.print(f"[green]Reports generated:[/green]")
    for p in paths:
        console.print(f"  • {p}")
    conn.close()


@app.command("describe-roles")
def describe_roles(
    db: str = typer.Option(DEFAULT_DB_PATH, help="Database path."),
):
    """Generate descriptions for roles that don't have one yet."""
    from career_rnd.extract import extract_text
    from career_rnd.llm import generate_role_description

    conn = get_db(db)
    cursor = conn.execute(
        "SELECT role_id, company, title, raw_text_path FROM roles "
        "WHERE (description IS NULL OR description = '') AND raw_text_path IS NOT NULL"
    )
    roles = cursor.fetchall()

    if not roles:
        console.print("[yellow]All roles already have descriptions.[/yellow]")
        conn.close()
        return

    count = 0
    for role in roles:
        role_id = role["role_id"]
        company = role["company"] or "Unknown"
        title = role["title"] or "Unknown"
        raw_path = role["raw_text_path"]

        try:
            text = extract_text(raw_path)
            description = generate_role_description(text)
            conn.execute(
                "UPDATE roles SET description=? WHERE role_id=?",
                (description, role_id),
            )
            conn.commit()
            count += 1
            console.print(f"  ✓ {company} — {title}")
        except Exception as e:
            console.print(f"  [red]✗ {company} — {title}: {e}[/red]")

    console.print(f"[green]Generated descriptions for {count} role(s).[/green]")
    conn.close()


@atoms_app.command("seed")
def atoms_seed(
    db: str = typer.Option(DEFAULT_DB_PATH, help="Database path."),
):
    """Load seed atoms from skill_library/atoms.json into the database."""
    from career_rnd.atoms import load_seed_atoms

    conn = get_db(db)
    count = load_seed_atoms(conn)
    console.print(f"[green]Loaded {count} seed atoms.[/green]")
    conn.close()


@atoms_app.command("suggest-merges")
def atoms_suggest_merges(
    db: str = typer.Option(DEFAULT_DB_PATH, help="Database path."),
):
    """Suggest atom merges/renames/splits based on current data."""
    from career_rnd.llm import suggest_merges

    conn = get_db(db)
    suggestions = suggest_merges(conn)
    if not suggestions:
        console.print("[yellow]No merge suggestions at this time.[/yellow]")
    else:
        for s in suggestions:
            console.print(f"  • {s['action']}: {s['description']}")
    conn.close()


if __name__ == "__main__":
    app()
