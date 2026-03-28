"""Main agent: monitors meeting transcript, flags contradictions using company knowledge."""

from __future__ import annotations

import json
import logging
import time
from collections import deque
from typing import TYPE_CHECKING

from google import genai
from google.genai import types
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from hackathon.config import ProjectSettings

logger = logging.getLogger(__name__)


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


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are a silent meeting assistant with access to internal company data. \
You passively listen to the conversation and ONLY speak up when someone \
makes a DEFINITIVE FACTUAL STATEMENT that contradicts the company's records.

Your knowledge base (Jira, Slack, financial reports):
{knowledge_base}

CRITICAL rules:
- NEVER intervene on questions. "Is it ready?" is a question — do NOT respond.
- ONLY intervene when someone ASSERTS a fact that is wrong. E.g. "Yes, we finished it" when records show it's not done.
- Also flag when someone proposes an action based on incomplete data
  (e.g. "we should cut them" when the financials show the trend is improving).
- Do NOT intervene if the knowledge base has no relevant information.
- Be brief: 1-2 sentences max. Cite the source (Jira, Slack, financial report).
- Start with: "Small correction:", "Worth noting:", or "Caution:"

Respond with JSON: should_intervene (bool), correction (string), confidence (0.0-1.0).
If no intervention needed, return should_intervene=false with empty correction."""

CHUNK_PROMPT = """\
Meeting transcript so far:
{context}

Corrections you have already made (do NOT repeat these):
{past_corrections}

Latest statement ({speaker}): {text}

Should you intervene? Return JSON."""


# ---------------------------------------------------------------------------
# MeetingAgent
# ---------------------------------------------------------------------------


class MeetingAgent:
    def __init__(self, settings: ProjectSettings, knowledge_base: str) -> None:
        self.client = genai.Client(api_key=settings.gemini_api_key)
        self.model = settings.gemini_model
        self.transcript: deque[TranscriptChunk] = deque(maxlen=settings.buffer_size)
        self.confidence_threshold = settings.confidence_threshold
        self._system = SYSTEM_PROMPT.format(knowledge_base=knowledge_base)
        self._past_corrections: list[str] = []

    async def process_chunk(self, chunk: TranscriptChunk) -> str | None:
        """Process a transcript chunk. Returns correction text if intervention needed."""
        self.transcript.append(chunk)

        past = "\n".join(f"- {c}" for c in self._past_corrections) if self._past_corrections else "(none)"
        prompt = CHUNK_PROMPT.format(
            context=self._build_context(),
            past_corrections=past,
            speaker=chunk.speaker,
            text=chunk.text,
        )

        logger.info("Sending chunk to agent: speaker=%s text='%s'", chunk.speaker, chunk.text[:80])
        t0 = time.monotonic()

        response = await self.client.aio.models.generate_content(
            model=self.model,
            contents=[
                types.Content(role="user", parts=[types.Part(text=self._system)]),
                types.Content(role="user", parts=[types.Part(text=prompt)]),
            ],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=AgentResponse,
                temperature=0.1,
            ),
        )

        elapsed = time.monotonic() - t0
        logger.info("Agent response in %.1fs: %s", elapsed, response.text)

        try:
            result = AgentResponse(**json.loads(response.text))
        except (json.JSONDecodeError, TypeError):
            logger.warning("Failed to parse agent response: %s", response.text)
            return None

        logger.info(
            "Decision: intervene=%s confidence=%.2f threshold=%.2f",
            result.should_intervene,
            result.confidence,
            self.confidence_threshold,
        )

        if result.should_intervene and result.confidence >= self.confidence_threshold:
            self._past_corrections.append(result.correction)
            return result.correction

        return None

    def _build_context(self) -> str:
        return "\n".join(f"{c.speaker}: {c.text}" for c in self.transcript)


# ---------------------------------------------------------------------------
# Standalone test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import asyncio

    from hackathon.config import ProjectSettings
    from hackathon.rag import load_knowledge_base

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

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
        knowledge = load_knowledge_base()
        agent = MeetingAgent(settings=settings, knowledge_base=knowledge)
        print(f"Knowledge base: {len(knowledge)} chars\n")  # noqa: T201

        for speaker, text in DEMO_TRANSCRIPT:
            print(f"\n{'=' * 60}")  # noqa: T201
            print(f"{speaker}: {text}")  # noqa: T201
            print(f"{'=' * 60}")  # noqa: T201
            correction = await agent.process_chunk(
                TranscriptChunk(speaker=speaker, text=text),
            )
            if correction:
                print(f"\n>>> AGENT: {correction}\n")  # noqa: T201
            else:
                print("  (no intervention)")  # noqa: T201

    asyncio.run(main())
