from hackathon.voiceover.audio import open_stream, play_audio, write_chunk
from hackathon.voiceover.tts import create_client, text_to_speech_stream

__all__ = ["create_client", "open_stream", "play_audio", "text_to_speech_stream", "write_chunk"]

if __name__ == "__main__":
    import asyncio

    from hackathon.config import ProjectSettings

    DEMO_TEXT = (
        "Small correction: the task board shows Feature X as implemented, "
        "but the lead engineer flagged deployment issues yesterday. "
        "It is not production-ready yet."
    )

    async def word_stream(text: str):
        for word in text.split():
            yield word + " "
            await asyncio.sleep(0.05)

    async def main() -> None:
        settings = ProjectSettings()
        client = create_client(settings)
        stream = open_stream(settings.audio_device, settings.sample_rate)
        try:
            async for chunk in text_to_speech_stream(client, word_stream(DEMO_TEXT), settings):
                print(f"audio chunk: {len(chunk)} bytes")
                write_chunk(stream, chunk)
        finally:
            stream.stop()
            stream.close()

    asyncio.run(main())
