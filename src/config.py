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
    """Provider configuration.

    Supported providers:
    - LLM: "openai", "huggingface", "anthropic", "local"
    - Embedding: "openai", "huggingface", "local"
    """
    # LLM Provider
    llm_provider: str = "openai"  # "openai", "huggingface", "anthropic", "local"
    llm_model: str = "gpt-5.2-codex"
    llm_api_key: Optional[str] = None
    llm_base_url: Optional[str] = None  # Для локальных моделей или custom endpoint
    reasoning_effort: str = "medium"  # "low", "medium", "high" (для reasoning моделей)

    # Embedding Provider
    embedding_provider: str = "openai"  # "openai", "huggingface", "local"
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
class CallGraphConfig:
    """Call graph configuration."""

    enabled: bool = True
    db_path: str = "./call_graph.db"
    max_call_depth: int = 10
    resolve_cross_file: bool = True


@dataclass
class Config:
    """Main configuration container."""

    chroma: ChromaConfig
    indexing: IndexingConfig
    server: ServerConfig
    patterns: FilePatterns
    provider: ProviderConfig
    call_graph: CallGraphConfig


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

    # Provider configuration
    llm_provider = os.getenv("LLM_PROVIDER", "openai")

    # Get LLM API key with fallback chain:
    # 1. LLM_API_KEY (универсальный)
    # 2. Provider-specific key (OPENAI_API_KEY, HUGGINGFACE_TOKEN, etc.)
    llm_api_key = os.getenv("LLM_API_KEY")
    if not llm_api_key:
        if llm_provider == "openai":
            llm_api_key = os.getenv("OPENAI_API_KEY")
        elif llm_provider == "huggingface":
            llm_api_key = os.getenv("HUGGINGFACE_TOKEN") or os.getenv("HF_TOKEN")

    # Get LLM model with defaults per provider
    llm_model = os.getenv("LLM_MODEL")
    if not llm_model:
        if llm_provider == "huggingface":
            llm_model = "meta-llama/Llama-3.1-70B-Instruct"
        else:
            llm_model = "gpt-5.2-codex"

    # Determine Embedding provider
    embedding_provider = os.getenv("EMBEDDING_PROVIDER", "openai")

    # Get Embedding API key with fallback chain:
    # 1. EMBEDDING_API_KEY (универсальный)
    # 2. LLM_API_KEY (если тот же провайдер)
    # 3. Provider-specific key
    embedding_api_key = os.getenv("EMBEDDING_API_KEY")
    if not embedding_api_key:
        # Если embedding провайдер совпадает с LLM, используем тот же ключ
        if embedding_provider == llm_provider and llm_api_key:
            embedding_api_key = llm_api_key
        elif embedding_provider == "openai":
            embedding_api_key = os.getenv("OPENAI_API_KEY")
        elif embedding_provider == "huggingface":
            embedding_api_key = os.getenv("HUGGINGFACE_TOKEN") or os.getenv("HF_TOKEN")

    # Get Embedding model with defaults per provider
    embedding_model = os.getenv("EMBEDDING_MODEL")
    if not embedding_model:
        if embedding_provider == "huggingface":
            embedding_model = "sentence-transformers/all-MiniLM-L6-v2"
        else:
            embedding_model = "text-embedding-3-small"

    provider_config = ProviderConfig(
        llm_provider=llm_provider,
        llm_model=llm_model,
        llm_api_key=llm_api_key,
        llm_base_url=os.getenv("LLM_BASE_URL"),
        reasoning_effort=os.getenv("LLM_REASONING_EFFORT", "medium"),

        embedding_provider=embedding_provider,
        embedding_model=embedding_model,
        embedding_api_key=embedding_api_key,
        embedding_base_url=os.getenv("EMBEDDING_BASE_URL"),

        max_retries=int(os.getenv("PROVIDER_MAX_RETRIES", "3")),
        timeout=int(os.getenv("PROVIDER_TIMEOUT", "60"))
    )

    # Call graph configuration
    call_graph_config = CallGraphConfig(
        enabled=os.getenv("CALL_GRAPH_ENABLED", "true").lower() == "true",
        db_path=os.getenv("CALL_GRAPH_DB_PATH", "./call_graph.db"),
        max_call_depth=int(os.getenv("CALL_GRAPH_MAX_DEPTH", "10")),
        resolve_cross_file=os.getenv("CALL_GRAPH_RESOLVE_CROSS_FILE", "true").lower() == "true"
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
        call_graph=call_graph_config,
    )
