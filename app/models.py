from sqlalchemy import (
    Column, Integer, String, Text, DateTime, ForeignKey, JSON
)
from sqlalchemy.orm import relationship
from datetime import datetime

from app.database import Base


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