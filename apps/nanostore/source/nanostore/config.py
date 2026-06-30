import os

from dotenv import load_dotenv


load_dotenv()


def normalize_database_url(value):
    raw = (value or "").strip()
    if not raw:
        return "sqlite:///nanostore.db"
    if raw.startswith("mysql://"):
        return raw.replace("mysql://", "mysql+pymysql://", 1)
    if raw.startswith("mariadb://"):
        return raw.replace("mariadb://", "mysql+pymysql://", 1)
    return raw


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key")
    SQLALCHEMY_DATABASE_URI = normalize_database_url(os.getenv("DATABASE_URL", "sqlite:///nanostore.db"))
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}
