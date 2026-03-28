from __future__ import annotations

import google.genai as genai

from hackathon.rag.base import RAGBackend


class StuffingRAG(RAGBackend):
    def __init__(self, api_key: str, model: str = "gemini-2.0-flash") -> None:
        self._client = genai.Client(api_key=api_key)
        self._model = model
        self._context = ""

    async def insert(self, documents: dict[str, str]) -> None:
        parts = []
        for name, content in documents.items():
            parts.append(f"# Source: {name}\n\n{content}")
        self._context = "\n\n---\n\n".join(parts)

    async def query(self, question: str) -> str:
        prompt = (
            "You are a helpful assistant. Use the following knowledge base to answer the question. "
            "If the answer is not in the knowledge base, say so.\n\n"
            f"## Knowledge Base\n\n{self._context}\n\n"
            f"## Question\n\n{question}"
        )
        response = await self._client.aio.models.generate_content(model=self._model, contents=prompt)
        return response.text
