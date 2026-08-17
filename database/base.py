"""SQLAlchemy ORM foundation for TrendForge."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base class for TrendForge ORM models."""


__all__ = ["Base"]
