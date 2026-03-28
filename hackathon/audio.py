import asyncio
from collections import deque
from collections.abc import AsyncIterator
from dataclasses import dataclass
from time import monotonic_ns
from typing import Any

import sounddevice

FRAME_MS = 20
BYTES_PER_SAMPLE = 2
CHANNELS = 1
SUPPORTED_SAMPLE_RATES = frozenset({8000, 16000, 32000, 48000})


@dataclass(frozen=True)
class AudioChunk:
    """Decoded audio emitted by a live input source.

    Attributes:
        pcm_s16le: Contiguous mono 16-bit little-endian PCM bytes.
        timestamp_ms: Monotonic start timestamp for this chunk in milliseconds.
    """

    pcm_s16le: bytes
    timestamp_ms: int


class MicrophoneInputError(RuntimeError):
    """Raised when microphone capture cannot continue."""


class MicrophoneSubscriberOverflowError(MicrophoneInputError):
    """Raised when a live subscriber falls behind the shared microphone stream."""


class MicrophoneInputStoppedError(MicrophoneInputError):
    """Raised when the microphone input stops while a subscriber is consuming it."""


class _Subscriber:
    def __init__(self, loop: asyncio.AbstractEventLoop, max_chunks: int) -> None:
        self._loop = loop
        self._max_chunks = max_chunks
        self._buffer: deque[AudioChunk] = deque()
        self._waiter: asyncio.Future[None] | None = None
        self._closed_error: Exception | None = None

    @property
    def is_closed(self) -> bool:
        return self._closed_error is not None

    def publish(self, chunk: AudioChunk) -> None:
        if self.is_closed:
            return

        if len(self._buffer) >= self._max_chunks:
            self.close(
                MicrophoneSubscriberOverflowError(
                    "A microphone subscriber fell behind the live stream and was closed.",
                ),
            )
            return

        self._buffer.append(chunk)
        self._wake_waiter()

    def close(self, error: Exception) -> None:
        if self.is_closed:
            return

        self._closed_error = error
        self._wake_waiter()

    async def get(self) -> AudioChunk:
        while True:
            if self._buffer:
                return self._buffer.popleft()

            if self._closed_error is not None:
                raise self._closed_error

            if self._waiter is None:
                self._waiter = self._loop.create_future()

            waiter = self._waiter
            try:
                await waiter
            finally:
                if self._waiter is waiter and waiter.done():
                    self._waiter = None

    def _wake_waiter(self) -> None:
        if self._waiter is None or self._waiter.done():
            return

        self._waiter.set_result(None)


class MicrophoneInput:
    """Shared live microphone input with low-latency fan-out subscriptions."""

    def __init__(
        self,
        *,
        sample_rate_hz: int = 16000,
        chunk_ms: int = FRAME_MS,
        queue_size: int = 5,
        device: str | int | None = None,
    ) -> None:
        if sample_rate_hz not in SUPPORTED_SAMPLE_RATES:
            msg = (
                "sample_rate_hz must be one of "
                f"{sorted(SUPPORTED_SAMPLE_RATES)}, got {sample_rate_hz}"
            )
            raise ValueError(msg)
        if chunk_ms != FRAME_MS:
            msg = f"chunk_ms must be fixed at {FRAME_MS}, got {chunk_ms}"
            raise ValueError(msg)
        if queue_size <= 0:
            msg = f"queue_size must be positive, got {queue_size}"
            raise ValueError(msg)

        self.sample_rate_hz = sample_rate_hz
        self.chunk_ms = chunk_ms
        self.queue_size = queue_size
        self.device = self._normalize_device(device)

        self.frame_samples = sample_rate_hz * chunk_ms // 1000

        self._loop: asyncio.AbstractEventLoop | None = None
        self._stream: Any | None = None
        self._callback_abort: type[Exception] | None = None
        self._shutdown_task: asyncio.Task[None] | None = None
        self._subscribers: set[_Subscriber] = set()

        self._started = False
        self._stream_epoch_ms: int | None = None
        self._emitted_samples = 0

    @property
    def is_started(self) -> bool:
        return self._started

    async def start(self) -> None:
        """Open the configured microphone and begin publishing live chunks."""
        if self._started:
            return

        if self._shutdown_task is not None:
            await self._shutdown_task
            self._shutdown_task = None

        self._loop = asyncio.get_running_loop()
        self._stream_epoch_ms = None
        self._emitted_samples = 0
        self._started = True

        try:
            await asyncio.to_thread(self._open_stream)
        except Exception:
            self._started = False
            self._loop = None
            raise

    async def stop(self) -> None:
        """Close the microphone stream and terminate all live subscribers."""
        if self._shutdown_task is None:
            if not self._started and self._stream is None:
                return

            self._shutdown_task = asyncio.create_task(
                self._shutdown(MicrophoneInputStoppedError("Microphone input stopped.")),
            )

        await self._shutdown_task
        self._shutdown_task = None

    def subscribe(self) -> AsyncIterator[AudioChunk]:
        """Create a live-only chunk subscription.

        Subscribers only receive future chunks after this method is called.
        """
        if not self._started or self._loop is None:
            msg = "MicrophoneInput must be started before subscribing."
            raise RuntimeError(msg)

        subscriber = _Subscriber(loop=self._loop, max_chunks=self.queue_size)
        self._subscribers.add(subscriber)
        return self._subscriber_stream(subscriber)

    async def _subscriber_stream(self, subscriber: _Subscriber) -> AsyncIterator[AudioChunk]:
        try:
            while True:
                yield await subscriber.get()
        finally:
            subscriber.close(MicrophoneInputStoppedError("Microphone subscription closed."))
            self._subscribers.discard(subscriber)

    def _open_stream(self) -> None:
        self._callback_abort = sounddevice.CallbackAbort

        try:
            self._stream = sounddevice.RawInputStream(
                samplerate=self.sample_rate_hz,
                blocksize=self.frame_samples,
                device=self.device,
                dtype="int16",
                channels=CHANNELS,
                callback=self._audio_callback,
                latency="low",
            )
            self._stream.start()
        except Exception as exc:
            self._stream = None
            msg = "Unable to open the configured microphone input."
            raise MicrophoneInputError(msg) from exc

    async def _shutdown(self, reason: Exception) -> None:
        self._started = False

        subscribers = tuple(self._subscribers)
        self._subscribers.clear()
        for subscriber in subscribers:
            subscriber.close(reason)

        stream = self._stream
        self._stream = None
        self._stream_epoch_ms = None
        self._emitted_samples = 0
        self._loop = None

        if stream is not None:
            await asyncio.to_thread(self._stop_and_close_stream, stream)

    def _audio_callback(self, indata: Any, frames: int, time_info: Any, status: Any) -> None:
        del time_info

        if not self._started or self._loop is None:
            return

        if status:
            error = MicrophoneInputError(f"Microphone input reported callback status: {status}")
            self._loop.call_soon_threadsafe(self._schedule_shutdown, error)
            if self._callback_abort is not None:
                raise self._callback_abort
            return

        try:
            chunk_duration_ms = self._samples_to_ms(frames)
            if self._stream_epoch_ms is None:
                self._stream_epoch_ms = monotonic_ns() // 1_000_000 - chunk_duration_ms

            timestamp_ms = self._stream_epoch_ms + self._samples_to_ms(self._emitted_samples)
            self._emitted_samples += frames
            chunk = AudioChunk(pcm_s16le=bytes(indata), timestamp_ms=timestamp_ms)
        except Exception as exc:
            error = MicrophoneInputError("Microphone callback failed to decode an audio chunk.")
            self._loop.call_soon_threadsafe(self._schedule_shutdown, error)
            if self._callback_abort is not None:
                raise self._callback_abort from exc
            raise

        self._loop.call_soon_threadsafe(self._publish_chunk, chunk)

    def _publish_chunk(self, chunk: AudioChunk) -> None:
        if not self._started:
            return

        for subscriber in tuple(self._subscribers):
            subscriber.publish(chunk)
            if subscriber.is_closed:
                self._subscribers.discard(subscriber)

    def _schedule_shutdown(self, reason: Exception) -> None:
        if self._shutdown_task is not None or self._loop is None:
            return

        self._shutdown_task = self._loop.create_task(self._shutdown(reason))

    @staticmethod
    def _stop_and_close_stream(stream: Any) -> None:
        try:
            stream.stop()
        except sounddevice.PortAudioError:
            if getattr(stream, "closed", False):
                return
        finally:
            stream.close()

    @staticmethod
    def _normalize_device(device: str | int | None) -> str | int | None:
        if not isinstance(device, str):
            return device

        stripped_device = device.strip()
        if not stripped_device:
            return None
        if stripped_device.isdigit():
            return int(stripped_device)
        return stripped_device

    def _samples_to_ms(self, sample_count: int) -> int:
        return sample_count * 1000 // self.sample_rate_hz
