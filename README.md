# CareerSynth — Career R&D Dashboard

A local-first CLI pipeline that ingests job descriptions (PDF/text/HTML), extracts skills, normalizes them to canonical **Skill Atoms**, and surfaces emergent overlap patterns across roles.

## Quick Start

```bash
# Install
pip install -e ".[dev]"

# Set your OpenAI API key
export OPENAI_API_KEY=your-key

# Seed the atom library
career atoms seed

# Drop job descriptions into data/inbox/, then:
career ingest data/inbox/
career extract --sectionize
career skills extract
career skills map
career analyze
career report
```

## CLI Commands

| Command | Description |
|---------|-------------|
| `career ingest <path>` | Ingest job descriptions from file or directory |
| `career extract` | Extract text and detect sections (Must/Want/etc.) |
| `career skills extract` | Extract skill phrases using LLM |
| `career skills map` | Map phrases to Skill Atoms (embedding + LLM judge) |
| `career analyze` | Compute overlap scores, graph, and clusters |
| `career report` | Generate CSV + HTML reports |
| `career atoms seed` | Load seed atom library into database |
| `career atoms suggest-merges` | Suggest atom merges/renames/splits |

## Architecture

```
inbox/ → ingest → extract text → sectionize → extract phrases (LLM)
  → embed phrases → match to atoms (similarity + LLM judge)
  → update mappings → recompute overlap scores → generate reports
```

**Two-stage hybrid matching:**
1. Embedding similarity for fast candidate selection
2. LLM merge judge for borderline cases

## Data Model

- **Roles**: Job descriptions with metadata
- **Phrases**: Extracted skill mentions with section + weight
- **Atoms**: Canonical skills with immutable IDs
- **Mappings**: Phrase→Atom decisions with confidence + rationale
- **Overlap Spine**: Top atoms ranked by composite score

## Overlap Score Formula

```
OverlapScore = 0.45 × frequency + 0.35 × centrality + 0.20 × cluster_coverage
```

## Reports

- `overlap_spine.csv` — Top 20 atoms by overlap score
- `role_cluster_summary.csv` — Roles grouped by cluster
- `role_skill_heatmap.csv` — Role × Atom matrix
- `report.html` — Visual dashboard

## Testing

```bash
python3 -m pytest tests/ -v
```

## Project Structure

```
career_rnd/           # Core Python package
  cli.py              # Typer CLI
  db.py               # SQLite schema + helpers
  ingest.py           # File ingestion
  extract.py          # Text extraction + section detection
  atoms.py            # Atom library management
  map_skills.py       # Phrase→Atom mapping pipeline
  overlap.py          # Overlap scoring + graph + clustering
  report.py           # CSV + HTML report generation
  embeddings.py       # Embedding computation + caching
  llm.py              # LLM API wrapper
  prompts/            # Prompt templates
skill_library/        # Atom library + decision logs
data/                 # Inbox, extracted text, exports
docs/brain/           # Project brain (ontology, architecture, etc.)
tests/                # Test suite
```
