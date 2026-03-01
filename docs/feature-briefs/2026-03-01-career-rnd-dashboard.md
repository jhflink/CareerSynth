# Feature: career-rnd-dashboard
Date: 2026-03-01

## Alignment Summary
This feature IS the core CareerSynth system. It directly implements the ontology (Skill Atoms, Phrases, Roles, Overlap Spine, Role Clusters, Mapping Decisions), addresses the primary design tension (precision vs. recall via two-stage hybrid matching), follows the architectural philosophy (local-first CLI Python pipeline), and fulfills all v1 phase priorities.

## Intent
Build the complete v1 Career R&D Dashboard: a CLI-driven pipeline that ingests job descriptions, extracts skills, normalizes them to canonical Skill Atoms, computes emergent overlap across roles, and produces actionable reports.

## Problem
Career planning across overlapping domains (UX, systems architecture, R&D, AI workflows) requires seeing which skills transfer broadly. Manually reading job descriptions and comparing skills is slow, inconsistent, and language-dependent. There is no tool that automatically discovers overlap patterns across diverse job descriptions in multiple languages.

## Non-goals
- Web UI or interactive dashboard (v1 is CLI + static reports)
- Notion/Google Sheets export integration
- Multi-user or team collaboration features
- Real-time streaming ingestion
- Fine-tuned or custom ML models
- Automated job board scraping

## Constraints
- Must run locally (Python 3.11+), only external dependency is LLM/embedding API
- Must handle mixed Japanese/English job descriptions
- Atom IDs are immutable once created
- Must be incremental — new roles don't require full reprocessing
- Taxonomy guardrails: merges/renames require explicit approval
- Section weighting (Must=1.0, Want=0.6, Responsibilities=0.8, Profile=0.5, Other=0.3)

## Edge Cases
1. **Identical skills, different languages**: "プロトタイピング" and "prototyping" must map to same atom
2. **Near-synonyms**: "cross-functional collaboration" vs "cross-discipline communication" — merge or separate?
3. **Hierarchical skills**: "React" is a child of "Frontend Development" — CHILD mapping needed
4. **Ambiguous phrases**: "communication skills" could be writing, presenting, or interpersonal
5. **Very short job descriptions**: fewer than 5 extractable phrases
6. **Duplicate job postings**: same role posted twice with minor wording changes
7. **Section detection failure**: job description without clear Must/Want structure
8. **Embedding API unavailable**: graceful fallback or clear error
9. **Atom library growth**: after 100+ roles, library may need pruning/restructuring
10. **Low-confidence cascades**: one bad early mapping propagates through overlap scores

## Risks
- **LLM cost**: each role requires 2-3 LLM calls (extract + map + optional merge judge). At scale, costs accumulate.
- **Embedding drift**: if embedding model changes, all cached embeddings become inconsistent.
- **Taxonomy drift**: without regular merge reviews, atom count grows unbounded.
- **Section weighting sensitivity**: overlap scores are sensitive to weight choices; no empirical basis for defaults yet.
- **Japanese extraction quality**: LLM skill extraction from Japanese text may be less reliable.

## Acceptance Criteria
1. CLI commands `career ingest`, `career extract`, `career skills extract`, `career skills map`, `career analyze overlap`, `career report` all work end-to-end
2. Can ingest PDF, plain text, and HTML job descriptions
3. Extracts 10-30 skill phrases per role with section classification
4. Maps phrases to atoms with SAME/CHILD/NEW/AMBIGUOUS decisions + confidence + rationale
5. Seed atom library contains 35-45 atoms with IDs, definitions, positive/negative examples
6. Overlap spine ranks atoms by composite score (frequency 0.45 + centrality 0.35 + cluster_coverage 0.20)
7. Role clustering produces 2-4 meaningful groups from 5+ roles
8. All data persisted in SQLite; decisions logged in JSONL
9. CSV exports: overlap_spine.csv, role_cluster_summary.csv, role_skill_heatmap.csv
10. HTML or Markdown report generated with overlap spine visualization
11. Adding a new role updates scores without reprocessing existing roles
12. Mixed Japanese/English job descriptions handled correctly
13. Traceability: can trace any atom's overlap score back to specific phrases and roles

## Alternatives

### Alternative A: Spreadsheet-First Approach
Manually maintain a Google Sheet with skills taxonomy. Use Apps Script to match keywords. Generate charts natively.
- **Pros**: No code, immediate visual output, easy to share
- **Cons**: No semantic matching, no multilingual support, manual maintenance, no graph analysis, doesn't scale

### Alternative B: Embedding-Only (No LLM Judge)
Use only embedding similarity with hard thresholds. Skip LLM merge judge entirely.
- **Pros**: Cheaper (no LLM API costs for mapping), faster, fully deterministic
- **Cons**: Misses nuanced distinctions (CHILD vs SAME), no rationale, poor on edge cases, no explanation for decisions

### Alternative C: Full LLM Pipeline (No Embeddings)
Send everything to LLM — extraction, mapping, and overlap analysis — in a single large prompt.
- **Pros**: Simpler architecture, potentially higher quality per-decision
- **Cons**: Expensive, slow, non-incremental (can't cache), context window limits, non-deterministic overlap scores

## Recommended Approach
**Two-stage hybrid** (the plan as described):
- Stage 1: Embedding similarity for fast, cheap candidate selection
- Stage 2: LLM merge judge for borderline cases only

This balances cost, quality, and incrementality. The embedding stage handles 70-80% of mappings automatically. The LLM judge provides nuanced decisions with rationale for the remaining 20-30%. The architecture supports graceful degradation (embedding-only mode if API is unavailable) and maintains traceability throughout.

The approach is also aligned with the design tension resolution: conservative thresholds prevent false merges, while the LLM judge catches true overlaps that pure similarity misses.
