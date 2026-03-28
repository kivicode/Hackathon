import asyncio
from contextlib import suppress
from time import monotonic_ns

from hackathon.audio import MicrophoneInput
from hackathon.turn_detector import InterruptEvent, TurnDetector


class InterruptServiceError(RuntimeError):
    """Raised when the live turn-detection service cannot continue."""


class InterruptService:
    """Continuously feeds a passive detector from a shared live microphone."""

    def __init__(
        self,
        microphone_input: MicrophoneInput,
        *,
        silence_ms: int = 700,
        max_wait_ms: int = 10_000,
        vad_mode: int = 2,
        detector: TurnDetector | None = None,
    ) -> None:
        self.microphone_input = microphone_input
        self.detector = detector or TurnDetector(
            sample_rate_hz=microphone_input.sample_rate_hz,
            silence_ms=silence_ms,
            max_wait_ms=max_wait_ms,
            vad_mode=vad_mode,
        )

        if self.detector.sample_rate_hz != microphone_input.sample_rate_hz:
            msg = (
                "TurnDetector sample rate must match the microphone input sample rate, got "
                f"{self.detector.sample_rate_hz} and {microphone_input.sample_rate_hz}"
            )
            raise ValueError(msg)

        self._loop: asyncio.AbstractEventLoop | None = None
        self._feed_task: asyncio.Task[None] | None = None
        self._pending_wait: asyncio.Future[InterruptEvent] | None = None
        self._terminal_error: Exception | None = None

    @property
    def is_started(self) -> bool:
        return self._feed_task is not None and not self._feed_task.done()

    async def start(self) -> None:
        """Start consuming the shared microphone stream."""
        if self.is_started:
            return

        if not self.microphone_input.is_started:
            msg = "MicrophoneInput must be started before InterruptService."
            raise RuntimeError(msg)

        self._loop = asyncio.get_running_loop()
        self._terminal_error = None
        self.detector.reset()
        self._feed_task = asyncio.create_task(self._run(), name="turn-detection-feed")

    async def stop(self) -> None:
        """Cancel any pending wait and stop consuming microphone audio."""
        self.cancel_interrupt()

        feed_task = self._feed_task
        self._feed_task = None
        if feed_task is not None:
            feed_task.cancel()
            with suppress(asyncio.CancelledError):
                await feed_task

        self.detector.reset()
        self._terminal_error = None

    async def wait_for_interrupt_window(self) -> InterruptEvent:
        """Wait until the detector decides an interruption may be spoken."""
        if self._terminal_error is not None:
            raise self._terminal_error
        if not self.is_started or self._loop is None:
            msg = "InterruptService must be started before waiting for an interrupt window."
            raise RuntimeError(msg)

        pending_wait = self._pending_wait
        if pending_wait is None or pending_wait.done():
            pending_wait = self._loop.create_future()
            self._pending_wait = pending_wait

            event = self.detector.request_interrupt(self._monotonic_ms())
            if event is not None:
                self._resolve_pending_wait(event)

        return await asyncio.shield(pending_wait)

    def cancel_interrupt(self) -> None:
        """Cancel the current pending interruption request, if any."""
        self.detector.cancel_interrupt()

        pending_wait = self._pending_wait
        self._pending_wait = None
        if pending_wait is not None and not pending_wait.done():
            pending_wait.cancel()

    async def _run(self) -> None:
        try:
            async for chunk in self.microphone_input.subscribe():
                event = self.detector.feed(chunk)
                if event is not None:
                    self._resolve_pending_wait(event)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._handle_terminal_error(
                InterruptServiceError(
                    f"Turn detection lost its microphone subscription: {exc}",
                ),
            )
            return

        self._handle_terminal_error(
            InterruptServiceError("Turn detection microphone subscription ended unexpectedly."),
        )

    def _resolve_pending_wait(self, event: InterruptEvent) -> None:
        pending_wait = self._pending_wait
        self._pending_wait = None
        if pending_wait is not None and not pending_wait.done():
            pending_wait.set_result(event)

    def _handle_terminal_error(self, error: Exception) -> None:
        self._terminal_error = error
        self.detector.cancel_interrupt()

        pending_wait = self._pending_wait
        self._pending_wait = None
        if pending_wait is not None and not pending_wait.done():
            pending_wait.set_exception(error)

    @staticmethod
    def _monotonic_ms() -> int:
        return monotonic_ns() // 1_000_000
