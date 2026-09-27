from sqlalchemy import (
    Column, Integer, String, Text, DateTime, Date, Float, ForeignKey, JSON, UniqueConstraint, Index
)
from sqlalchemy.orm import relationship
from datetime import datetime

from app.core.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    name = Column(String, nullable=True)
    google_id = Column(String, unique=True, index=True, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    tokens = relationship("Token", back_populates="user", cascade="all, delete-orphan")
    integrations = relationship("Integration", back_populates="user", cascade="all, delete-orphan")
    emails = relationship("Email", back_populates="user", cascade="all, delete-orphan")


class Token(Base):
    __tablename__ = "tokens"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    provider = Column(String, nullable=False)  # "google", "outlook", etc.

    # Store these ENCRYPTED, not plaintext - encrypt/decrypt in your auth code,
    # not here. This column just holds whatever ciphertext you write to it.
    access_token = Column(Text, nullable=False)
    refresh_token = Column(Text, nullable=True)
    expires_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="tokens")


class Integration(Base):
    """
    Registry of which 'apps' a user has connected/enabled.
    This is what lets you add new apps to the dashboard later
    without changing the schema again.
    """
    __tablename__ = "integrations"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    app_name = Column(String, nullable=False)  # "gmail", "calendar", "weather", etc.
    status = Column(String, default="active")  # "active", "disabled", "error"
    config = Column(JSON, nullable=True)  # app-specific settings, free-form

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="integrations")


class Email(Base):
    __tablename__ = "emails"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    gmail_id = Column(String, index=True, nullable=False)  # Gmail's message id
    subject = Column(String, nullable=True)
    snippet = Column(Text, nullable=True)
    full_body = Column(Text, nullable=True)
    sender = Column(String, nullable=True)
    timestamp = Column(DateTime, nullable=True)

    category = Column(String, nullable=True)
    summary = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="emails")

class NutritionEntry(Base):
    """One food logged by the user on a given (local) day."""
    __tablename__ = "nutrition_entries"
    __table_args__ = (Index("ix_nutrition_entries_user_day", "user_id", "day"),)

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    day = Column(Date, nullable=False, index=True)  # the user's local date

    name = Column(String(200), nullable=False)
    grams = Column(Float, nullable=True)
    source = Column(String(10), nullable=False, default="manual")  # "manual" | "usda"
    fdc_id = Column(Integer, nullable=True)  # USDA FoodData Central id

    calories = Column(Float, nullable=False, default=0)
    protein = Column(Float, nullable=False, default=0)
    carbs = Column(Float, nullable=False, default=0)
    fat = Column(Float, nullable=False, default=0)
    fiber = Column(Float, nullable=False, default=0)
    sugar = Column(Float, nullable=False, default=0)
    sat_fat = Column(Float, nullable=False, default=0)

    created_at = Column(DateTime, default=datetime.utcnow)


class NutritionDay(Base):
    """The goals that applied on a day (snapshotted when food is logged), so past
    days keep being judged against the goals of that time."""
    __tablename__ = "nutrition_days"
    __table_args__ = (UniqueConstraint("user_id", "day", name="uq_nutrition_days_user_day"),)

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    day = Column(Date, nullable=False)
    goals = Column(JSON, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class JournalEntry(Base):
    """A journal entry. `body` is Fernet-encrypted (app/crypto.py); the prompt is
    stored as shown, so editing content/journal_prompts.md later doesn't change old entries."""
    __tablename__ = "journal_entries"
    __table_args__ = (Index("ix_journal_entries_user_day", "user_id", "day"),)

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    day = Column(Date, nullable=False)  # the user's local date

    prompt_id = Column(Integer, nullable=True)  # number in content/journal_prompts.md; null = free writing
    prompt_text = Column(Text, nullable=True)
    mood = Column(String(32), nullable=True)  # any emoji, optional
    body = Column(Text, nullable=False)  # encrypted

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
