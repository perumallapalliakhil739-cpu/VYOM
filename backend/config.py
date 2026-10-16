import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env if present
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

class Settings:
    PROJECT_NAME: str = "Neurora — AI-Powered Worldwide Fire Monitoring & Forecasting System"
    VERSION: str = "1.0.0"
    DEBUG: bool = os.getenv("DEBUG", "True").lower() in ("true", "1")
    PORT: int = int(os.getenv("PORT", "8000"))
    HOST: str = os.getenv("HOST", "0.0.0.0")
    BASE_DIR: Path = BASE_DIR

    # NASA FIRMS
    FIRMS_MAP_KEY: str = os.getenv("FIRMS_MAP_KEY", "").strip()
    FIRMS_BASE_URL: str = "https://firms.modaps.eosdis.nasa.gov"
    
    # Storage & Cache
    DATA_DIR: Path = BASE_DIR / "data"
    CACHE_DIR: Path = BASE_DIR / "data" / "cache"
    CACHE_TTL_SECONDS: int = int(os.getenv("CACHE_TTL_SECONDS", "1800"))  # 30 mins
    
    USER_AGENT: str = os.getenv("USER_AGENT", "Neurora-Wildfire-Monitor/1.0 (environmental-research)")

settings = Settings()

# Ensure directories exist
settings.CACHE_DIR.mkdir(parents=True, exist_ok=True)
