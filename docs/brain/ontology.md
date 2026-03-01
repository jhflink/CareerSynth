# Ontology

## Core Identity
CareerSynth is a **Career R&D Dashboard** — a local-first system that ingests job descriptions, extracts and normalizes skills into canonical "Skill Atoms," and surfaces emergent overlap patterns across roles.

## Key Concepts

### Skill Atom
The fundamental unit of capability. A stable, canonically-defined skill with a unique immutable ID, a definition, positive/negative examples, and optional parent/child relations. Atoms are language-agnostic — the same atom can be surfaced from English or Japanese job descriptions.

### Phrase
A raw skill mention extracted from a job description. Phrases are transient; they get mapped to Atoms. Multiple phrases can map to the same Atom.

### Role
A single job description (from PDF, text, or HTML). Roles produce Phrases, which map to Atoms.

### Overlap Spine
The ranked list of Atoms that appear across the most roles and clusters. The spine reveals career leverage points — skills worth deepening because they transfer broadly.

### Role Cluster
A group of roles that share similar Atom profiles, discovered via community detection on the co-occurrence graph. Clusters reveal career neighborhoods.

### Mapping Decision
The recorded judgment (SAME / CHILD / NEW / AMBIGUOUS) linking a Phrase to an Atom, with confidence and rationale. Decisions are append-only for traceability.

## Guiding Principles
- **Overlap must emerge automatically** even when language differs across job posts.
- **Stability over novelty**: prefer reusing existing Atoms over creating new ones.
- **Traceability**: every mapping and merge is logged with rationale.
- **Incrementality**: adding new roles updates scores without reprocessing everything.
