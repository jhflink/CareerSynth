# Design Tension

## Primary Tension: Precision vs. Recall in Skill Normalization
The system must aggressively merge similar skills to reveal overlap (high recall), while avoiding false merges that collapse genuinely distinct capabilities (high precision).

### Why This Matters
- Too many Atoms → fragmented taxonomy, overlap is invisible
- Too few Atoms → loss of specificity, all roles look the same
- The merge threshold and LLM judge calibration are the critical tuning knobs

## Secondary Tension: Automation vs. Human Oversight
- Full automation enables fast ingestion of many roles
- But taxonomy drift (atoms slowly losing meaning) is a real risk
- Resolution: automate confidently-clear mappings, queue ambiguous ones for review, require explicit approval for merges/renames

## Tertiary Tension: Multilingual Normalization
- Job descriptions arrive in English and Japanese
- Same capability expressed very differently across languages
- Embeddings handle most of this, but edge cases need LLM judgment
- Atom definitions and examples should include both languages where possible

## Design Resolution Strategy
- Use a **two-stage hybrid** (embedding similarity → LLM merge judge)
- Set conservative thresholds initially (prefer more NEW over false SAME)
- Periodic merge-suggestion reviews every 10–20 ingested roles
- Immutable Atom IDs prevent downstream breakage
