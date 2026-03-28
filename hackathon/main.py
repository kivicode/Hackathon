"""FastAPI app — wires MeetingAgent with RAG and delivery."""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from hackathon.agent import MeetingAgent, TranscriptChunk
from hackathon.config import ProjectSettings
from hackathon.delivery import mock_delivery
from hackathon.rag import mock_rag

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    settings = ProjectSettings()
    app.state.agent = MeetingAgent(
        settings=settings,
        rag_fn=mock_rag,
        delivery_fn=mock_delivery,
    )
    yield


app = FastAPI(title="Meeting Fact-Check Agent", lifespan=lifespan)


@app.websocket("/ws/transcription")
async def transcription_ws(websocket: WebSocket) -> None:
    await websocket.accept()
    agent: MeetingAgent = websocket.app.state.agent
    try:
        while True:
            data = await websocket.receive_json()
            chunk = TranscriptChunk(**data)
            correction = await agent.process_chunk(chunk)
            if correction:
                await websocket.send_json({"type": "correction", "text": correction})
    except WebSocketDisconnect:
        pass


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/transcript")
async def get_transcript() -> list[dict]:
    agent: MeetingAgent = app.state.agent
    return [c.model_dump() for c in agent.transcript]
