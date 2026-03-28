"""Main agent: monitors meeting transcript, flags contradictions using company knowledge."""

from __future__ import annotations

import json
import time
from collections import deque
from typing import TYPE_CHECKING

from google import genai
from google.genai import types
from loguru import logger
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from hackathon.config import ProjectSettings
    from hackathon.rag.base import RAGBackend


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class TranscriptChunk(BaseModel):
    speaker: str
    text: str
    timestamp: float = 0.0


class AgentResponse(BaseModel):
    should_intervene: bool
    correction: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    source_key: str = ""


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------

SOURCES: dict[str, dict[str, str]] = {
    "financial_report": {
        "alias": "Financial Report",
        "url": "https://docs.google.com/spreadsheets/d/1Nz0KaovwH2uJRO0rbYFXRF82bNMI0jdwseNZtAWTqeA/edit?gid=146781967#gid=146781967",
    },
    "jira": {
        "alias": "Jira Board",
        "url": "",
    },
    "slack": {
        "alias": "Slack",
        "url": "",
    },
}


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are a silent meeting assistant with access to internal company data. \
You passively listen to the conversation and ONLY speak up when someone \
makes a DEFINITIVE FACTUAL STATEMENT that contradicts the company's records.

Your knowledge base (Jira, Slack, financial reports):
{knowledge_base}

Available source keys for referencing: {source_keys}

CRITICAL rules:
- NEVER intervene on questions. "Is it ready?" is a question — do NOT respond.
- ONLY intervene when someone ASSERTS a fact that is wrong. E.g. "Yes, we finished it" when records show it's not done.
- Also flag when someone proposes an action based on incomplete data \
  (e.g. "we should cut them" when the financials show the trend is improving).
- Do NOT intervene if the knowledge base has no relevant information.
- Be brief: 1-2 sentences max. Cite the source (Jira, Slack, financial report).
- Start with: "Small correction:", "Worth noting:", or "Caution:"
- Set source_key to the most relevant source key from the list above (e.g. "financial_report").
- NEVER repeat a correction you already made, even if the speaker repeats the claim or a different \
  speaker agrees with it. Once corrected, the topic is DONE.

Respond with JSON: should_intervene (bool), correction (string), confidence (0.0-1.0), source_key (string).
If no intervention needed, return {{"should_intervene": false}}."""


# ---------------------------------------------------------------------------
# MeetingAgent — uses async chat to keep session alive
# ---------------------------------------------------------------------------


class MeetingAgent:
    def __init__(
        self,
        settings: ProjectSettings,
        knowledge_base: str = "",
        rag: RAGBackend | None = None,
    ) -> None:
        self.client = genai.Client(api_key=settings.gemini_api_key)
        self.model = settings.gemini_model
        self.transcript: deque[TranscriptChunk] = deque(maxlen=settings.buffer_size)
        self.confidence_threshold = settings.confidence_threshold
        self._system = SYSTEM_PROMPT.format(
            knowledge_base=knowledge_base,
            source_keys=", ".join(SOURCES.keys()),
        )
        self._rag = rag
        self._chat = None

    async def connect(self) -> None:
        """Create a persistent chat session with the system prompt baked in."""
        self._chat = self.client.aio.chats.create(
            model=self.model,
            config=types.GenerateContentConfig(
                system_instruction=self._system,
                response_mime_type="application/json",
                response_schema=AgentResponse,
                temperature=0.1,
            ),
        )
        logger.debug("Chat session created")

    async def close(self) -> None:
        """Release the chat session."""
        self._chat = None

    async def process_chunk(self, chunk: TranscriptChunk) -> AgentResponse | None:
        """Process a transcript chunk via the persistent chat session."""
        self.transcript.append(chunk)

        if len(chunk.text.strip()) < 10:
            return None

        if self._chat is None:
            await self.connect()

        prompt = f"[{chunk.speaker}]: {chunk.text}"

        logger.debug("Sending: {}", prompt[:80])
        t0 = time.monotonic()

        try:
            response = await self._chat.send_message(prompt)
        except Exception:
            logger.warning("Chat error, recreating session...")
            await self.connect()
            try:
                response = await self._chat.send_message(prompt)
            except Exception:
                logger.exception("Chat retry failed")
                return None

        elapsed = time.monotonic() - t0
        logger.debug("Response in {:.1f}s: {}", elapsed, response.text)

        try:
            result = AgentResponse(**json.loads(response.text))
        except (json.JSONDecodeError, TypeError):
            logger.warning("Failed to parse: {}", response.text)
            return None

        logger.info(
            "intervene={} confidence={:.2f} ({:.1f}s) | {}",
            result.should_intervene,
            result.confidence,
            elapsed,
            chunk.text[:60],
        )

        if result.should_intervene and result.confidence >= self.confidence_threshold:
            return result

        return None

    def _build_context(self) -> str:
        return "\n".join(f"{c.speaker}: {c.text}" for c in self.transcript)


# ---------------------------------------------------------------------------
# Standalone test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import asyncio
    from pathlib import Path

    from hackathon.config import ProjectSettings

    DEMO_TRANSCRIPT = [
        (
            "CEO",
            "We've got a lead, XYZ Corp. They're interested in Feature X. "
            "I'm meeting them tomorrow, is it ready?",
        ),
        ("CTO", "Yes, we finished it this week."),
        (
            "CTO",
            "Another point: the Poland team running XYZ service brings in about 3 million a year, "
            "but infra costs are 3.5 million. I think we should cut them.",
        ),
        ("CFO", "That seems reasonable."),
    ]

    async def main() -> None:
        settings = ProjectSettings()
        data_dir = Path(settings.rag_data_dir)
        knowledge = "\n\n".join(f"=== {p.name} ===\n{p.read_text()}" for p in sorted(data_dir.glob("*.md")))
        agent = MeetingAgent(settings=settings, knowledge_base=knowledge)
        await agent.connect()
        logger.info("Knowledge base: {} chars", len(knowledge))

        for speaker, text in DEMO_TRANSCRIPT:
            logger.info("{}: {}", speaker, text)
            result = await agent.process_chunk(
                TranscriptChunk(speaker=speaker, text=text),
            )
            if result:
                logger.success("AGENT: {}", result.correction)
                if result.source_key:
                    src = SOURCES.get(result.source_key, {})
                    logger.info("Source: {} ({})", src.get("alias", result.source_key), src.get("url", ""))
            else:
                logger.debug("(no intervention)")

    asyncio.run(main())
