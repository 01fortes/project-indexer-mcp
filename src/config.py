"""Configuration management for the project indexer."""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import yaml
from dotenv import load_dotenv


@dataclass
class ChromaConfig:
    """ChromaDB configuration."""

    host: Optional[str] = None
    port: Optional[int] = None
    persist_directory: str = "./chroma_data"


@dataclass
class IndexingConfig:
    """Indexing behavior configuration."""

    max_file_size_mb: float = 1.0
    max_chunk_size_tokens: int = 6000
    chunk_overlap_tokens: int = 500
    max_concurrent_files: int = 5
    rate_limit_rpm: int = 3500  # Requests per minute
    rate_limit_tpm: int = 1000000  # Tokens per minute


@dataclass
class ServerConfig:
    """MCP server configuration."""

    log_level: str = "INFO"
    name: str = "project-indexer"
    version: str = "1.0.0"


@dataclass
class ProviderConfig:
    """Provider configuration."""
    # LLM Provider
    llm_provider: str = "openai"  # "openai", "local", "anthropic"
    llm_model: str = "gpt-5.2-codex"
    llm_api_key: Optional[str] = None
    llm_base_url: Optional[str] = None  # Для локальных моделей
    reasoning_effort: str = "medium"  # "low", "medium", "high" (для reasoning моделей)

    # Embedding Provider
    embedding_provider: str = "openai"  # "openai", "local"
    embedding_model: str = "text-embedding-3-small"
    embedding_api_key: Optional[str] = None
    embedding_base_url: Optional[str] = None

    # Common settings
    max_retries: int = 3
    timeout: int = 60


@dataclass
class FilePatterns:
    """File patterns for scanning."""

    include: List[str] = field(default_factory=lambda: [
        "**/*.py", "**/*.js", "**/*.ts", "**/*.tsx", "**/*.jsx",
        "**/*.java", "**/*.cpp", "**/*.c", "**/*.h",
        "**/*.go", "**/*.rs", "**/*.rb", "**/*.php",
        "**/*.swift", "**/*.kt", "**/*.scala",
        "**/*.md", "**/*.yaml", "**/*.yml", "**/*.json", "**/*.toml"
    ])
    exclude: List[str] = field(default_factory=lambda: [
        "**/node_modules/**", "**/venv/**", "**/.venv/**", "**/env/**",
        "**/__pycache__/**", "**/.git/**", "**/dist/**", "**/build/**",
        "**/*.min.js", "**/*.min.css", "**/.next/**", "**/.cache/**",
        "**/coverage/**", "**/*.lock", "**/package-lock.json",
        "**/yarn.lock", "**/poetry.lock"
    ])
    binary_extensions: List[str] = field(default_factory=lambda: [
        ".png", ".jpg", ".jpeg", ".gif", ".pdf", ".zip", ".tar", ".gz",
        ".ico", ".woff", ".woff2", ".ttf", ".eot", ".pyc"
    ])


@dataclass
class Config:
    """Main configuration container."""

    chroma: ChromaConfig
    indexing: IndexingConfig
    server: ServerConfig
    patterns: FilePatterns
    provider: ProviderConfig


def load_config(config_path: Optional[Path] = None) -> Config:
    """
    Load configuration from environment variables and YAML file.

    Args:
        config_path: Path to config.yaml file. If None, looks for config.yaml in current directory.

    Returns:
        Config object with all settings.

    Raises:
        ValueError: If required configuration is missing.
    """
    # Load environment variables
    load_dotenv()

    # ChromaDB configuration
    chroma_host = os.getenv("CHROMA_HOST")
    chroma_port = os.getenv("CHROMA_PORT")
    chroma_config = ChromaConfig(
        host=chroma_host if chroma_host else None,
        port=int(chroma_port) if chroma_port else None,
        persist_directory=os.getenv("CHROMA_PERSIST_DIRECTORY", "./chroma_data"),
    )

    # Indexing configuration
    indexing_config = IndexingConfig(
        max_file_size_mb=float(os.getenv("MAX_FILE_SIZE_MB", "1.0")),
        max_chunk_size_tokens=int(os.getenv("MAX_CHUNK_SIZE_TOKENS", "6000")),
        chunk_overlap_tokens=int(os.getenv("CHUNK_OVERLAP_TOKENS", "500")),
        max_concurrent_files=int(os.getenv("MAX_CONCURRENT_FILES", "5")),
        rate_limit_rpm=int(os.getenv("RATE_LIMIT_RPM", "3500")),
        rate_limit_tpm=int(os.getenv("RATE_LIMIT_TPM", "1000000")),
    )

    # Server configuration
    server_config = ServerConfig(
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        name=os.getenv("SERVER_NAME", "project-indexer"),
        version=os.getenv("SERVER_VERSION", "1.0.0"),
    )

    # Provider configuration (NEW!)
    provider_config = ProviderConfig(
        llm_provider=os.getenv("LLM_PROVIDER", "openai"),
        llm_model=os.getenv("LLM_MODEL", os.getenv("OPENAI_MODEL", "gpt-5.2-codex")),
        llm_api_key=os.getenv("LLM_API_KEY", os.getenv("OPENAI_API_KEY")),
        llm_base_url=os.getenv("LLM_BASE_URL"),
        reasoning_effort=os.getenv("LLM_REASONING_EFFORT", "medium"),

        embedding_provider=os.getenv("EMBEDDING_PROVIDER", "openai"),
        embedding_model=os.getenv("EMBEDDING_MODEL", os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")),
        embedding_api_key=os.getenv("EMBEDDING_API_KEY", os.getenv("OPENAI_API_KEY")),
        embedding_base_url=os.getenv("EMBEDDING_BASE_URL"),

        max_retries=int(os.getenv("PROVIDER_MAX_RETRIES", "3")),
        timeout=int(os.getenv("PROVIDER_TIMEOUT", "60"))
    )

    # Load file patterns from YAML if exists
    patterns = FilePatterns()
    if config_path is None:
        config_path = Path("config.yaml")

    if config_path.exists():
        with open(config_path) as f:
            yaml_config = yaml.safe_load(f)
            if yaml_config:
                if "include_patterns" in yaml_config:
                    patterns.include = yaml_config["include_patterns"]
                if "exclude_patterns" in yaml_config:
                    patterns.exclude = yaml_config["exclude_patterns"]
                if "binary_extensions" in yaml_config:
                    patterns.binary_extensions = yaml_config["binary_extensions"]

    return Config(
        chroma=chroma_config,
        indexing=indexing_config,
        server=server_config,
        patterns=patterns,
        provider=provider_config,
    )
