from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- Core (required) ---
    # Use the asyncpg driver. Neon gives you a "postgresql://..." URL;
    # swap the scheme to "postgresql+asyncpg://..." (see .env.example).
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/book_beacon"

    # --- Auth ---
    # CHANGE THIS in production: openssl rand -hex 32
    jwt_secret: str = "dev-secret-change-me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24 * 7  # 7 days


    # --- Book search (optional — works without a key but rate-limited) ---
    # Enable at: https://console.cloud.google.com/ → APIs & Services → Google Books API
    google_books_api_key: str | None = None

    # --- AI features (optional — leave blank to run the core API only) ---
    # When set, enables embeddings, cover-image search, and the keeper agent.
    # Free key, no card: https://aistudio.google.com/apikey
    gemini_api_key: str | None = None
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    embedding_model: str = "gemini-embedding-001"
    embedding_dim: int = 768
    vision_model: str = "gemini-2.5-flash"
    chat_model: str = "gemini-2.5-flash"

    # --- CORS (set to your Vercel URL in production) ---
    # Plain string, not JSON — comma-separated if you need more than one origin,
    # e.g. "https://book-beacon.vercel.app,https://www.book-beacon.app"
    cors_origins: str = "*"

    @property
    def cors_origins_list(self) -> list[str]:
        if self.cors_origins.strip() == "*":
            return ["*"]
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


settings = Settings()
