from __future__ import annotations

import os

import numpy as np
from lightrag import LightRAG
from lightrag.llm.gemini import gemini_embed, gemini_model_complete
from lightrag.utils import wrap_embedding_func_with_attrs

from hackathon.rag.base import RAGBackend


def _make_llm_func(api_key: str):  # noqa: ANN202
    async def llm_model_func(
        prompt: str,
        system_prompt: str | None = None,
        history_messages: list | None = None,
        keyword_extraction: bool = False,
        **kwargs,
    ) -> str:
        return await gemini_model_complete(
            prompt,
            system_prompt=system_prompt,
            history_messages=history_messages or [],
            api_key=api_key,
            model_name="gemini-2.0-flash",
            **kwargs,
        )

    return llm_model_func


def _make_embedding_func(api_key: str):  # noqa: ANN202
    @wrap_embedding_func_with_attrs(embedding_dim=768, max_token_size=2048, model_name="models/text-embedding-004")
    async def embedding_func(texts: list[str]) -> np.ndarray:
        return await gemini_embed.func(
            texts,
            api_key=api_key,
            model="models/text-embedding-004",
        )

    return embedding_func


class LightRAGBackend(RAGBackend):
    def __init__(self, api_key: str, working_dir: str = "rag_storage") -> None:
        os.makedirs(working_dir, exist_ok=True)
        self._rag = LightRAG(
            working_dir=working_dir,
            llm_model_func=_make_llm_func(api_key),
            llm_model_name="gemini-2.0-flash",
            embedding_func=_make_embedding_func(api_key),
        )

    async def insert(self, documents: dict[str, str]) -> None:
        await self._rag.initialize_storages()
        for name, content in documents.items():
            await self._rag.ainsert(f"# Source: {name}\n\n{content}")

    async def query(self, question: str) -> str:
        return await self._rag.aquery(question)
