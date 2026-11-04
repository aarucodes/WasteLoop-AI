"""
Database engine and session factory.

DATABASE_URL defaults to a local SQLite file (wasteloop.db).
To use PostgreSQL, set DATABASE_URL=postgresql+psycopg2://user:pass@host/dbname
in the .env file — no other code changes are required.
"""

import os
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

load_dotenv()

DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./wasteloop.db")

# SQLite-specific: enable foreign key enforcement (off by default in SQLite)
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, connect_args=connect_args)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""
    pass


def get_db():
    """FastAPI dependency that yields a DB session and guarantees it is closed."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create all tables defined on Base. Safe to call on every startup."""
    Base.metadata.create_all(bind=engine)
