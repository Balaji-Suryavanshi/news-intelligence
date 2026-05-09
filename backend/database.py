"""
database.py — SQLAlchemy setup + Article model
"""

import os
from datetime import datetime
from sqlalchemy import (
    create_engine, Column, String, Text,
    DateTime, Float, JSON, Integer
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./news_intelligence.db")

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class Article(Base):
    __tablename__ = "articles"

    # ── Primary identity ────────────────────────────────────────────────
    article_id   = Column(String, primary_key=True, index=True)   # from NewsData
    title        = Column(String, nullable=False)
    description  = Column(Text)
    content      = Column(Text)
    url          = Column(String, unique=True)
    image_url    = Column(String)

    # ── Source metadata ─────────────────────────────────────────────────
    source_name  = Column(String)
    category     = Column(String)
    country      = Column(String)
    language     = Column(String)
    published_at = Column(DateTime)

    # ── AI-generated fields ─────────────────────────────────────────────
    summary          = Column(Text)
    sentiment        = Column(String)   # positive | negative | neutral
    sentiment_score  = Column(Float)    # -1.0 … +1.0
    key_insights     = Column(JSON)     # list[str] of 3-5 insights

    # ── Internal timestamps ──────────────────────────────────────────────
    created_at   = Column(DateTime, default=datetime.utcnow)
    processed_at = Column(DateTime)


def init_db():
    """Create all tables if they don't exist."""
    Base.metadata.create_all(bind=engine)


def get_db():
    """Dependency-injection helper for FastAPI."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()