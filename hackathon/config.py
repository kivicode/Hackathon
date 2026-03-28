from pydantic_settings import BaseSettings, SettingsConfigDict


class ProjectSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")

    gemini_api_key: str
    voice_name: str = "Kore"
    audio_device: str = "BlackHole 2ch"
    sample_rate: int = 24000
    gemini_model: str = "gemini-3.1-flash-live-preview"
