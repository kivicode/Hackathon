"""Main agent: detects factual claims in meeting transcripts and generates corrections."""

from __future__ import annotations

import json
import logging
from collections import deque
from typing import TYPE_CHECKING, Callable

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


class Claim(BaseModel):
    text: str
    category: str  # feature_status | financial | timeline | staffing
    speaker: str


class Evidence(BaseModel):
    source: str
    snippet: str
    relevance_score: float = 1.0


class ContradictionResult(BaseModel):
    is_contradicted: bool
    confidence: float = Field(ge=0.0, le=1.0)
    summary: str


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

CLAIM_DETECTION_PROMPT = """\
You are a meeting analyst. Given a transcript chunk and recent context, \
identify verifiable factual claims — statements about feature status, \
financial figures, timelines, team assignments, costs, or revenue.

Do NOT flag opinions, plans, or questions. Only flag assertions of fact.

Recent context:
{context}

Latest chunk ({speaker}): {text}

Return a JSON list of claims. Each claim has: text, category, speaker.
Return [] if no verifiable claims found."""

CONTRADICTION_PROMPT = """\
You are a fact-checking analyst. Given a claim from a meeting and evidence \
from company systems, determine if the evidence CONTRADICTS the claim.

Be conservative — only flag contradictions where the evidence clearly \
shows the claim is wrong or misleading.

Claim: {claim_text} (by {speaker})
Evidence:
{evidence_text}

Return JSON with: is_contradicted (bool), confidence (0.0-1.0), summary (string)."""

CORRECTION_PROMPT = """\
You are a polite, concise meeting assistant. Compose a brief correction:

Rules:
- Start with a soft opener: "Small correction:", "Worth noting:", "Caution:", or "Quick flag:"
- 1-2 sentences max
- Cite the source (Jira, Slack, financial report, etc.)
- Never confrontational. Tone: helpful assistant passing a note.

Meeting context:
{context}

Claim: {claim_text} (by {speaker})
Evidence: {evidence_text}
Contradiction: {contradiction_summary}

Compose the correction:"""


# ---------------------------------------------------------------------------
# MeetingAgent
# ---------------------------------------------------------------------------


class MeetingAgent:
    def __init__(
        self,
        settings: ProjectSettings,
        rag_fn: Callable[[str, str], list[Evidence]],
        delivery_fn: Callable[[str], None],
    ) -> None:
        self.client = genai.Client(api_key=settings.gemini_api_key)
        self.model = settings.gemini_model
        self.transcript: deque[TranscriptChunk] = deque(maxlen=settings.buffer_size)
        self.rag_fn = rag_fn
        self.delivery_fn = delivery_fn
        self.confidence_threshold = settings.confidence_threshold

    async def process_chunk(self, chunk: TranscriptChunk) -> str | None:
        """Run the full pipeline on a new transcript chunk. Returns correction text or None."""
        self.transcript.append(chunk)
        context = self._build_context()

        claims = await self._detect_claims(chunk, context)
        if not claims:
            return None

        for claim in claims:
            evidence = self.rag_fn(claim.text, claim.category)
            if not evidence:
                continue

            contradiction = await self._check_contradiction(claim, evidence, context)
            if not contradiction.is_contradicted:
                continue
            if contradiction.confidence < self.confidence_threshold:
                continue

            correction = await self._build_correction(claim, evidence, contradiction, context)
            self.delivery_fn(correction)
            return correction

        return None

    # -- LLM calls ----------------------------------------------------------

    async def _detect_claims(self, chunk: TranscriptChunk, context: str) -> list[Claim]:
        prompt = CLAIM_DETECTION_PROMPT.format(
            context=context,
            speaker=chunk.speaker,
            text=chunk.text,
        )
        response = await self.client.aio.models.generate_content(
            model=self.model,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=list[Claim],
                temperature=0.1,
            ),
        )
        try:
            raw = json.loads(response.text)
            return [Claim(**c) if isinstance(c, dict) else c for c in raw]
        except (json.JSONDecodeError, TypeError):
            logger.warning("Failed to parse claims: %s", response.text)
            return []

    async def _check_contradiction(
        self,
        claim: Claim,
        evidence: list[Evidence],
        context: str,
    ) -> ContradictionResult:
        evidence_text = "\n".join(f"[{e.source}] {e.snippet}" for e in evidence)
        prompt = CONTRADICTION_PROMPT.format(
            claim_text=claim.text,
            speaker=claim.speaker,
            evidence_text=evidence_text,
        )
        response = await self.client.aio.models.generate_content(
            model=self.model,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=ContradictionResult,
                temperature=0.1,
            ),
        )
        try:
            return ContradictionResult(**json.loads(response.text))
        except (json.JSONDecodeError, TypeError):
            logger.warning("Failed to parse contradiction: %s", response.text)
            return ContradictionResult(is_contradicted=False, confidence=0.0, summary="")

    async def _build_correction(
        self,
        claim: Claim,
        evidence: list[Evidence],
        contradiction: ContradictionResult,
        context: str,
    ) -> str:
        evidence_text = "\n".join(f"[{e.source}] {e.snippet}" for e in evidence)
        prompt = CORRECTION_PROMPT.format(
            context=context,
            claim_text=claim.text,
            speaker=claim.speaker,
            evidence_text=evidence_text,
            contradiction_summary=contradiction.summary,
        )
        response = await self.client.aio.models.generate_content(
            model=self.model,
            contents=prompt,
            config=types.GenerateContentConfig(temperature=0.3),
        )
        return response.text.strip()

    # -- helpers -------------------------------------------------------------

    def _build_context(self) -> str:
        return "\n".join(f"{c.speaker}: {c.text}" for c in self.transcript)
