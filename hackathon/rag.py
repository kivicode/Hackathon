"""Mock RAG function. Replace with real retrieval over data/ files."""

from __future__ import annotations

from hackathon.agent import Evidence


def mock_rag(query: str, category: str) -> list[Evidence]:
    """Return hardcoded evidence for the demo scenario."""
    q = query.lower()

    if "feature" in q and ("ready" in q or "finished" in q or "done" in q or "implemented" in q):
        return [
            Evidence(
                source="Jira",
                snippet="Feature X ticket marked as 'Implemented' on March 25.",
                relevance_score=0.95,
            ),
            Evidence(
                source="Slack",
                snippet=(
                    "Lead engineer posted yesterday: 'Feature X has deployment issues, not production-ready yet.'"
                ),
                relevance_score=0.98,
            ),
        ]

    if "revenue" in q or "cost" in q or "million" in q or "infra" in q or "cut" in q:
        return [
            Evidence(
                source="Financial Report 2025",
                snippet=(
                    "Poland team XYZ service: 2024 revenue $1M, infra costs $3.4M. 2025 revenue $3M, infra costs $3.5M."
                ),
                relevance_score=0.97,
            ),
        ]

    return []
