from collections.abc import AsyncIterator

from google import genai
from google.genai import types

from hackathon.config import ProjectSettings


def create_client(settings: ProjectSettings) -> genai.Client:
    return genai.Client(
        api_key=settings.gemini_api_key,
        http_options={"api_version": "v1alpha"},
    )


async def text_to_speech_stream(client: genai.Client, text: str, settings: ProjectSettings) -> AsyncIterator[bytes]:
    """Stream PCM audio chunks from Gemini Live API in real-time."""
    config = types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(
                    voice_name=settings.voice_name,
                ),
            ),
        ),
    )
    async with client.aio.live.connect(model=settings.gemini_model, config=config) as session:
        await session.send_realtime_input(text=text)
        async for response in session.receive():
            if response.server_content and response.server_content.model_turn:
                for part in response.server_content.model_turn.parts:
                    if part.inline_data:
                        yield part.inline_data.data
            if response.server_content and response.server_content.turn_complete:
                break


async def text_to_speech(client: genai.Client, text: str, settings: ProjectSettings) -> bytes:
    """Convert text to raw PCM audio bytes (non-streaming, collects all chunks)."""
    chunks = []
    async for chunk in text_to_speech_stream(client, text, settings):
        chunks.append(chunk)
    return b"".join(chunks)
