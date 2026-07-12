# -*- coding: utf-8 -*-
"""
Account data models — accounts, subscriptions, API tokens, usage records.

Uses SQLAlchemy ORM via Base from src.storage. Tables are auto-created
by DatabaseManager when the module is imported before DB initialization.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Boolean,
)
from sqlalchemy.orm import relationship

from src.storage import Base


class Account(Base):
    """用户账号 — 支持多租户。"""

    __tablename__ = "accounts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String(255), nullable=False, unique=True, index=True)
    password_hash = Column(String(255), nullable=False)  # salt_b64:hash_b64 (PBKDF2)
    role = Column(String(20), nullable=False, default="user")  # admin / user
    status = Column(String(20), nullable=False, default="active")  # active / disabled
    display_name = Column(String(100))
    created_at = Column(DateTime, default=datetime.now, nullable=False)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, nullable=False)

    subscriptions = relationship("Subscription", back_populates="account", cascade="all, delete-orphan")
    api_tokens = relationship("ApiToken", back_populates="account", cascade="all, delete-orphan")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "email": self.email,
            "role": self.role,
            "status": self.status,
            "display_name": self.display_name,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class Subscription(Base):
    """订阅记录 — 一个账号可有历史订阅，但只有一条 active。"""

    __tablename__ = "subscriptions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(Integer, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False, index=True)
    tier = Column(String(30), nullable=False)  # free / pro / enterprise
    starts_at = Column(DateTime, default=datetime.now, nullable=False)
    expires_at = Column(DateTime, nullable=True)  # NULL = 永不过期
    status = Column(String(20), nullable=False, default="active")  # active / expired / cancelled
    created_at = Column(DateTime, default=datetime.now, nullable=False)

    account = relationship("Account", back_populates="subscriptions")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "account_id": self.account_id,
            "tier": self.tier,
            "starts_at": self.starts_at.isoformat() if self.starts_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class ApiToken(Base):
    """API 令牌 — 客户端登录后持有的 Bearer token（DB-backed，可吊销）。"""

    __tablename__ = "api_tokens"

    id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(Integer, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash = Column(String(128), nullable=False, unique=True, index=True)  # SHA256 hex
    token_prefix = Column(String(20), nullable=False)  # 前 8 字符，用于展示标识
    device_info = Column(String(255))  # User-Agent / 设备名称
    created_at = Column(DateTime, default=datetime.now, nullable=False)
    expires_at = Column(DateTime, nullable=True)  # NULL = 永不过期
    revoked_at = Column(DateTime, nullable=True)  # 非空 = 已吊销
    last_used_at = Column(DateTime, nullable=True)

    account = relationship("Account", back_populates="api_tokens")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "account_id": self.account_id,
            "token_prefix": self.token_prefix,
            "device_info": self.device_info,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "revoked_at": self.revoked_at.isoformat() if self.revoked_at else None,
            "last_used_at": self.last_used_at.isoformat() if self.last_used_at else None,
        }


class UsageRecord(Base):
    """用量记录 — 用于计费/限流统计。"""

    __tablename__ = "usage_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(Integer, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False, index=True)
    endpoint = Column(String(255), nullable=False)
    method = Column(String(10), nullable=False)
    market = Column(String(30))  # cn / hk / us / crypto_binance
    model_used = Column(String(100))
    tokens_consumed = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.now, nullable=False, index=True)

    __table_args__ = (
        Index("ix_usage_records_account_time", "account_id", "created_at"),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "account_id": self.account_id,
            "endpoint": self.endpoint,
            "method": self.method,
            "market": self.market,
            "model_used": self.model_used,
            "tokens_consumed": self.tokens_consumed,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
