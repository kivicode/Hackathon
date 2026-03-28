"""Delivery callback for agent corrections."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def mock_delivery(correction_text: str) -> None:
    """Log the correction. Replace with real turn detection + TTS."""
    logger.info("AGENT CORRECTION: %s", correction_text)
    print(f"\n  Agent: {correction_text}\n")  # noqa: T201
