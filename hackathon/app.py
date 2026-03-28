import asyncio
from contextlib import asynccontextmanager

import google.genai as genai
from fastapi import FastAPI
from pydantic import BaseModel

from hackathon.config import ProjectSettings
from hackathon.voiceover.audio import open_stream, write_chunk
from hackathon.voiceover.tts import create_client, text_to_speech_stream


class SpeakRequest(BaseModel):
    text: str


settings = ProjectSettings()
client: genai.Client


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global client  # noqa: PLW0603
    client = create_client(settings)
    yield


app = FastAPI(lifespan=lifespan)


@app.post("/speak")
async def speak(request: SpeakRequest) -> dict:
    stream = await asyncio.to_thread(open_stream, settings.audio_device, settings.sample_rate)
    try:
        async for chunk in text_to_speech_stream(client, request.text, settings):
            await asyncio.to_thread(write_chunk, stream, chunk)
    finally:
        await asyncio.to_thread(stream.stop)
        await asyncio.to_thread(stream.close)
    return {"status": "ok", "text": request.text}
