import os
from pathlib import Path


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY")
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    MAX_CONTENT_LENGTH = int(os.getenv("MAX_CONTENT_LENGTH", "5242880"))
    UPLOAD_FOLDER = os.getenv("UPLOAD_FOLDER", "instance/uploads")
    CANONICAL_ORIGIN = os.getenv("CANONICAL_ORIGIN", "http://localhost:5000")
    PAYSTACK_SECRET_KEY = os.getenv("PAYSTACK_SECRET_KEY", "")
    PAYSTACK_PUBLIC_KEY = os.getenv("PAYSTACK_PUBLIC_KEY", "")
    REDIS_URL = os.getenv("REDIS_URL", "")
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    WTF_CSRF_TIME_LIMIT = 3600


class DevelopmentConfig(Config):
    SECRET_KEY = Config.SECRET_KEY or "local-only-change-before-deploy"
    SQLALCHEMY_DATABASE_URI = Config.SQLALCHEMY_DATABASE_URI or "sqlite:///cafe-dev.sqlite"
    DEBUG = True


class TestingConfig(Config):
    SECRET_KEY = "test-secret"
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    TESTING = True
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False


class ProductionConfig(Config):
    DEBUG = False
    SESSION_COOKIE_SECURE = True
    PREFERRED_URL_SCHEME = "https"

    @classmethod
    def validate(cls):
        missing = [name for name in ("SECRET_KEY", "DATABASE_URL", "REDIS_URL") if not os.getenv(name)]
        if missing:
            raise RuntimeError(f"Production configuration requires: {', '.join(missing)}")
        if not os.getenv("DATABASE_URL", "").startswith(("postgresql://", "postgresql+psycopg://")):
            raise RuntimeError("Production DATABASE_URL must use PostgreSQL")


def get_config(name=None):
    environment = name or os.getenv("FLASK_ENV", "development")
    configs = {
        "development": DevelopmentConfig,
        "testing": TestingConfig,
        "production": ProductionConfig,
    }
    try:
        selected = configs[environment]
    except KeyError as error:
        raise RuntimeError(f"Unknown FLASK_ENV: {environment}") from error
    if selected is ProductionConfig:
        selected.validate()
    return selected