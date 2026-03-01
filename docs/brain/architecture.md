# Architecture

## Philosophy
Local-first, CLI-driven, Python pipeline. No cloud dependencies except optional LLM API calls. Data stays on disk in SQLite + JSONL + CSV. Designed for a single user running periodic batch operations.

## Stack
- **Language**: Python 3.11+
- **Storage**: SQLite (structured), JSONL (append-only logs), CSV (exports)
- **Text Extraction**: PyMuPDF or pdfplumber (PDF), BeautifulSoup (HTML), direct (text)
- **Embeddings**: OpenAI embeddings (primary) or local sentence-transformers (fallback)
- **LLM**: OpenAI API for merge judge and skill extraction prompts
- **Graph**: NetworkX for co-occurrence graph + centrality
- **Clustering**: HDBSCAN or Agglomerative for phrase clustering; Leiden/greedy modularity for role clusters
- **CLI**: Typer
- **Reports**: Jinja2 HTML templates, CSV, Markdown

## Key Architectural Decisions
1. **SQLite as single source of truth** — all structured data in one DB file, easy to backup/version
2. **Embedding cache in DB** — avoid recomputing embeddings for known phrases/atoms
3. **Append-only decision log** — every mapping decision stored in JSONL for audit trail
4. **Incremental processing** — new roles only process new phrases, existing atoms/scores update in-place
5. **Prompt templates as files** — stored in career_rnd/prompts/, easy to iterate without code changes

## Data Flow
```
inbox/ → ingest → extract text → sectionize → extract phrases (LLM)
  → embed phrases → match to atoms (similarity + LLM judge)
  → update mappings → recompute overlap scores → generate reports
```

## Constraints
- Must work offline except for LLM/embedding API calls
- Must handle mixed Japanese/English input
- Atom IDs never change once created
- No UI beyond CLI + generated reports (v1)
