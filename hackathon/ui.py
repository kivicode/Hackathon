"""Terminal UI for the meeting agent pipeline."""

from __future__ import annotations

import asyncio
import time
from datetime import datetime
from pathlib import Path

from loguru import logger
from textual.app import App, ComposeResult
from textual.containers import Container
from textual.widgets import Label, RichLog, Static

from hackathon.agent import MeetingAgent, TranscriptChunk
from hackathon.config import ProjectSettings
from hackathon.rag.light import LightRAGBackend
from hackathon.rag.stuffing import StuffingRAG
from hackathon.stt import ResumableMicrophoneStream, generate_transcripts
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

    def compose(self) -> ComposeResult:
        yield Static(BANNER, id="banner")
        yield RichLog(id="transcript-log", wrap=True, markup=True)
        yield Static("", id="interim")
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

    def show_alert(self, text: str) -> None:
        container = self.query_one("#alert-container")
        label = self.query_one("#alert-box", Label)
        label.update(f"  CORRECTION: {text}")
        container.add_class("visible")
        self.set_timer(10, self._hide_alert)

    def _hide_alert(self) -> None:
        self.query_one("#alert-container").remove_class("visible")

    def set_status(self, text: str) -> None:
        self.query_one("#status", Static).update(text)

    async def _pipeline(self) -> None:
        settings = ProjectSettings()
        loop = asyncio.get_event_loop()

        # -- TTS --
        tts_client = create_client(settings)
        audio_out = open_stream(settings.audio_device, settings.sample_rate)

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

        # -- STT thread → queue --
        transcript_queue: asyncio.Queue[TranscriptChunk | None] = asyncio.Queue()

        def _put(chunk: TranscriptChunk | None) -> None:
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
                        _put(chunk)
                        self.call_from_thread(self.add_final, event.text.strip())
                    else:
                        self.call_from_thread(self.show_interim, event.text.strip())
            except KeyboardInterrupt:
                pass
            finally:
                mic.close()
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
                    correction = await agent.process_chunk(chunk)
                except Exception:
                    logger.exception("Agent error")
                    self.set_status("Listening...")
                    continue
                if correction:
                    self.show_alert(correction)
                    self.set_status("Speaking correction...")
                    try:
                        async for audio_chunk in text_to_speech_stream(tts_client, correction, settings):
                            write_chunk(audio_out, audio_chunk)
                    except Exception:
                        logger.exception("TTS error")
                self.set_status("Listening...")
        finally:
            audio_out.stop()
            audio_out.close()


if __name__ == "__main__":
    MeetingUI().run()
