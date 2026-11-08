"""The project only has an OpenAI API key, so every LLM call must go to OpenAI.

These tests fail if Anthropic code or the Anthropic dependency comes back, for
example from a branch written before the OpenAI port.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CODE_DIRS = [REPO / "backend", REPO / "scripts"]
DEPENDENCY_FILES = [REPO / "requirements.txt", REPO / "backend" / "requirements.txt", REPO / "pyproject.toml"]

ANTHROPIC_IMPORT = re.compile(r"^\s*(from\s+anthropic\b|import\s+anthropic\b)", re.M)


def test_no_python_file_imports_anthropic():
    offenders = [
        str(path.relative_to(REPO))
        for root in CODE_DIRS
        for path in root.rglob("*.py")
        if ANTHROPIC_IMPORT.search(path.read_text(encoding="utf-8"))
    ]
    assert not offenders, f"These files import anthropic; use openai.AsyncOpenAI instead: {offenders}"


def test_dependencies_name_openai_not_anthropic():
    for path in DEPENDENCY_FILES:
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"^\s*\"?anthropic\b", text, re.M), f"{path.name} still lists anthropic"
        assert re.search(r"^\s*\"?openai\b", text, re.M), f"{path.name} does not list openai"
