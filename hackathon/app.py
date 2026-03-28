"""Voiceover HTTP endpoint — speaks text via TTS to the virtual audio device."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from google import genai
from pydantic import BaseModel

from hackathon.config import ProjectSettings
from hackathon.rag.base import RAGBackend
from hackathon.rag.light import LightRAGBackend
from hackathon.rag.stuffing import StuffingRAG
from hackathon.voiceover.audio import open_stream, write_chunk
from hackathon.voiceover.tts import create_client, text_to_speech_stream


class SpeakRequest(BaseModel):
    text: str


class AskRequest(BaseModel):
    question: str


settings = ProjectSettings()
client: genai.Client
rag: RAGBackend


def _load_documents(data_dir: str) -> dict[str, str]:
    docs = {}
    for md_file in sorted(Path(data_dir).glob("*.md")):
        docs[md_file.name] = md_file.read_text()
    return docs


def _create_rag_backend(s: ProjectSettings) -> RAGBackend:
    if s.rag_mode == "lightrag":
        return LightRAGBackend(api_key=s.gemini_api_key, working_dir=s.rag_working_dir)

    return StuffingRAG(api_key=s.gemini_api_key)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None]:
    global client, rag  # noqa: PLW0603
    client = create_client(settings)
    rag = _create_rag_backend(settings)
    docs = _load_documents(settings.rag_data_dir)
    await rag.insert(docs)
    yield


app = FastAPI(lifespan=lifespan)


@app.post("/speak")
async def speak(request: SpeakRequest) -> dict[str, str]:
    stream = await asyncio.to_thread(open_stream, settings.audio_device, settings.sample_rate)
    try:
        async for chunk in text_to_speech_stream(client, request.text, settings):
            await asyncio.to_thread(write_chunk, stream, chunk)
    finally:
        await asyncio.to_thread(stream.stop)
        await asyncio.to_thread(stream.close)
    return {"status": "ok", "text": request.text}


@app.post("/ask")
async def ask(request: AskRequest) -> dict:
    answer = await rag.query(request.question)
    return {"answer": answer}
