from dataclasses import dataclass

import webrtcvad

_FRAME_MS = 20
_BYTES_PER_SAMPLE = 2
_SUPPORTED_SAMPLE_RATES = frozenset({8000, 16000, 32000, 48000})


@dataclass(frozen=True)
class AudioChunk:
    """Decoded audio passed into the turn detector.

    Attributes:
        pcm_s16le: Contiguous mono 16-bit little-endian PCM bytes.
        timestamp_ms: Monotonic start timestamp for this chunk in milliseconds.

    Notes:
        Chunks are expected to be contiguous in time. If a chunk does not align
        to the detector's internal 20 ms frame size, later chunks are assumed
        to continue immediately after the buffered remainder.
    """

    pcm_s16le: bytes
    timestamp_ms: int


@dataclass(frozen=True)
class InterruptEvent:
    """Signal that a pending interruption may be spoken now.

    Attributes:
        timestamp_ms: When the detector decided the interrupt window opened.
        silence_duration_ms: Informational silence observed when the event was
            emitted. This may be 0 for a forced max-wait timeout during speech.
    """

    timestamp_ms: int
    silence_duration_ms: int


class TurnDetector:
    """Passive PCM turn detector built on top of WebRTC VAD.

    The detector does not run its own clock or background task. It only
    advances when ``feed()`` is called with new audio or an explicit empty
    chunk used as a timing tick.

    Expected input:
        - mono 16-bit little-endian PCM
        - sample rate supported by WebRTC VAD
        - chunks that are monotonic and contiguous in time

    Behavior:
        - ``request_interrupt()`` starts a pending interrupt window
        - repeated ``request_interrupt()`` calls are ignored while a request is
          already pending
        - ``feed()`` evaluates both silence-based firing and ``max_wait_ms``
    """

    def __init__(
        self,
        sample_rate_hz: int = 16000,
        silence_ms: int = 700,
        max_wait_ms: int = 10_000,
        vad_mode: int = 2,
    ) -> None:
        if sample_rate_hz not in _SUPPORTED_SAMPLE_RATES:
            msg = (
                "sample_rate_hz must be one of "
                f"{sorted(_SUPPORTED_SAMPLE_RATES)}, got {sample_rate_hz}"
            )
            raise ValueError(msg)
        if silence_ms <= 0:
            msg = f"silence_ms must be positive, got {silence_ms}"
            raise ValueError(msg)
        if max_wait_ms <= 0:
            msg = f"max_wait_ms must be positive, got {max_wait_ms}"
            raise ValueError(msg)
        if not 0 <= vad_mode <= 3:
            msg = f"vad_mode must be between 0 and 3 inclusive, got {vad_mode}"
            raise ValueError(msg)

        self.sample_rate_hz = sample_rate_hz
        self.silence_ms = silence_ms
        self.max_wait_ms = max_wait_ms
        self.vad_mode = vad_mode

        self._vad = webrtcvad.Vad(vad_mode)
        self._frame_bytes = self._samples_to_bytes(sample_rate_hz * _FRAME_MS // 1000)
        self.reset()

    def feed(self, chunk: AudioChunk) -> InterruptEvent | None:
        """Consume PCM audio and emit at most one interrupt event.

        The detector evaluates timeouts only while ``feed()`` is being called.
        In normal operation, upstream should keep feeding audio chunks,
        including silence. If audio delivery stalls entirely but the caller
        still wants ``max_wait_ms`` to advance, it may call ``feed()`` with an
        empty ``pcm_s16le`` payload and an updated timestamp.
        """
        if len(chunk.pcm_s16le) % _BYTES_PER_SAMPLE != 0:
            msg = "pcm_s16le must contain whole 16-bit samples"
            raise ValueError(msg)

        emitted_event = None
        if not chunk.pcm_s16le:
            return self._emit_timeout_if_due(chunk.timestamp_ms)

        self._append_chunk(chunk)
        for frame_pcm, frame_timestamp_ms in self._consume_frames():
            if emitted_event is None:
                emitted_event = self._emit_timeout_if_due(frame_timestamp_ms)

            frame_event = self._process_frame(frame_pcm, frame_timestamp_ms)
            if emitted_event is None and frame_event is not None:
                emitted_event = frame_event

        return emitted_event

    def request_interrupt(self, timestamp_ms: int) -> InterruptEvent | None:
        """Start an interrupt request if none is already pending.

        This method is idempotent while a request is pending: repeated calls are
        ignored and do not reset the original deadline.
        """
        if self._request_timestamp_ms is not None:
            return None

        self._request_timestamp_ms = timestamp_ms
        self._request_deadline_ms = timestamp_ms + self.max_wait_ms

        if self._is_interruptible_at_request_time(timestamp_ms):
            return self._emit_interrupt(timestamp_ms)

        return None

    def cancel_interrupt(self) -> None:
        """Clear the pending interrupt request without resetting speech state."""
        self._clear_request()

    def reset(self) -> None:
        """Clear buffered audio, request state, and speech tracking."""
        self._pending_pcm = bytearray()
        self._pending_start_ms: int | None = None

        self._consecutive_silence_ms = 0
        self._silence_start_ms: int | None = None
        self._last_frame_was_speech = False

        self._request_timestamp_ms: int | None = None
        self._request_deadline_ms: int | None = None

    def _append_chunk(self, chunk: AudioChunk) -> None:
        if not self._pending_pcm:
            self._pending_start_ms = chunk.timestamp_ms

        self._pending_pcm.extend(chunk.pcm_s16le)

    def _consume_frames(self) -> list[tuple[bytes, int]]:
        if self._pending_start_ms is None:
            return []

        frames: list[tuple[bytes, int]] = []
        frame_timestamp_ms = self._pending_start_ms
        while len(self._pending_pcm) >= self._frame_bytes:
            frame_pcm = bytes(self._pending_pcm[: self._frame_bytes])
            del self._pending_pcm[: self._frame_bytes]
            frames.append((frame_pcm, frame_timestamp_ms))
            frame_timestamp_ms += _FRAME_MS

        self._pending_start_ms = frame_timestamp_ms if self._pending_pcm else None
        return frames

    def _process_frame(self, frame_pcm: bytes, frame_timestamp_ms: int) -> InterruptEvent | None:
        if self._vad.is_speech(frame_pcm, self.sample_rate_hz):
            self._handle_speech_frame()
            return None

        return self._handle_silence_frame(frame_timestamp_ms)

    def _handle_speech_frame(self) -> None:
        self._last_frame_was_speech = True
        self._consecutive_silence_ms = 0
        self._silence_start_ms = None

    def _handle_silence_frame(self, frame_timestamp_ms: int) -> InterruptEvent | None:
        if self._last_frame_was_speech or self._silence_start_ms is None:
            self._silence_start_ms = frame_timestamp_ms
            self._consecutive_silence_ms = 0

        self._last_frame_was_speech = False
        self._consecutive_silence_ms += _FRAME_MS

        if (event_timestamp_ms := self._interrupt_timestamp_for_current_silence()) is None:
            return None

        return self._emit_interrupt(event_timestamp_ms)

    def _interrupt_timestamp_for_current_silence(self) -> int | None:
        if self._request_timestamp_ms is None or self._silence_start_ms is None:
            return None

        effective_silence_start_ms = max(self._request_timestamp_ms, self._silence_start_ms)
        current_silence_end_ms = self._silence_start_ms + self._consecutive_silence_ms
        if current_silence_end_ms - effective_silence_start_ms < self.silence_ms:
            return None

        return effective_silence_start_ms + self.silence_ms

    def _is_interruptible_at_request_time(self, request_timestamp_ms: int) -> bool:
        if self._silence_start_ms is None or self._consecutive_silence_ms < self.silence_ms:
            return False

        current_silence_end_ms = self._silence_start_ms + self._consecutive_silence_ms
        if request_timestamp_ms > current_silence_end_ms:
            return False

        return request_timestamp_ms - self._silence_start_ms >= self.silence_ms

    def _emit_timeout_if_due(self, observed_timestamp_ms: int) -> InterruptEvent | None:
        if self._request_deadline_ms is None or observed_timestamp_ms < self._request_deadline_ms:
            return None

        return self._emit_interrupt(self._request_deadline_ms)

    def _emit_interrupt(self, timestamp_ms: int) -> InterruptEvent:
        event = InterruptEvent(
            timestamp_ms=timestamp_ms,
            silence_duration_ms=self._consecutive_silence_ms,
        )
        self._clear_request()
        return event

    def _clear_request(self) -> None:
        self._request_timestamp_ms = None
        self._request_deadline_ms = None

    @staticmethod
    def _samples_to_bytes(sample_count: int) -> int:
        return sample_count * _BYTES_PER_SAMPLE
