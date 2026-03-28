"""Unified pipeline: mic → STT → agent → TTS → audio device."""

from __future__ import annotations

import asyncio
import logging
import time

from hackathon.agent import MeetingAgent, TranscriptChunk
from hackathon.config import ProjectSettings
from hackathon.rag import load_knowledge_base
from hackathon.stt import ResumableMicrophoneStream, generate_transcripts
from hackathon.voiceover.audio import open_stream, write_chunk
from hackathon.voiceover.tts import create_client, text_to_speech_stream

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def run() -> None:
    settings = ProjectSettings()
    loop = asyncio.get_event_loop()

    # -- TTS setup --
    tts_client = create_client(settings)
    audio_out = open_stream(settings.audio_device, settings.sample_rate)

    # -- Agent setup --
    knowledge = load_knowledge_base()
    agent = MeetingAgent(settings=settings, knowledge_base=knowledge)
    logger.info("Loaded %d chars of knowledge base", len(knowledge))

    # -- Thread-safe queue bridge --
    transcript_queue: asyncio.Queue[TranscriptChunk | None] = asyncio.Queue()

    def _put_chunk(chunk: TranscriptChunk | None) -> None:
        """Thread-safe put into the asyncio queue."""
        loop.call_soon_threadsafe(transcript_queue.put_nowait, chunk)

    def _stt_worker() -> None:
        mic = ResumableMicrophoneStream()
        try:
            for event in generate_transcripts(mic.generator()):
                if event.is_final:
                    chunk = TranscriptChunk(
                        speaker="Speaker",
                        text=event.text,
                        timestamp=time.time(),
                    )
                    _put_chunk(chunk)
                    logger.info("STT: %s", event.text)
                else:
                    logger.debug("STT (interim): %s", event.text)
        except KeyboardInterrupt:
            pass
        finally:
            mic.close()
            _put_chunk(None)

    stt_task = loop.run_in_executor(None, _stt_worker)

    # -- Main loop: consume transcript → run agent → voice corrections --
    logger.info("Pipeline running. Speak into the mic...")
    try:
        while True:
            chunk = await transcript_queue.get()
            if chunk is None:
                break
            if not chunk.text.strip():
                continue
            logger.info("Processing chunk: %s", chunk.text[:80])
            try:
                correction = await agent.process_chunk(chunk)
            except Exception:
                logger.exception("Agent error")
                continue
            if correction:
                logger.info("Voicing correction: %s", correction)
                try:
                    async for audio_chunk in text_to_speech_stream(tts_client, correction, settings):
                        write_chunk(audio_out, audio_chunk)
                    logger.info("Correction voiced successfully")
                except Exception:
                    logger.exception("TTS error")
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        audio_out.stop()
        audio_out.close()
        await stt_task


asyncio.run(run())
