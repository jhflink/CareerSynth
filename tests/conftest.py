"""Shared test fixtures for CareerSynth tests."""

import os
import sqlite3
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def tmp_dir(tmp_path):
    """Provide a temporary directory for test data."""
    return tmp_path


@pytest.fixture
def sample_job_text():
    """Sample English job description text."""
    return """
Senior UX Prototyping Lead

Company: TechCorp
Location: Tokyo, Japan

Responsibilities:
- Lead UX prototyping for next-generation products
- Collaborate cross-functionally with engineering, design, and product teams
- Build and evaluate interactive prototypes
- Conduct user research and usability testing

Must have:
- 5+ years experience in UX design
- Proficiency in Figma and prototyping tools
- Strong understanding of interaction design principles
- Experience with user research methodologies

Nice to have:
- Experience with React or similar frontend frameworks
- Knowledge of spatial UI / XR interfaces
- Japanese language ability (JLPT N2+)
- Experience with AI-assisted design workflows
"""


@pytest.fixture
def sample_job_text_ja():
    """Sample Japanese job description text."""
    return """
シニアUXプロトタイピングリード

会社: テックコープ
勤務地: 東京

職務内容:
- 次世代製品のUXプロトタイピングをリード
- エンジニアリング、デザイン、プロダクトチームとの横断的な協業
- インタラクティブプロトタイプの構築と評価
- ユーザーリサーチとユーザビリティテストの実施

必須要件:
- UXデザイン5年以上の経験
- Figmaおよびプロトタイピングツールの習熟
- インタラクションデザインの深い理解
- ユーザーリサーチ手法の経験

歓迎要件:
- ReactまたはフロントエンドFWの経験
- 空間UI / XRインターフェースの知識
- AI支援デザインワークフローの経験
"""


@pytest.fixture
def sample_pdf_path(tmp_dir, sample_job_text):
    """Create a simple text file pretending to be extracted PDF content."""
    p = tmp_dir / "test_job.txt"
    p.write_text(sample_job_text)
    return p


@pytest.fixture
def db_path(tmp_dir):
    """Provide a path for a temporary SQLite database."""
    return tmp_dir / "test_career.db"
