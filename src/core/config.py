from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = "postgresql+asyncpg://postgres:password@localhost:5432/agentic_engine"
    
    # RabbitMQ
    RABBITMQ_URL: str = "amqp://guest:guest@localhost:5672/"
    
    # LLM Settings
    LLM_PROVIDER: str = "mock" # mock, openai, vertex, gemini, bedrock, groq
    OPENAI_API_KEY: str = ""
    GEMINI_API_KEY: str = ""
    GOOGLE_APPLICATION_CREDENTIALS: str = ""
    GROQ_API_KEY: str = ""
    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: str = ""
    
    # MCP
    MCP_SERVER_URL: str = "http://127.0.0.1:8080/sse"

    # Worker Settings
    MAX_LLM_RETRIES: int = 3
    IDEMPOTENCY_TTL_SECONDS: int = 86400
    
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

settings = Settings()
