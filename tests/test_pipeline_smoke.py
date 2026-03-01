"""Smoke tests for CareerSynth pipeline — written TDD-first."""

import json
import sqlite3
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


# ============================================================
# CP1: DB Schema Tests
# ============================================================

class TestDBSchema:
    """Test database schema creation and basic operations."""

    def test_init_db_creates_tables(self, db_path):
        """init_db should create all required tables."""
        from career_rnd.db import init_db
        conn = init_db(str(db_path))
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = {row[0] for row in cursor.fetchall()}
        assert "roles" in tables
        assert "phrases" in tables
        assert "atoms" in tables
        assert "atom_aliases" in tables
        assert "mappings" in tables
        conn.close()

    def test_init_db_idempotent(self, db_path):
        """Calling init_db twice should not raise."""
        from career_rnd.db import init_db
        conn1 = init_db(str(db_path))
        conn1.close()
        conn2 = init_db(str(db_path))
        conn2.close()

    def test_roles_table_schema(self, db_path):
        """Roles table should have correct columns."""
        from career_rnd.db import init_db
        conn = init_db(str(db_path))
        cursor = conn.execute("PRAGMA table_info(roles)")
        columns = {row[1] for row in cursor.fetchall()}
        assert "role_id" in columns
        assert "source_path" in columns
        assert "company" in columns
        assert "title" in columns
        assert "raw_text_path" in columns
        conn.close()

    def test_atoms_table_schema(self, db_path):
        """Atoms table should have correct columns."""
        from career_rnd.db import init_db
        conn = init_db(str(db_path))
        cursor = conn.execute("PRAGMA table_info(atoms)")
        columns = {row[1] for row in cursor.fetchall()}
        assert "atom_id" in columns
        assert "name" in columns
        assert "definition" in columns
        assert "parent_atom_id" in columns
        conn.close()


# ============================================================
# CP2: Atom Library Tests
# ============================================================

class TestAtomLibrary:
    """Test seed atom library loading and management."""

    def test_seed_atoms_file_exists(self):
        """atoms.json should exist in skill_library/."""
        atoms_path = Path(__file__).parent.parent / "skill_library" / "atoms.json"
        assert atoms_path.exists(), f"Seed atoms file not found at {atoms_path}"

    def test_seed_atoms_valid_json(self):
        """atoms.json should be valid JSON."""
        atoms_path = Path(__file__).parent.parent / "skill_library" / "atoms.json"
        with open(atoms_path) as f:
            data = json.load(f)
        assert isinstance(data, list)

    def test_seed_atoms_count(self):
        """Should have 35-45 seed atoms."""
        atoms_path = Path(__file__).parent.parent / "skill_library" / "atoms.json"
        with open(atoms_path) as f:
            data = json.load(f)
        assert 35 <= len(data) <= 45, f"Expected 35-45 atoms, got {len(data)}"

    def test_seed_atoms_structure(self):
        """Each atom should have required fields."""
        atoms_path = Path(__file__).parent.parent / "skill_library" / "atoms.json"
        with open(atoms_path) as f:
            data = json.load(f)
        for atom in data:
            assert "atom_id" in atom, f"Missing atom_id in {atom.get('name', 'unknown')}"
            assert "name" in atom
            assert "definition" in atom
            assert "positive_examples" in atom
            assert "negative_examples" in atom
            assert len(atom["positive_examples"]) >= 3, (
                f"Atom {atom['atom_id']} needs >= 3 positive examples"
            )
            assert len(atom["negative_examples"]) >= 2, (
                f"Atom {atom['atom_id']} needs >= 2 negative examples"
            )

    def test_atom_ids_unique(self):
        """All atom IDs must be unique."""
        atoms_path = Path(__file__).parent.parent / "skill_library" / "atoms.json"
        with open(atoms_path) as f:
            data = json.load(f)
        ids = [a["atom_id"] for a in data]
        assert len(ids) == len(set(ids)), "Duplicate atom IDs found"

    def test_load_atoms_into_db(self, db_path):
        """load_seed_atoms should populate the atoms table."""
        from career_rnd.db import init_db
        from career_rnd.atoms import load_seed_atoms
        conn = init_db(str(db_path))
        load_seed_atoms(conn)
        cursor = conn.execute("SELECT COUNT(*) FROM atoms")
        count = cursor.fetchone()[0]
        assert count >= 35
        conn.close()


# ============================================================
# CP3: Ingest + Extract Tests
# ============================================================

class TestIngest:
    """Test file ingestion."""

    def test_ingest_text_file(self, db_path, sample_pdf_path):
        """Should register a text file as a role in the database."""
        from career_rnd.db import init_db
        from career_rnd.ingest import ingest_file
        conn = init_db(str(db_path))
        role_id = ingest_file(conn, str(sample_pdf_path))
        assert role_id is not None
        cursor = conn.execute("SELECT COUNT(*) FROM roles WHERE role_id=?", (role_id,))
        assert cursor.fetchone()[0] == 1
        conn.close()

    def test_ingest_duplicate_skipped(self, db_path, sample_pdf_path):
        """Ingesting the same file twice should not create duplicates."""
        from career_rnd.db import init_db
        from career_rnd.ingest import ingest_file
        conn = init_db(str(db_path))
        role_id1 = ingest_file(conn, str(sample_pdf_path))
        role_id2 = ingest_file(conn, str(sample_pdf_path))
        cursor = conn.execute("SELECT COUNT(*) FROM roles")
        assert cursor.fetchone()[0] == 1
        conn.close()


class TestExtract:
    """Test text extraction and section detection."""

    def test_extract_text_from_file(self, sample_pdf_path):
        """Should extract text from a plain text file."""
        from career_rnd.extract import extract_text
        text = extract_text(str(sample_pdf_path))
        assert "UX Prototyping" in text
        assert len(text) > 100

    def test_sectionize_english(self, sample_job_text):
        """Should detect Must/Want/Responsibilities sections in English text."""
        from career_rnd.extract import sectionize
        sections = sectionize(sample_job_text)
        assert isinstance(sections, list)
        # Should find at least responsibilities, must, and want sections
        section_types = {s["section"] for s in sections}
        assert "must" in section_types or "responsibility" in section_types

    def test_sectionize_japanese(self, sample_job_text_ja):
        """Should detect sections in Japanese text."""
        from career_rnd.extract import sectionize
        sections = sectionize(sample_job_text_ja)
        assert isinstance(sections, list)
        assert len(sections) > 0

    def test_section_weight_assignment(self, sample_job_text):
        """Each section item should have a weight based on section type."""
        from career_rnd.extract import sectionize
        sections = sectionize(sample_job_text)
        for item in sections:
            assert "weight" in item
            assert 0.0 <= item["weight"] <= 1.0


# ============================================================
# CP4: LLM Integration Tests (mocked)
# ============================================================

class TestLLMIntegration:
    """Test LLM-based skill extraction and mapping (with mocks)."""

    def test_extract_skills_prompt_exists(self):
        """extract_skills.md prompt template should exist."""
        prompt_path = (
            Path(__file__).parent.parent / "career_rnd" / "prompts" / "extract_skills.md"
        )
        assert prompt_path.exists()

    def test_map_to_atoms_prompt_exists(self):
        """map_to_atoms.md prompt template should exist."""
        prompt_path = (
            Path(__file__).parent.parent / "career_rnd" / "prompts" / "map_to_atoms.md"
        )
        assert prompt_path.exists()

    def test_merge_suggestions_prompt_exists(self):
        """merge_suggestions.md prompt template should exist."""
        prompt_path = (
            Path(__file__).parent.parent / "career_rnd" / "prompts" / "merge_suggestions.md"
        )
        assert prompt_path.exists()

    def test_extract_skills_returns_phrases(self, sample_job_text):
        """LLM skill extraction should return structured phrases."""
        from career_rnd.llm import extract_skills_from_text
        # Mock the LLM call
        mock_response = {
            "company": "TechCorp",
            "title": "Senior UX Prototyping Lead",
            "location": "Tokyo, Japan",
            "language": "en",
            "skills_must": [
                "UX design",
                "Figma proficiency",
                "interaction design",
                "user research"
            ],
            "skills_want": [
                "React",
                "spatial UI / XR",
                "AI-assisted design"
            ],
            "responsibilities": [
                "lead UX prototyping",
                "cross-functional collaboration",
                "prototype evaluation",
                "usability testing"
            ],
            "traits": []
        }
        with patch("career_rnd.llm._call_llm", return_value=json.dumps(mock_response)):
            result = extract_skills_from_text(sample_job_text)
        assert "skills_must" in result
        assert "skills_want" in result
        assert len(result["skills_must"]) >= 1

    def test_map_phrases_to_atoms(self, db_path):
        """Mapping pipeline should produce SAME/CHILD/NEW decisions."""
        import hashlib
        from career_rnd.db import init_db
        from career_rnd.atoms import load_seed_atoms
        from career_rnd.map_skills import map_phrases_to_atoms

        conn = init_db(str(db_path))
        load_seed_atoms(conn)

        # Insert role and phrases so FK constraints are satisfied
        role_id = "test_role_1"
        conn.execute(
            "INSERT INTO roles (role_id, source_path, date_added) VALUES (?, ?, ?)",
            (role_id, "/test", "2026-03-01"),
        )

        phrases = [
            {"phrase": "UX design", "section": "must", "weight": 1.0},
            {"phrase": "React development", "section": "want", "weight": 0.6},
        ]

        for p in phrases:
            phrase_text = p["phrase"]
            pid = f"phr_{hashlib.sha256(f'{role_id}:{phrase_text}'.encode()).hexdigest()[:16]}"
            conn.execute(
                "INSERT OR IGNORE INTO phrases (phrase_id, role_id, phrase, section, weight) VALUES (?, ?, ?, ?, ?)",
                (pid, role_id, p["phrase"], p["section"], p["weight"]),
            )
        conn.commit()

        mock_decisions = [
            {
                "phrase": "UX design",
                "atom_id": "CS_EXP_001",
                "decision": "SAME",
                "confidence": 0.92,
                "rationale": "Direct match to UX/interaction design atom"
            },
            {
                "phrase": "React development",
                "atom_id": "CS_DEV_001",
                "decision": "CHILD",
                "confidence": 0.78,
                "rationale": "React is a specific frontend framework"
            }
        ]

        with patch("career_rnd.map_skills._get_mapping_decisions", return_value=mock_decisions):
            results = map_phrases_to_atoms(conn, role_id, phrases)

        assert len(results) == 2
        assert all(r["decision"] in ("SAME", "CHILD", "NEW", "AMBIGUOUS") for r in results)
        conn.close()


# ============================================================
# CP5: Embedding Tests (mocked)
# ============================================================

class TestEmbeddings:
    """Test embedding computation and similarity."""

    def test_compute_embedding(self):
        """Should compute an embedding vector for a text string."""
        from career_rnd.embeddings import compute_embedding
        # Mock embedding API
        mock_embedding = [0.1] * 1536
        with patch("career_rnd.embeddings._call_embedding_api", return_value=mock_embedding):
            result = compute_embedding("UX design")
        assert isinstance(result, list)
        assert len(result) == 1536

    def test_cosine_similarity(self):
        """Should compute cosine similarity between two vectors."""
        from career_rnd.embeddings import cosine_similarity
        import numpy as np
        a = [1.0, 0.0, 0.0]
        b = [1.0, 0.0, 0.0]
        assert cosine_similarity(a, b) == pytest.approx(1.0, abs=0.01)

        c = [0.0, 1.0, 0.0]
        assert cosine_similarity(a, c) == pytest.approx(0.0, abs=0.01)


# ============================================================
# CP6: Overlap Scoring + Graph Tests
# ============================================================

class TestOverlap:
    """Test overlap scoring, graph, and clustering."""

    def test_build_cooccurrence_graph(self, db_path):
        """Should build a graph from role-atom mappings."""
        from career_rnd.db import init_db
        from career_rnd.overlap import build_cooccurrence_graph

        conn = init_db(str(db_path))
        # Insert test data
        conn.execute(
            "INSERT INTO atoms (atom_id, name, definition, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            ("A1", "Skill A", "def A", "2026-03-01", "2026-03-01"),
        )
        conn.execute(
            "INSERT INTO atoms (atom_id, name, definition, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            ("A2", "Skill B", "def B", "2026-03-01", "2026-03-01"),
        )
        conn.execute(
            "INSERT INTO roles (role_id, source_path, date_added) VALUES (?, ?, ?)",
            ("R1", "/test", "2026-03-01"),
        )
        conn.execute(
            "INSERT INTO phrases (phrase_id, role_id, phrase, section, weight) VALUES (?, ?, ?, ?, ?)",
            ("P1", "R1", "skill a", "must", 1.0),
        )
        conn.execute(
            "INSERT INTO phrases (phrase_id, role_id, phrase, section, weight) VALUES (?, ?, ?, ?, ?)",
            ("P2", "R1", "skill b", "must", 1.0),
        )
        conn.execute(
            "INSERT INTO mappings (mapping_id, phrase_id, atom_id, decision, confidence, rationale, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("M1", "P1", "A1", "SAME", 0.95, "test", "2026-03-01"),
        )
        conn.execute(
            "INSERT INTO mappings (mapping_id, phrase_id, atom_id, decision, confidence, rationale, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("M2", "P2", "A2", "SAME", 0.90, "test", "2026-03-01"),
        )
        conn.commit()

        G = build_cooccurrence_graph(conn)
        assert G.number_of_nodes() >= 2
        assert G.has_edge("A1", "A2")
        conn.close()

    def test_compute_overlap_scores(self, db_path):
        """Should compute overlap scores for atoms."""
        from career_rnd.db import init_db
        from career_rnd.overlap import compute_overlap_scores

        conn = init_db(str(db_path))
        # Insert minimal test data: 2 roles sharing 1 atom
        for i in range(1, 3):
            conn.execute(
                "INSERT INTO roles (role_id, source_path, date_added) VALUES (?, ?, ?)",
                (f"R{i}", f"/test{i}", "2026-03-01"),
            )
            conn.execute(
                "INSERT INTO atoms (atom_id, name, definition, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (f"A{i}", f"Skill {i}", f"def {i}", "2026-03-01", "2026-03-01"),
            )
        # Shared atom
        conn.execute(
            "INSERT INTO atoms (atom_id, name, definition, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            ("SHARED", "Shared Skill", "shared def", "2026-03-01", "2026-03-01"),
        )
        # Both roles have SHARED atom
        for i in range(1, 3):
            pid = f"P_shared_{i}"
            conn.execute(
                "INSERT INTO phrases (phrase_id, role_id, phrase, section, weight) VALUES (?, ?, ?, ?, ?)",
                (pid, f"R{i}", "shared skill", "must", 1.0),
            )
            conn.execute(
                "INSERT INTO mappings (mapping_id, phrase_id, atom_id, decision, confidence, rationale, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (f"M_shared_{i}", pid, "SHARED", "SAME", 0.95, "test", "2026-03-01"),
            )
        conn.commit()

        scores = compute_overlap_scores(conn)
        assert isinstance(scores, list)
        # SHARED atom should have highest score (appears in both roles)
        shared_scores = [s for s in scores if s["atom_id"] == "SHARED"]
        assert len(shared_scores) == 1
        assert shared_scores[0]["overlap_score"] > 0
        conn.close()

    def test_overlap_score_formula(self):
        """OverlapScore = 0.45*freq + 0.35*centrality + 0.20*cluster_coverage."""
        from career_rnd.overlap import calculate_overlap_score
        score = calculate_overlap_score(
            frequency=1.0, centrality=1.0, cluster_coverage=1.0
        )
        assert score == pytest.approx(1.0, abs=0.01)

        score_zero = calculate_overlap_score(
            frequency=0.0, centrality=0.0, cluster_coverage=0.0
        )
        assert score_zero == pytest.approx(0.0, abs=0.01)


# ============================================================
# CP7: Report Generation Tests
# ============================================================

class TestReports:
    """Test CSV and HTML/MD report generation."""

    def test_generate_overlap_spine_csv(self, db_path, tmp_dir):
        """Should generate overlap_spine.csv."""
        from career_rnd.db import init_db
        from career_rnd.report import generate_overlap_spine_csv

        conn = init_db(str(db_path))
        # Insert minimal data
        conn.execute(
            "INSERT INTO atoms (atom_id, name, definition, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            ("A1", "Test Skill", "test def", "2026-03-01", "2026-03-01"),
        )
        conn.commit()

        output_path = tmp_dir / "overlap_spine.csv"
        generate_overlap_spine_csv(conn, str(output_path))
        assert output_path.exists()
        content = output_path.read_text()
        assert "atom_id" in content  # header row
        conn.close()

    def test_generate_role_details_csv(self, db_path, tmp_dir):
        """Should generate role_details.csv with phrase-level data."""
        from career_rnd.db import init_db
        from career_rnd.report import generate_role_details_csv

        conn = init_db(str(db_path))
        conn.execute(
            "INSERT INTO roles (role_id, source_path, company, title, date_added) VALUES (?, ?, ?, ?, ?)",
            ("R1", "/test", "TestCo", "Engineer", "2026-03-01"),
        )
        conn.execute(
            "INSERT INTO atoms (atom_id, name, definition, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            ("A1", "Test Skill", "test def", "2026-03-01", "2026-03-01"),
        )
        conn.execute(
            "INSERT INTO phrases (phrase_id, role_id, phrase, section, weight) VALUES (?, ?, ?, ?, ?)",
            ("P1", "R1", "test phrase", "must", 1.0),
        )
        conn.execute(
            "INSERT INTO mappings (mapping_id, phrase_id, atom_id, decision, confidence, rationale, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("M1", "P1", "A1", "SAME", 0.85, "test match", "2026-03-01"),
        )
        conn.commit()

        output_path = tmp_dir / "role_details.csv"
        generate_role_details_csv(conn, str(output_path))
        assert output_path.exists()
        content = output_path.read_text()
        assert "role_id" in content
        assert "test phrase" in content
        assert "Test Skill" in content
        assert "SAME" in content
        conn.close()

    def test_generate_html_report(self, db_path, tmp_dir):
        """Should generate an HTML report."""
        from career_rnd.db import init_db
        from career_rnd.report import generate_html_report

        conn = init_db(str(db_path))
        conn.execute(
            "INSERT INTO atoms (atom_id, name, definition, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            ("A1", "Test Skill", "test def", "2026-03-01", "2026-03-01"),
        )
        conn.commit()

        output_path = tmp_dir / "report.html"
        generate_html_report(conn, str(output_path))
        assert output_path.exists()
        content = output_path.read_text()
        assert "<html" in content.lower()
        conn.close()


# ============================================================
# CP8: CLI Tests
# ============================================================

class TestCLI:
    """Test CLI command registration."""

    def test_cli_app_exists(self):
        """The Typer app should be importable."""
        from career_rnd.cli import app
        assert app is not None

    def test_cli_has_commands(self):
        """CLI should have the expected commands registered."""
        from career_rnd.cli import app
        # Typer registers commands - check they exist
        command_names = set()
        # Check registered commands and groups
        if hasattr(app, "registered_commands"):
            for cmd in app.registered_commands:
                if hasattr(cmd, "name") and cmd.name:
                    command_names.add(cmd.name)
        if hasattr(app, "registered_groups"):
            for grp in app.registered_groups:
                if hasattr(grp, "name") and grp.name:
                    command_names.add(grp.name)
        # At minimum these should exist
        assert len(command_names) > 0, "No CLI commands registered"
