from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Twilio
    twilio_account_sid: str = ""
    twilio_api_key_sid: str = ""
    twilio_api_key_secret: str = ""
    twilio_auth_token: str = ""  # For signature validation on /twilio/incoming
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

    # Google OAuth (server-side credentials for one-click calendar setup)
    google_client_id: str = ""
    google_client_secret: str = ""

    # Auth — API key for dashboard + API access
    callme_api_key: str = ""

    # Separate JWT signing secret (falls back to callme_api_key if not set)
    jwt_secret: str = ""

    # Invite code for gated registration (if empty, registration is disabled)
    callme_invite_code: str = ""

    # Configurable demo credentials (used when SEED_DEMO=true)
    demo_email: str = "demo@callme.ai"
    demo_password: str = ""  # auto-generated UUID if not set

    # Encryption key for integration credentials (Fernet / base64)
    callme_encryption_key: str = ""

    # Fallback transfer number for unrecoverable errors mid-call
    callme_fallback_number: str = ""

    model_config = {
        "env_file": ("../.env", "../.env.local"),
        "env_file_encoding": "utf-8",
    }


settings = Settings()
