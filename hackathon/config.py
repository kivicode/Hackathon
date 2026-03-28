from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ProjectSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )

    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    tts_model: str = "gemini-3.1-flash-live-preview"
    confidence_threshold: float = 0.7
    buffer_size: int = 200
    voice_name: str = "Kore"
    audio_device: str = "BlackHole 2ch"
    sample_rate: int = 24000

    rag_mode: str = "stuffing"
    rag_data_dir: str = "data"
    rag_working_dir: str = "rag_storage"

    microphone_device: str | None = None
    microphone_sample_rate_hz: int = Field(default=16000, gt=0)
    microphone_chunk_ms: Literal[20] = 20
    microphone_queue_size: int = Field(default=5, gt=0)
    turn_detector_silence_ms: int = Field(default=700, gt=0)
    turn_detector_max_wait_ms: int = Field(default=10_000, gt=0)
    turn_detector_vad_mode: int = Field(default=2, ge=0, le=3)

    def microphone_device_selector(self) -> str | int | None:
        if self.microphone_device is None:
            return None

        stripped_device = self.microphone_device.strip()
        if not stripped_device:
            return None
        if stripped_device.isdigit():
            return int(stripped_device)
        return stripped_device
