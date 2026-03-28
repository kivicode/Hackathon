from collections.abc import AsyncIterator

from google import genai
from google.genai import types

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
    """Synthesize a single sentence via Gemini Live API."""
    async with client.aio.live.connect(model=settings.tts_model, config=config) as session:
        await session.send_realtime_input(text=sentence)
        async for response in session.receive():
            if response.server_content and response.server_content.model_turn:
                for part in response.server_content.model_turn.parts:
                    if part.inline_data:
                        yield part.inline_data.data
            if response.server_content and response.server_content.turn_complete:
                break


async def text_to_speech_stream(
    client: genai.Client,
    text: str | AsyncIterator[str],
    settings: ProjectSettings,
) -> AsyncIterator[bytes]:
    """Convert text to streaming PCM audio via Gemini Live API.

    Accepts a string or async iterator of text chunks.
    When given a stream, buffers into sentences and synthesizes
    each one for semi-realtime output.
    """
    config = _make_config(settings)

    if isinstance(text, str):
        async for chunk in _synthesize_one(client, text, config, settings):
            yield chunk
    else:
        async for sentence in _buffer_sentences(text):
            async for chunk in _synthesize_one(client, sentence, config, settings):
                yield chunk
