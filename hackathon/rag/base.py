from __future__ import annotations

from abc import ABC, abstractmethod


class RAGBackend(ABC):
    @abstractmethod
    async def insert(self, documents: dict[str, str]) -> None:
        """Index documents. Keys are filenames, values are content."""

    @abstractmethod
    async def query(self, question: str) -> str:
        """Ask a question and return the answer."""
