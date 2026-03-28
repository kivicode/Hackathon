"""RAG: loads data/ docs into memory for the agent context."""

from __future__ import annotations

from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def load_knowledge_base() -> str:
    """Load all data/*.md files and return as a single string."""
    parts = []
    for path in sorted(DATA_DIR.glob("*.md")):
        parts.append(f"=== {path.name} ===\n{path.read_text()}")
    return "\n\n".join(parts)
