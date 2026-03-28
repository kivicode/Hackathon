from pydantic_settings import BaseSettings


class ProjectSettings(BaseSettings):
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash"
    confidence_threshold: float = 0.7
    buffer_size: int = 200

    model_config = {"env_file": ".env"}
