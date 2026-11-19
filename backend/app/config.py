"""Konfigurimi i aplikacionit. Të gjitha vlerat lexohen nga skedari .env."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # .env lexohet nga rrënja e projektit ose nga dosja backend
    model_config = SettingsConfigDict(env_file=("../.env", ".env"), extra="ignore")

    # Baza e të dhënave (PostgreSQL me pgvector)
    database_url: str = "postgresql+psycopg://chatbot:chatbot@localhost:5432/chatbot"

    # Modeli gjuhësor (LLM). Çdo API e përputhshme me OpenAI funksionon:
    #   DeepSeek: https://api.deepseek.com
    #   Ollama:   http://localhost:11434/v1
    llm_base_url: str = "https://api.deepseek.com"
    llm_api_key: str = ""
    llm_model: str = "deepseek-flash"
    llm_temperature: float = 0.2
    # Përfshin edhe tokenët e arsyetimit te modelet "reasoning", prandaj mos e ul shumë.
    llm_max_tokens: int = 2000

    # Embeddings lokale (nuk varen nga LLM-i, mbeten të njëjta edhe me Ollama)
    embedding_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    embedding_dim: int = 384
    embedding_cache_dir: str = "models"

    # Kërkimi në dokumente (RAG)
    top_k: int = 5
    # Kërkimi hibrid: sa kandidatë merren nga secila metodë para bashkimit
    hybrid_search: bool = True
    candidate_pool: int = 20
    # Lajmet më të vjetra se kaq ditë nuk përdoren si burim
    news_max_age_days: int = 365
    # Distanca kosinus maksimale (0 = identike, 2 = e kundërt). Pjesët më larg se kjo injorohen.
    max_distance: float = 0.65
    # Burimet e shfaqura: vetëm dokumentet brenda kësaj diference nga pjesa më e afërt
    source_margin: float = 0.08
    max_sources: int = 3
    chunk_size: int = 900
    chunk_overlap: int = 150

    # Paneli i administratës
    admin_username: str = "admin"
    admin_password: str = "ndrysho-kete"
    jwt_secret: str = "ndrysho-edhe-kete"
    jwt_expire_hours: int = 12

    # Siguria dhe kufizimet
    cors_origins: str = "http://localhost:5173"
    rate_limit_per_minute: int = 10
    max_upload_mb: int = 20
    upload_dir: str = "data/uploads"
    # IPv4 publike e serverit, përdoret nga ndihmësi i domenit në panelin e administratës.
    server_public_ip: str = ""
    # Dosja docs/ e projektit (në Docker montohet te /app/docs)
    docs_dir: str = ""

    @property
    def docs_path(self) -> "Path":
        from pathlib import Path

        if self.docs_dir:
            return Path(self.docs_dir)
        docker = Path("/app/docs")
        return docker if docker.exists() else Path(__file__).resolve().parents[2] / "docs"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
