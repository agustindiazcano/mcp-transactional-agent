from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = "postgresql+asyncpg://postgres:password@localhost:5432/agentic_engine"
    # Test suite only (tests/support/database.py): the database pytest runs
    # against. Empty means "<DATABASE_URL's db name>_test" on the same server.
    # Must end in _test -- the suite refuses to start otherwise.
    TEST_DATABASE_URL: str = ""
    
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

    # Vertex AI (Phase 6, GCP). Auth is ADC / the Cloud Run service account,
    # never an API key. An empty VERTEX_PROJECT lets ADC resolve the project.
    # "global": the Gemini 3.5 models aren't served from regional endpoints.
    VERTEX_PROJECT: str = ""
    VERTEX_LOCATION: str = "global"
    # Embeddings are also served regionally, where they answer ~4x faster.
    VERTEX_EMBEDDING_LOCATION: str = "us-central1"
    VERTEX_MODEL: str = "gemini-3.5-flash-lite"
    VERTEX_EMBEDDING_MODEL: str = "gemini-embedding-001"

    # Prompt Guard: Groq returns a malicious-probability score in [0, 1];
    # inputs scoring at or above this are blocked as BLOCKED_MALICIOUS_PROMPT.
    PROMPT_GUARD_THRESHOLD: float = 0.5

    # MCP
    MCP_SERVER_URL: str = "http://127.0.0.1:8080/sse"

    # MCP Security Boundary (Phase 1.B)
    # Local-dev defaults below are placeholders, not secrets (the registry
    # stores only a SHA-256 hash) -- rotate both for any shared/production
    # deployment, the same convention already used for DATABASE_URL/RABBITMQ_URL.
    MCP_CLIENTS_FILE: str = "mcp_clients.json"
    MCP_CLIENT_TOKEN: str = "local-dev-worker-token-change-me"
    REFUND_MAX_AMOUNT: float = 10000.0
    MCP_RATE_LIMIT_PER_MIN: int = 30

    # MCP tool calls from the worker (src/worker/refund_executor.py). The read
    # timeout bounds each attempt, since MCP SDK 2.2.0 hangs in call_tool when
    # the security boundary rejects a request with a 4xx.
    MCP_TOOL_TIMEOUT_SECONDS: float = 10.0
    MCP_TOOL_MAX_RETRIES: int = 3
    MCP_TOOL_BACKOFF_BASE_SECONDS: float = 1.0

    # Worker Settings
    MAX_LLM_RETRIES: int = 3
    IDEMPOTENCY_TTL_SECONDS: int = 86400

    # Recovery Sweeper Settings
    SWEEPER_INTERVAL_SECONDS: int = 300        # How often the sweeper polls (default 5 min)
    SWEEPER_STALE_THRESHOLD_SECONDS: int = 300 # Rows older than this are zombies (default 5 min)

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

settings = Settings()
