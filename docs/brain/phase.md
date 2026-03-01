# Phase

## Current Phase: v1 Foundation Build
**Started**: 2026-03-01

## Phase Priorities (ordered)
1. **Scaffold** — repo structure, CLI skeleton, DB schema, seed atom library
2. **Ingest + Extract** — PDF/text/HTML ingestion, text extraction, section detection
3. **Skill Extraction** — LLM-based phrase extraction with section weighting
4. **Atom Mapping** — embedding similarity + LLM merge judge pipeline
5. **Overlap Analysis** — co-occurrence graph, centrality, clustering, overlap scoring
6. **Reports** — CSV exports + HTML/MD dashboard report
7. **Validation** — run on 5+ real job descriptions, verify overlap spine is meaningful

## Done-When (v1)
- Can ingest 5–15 job descriptions (mixed Japanese/English)
- Outputs a stable Overlap Spine (top 10–20 canonical skills)
- Clusters roles into 2–4 meaningful groups
- Adding new jobs updates scores without breaking taxonomy
- Produces CSV exports + readable report
- Maintains traceability (why a phrase mapped to an atom)

## Not In Scope (v1)
- Web UI
- Notion/Sheets export
- Multi-user support
- Continuous/streaming ingestion
- Fine-tuned models
