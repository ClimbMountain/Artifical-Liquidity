import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Callable, TypeVar


T = TypeVar("T")


def _parse_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _cast(value: Optional[str], default: T, caster: Callable[[str], T]) -> T:
    if value is None:
        return default
    try:
        return caster(value)
    except Exception:
        return default


def load_env_file(path: str = ".env") -> None:
    """Load simple KEY=VALUE pairs from a .env file into os.environ if present."""
    env_path = Path(path)
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" not in stripped:
            continue
        key, _, val = stripped.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        os.environ.setdefault(key, val)


@dataclass(frozen=True)
class Settings:
    """Runtime application configuration loaded from environment variables."""

    # Network / API
    clob_host: str = "https://clob.polymarket.com"
    chain_id: int = 137
    clob_signature_type: int = 2

    # Files/paths
    db_path: str = "polyfarm.db"
    wallets_csv: str = "wallets.csv"
    cheap_markets_file: str = "cheap_markets.txt"

    # Orchestration defaults
    min_active_markets: int = 20
    max_workers: int = 10

    # Trading delays (seconds)
    trade_delay_min: float = 4.0
    trade_delay_max: float = 8.0

    # Logging
    log_level: str = "INFO"

    # HTTP
    http_timeout_sec: float = 5.0


def load_settings() -> Settings:
    """Create a Settings object from environment variables (and optional .env)."""
    load_env_file()

    def env(key: str, default: T, caster: Callable[[str], T]) -> T:
        return _cast(os.environ.get(key), default, caster)

    return Settings(
        clob_host=env("CLOB_HOST", "https://clob.polymarket.com", str),
        chain_id=env("CHAIN_ID", 137, int),
        clob_signature_type=env("CLOB_SIGNATURE_TYPE", 2, int),
        db_path=env("DB_PATH", "polyfarm.db", str),
        wallets_csv=env("WALLETS_CSV", "wallets.csv", str),
        cheap_markets_file=env("CHEAP_MARKETS_FILE", "cheap_markets.txt", str),
        min_active_markets=env("MIN_ACTIVE_MARKETS", 20, int),
        max_workers=env("MAX_WORKERS", 10, int),
        trade_delay_min=env("TRADE_DELAY_MIN", 4.0, float),
        trade_delay_max=env("TRADE_DELAY_MAX", 8.0, float),
        log_level=env("LOG_LEVEL", "INFO", str).upper(),
        http_timeout_sec=env("HTTP_TIMEOUT_SEC", 5.0, float),
    )


