import time
from collections.abc import AsyncIterator

from google import genai
from google.genai import types
from loguru import logger

from hackathon.config import ProjectSettings

TTS_SYSTEM_INSTRUCTION = (
    "You are a text-to-speech engine. Read the user's message aloud exactly as written. "
    "Do not respond, comment, or add anything. Just read the text verbatim."
)


def create_client(settings: ProjectSettings) -> genai.Client:
    return genai.Client(
        api_key=settings.gemini_api_key,
        http_options={"api_version": "v1alpha"},
    )


def _make_config(settings: ProjectSettings) -> types.LiveConnectConfig:
    return types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        system_instruction=types.Content(
            parts=[types.Part(text=TTS_SYSTEM_INSTRUCTION)],
        ),
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(
                    voice_name=settings.voice_name,
                ),
            ),
        ),
    )


async def _buffer_sentences(text: AsyncIterator[str]) -> AsyncIterator[str]:
    """Buffer an async stream of tokens into sentences (split on '. ')."""
    buf = ""
    async for chunk in text:
        buf += chunk
        while ". " in buf:
            sentence, buf = buf.split(". ", 1)
            yield sentence + "."
    if buf.strip():
        yield buf.strip()


async def _synthesize_one(
    client: genai.Client,
    sentence: str,
    config: types.LiveConnectConfig,
    settings: ProjectSettings,
) -> AsyncIterator[bytes]:
    """Synthesize a single sentence via a fresh Live API connection."""
    t0 = time.monotonic()
    chunk_count = 0
    async with client.aio.live.connect(model=settings.tts_model, config=config) as session:
        await session.send_realtime_input(text=sentence)
        async for response in session.receive():
            if response.server_content and response.server_content.model_turn:
                for part in response.server_content.model_turn.parts:
                    if part.inline_data:
                        chunk_count += 1
                        if chunk_count == 1:
                            logger.info("TTS first chunk in {:.1f}s", time.monotonic() - t0)
                        yield part.inline_data.data
            if response.server_content and response.server_content.turn_complete:
                break
    logger.info("TTS done: {} chunks in {:.1f}s", chunk_count, time.monotonic() - t0)


# Keep TTSSession as a no-op wrapper for API compatibility
class TTSSession:
    """Placeholder — each synthesize call creates its own connection."""

    def __init__(self, client: genai.Client, settings: ProjectSettings) -> None:
        self._client = client
        self._settings = settings
        self._config = _make_config(settings)

    async def close(self) -> None:
        pass

    async def synthesize(self, text: str) -> AsyncIterator[bytes]:
        async for chunk in _synthesize_one(self._client, text, self._config, self._settings):
            yield chunk


async def text_to_speech_stream(
    client: genai.Client,
    text: str | AsyncIterator[str],
    settings: ProjectSettings,
    session: TTSSession | None = None,
) -> AsyncIterator[bytes]:
    """Convert text to streaming PCM audio via Gemini Live API."""
    if session is None:
        session = TTSSession(client, settings)

    if isinstance(text, str):
        async for chunk in session.synthesize(text):
            yield chunk
    else:
        async for sentence in _buffer_sentences(text):
            async for chunk in session.synthesize(sentence):
                yield chunk
