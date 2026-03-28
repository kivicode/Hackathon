"""Speech-to-text via Google Cloud Speech API."""

from __future__ import annotations

import queue
import time as _time
from collections.abc import Generator, Iterator

import pyaudio
from google.api_core.exceptions import GoogleAPICallError
from google.cloud import speech
from loguru import logger
from pydantic import BaseModel

RATE = 16000
CHUNK = int(RATE / 10)  # 100ms chunks


class TranscriptEvent(BaseModel):
    text: str
    is_final: bool


class ResumableMicrophoneStream:
    """Opens a recording stream as a generator yielding audio chunks."""

    def __init__(self, rate: int = RATE, chunk_size: int = CHUNK) -> None:
        self._rate = rate
        self._chunk = chunk_size
        self._buff: queue.Queue[bytes | None] = queue.Queue()
        self.closed = True
        self._audio_interface = pyaudio.PyAudio()
        self._audio_stream = self._audio_interface.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=self._rate,
            input=True,
            frames_per_buffer=self._chunk,
            stream_callback=self._fill_buffer,
        )
        self.closed = False

    def _fill_buffer(
        self,
        in_data: bytes | None,
        frame_count: int,  # noqa: ARG002
        time_info: dict,  # noqa: ARG002
        status_flags: int,  # noqa: ARG002
    ) -> tuple[None, int]:
        self._buff.put(in_data)
        return None, pyaudio.paContinue

    def generator(self) -> Generator[bytes]:
        while not self.closed:
            chunk = self._buff.get()
            if chunk is None:
                return
            data = [chunk]
            while True:
                try:
                    chunk = self._buff.get(block=False)
                    if chunk is None:
                        return
                    data.append(chunk)
                except queue.Empty:
                    break
            yield b"".join(data)

    def close(self) -> None:
        self.closed = True
        self._buff.put(None)
        self._audio_stream.stop_stream()
        self._audio_stream.close()
        self._audio_interface.terminate()


def _drain_queue(audio_queue: queue.Queue) -> None:
    """Drain stale audio from the queue."""
    drained = 0
    while not audio_queue.empty():
        try:
            audio_queue.get_nowait()
            drained += 1
        except queue.Empty:
            break
    if drained:
        logger.debug("Drained {} stale audio chunks", drained)


def _make_audio_gen(audio_queue: queue.Queue) -> Generator[bytes]:
    """Create a fresh generator that reads from the audio queue."""
    while True:
        try:
            data = audio_queue.get(timeout=30)
        except queue.Empty:
            return
        if data is None:
            return
        yield data


def generate_transcripts(
    audio_queue: queue.Queue,
) -> Generator[TranscriptEvent]:
    """Consume Google Speech API responses and yield transcript events.

    Creates a fresh audio generator on each reconnect so the gRPC stream
    always gets a clean iterator.
    """
    client = speech.SpeechClient()

    config = speech.RecognitionConfig(
        encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
        sample_rate_hertz=RATE,
        language_code="en-US",
        enable_automatic_punctuation=True,
    )

    streaming_config = speech.StreamingRecognitionConfig(
        config=config,
        interim_results=True,
    )

    consecutive_errors = 0
    while True:
        _drain_queue(audio_queue)
        audio_gen = _make_audio_gen(audio_queue)

        try:
            requests = (speech.StreamingRecognizeRequest(audio_content=content) for content in audio_gen)
            responses = client.streaming_recognize(streaming_config, requests)

            for response in responses:
                if not response.results:
                    continue
                result = response.results[0]
                if not result.alternatives:
                    continue
                consecutive_errors = 0
                yield TranscriptEvent(
                    text=result.alternatives[0].transcript,
                    is_final=result.is_final,
                )
        except GoogleAPICallError as e:
            consecutive_errors += 1
            if consecutive_errors > 5:
                logger.warning("STT: too many errors, backing off 2s...")
                _time.sleep(2)
                consecutive_errors = 0
            else:
                logger.warning("STT stream error ({}), reconnecting...", e.__class__.__name__)
        except Exception as e:
            if "shutdown" in str(e).lower() or "interpreter" in str(e).lower():
                break
            consecutive_errors += 1
            if consecutive_errors > 5:
                logger.warning("STT: too many errors, backing off 2s...")
                _time.sleep(2)
                consecutive_errors = 0
            else:
                logger.warning("STT unexpected error ({}), reconnecting...", e)


if __name__ == "__main__":
    logger.info("Starting audio stream... (Press Ctrl+C to stop)")
    mic_stream = ResumableMicrophoneStream(RATE, CHUNK)
    q: queue.Queue[bytes | None] = queue.Queue()

    import threading

    def _feed() -> None:
        for chunk in mic_stream.generator():
            q.put(chunk)
        q.put(None)

    threading.Thread(target=_feed, daemon=True).start()

    try:
        for event in generate_transcripts(q):
            if event.is_final:
                logger.info("[FINAL] {}", event.text)
            else:
                logger.debug("[interim] {}", event.text)
    except KeyboardInterrupt:
        logger.info("Stopping...")
    finally:
        mic_stream.close()
