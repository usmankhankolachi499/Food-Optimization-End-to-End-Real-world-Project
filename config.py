"""Application configuration.

All values can be overridden with environment variables (see .env.example).
"""
import os
from datetime import timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
INSTANCE_DIR = BASE_DIR / "instance"
INSTANCE_DIR.mkdir(parents=True, exist_ok=True)
# data deliverable folders (raw / cleaned / sql_server / mongodb / ml)
DATA_DIR = os.path.join(BASE_DIR, "data")

try:  # optional dependency, handy for local development
    from dotenv import load_dotenv

    load_dotenv(BASE_DIR / ".env")
except ImportError:  # pragma: no cover
    pass


def _bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


class Config:
    # ------------------------------------------------------------------ core
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-only-change-me-in-production-8f4b2c")
    APP_NAME = os.getenv("APP_NAME", "MOON Light")
    ENV = os.getenv("FLASK_ENV", "development")

    # -------------------------------------------------------------- database
    # Two persistence modes:
    #   1) SQL Server (T-SQL) via pyodbc - set MSSQL_CONN_STR (SRS primary).
    #   2) SQLite fallback when MSSQL is not configured (simple local run).
    _database_url = os.getenv("DATABASE_URL", "").strip()
    if _database_url.startswith("sqlite:///"):
        DATABASE_PATH = _database_url[len("sqlite:///"):]
    else:
        DATABASE_PATH = os.getenv(
            "DATABASE_PATH", str(INSTANCE_DIR / "food_delivery.db")
        )
    MSSQL_CONN_STR = os.getenv(
        "MSSQL_CONN_STR",
        r"DRIVER={ODBC Driver 17 for SQL Server};SERVER=.\SQLEXPRESS;"
        r"DATABASE=food_delivery_sys;Trusted_Connection=yes;",
    )
    MSSQL_MASTER_CONN_STR = os.getenv(
        "MSSQL_MASTER_CONN_STR",
        r"DRIVER={ODBC Driver 17 for SQL Server};SERVER=.\SQLEXPRESS;"
        r"DATABASE=master;Trusted_Connection=yes;",
    )
    MSSQL_DATABASE = os.getenv("MSSQL_DATABASE", "food_delivery_sys")
    AUTO_CREATE_DB = _bool("AUTO_CREATE_DB", True)
    # Flip to False to force the SQLite fallback (useful when SSMS is not running)
    USE_MSSQL = _bool("USE_MSSQL", True)

    # ----------------------------------------------------------------- auth
    PERMANENT_SESSION_LIFETIME = timedelta(
        minutes=int(os.getenv("SESSION_TIMEOUT_MINUTES", "30"))
    )
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = _bool("SESSION_COOKIE_SECURE", False)
    REMEMBER_COOKIE_HTTPONLY = True
    CSRF_ENABLED = _bool("CSRF_ENABLED", True)

    # --------------------------------------------------------------- uploads
    MAX_CONTENT_LENGTH = int(os.getenv("MAX_CONTENT_MB", "8")) * 1024 * 1024
    UPLOAD_FOLDER = str(INSTANCE_DIR / "uploads")
    ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}

    # --------------------------------------------------------- integrations
    # The ML / data pipeline is built separately. When a compatible module is
    # importable it will be used automatically; otherwise deterministic
    # heuristics keep the web application fully functional.
    ML_MODULE = os.getenv("ML_MODULE", "ml.predictor")
    ML_ENABLED = _bool("ML_ENABLED", True)

    # Optional MongoDB for high-volume location / tracking logs (SRS 3.11).
    # When MONGO_URI is set and pymongo is available every GPS ping is mirrored
    # to MongoDB; otherwise the relational LocationLog table is used alone.
    MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
    MONGO_DB = os.getenv("MONGO_DB", "moonlight_tracking")
    MONGO_COLLECTION = os.getenv("MONGO_COLLECTION", "location_logs")

    # ------------------------------------------------------------ behaviour
    DEFAULT_PAGE_SIZE = int(os.getenv("PAGE_SIZE", "12"))
    AUTO_ASSIGN_ORDERS = _bool("AUTO_ASSIGN_ORDERS", True)

    @staticmethod
    def init_app(app):  # pragma: no cover - kept for Flask convention
        os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)


class DevelopmentConfig(Config):
    DEBUG = True


class ProductionConfig(Config):
    DEBUG = False
    SESSION_COOKIE_SECURE = _bool("SESSION_COOKIE_SECURE", True)
