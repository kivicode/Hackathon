"""Voiceover HTTP endpoint — speaks text via TTS to the virtual audio device."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator

from fastapi import FastAPI
from google import genai
from pydantic import BaseModel

from hackathon.config import ProjectSettings
from hackathon.voiceover.audio import open_stream, write_chunk
from hackathon.voiceover.tts import create_client, text_to_speech_stream


class SpeakRequest(BaseModel):
    text: str


settings = ProjectSettings()
client: genai.Client


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None]:
    global client  # noqa: PLW0603
    client = create_client(settings)
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
