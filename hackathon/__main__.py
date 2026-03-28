"""Entry point for the meeting agent pipeline."""

import argparse
import asyncio
import queue
import sys
import time

from loguru import logger


def _run_headless() -> None:
    from pathlib import Path

    from hackathon.agent import MeetingAgent, TranscriptChunk
    from hackathon.audio import MicrophoneInput
    from hackathon.config import ProjectSettings
    from hackathon.interrupt_service import InterruptService
    from hackathon.stt import generate_transcripts
    from hackathon.voiceover.audio import open_stream, write_chunk
    from hackathon.voiceover.tts import create_client, text_to_speech_stream

    logger.remove()
    logger.add(sys.stderr, level="INFO", format="{time:HH:mm:ss} | {level:<7} | {message}")

    async def run() -> None:
        settings = ProjectSettings()
        loop = asyncio.get_event_loop()

        tts_client = create_client(settings)
        audio_out = open_stream(settings.audio_device, settings.sample_rate)

        # -- Shared mic --
        mic_input = MicrophoneInput(sample_rate_hz=16000)
        await mic_input.start()
        interrupt_svc = InterruptService(mic_input)
        await interrupt_svc.start()

        # -- Bridge: async mic subscriber → sync queue for STT --
        audio_queue: queue.Queue[bytes | None] = queue.Queue()

        async def _mic_bridge() -> None:
            async for chunk in mic_input.subscribe():
                audio_queue.put(chunk.pcm_s16le)
            audio_queue.put(None)

        bridge_task = asyncio.create_task(_mic_bridge())

        def _audio_gen():
            while True:
                data = audio_queue.get()
                if data is None:
                    return
                yield data

        # -- Knowledge --
        knowledge = ""
        if settings.use_rag:
            data_dir = Path(settings.rag_data_dir)
            docs = {p.name: p.read_text() for p in sorted(data_dir.glob("*.md"))}
            knowledge = "\n\n---\n\n".join(f"# {k}\n{v}" for k, v in docs.items())

        agent = MeetingAgent(settings=settings, knowledge_base=knowledge)
        logger.info("Pipeline running (headless). Speak into the mic...")

        # -- STT thread --
        transcript_queue: asyncio.Queue[TranscriptChunk | None] = asyncio.Queue()

        def _put(chunk: TranscriptChunk | None) -> None:
            loop.call_soon_threadsafe(transcript_queue.put_nowait, chunk)

        def _stt_worker() -> None:
            try:
                for event in generate_transcripts(_audio_gen()):
                    if event.is_final:
                        _put(TranscriptChunk(speaker="Speaker", text=event.text, timestamp=time.time()))
                        logger.info("STT: {}", event.text.strip())
                    else:
                        logger.debug("STT (interim): {}", event.text.strip())
            except Exception:
                logger.exception("STT error")
            finally:
                _put(None)

        loop.run_in_executor(None, _stt_worker)

        # -- Main loop --
        try:
            while True:
                chunk = await transcript_queue.get()
                if chunk is None:
                    break
                if not chunk.text.strip():
                    continue
                try:
                    correction = await agent.process_chunk(chunk)
                except Exception:
                    logger.exception("Agent error")
                    continue
                if correction:
                    logger.success("Correction: {}", correction)
                    try:
                        await interrupt_svc.wait_for_interrupt_window()
                    except Exception:
                        logger.warning("Turn detector error, speaking immediately")
                    logger.info("Speaking...")
                    try:
                        async for audio_chunk in text_to_speech_stream(tts_client, correction, settings):
                            write_chunk(audio_out, audio_chunk)
                    except Exception:
                        logger.exception("TTS error")
        except KeyboardInterrupt:
            logger.info("Shutting down...")
        finally:
            bridge_task.cancel()
            await interrupt_svc.stop()
            await mic_input.stop()
            audio_out.stop()
            audio_out.close()

    asyncio.run(run())


def main() -> None:
    parser = argparse.ArgumentParser(description="Meeting fact-check agent")
    parser.add_argument("--no-ui", action="store_true", help="Run in headless mode (terminal logs only)")
    args = parser.parse_args()

    if args.no_ui:
        _run_headless()
    else:
        from hackathon.ui import MeetingUI
        MeetingUI().run()


main()
