"""Speech-to-text via Google Cloud Speech API."""

from __future__ import annotations

import queue
from collections.abc import Generator, Iterator

import pyaudio
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


def generate_transcripts(stream_generator: Iterator[bytes]) -> Generator[TranscriptEvent]:
    """Consume Google Speech API responses and yield transcript events (interim + final)."""
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

    requests = (speech.StreamingRecognizeRequest(audio_content=content) for content in stream_generator)
    responses = client.streaming_recognize(streaming_config, requests)

    for response in responses:
        if not response.results:
            continue
        result = response.results[0]
        if not result.alternatives:
            continue
        yield TranscriptEvent(
            text=result.alternatives[0].transcript,
            is_final=result.is_final,
        )


if __name__ == "__main__":
    logger.info("Starting audio stream... (Press Ctrl+C to stop)")
    mic_stream = ResumableMicrophoneStream(RATE, CHUNK)
    try:
        for event in generate_transcripts(mic_stream.generator()):
            if event.is_final:
                logger.info("[FINAL] {}", event.text)
            else:
                logger.debug("[interim] {}", event.text)
    except KeyboardInterrupt:
        logger.info("Stopping...")
    finally:
        mic_stream.close()
