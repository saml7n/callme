from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Twilio
    twilio_account_sid: str = ""
    twilio_api_key_sid: str = ""
    twilio_api_key_secret: str = ""
    twilio_phone_number: str = ""

    # Deepgram
    deepgram_api_key: str = ""

    # ElevenLabs
    elevenlabs_api_key: str = ""
    elevenlabs_voice_id: str = "21m00Tcm4TlvDq8ikWAM"

    # OpenAI
    openai_api_key: str = ""

    # Server
    port: int = 3000
    public_url: str = ""
    database_url: str = "sqlite:///./callme.db"

    model_config = {"env_file": "../.env", "env_file_encoding": "utf-8"}


settings = Settings()
