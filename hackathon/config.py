from pydantic_settings import BaseSettings, SettingsConfigDict


class ProjectSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")

    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    tts_model: str = "gemini-3.1-flash-live-preview"
    confidence_threshold: float = 0.7
    buffer_size: int = 200
    voice_name: str = "Kore"
    audio_device: str = "BlackHole 2ch"
    sample_rate: int = 24000

    use_rag: bool = True
    rag_mode: str = "stuffing"
    rag_data_dir: str = "data"
    rag_working_dir: str = "rag_storage"
