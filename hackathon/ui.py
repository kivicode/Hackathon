"""Terminal UI for the meeting agent pipeline."""

from __future__ import annotations

import asyncio
import logging
import queue
import time
from datetime import datetime
from pathlib import Path

# Silence noisy gRPC/protobuf loggers
logging.getLogger("grpc").setLevel(logging.ERROR)
logging.getLogger("google").setLevel(logging.WARNING)

from loguru import logger
from textual.app import App, ComposeResult
from textual.containers import Container
from textual.widgets import Label, RichLog, Static

from hackathon.agent import SOURCES, MeetingAgent, TranscriptChunk
from hackathon.audio import MicrophoneInput
from hackathon.config import ProjectSettings
from hackathon.interrupt_service import InterruptService
from hackathon.turn_detector import TurnDetector
from hackathon.rag.light import LightRAGBackend
from hackathon.rag.stuffing import StuffingRAG
from hackathon.stt import generate_transcripts
from hackathon.voiceover.audio import open_stream, write_chunk
from hackathon.voiceover.tts import create_client, text_to_speech_stream

BANNER = r"""
  __ _  ___ ___| |_   ___| |__   ___  ___| | __
 / _` |/ _ | __| __| / __| '_ \ / _ \/ __| |/ /
| |_| |  __| |_| |_ | (__| | | |  __| (__|   <
 \__,_|\___|\__|\__| \___|_| |_|\___|\___|_|\_\
"""

APP_CSS = """
Screen {
    background: $surface;
}

#banner {
    height: 6;
    content-align: center middle;
    color: $text-muted;
    text-style: bold;
}

#transcript-log {
    height: 1fr;
    border: solid $primary;
    padding: 0 1;
}

#interim {
    height: 1;
    color: $text-muted;
    padding: 0 2;
}

#turn-indicator {
    height: 1;
    padding: 0 2;
}

#alert-container {
    display: none;
    layer: overlay;
    align: center middle;
    width: 100%;
    height: 100%;
}

#alert-container.visible {
    display: block;
}

#alert-box {
    background: yellow;
    color: black;
    text-style: bold;
    padding: 2 4;
    text-align: center;
    width: 70%;
    max-width: 90;
    border: thick black;
}

#status {
    height: 1;
    dock: bottom;
    background: $primary;
    color: $text;
    padding: 0 1;
}
"""


class MeetingUI(App):
    CSS = APP_CSS
    BINDINGS = [("space", "open_source", "Open source")]

    _pending_source_url: str = ""

    def compose(self) -> ComposeResult:
        yield Static(BANNER, id="banner")
        yield RichLog(id="transcript-log", wrap=True, markup=True)
        yield Static("", id="interim")
        yield Static("", id="turn-indicator")
        with Container(id="alert-container"):
            yield Label("", id="alert-box")
        yield Static("Initializing...", id="status")

    def on_mount(self) -> None:
        self.run_worker(self._pipeline(), exclusive=True)

    def show_interim(self, text: str) -> None:
        self.query_one("#interim", Static).update(f"[dim]... {text}[/dim]")

    def add_final(self, text: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")  # noqa: DTZ005
        self.query_one("#interim", Static).update("")
        self.query_one("#transcript-log", RichLog).write(f"[dim]{ts}[/dim]  {text}")

    def show_alert(self, text: str, source_key: str = "") -> None:
        container = self.query_one("#alert-container")
        label = self.query_one("#alert-box", Label)

        source = SOURCES.get(source_key, {})
        url = source.get("url", "")
        alias = source.get("alias", "")

        msg = f"  CORRECTION: {text}"
        if url and alias:
            msg += f"\n\n  Press SPACE to open the {alias}"
            self._pending_source_url = url
        else:
            self._pending_source_url = ""

        label.update(msg)
        container.add_class("visible")
        self.set_timer(15, self._hide_alert)

    def _hide_alert(self) -> None:
        self.query_one("#alert-container").remove_class("visible")
        self._pending_source_url = ""

    def action_open_source(self) -> None:
        if self._pending_source_url:
            import webbrowser
            webbrowser.open(self._pending_source_url)

    def set_turn_indicator(self, state: str) -> None:
        indicator = self.query_one("#turn-indicator", Static)
        if state == "waiting":
            indicator.update("[bold orange3]>> Correction ready — waiting for pause to speak...[/bold orange3]")
        elif state == "speaking":
            indicator.update("[bold green]>> Speaking correction[/bold green]")
        elif state == "speech":
            indicator.update("[bold red]  SPEECH DETECTED[/bold red]")
        elif state == "silence":
            indicator.update("[dim]  silence — agent can interject[/dim]")
        else:
            indicator.update("")

    def set_status(self, text: str) -> None:
        self.query_one("#status", Static).update(text)

    async def _pipeline(self) -> None:  # noqa: PLR0915
        settings = ProjectSettings()
        loop = asyncio.get_event_loop()

        # -- TTS --
        tts_client = create_client(settings)
        audio_out = await asyncio.to_thread(open_stream, settings.audio_device, settings.sample_rate)

        # -- Shared mic (single source for both STT and turn detector) --
        mic_input = MicrophoneInput(sample_rate_hz=16000)
        await mic_input.start()

        interrupt_svc = InterruptService(mic_input)
        await interrupt_svc.start()

        # -- Bridge: async MicrophoneInput subscriber → sync queue for STT --
        audio_queue: queue.Queue[bytes | None] = queue.Queue()

        async def _mic_to_stt_bridge() -> None:
            """Forward mic audio chunks to the sync STT queue."""
            async for chunk in mic_input.subscribe():
                audio_queue.put_nowait(chunk.pcm_s16le)
            audio_queue.put_nowait(None)

        bridge_task = asyncio.create_task(_mic_to_stt_bridge())

        # -- VAD indicator: uses TurnDetector to show speech/silence --
        vad_detector = TurnDetector(sample_rate_hz=mic_input.sample_rate_hz)
        _vad_frame_count = 0

        async def _vad_monitor() -> None:
            nonlocal _vad_frame_count
            last_state = ""
            async for chunk in mic_input.subscribe():
                _vad_frame_count += 1
                # Only run VAD every 5th frame (~100ms) to reduce CPU load
                if _vad_frame_count % 5 != 0:
                    continue
                await asyncio.to_thread(vad_detector.feed, chunk)
                state = "speech" if vad_detector._last_frame_was_speech else "silence"
                if state != last_state:
                    last_state = state
                    self.set_turn_indicator(state)

        vad_task = asyncio.create_task(_vad_monitor())

        def _audio_generator():
            """Sync generator that reads from the audio queue."""
            while True:
                data = audio_queue.get()
                if data is None:
                    return
                yield data

        # -- Agent + RAG --
        knowledge = ""
        rag = None
        if settings.use_rag:
            if settings.rag_mode == "stuffing":
                rag_backend = StuffingRAG(api_key=settings.gemini_api_key, model=settings.gemini_model)
                data_dir = Path(settings.rag_data_dir)
                docs = {p.name: p.read_text() for p in sorted(data_dir.glob("*.md"))}
                await rag_backend.insert(docs)
                knowledge = "\n\n---\n\n".join(f"# {k}\n{v}" for k, v in docs.items())
            elif settings.rag_mode == "light":
                rag_backend = LightRAGBackend(api_key=settings.gemini_api_key, working_dir=settings.rag_working_dir)
                data_dir = Path(settings.rag_data_dir)
                docs = {p.name: p.read_text() for p in sorted(data_dir.glob("*.md"))}
                await rag_backend.insert(docs)
                rag = rag_backend

        agent = MeetingAgent(settings=settings, knowledge_base=knowledge, rag=rag)
        self.set_status("Listening...")

        # -- STT in background thread (reads from shared mic via bridge) --
        transcript_queue: asyncio.Queue[TranscriptChunk | None] = asyncio.Queue()

        def _put(chunk: TranscriptChunk | None) -> None:
            loop.call_soon_threadsafe(transcript_queue.put_nowait, chunk)

        def _stt_worker() -> None:
            try:
                for event in generate_transcripts(_audio_generator(), audio_queue=audio_queue):
                    if event.is_final:
                        chunk = TranscriptChunk(
                            speaker="Speaker",
                            text=event.text,
                            timestamp=time.time(),
                        )
                        _put(chunk)
                        self.call_from_thread(self.add_final, event.text.strip())
                    else:
                        self.call_from_thread(self.show_interim, event.text.strip())
            except Exception:
                logger.exception("STT worker error")
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
                self.set_status("Analyzing...")
                try:
                    result = await agent.process_chunk(chunk)
                except Exception:
                    logger.exception("Agent error")
                    self.set_status("Listening...")
                    continue
                if result:
                    if settings.eager_alert:
                        self.show_alert(result.correction, result.source_key)

                    self.set_status("Generating speech...")
                    try:
                        first_chunk = True
                        async for audio_chunk in text_to_speech_stream(tts_client, result.correction, settings):
                            if first_chunk:
                                first_chunk = False
                                if not settings.eager_alert:
                                    self.show_alert(result.correction, result.source_key)
                                self.set_turn_indicator("waiting")
                                self.set_status("Waiting for pause...")
                                try:
                                    await interrupt_svc.wait_for_interrupt_window()
                                except Exception:
                                    logger.warning("Turn detector error, speaking immediately")
                                self.set_turn_indicator("speaking")
                                self.set_status("Speaking correction...")
                            await asyncio.to_thread(write_chunk, audio_out, audio_chunk)
                    except Exception:
                        logger.exception("TTS error")
                    self.set_turn_indicator("")
                self.set_status("Listening...")
        finally:
            vad_task.cancel()
            bridge_task.cancel()
            await interrupt_svc.stop()
            await mic_input.stop()
            await asyncio.to_thread(audio_out.stop)
            await asyncio.to_thread(audio_out.close)


if __name__ == "__main__":
    MeetingUI().run()
