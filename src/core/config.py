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

    # MCP Security Boundary (Phase 1.B)
    # Local-dev defaults below are placeholders, not secrets (the registry
    # stores only a SHA-256 hash) -- rotate both for any shared/production
    # deployment, the same convention already used for DATABASE_URL/RABBITMQ_URL.
    MCP_CLIENTS_FILE: str = "mcp_clients.json"
    MCP_CLIENT_TOKEN: str = "local-dev-worker-token-change-me"
    REFUND_MAX_AMOUNT: float = 10000.0

    # Worker Settings
    MAX_LLM_RETRIES: int = 3
    IDEMPOTENCY_TTL_SECONDS: int = 86400

    # Recovery Sweeper Settings
    SWEEPER_INTERVAL_SECONDS: int = 300        # How often the sweeper polls (default 5 min)
    SWEEPER_STALE_THRESHOLD_SECONDS: int = 300 # Rows older than this are zombies (default 5 min)

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

settings = Settings()
